"""/api/health — provider 信息 + 一致性真实逻辑 + 各类降级 + lifespan

关键改进：不再用「mock 返回什么就断言什么」的自证循环。
这里只替换最外层的 I/O（MySQL 查询、ES 客户端方法），
让真实的 consistency_status() 比对逻辑真正跑起来再断言。
"""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings


@pytest.fixture
def es(monkeypatch):
    """可控的 ES 替身（ping / index_dims / count 全部可覆盖）"""
    state = {
        "ping": True,
        "dims": settings.resolved_embed_dims,
        "count": 156,
        "dims_error": False,
    }

    async def _ping():
        return state["ping"]

    async def _index_dims():
        if state["dims_error"]:
            raise RuntimeError("es unreachable")
        return state["dims"]

    async def _count():
        return state["count"]

    monkeypatch.setattr(main.elastic, "ping", _ping)
    monkeypatch.setattr(main.elastic, "index_dims", _index_dims)
    monkeypatch.setattr(main.elastic, "count", _count)
    return state


@pytest.fixture
def client(fake_db, es):
    """TestClient + 已接线的 MySQL/ES 替身"""
    fake_db.route("SELECT 1 AS ok", {"ok": 1})
    fake_db.route("SUM(chunk_count)", {"n": 156})
    return TestClient(main.app)


# ---------- 正常态 ----------

def test_health_reports_provider_info(client):
    """暴露当前生效的 LLM / Embedding 供应商信息

    断言一律跟随 settings（而非硬编码 1024 / deepseek），
    换厂商或换维度时不会因环境差异误报。
    """
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm"]["provider"] == settings.active_llm_spec.name
    assert body["llm"]["model"] == settings.resolved_llm_model
    assert body["llm"]["capabilities"]["vision"] == settings.active_llm_spec.llm_capabilities.vision
    assert body["embedding"]["provider"] == settings.active_embed_spec.name
    assert body["embedding"]["dims"] == settings.resolved_embed_dims
    assert body["embedding"]["dims_match"] is True
    assert body["mysql"] is True
    assert body["elasticsearch"] is True


def test_health_consistency_computed_from_real_inputs(client):
    """一致性由真实比对逻辑得出（MySQL 156 vs ES 156 → 一致）"""
    body = client.get("/api/health").json()
    assert body["consistency"]["match"] is True
    assert body["consistency"]["mysql_ready_chunks"] == 156
    assert body["consistency"]["es_docs"] == 156


async def test_consistency_counts_only_ready_documents(fake_db):
    """MySQL 侧只统计 status='ready' 的文档

    把失败/处理中的文档算进来会让计数虚高，
    一致性校验就会永远"看起来不一致"（2026-10-19 事故的同类陷阱）。
    """
    from app import startup_check

    fake_db.route("FROM kb_document", {"n": 0})
    await startup_check.consistency_status()
    sql = fake_db.sqls()[0]
    assert "SUM(chunk_count)" in sql
    assert "status = 'ready'" in sql


# ---------- 降级态 ----------

def test_health_degraded_on_consistency_mismatch(client, es):
    """事故回归：ES 丢数据（MySQL ready ≠ ES 文档数）→ degraded"""
    es["count"] = 0
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["consistency"]["match"] is False
    assert body["consistency"]["es_docs"] == 0
    assert body["consistency"]["mysql_ready_chunks"] == 156
    # 不一致时必须给出恢复指引
    assert "backfill_es_from_mysql" in body["consistency"]["detail"]


def test_health_degraded_on_dims_conflict(client, es):
    """ES 索引维度与供应商不一致 → degraded"""
    es["dims"] = settings.resolved_embed_dims + 1
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["embedding"]["dims_match"] is False


def test_health_degraded_when_mysql_down(client, fake_db, monkeypatch):
    """MySQL 不可用 → mysql=false 且一致性跳过"""
    from app import db

    async def _boom(sql, params=None):
        raise RuntimeError("mysql down")

    monkeypatch.setattr(db, "aquery_one", _boom)
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["mysql"] is False
    assert body["consistency"]["match"] is None


def test_health_degraded_when_es_unreachable(client, es):
    """ES 不可用 → elasticsearch=false 且维度检查降级"""
    es["ping"] = False
    es["dims_error"] = True
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["elasticsearch"] is False
    assert body["embedding"]["dims_match"] is False


def test_health_status_ok_when_consistency_skipped(client, fake_db):
    """一致性无法判定（MySQL 统计失败）时不算 degraded——判不了 ≠ 不一致"""
    def _raise(params):
        raise RuntimeError("统计查询失败")

    fake_db.route("SUM(chunk_count)", _raise)
    body = client.get("/api/health").json()
    assert body["consistency"]["match"] is None
    assert body["status"] == "ok"


# ---------- lifespan ----------

def test_lifespan_startup_and_close_providers(monkeypatch):
    """lifespan：启动跑自检 + ES 建索引，关闭调 close_providers"""
    calls = {"startup": 0, "ensure_index": 0, "elastic_close": 0, "providers_close": 0}

    async def _fake_startup():
        calls["startup"] += 1

    async def _fake_ensure_index():
        calls["ensure_index"] += 1

    async def _fake_elastic_close():
        calls["elastic_close"] += 1

    async def _fake_providers_close():
        calls["providers_close"] += 1

    monkeypatch.setattr(main, "run_startup_checks", _fake_startup)
    monkeypatch.setattr(main.elastic, "ensure_index", _fake_ensure_index)
    monkeypatch.setattr(main.elastic, "close", _fake_elastic_close)
    monkeypatch.setattr(main, "close_providers", _fake_providers_close)

    with TestClient(main.app):
        assert calls["startup"] == 1
        assert calls["ensure_index"] == 1
    assert calls["elastic_close"] == 1
    assert calls["providers_close"] == 1


def test_lifespan_survives_ensure_index_failure(monkeypatch, fake_db, es):
    """ES 建索引失败 → 服务降级启动（不崩）"""
    async def _boom():
        raise RuntimeError("es down")

    async def _noop_startup():
        return None

    async def _noop_close():
        return None

    monkeypatch.setattr(main, "run_startup_checks", _noop_startup)
    monkeypatch.setattr(main.elastic, "ensure_index", _boom)
    monkeypatch.setattr(main.elastic, "close", _noop_close)
    monkeypatch.setattr(main, "close_providers", _noop_close)

    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200

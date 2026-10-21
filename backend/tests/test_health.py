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
    """Controllable ES double (ping / index_dims / count are all overridable)."""
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
    """TestClient with wired MySQL/ES doubles."""
    fake_db.route("SELECT 1 AS ok", {"ok": 1})
    fake_db.route("SUM(chunk_count)", {"n": 156})
    return TestClient(main.app)


# ---------- Healthy state ----------

def test_health_reports_provider_info(client):
    """Expose the active LLM / Embedding provider information.

    Assertions follow settings instead of hard-coded 1024 / deepseek values,
    so switching provider or dimensions never raises a false alarm.
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
    """Consistency comes from the real comparison logic (MySQL 156 vs ES 156 -> consistent)."""
    body = client.get("/api/health").json()
    assert body["consistency"]["match"] is True
    assert body["consistency"]["mysql_ready_chunks"] == 156
    assert body["consistency"]["es_docs"] == 156


async def test_consistency_counts_only_ready_documents(fake_db):
    """The MySQL side counts only status='ready' documents.

    Including failed or in-flight documents inflates the count,
    and the consistency check would then always look inconsistent (the same trap as the 2026-10-19 incident).
    """
    from app import startup_check

    fake_db.route("FROM kb_document", {"n": 0})
    await startup_check.consistency_status()
    sql = fake_db.sqls()[0]
    assert "SUM(chunk_count)" in sql
    assert "status = 'ready'" in sql


# ---------- Degraded state ----------

def test_health_degraded_on_consistency_mismatch(client, es):
    """Incident regression: ES lost data (MySQL ready != ES document count) -> degraded."""
    es["count"] = 0
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["consistency"]["match"] is False
    assert body["consistency"]["es_docs"] == 0
    assert body["consistency"]["mysql_ready_chunks"] == 156
    # a mismatch must include recovery instructions
    assert "backfill_es_from_mysql" in body["consistency"]["detail"]


def test_health_degraded_on_dims_conflict(client, es):
    """ES index dims differ from the provider dims -> degraded."""
    es["dims"] = settings.resolved_embed_dims + 1
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["embedding"]["dims_match"] is False


def test_health_degraded_when_mysql_down(client, fake_db, monkeypatch):
    """MySQL unavailable -> mysql=false and the consistency check is skipped."""
    from app import db

    async def _boom(sql, params=None):
        raise RuntimeError("mysql down")

    monkeypatch.setattr(db, "aquery_one", _boom)
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["mysql"] is False
    assert body["consistency"]["match"] is None


def test_health_degraded_when_es_unreachable(client, es):
    """ES unavailable -> elasticsearch=false and the dims check degrades."""
    es["ping"] = False
    es["dims_error"] = True
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["elasticsearch"] is False
    assert body["embedding"]["dims_match"] is False


def test_health_status_ok_when_consistency_skipped(client, fake_db):
    """An undecidable consistency check (MySQL count failed) is not degraded — undecidable is not inconsistent."""
    def _raise(params):
        raise RuntimeError("统计查询失败")

    fake_db.route("SUM(chunk_count)", _raise)
    body = client.get("/api/health").json()
    assert body["consistency"]["match"] is None
    assert body["status"] == "ok"


# ---------- lifespan ----------

def test_lifespan_startup_and_close_providers(monkeypatch):
    """lifespan: run the self-check and create the ES index on startup, call close_providers on shutdown."""
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
    """ES index creation fails -> the service starts degraded (no crash)."""
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

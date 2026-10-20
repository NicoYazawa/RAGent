"""ES/MySQL 一致性 guard — 栈重建丢 ES 卷的静默故障防护

场景回归：2026-10-19 事故——Docker 栈重建后 ES 索引 0 文档而 MySQL 显示 ready，
检索静默降级为「知识库未覆盖」。本 guard 在启动自检与 /api/health 中比对
「MySQL ready 切片总数」与「ES 文档数」，不一致即显式失败。
"""
import httpx

from app import startup_check


class _FakeEs:
    """可控的 ES 替身（index_dims / count）"""

    def __init__(self, dims: int | None = 1024, count: int = 156, count_error: bool = False, dims_error: bool = False):
        self._dims = dims
        self._count = count
        self._count_error = count_error
        self._dims_error = dims_error

    async def index_dims(self):
        if self._dims_error:
            raise httpx.HTTPError("es unreachable")
        return self._dims

    async def count(self) -> int:
        if self._count_error:
            raise httpx.HTTPError("es unreachable")
        return self._count


def _patch_mysql(monkeypatch, value: int | None = 156, error: bool = False):
    async def _aquery_one(sql, params=None):
        if error:
            raise RuntimeError("mysql down")
        return {"n": value}

    monkeypatch.setattr(startup_check.db, "aquery_one", _aquery_one)


# ---------- consistency_status ----------

async def test_status_match(monkeypatch):
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims=1024, count=156))
    st = await startup_check.consistency_status()
    assert st["match"] is True
    assert st["mysql_ready_chunks"] == 156 and st["es_docs"] == 156
    assert "一致" in st["detail"]


async def test_status_zero_zero_is_ok(monkeypatch):
    """全新环境（无文档）两边都是 0，属一致，不应告警"""
    _patch_mysql(monkeypatch, 0)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims=1024, count=0))
    st = await startup_check.consistency_status()
    assert st["match"] is True


async def test_status_mismatch_incident_scenario(monkeypatch):
    """事故场景：MySQL 156 ready vs ES 0 文档"""
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims=1024, count=0))
    st = await startup_check.consistency_status()
    assert st["match"] is False
    assert "156" in st["detail"] and "0" in st["detail"]
    assert "恢复" in st["detail"]  # 必须给出恢复脚本指引


async def test_status_mysql_error(monkeypatch):
    _patch_mysql(monkeypatch, error=True)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs())
    st = await startup_check.consistency_status()
    assert st["match"] is None
    assert "MySQL" in st["detail"]


async def test_status_index_missing_skips(monkeypatch):
    """索引不存在（尚未创建）→ 跳过比对，不算不一致"""
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims=None))
    st = await startup_check.consistency_status()
    assert st["match"] is None
    assert "索引不存在" in st["detail"]


async def test_status_es_count_error(monkeypatch):
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(count_error=True))
    st = await startup_check.consistency_status()
    assert st["match"] is None
    assert "ES" in st["detail"]


# ---------- check_es_mysql_consistency（启动自检入口） ----------

async def test_check_ok_on_match(monkeypatch):
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(count=156))
    ok, detail = await startup_check.check_es_mysql_consistency()
    assert ok is True
    assert "一致" in detail


async def test_check_fail_on_mismatch(monkeypatch):
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(count=0))
    ok, detail = await startup_check.check_es_mysql_consistency()
    assert ok is False
    assert "不一致" in detail


async def test_status_es_dims_query_error(monkeypatch):
    """ES 宕机：index_dims 抛错必须降级为跳过（health 不得 500）"""
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims_error=True))
    st = await startup_check.consistency_status()
    assert st["match"] is None
    assert "ES" in st["detail"]


async def test_check_ok_when_skipped(monkeypatch):
    """跳过态（MySQL 挂了 / 索引不存在 / ES 不可达）不打 FAIL，返回 None（[SKIP]）"""
    _patch_mysql(monkeypatch, error=True)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs())
    ok, detail = await startup_check.check_es_mysql_consistency()
    assert ok is None
    assert detail

    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims_error=True))
    ok2, detail2 = await startup_check.check_es_mysql_consistency()
    assert ok2 is None
    assert "ES" in detail2


# ---------- run_startup_checks 接线 ----------

async def test_startup_checks_include_consistency(monkeypatch):
    captured = {}

    async def _ok(*a, **k):
        return True, "ok"

    monkeypatch.setattr(startup_check, "check_es", _ok)
    monkeypatch.setattr(startup_check, "check_provider", _ok)
    monkeypatch.setattr(startup_check, "check_embedding_dims", _ok)
    monkeypatch.setattr(startup_check, "check_es_mysql_consistency", _ok)

    def _capture(text):
        captured["text"] = text

    monkeypatch.setattr(startup_check, "_print_block", _capture)
    await startup_check.run_startup_checks()

    assert "ES/MySQL 数据一致性" in captured["text"]
    assert captured["text"].count("[OK]") == 5  # 五项检查全部出现在摘要中


async def test_startup_checks_survives_single_check_exception(monkeypatch):
    """单项检查自身异常不吞掉其余四项诊断（gather return_exceptions=True）"""
    captured = {}

    async def _ok(*a, **k):
        return True, "ok"

    async def _boom(*a, **k):
        raise RuntimeError("check crashed")

    monkeypatch.setattr(startup_check, "check_es", _ok)
    monkeypatch.setattr(startup_check, "check_provider", _ok)
    monkeypatch.setattr(startup_check, "check_embedding_dims", _boom)
    monkeypatch.setattr(startup_check, "check_es_mysql_consistency", _ok)

    def _capture(text):
        captured["text"] = text

    monkeypatch.setattr(startup_check, "_print_block", _capture)
    await startup_check.run_startup_checks()

    assert "检查自身异常" in captured["text"]
    assert captured["text"].count("[OK]") == 4
    assert "[FAIL]" in captured["text"]


async def test_startup_checks_skip_badge(monkeypatch):
    """跳过态打 [SKIP] 而非 [OK]/[FAIL]，不计入 problems"""
    captured = {}

    async def _ok(*a, **k):
        return True, "ok"

    async def _skip(*a, **k):
        return None, "MySQL 查询失败，跳过比对"

    monkeypatch.setattr(startup_check, "check_es", _ok)
    monkeypatch.setattr(startup_check, "check_provider", _ok)
    monkeypatch.setattr(startup_check, "check_embedding_dims", _ok)
    monkeypatch.setattr(startup_check, "check_es_mysql_consistency", _skip)

    def _capture(text):
        captured["text"] = text

    monkeypatch.setattr(startup_check, "_print_block", _capture)
    await startup_check.run_startup_checks()

    assert "[SKIP]" in captured["text"]
    assert "[FAIL]" not in captured["text"]
    assert "全部依赖正常" in captured["text"]  # 跳过不算异常

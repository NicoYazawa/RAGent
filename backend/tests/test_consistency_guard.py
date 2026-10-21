"""ES/MySQL 一致性 guard — 栈重建丢 ES 卷的静默故障防护

场景回归：2026-10-19 事故——Docker 栈重建后 ES 索引 0 文档而 MySQL 显示 ready，
检索静默降级为「知识库未覆盖」。本 guard 在启动自检与 /api/health 中比对
「MySQL ready 切片总数」与「ES 文档数」，不一致即显式失败。
"""
import httpx

from app import startup_check


class _FakeEs:
    """Controllable ES double (index_dims / count)."""

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
    """A fresh environment with no documents has 0 on both sides: consistent, so no warning."""
    _patch_mysql(monkeypatch, 0)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims=1024, count=0))
    st = await startup_check.consistency_status()
    assert st["match"] is True


async def test_status_mismatch_incident_scenario(monkeypatch):
    """Incident scenario: MySQL 156 ready chunks vs 0 ES documents."""
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims=1024, count=0))
    st = await startup_check.consistency_status()
    assert st["match"] is False
    assert "156" in st["detail"] and "0" in st["detail"]
    assert "恢复" in st["detail"]  # must point at the recovery script


async def test_status_mysql_error(monkeypatch):
    _patch_mysql(monkeypatch, error=True)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs())
    st = await startup_check.consistency_status()
    assert st["match"] is None
    assert "MySQL" in st["detail"]


async def test_status_index_missing_skips(monkeypatch):
    """The index does not exist yet -> skip the comparison instead of reporting a mismatch."""
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


# ---------- check_es_mysql_consistency (startup self-check entry) ----------

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
    """ES is down: an index_dims error must degrade to skipped (health must not return 500)."""
    _patch_mysql(monkeypatch, 156)
    monkeypatch.setattr(startup_check, "elastic", _FakeEs(dims_error=True))
    st = await startup_check.consistency_status()
    assert st["match"] is None
    assert "ES" in st["detail"]


async def test_check_ok_when_skipped(monkeypatch):
    """Skipped states (MySQL down / index missing / ES unreachable) are not FAIL but None ([SKIP])."""
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


# ---------- run_startup_checks wiring ----------

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
    assert captured["text"].count("[OK]") == 5  # all five checks appear in the summary


async def test_startup_checks_survives_single_check_exception(monkeypatch):
    """An exception in one check does not swallow the other four diagnostics (gather return_exceptions=True)."""
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
    """A skipped state prints [SKIP] instead of [OK]/[FAIL] and is not counted in problems."""
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
    assert "全部依赖正常" in captured["text"]  # a skip is not an error

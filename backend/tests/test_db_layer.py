"""MySQL 访问层 — 行序列化（日期/Decimal/bytes/JSON）与同步原语

db._serialize 决定 JSON 字段能否正确回传给前端，
历史上完全没有测试（覆盖率 38%）。
"""
import datetime
import decimal
import json

import pytest

from app import db

# ---------- _serialize ----------

def test_serialize_converts_datetime_and_date():
    """datetime / date -> ISO strings."""
    out = db._serialize({
        "created_at": datetime.datetime(2026, 10, 20, 12, 30, 45),
        "day": datetime.date(2026, 10, 20),
    })
    assert out["created_at"] == "2026-10-20T12:30:45"
    assert out["day"] == "2026-10-20"


def test_serialize_converts_decimal():
    """Decimal: integral values -> int, others -> float."""
    out = db._serialize({"n": decimal.Decimal("10"), "ratio": decimal.Decimal("0.25")})
    assert out["n"] == 10 and isinstance(out["n"], int)
    assert out["ratio"] == 0.25 and isinstance(out["ratio"], float)


def test_serialize_decodes_bytes():
    """bytes -> UTF-8 string (replace as the fallback for invalid bytes)."""
    out = db._serialize({"raw": b"hello", "bad": b"\xff\xfe"})
    assert out["raw"] == "hello"
    assert isinstance(out["bad"], str)


def test_serialize_parses_json_fields():
    """JSON fields such as citations / steps / config / images are deserialized automatically."""
    out = db._serialize({
        "citations": json.dumps([{"doc_name": "手册"}]),
        "steps": json.dumps([{"step": 1}]),
        "config": json.dumps({"k": "v"}),
        "images": json.dumps(["/api/chat/images/a.png"]),
        "other": json.dumps({"x": 1}),
    })
    assert out["citations"] == [{"doc_name": "手册"}]
    assert out["steps"] == [{"step": 1}]
    assert out["config"] == {"k": "v"}
    assert out["images"] == ["/api/chat/images/a.png"]
    # fields outside the JSON allowlist pass through unchanged
    assert out["other"] == '{"x": 1}'


def test_serialize_invalid_json_field_becomes_none():
    """Invalid JSON content -> None (no exception that would break the whole row)."""
    out = db._serialize({"citations": "not-json"})
    assert out["citations"] is None


def test_serialize_passthrough_plain_values():
    """Plain values pass through unchanged."""
    out = db._serialize({"id": 1, "name": "x", "ok": True, "none": None})
    assert out == {"id": 1, "name": "x", "ok": True, "none": None}


def test_serialize_json_field_not_string_untouched():
    """A JSON field already holding a list/dict is not parsed again."""
    out = db._serialize({"citations": [{"a": 1}]})
    assert out["citations"] == [{"a": 1}]


# ---------- Synchronous primitives (mock connection) ----------

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.lastrowid = 42
        self.rowcount = 3

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    def executemany(self, sql, seq):
        self.conn.executed.append((sql, seq))

    def fetchall(self):
        return self.conn.rows


class _FakeConn:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{"id": 1}]
        self.executed: list = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        return False

    def cursor(self):
        return _FakeCursor(self)


@pytest.fixture
def fake_conn(monkeypatch):
    """Replace pymysql.connect and return a controllable fake connection."""
    holder = {}

    def _connect(**kwargs):
        conn = _FakeConn(holder.get("rows"))
        holder["conn"] = conn
        holder["kwargs"] = kwargs
        return conn

    monkeypatch.setattr(db.pymysql, "connect", _connect)
    return holder


def test_query_all_returns_serialized_rows(fake_conn):
    """query_all serializes every row."""
    fake_conn["rows"] = [{"id": 1, "n": decimal.Decimal("3")}]
    rows = db.query_all("SELECT * FROM t")
    assert rows == [{"id": 1, "n": 3}]


def test_query_one_returns_first_or_none(fake_conn):
    """query_one returns the first row, or None when there is none."""
    fake_conn["rows"] = [{"id": 7}, {"id": 8}]
    assert db.query_one("SELECT * FROM t") == {"id": 7}
    fake_conn["rows"] = []
    assert db.query_one("SELECT * FROM t") is None


def test_execute_returns_lastrowid(fake_conn):
    """execute returns lastrowid."""
    assert db.execute("INSERT INTO t VALUES (1)") == 42


def test_execute_many_returns_rowcount(fake_conn):
    """execute_many returns the affected row count."""
    assert db.execute_many("INSERT INTO t VALUES (%s)", [(1,), (2,), (3,)]) == 3


def test_get_conn_passes_settings(monkeypatch):
    """Connection parameters come from settings and always force utf8mb4."""
    captured = {}

    def _connect(**kwargs):
        captured.update(kwargs)
        return _FakeConn()

    monkeypatch.setattr(db.pymysql, "connect", _connect)
    db.get_conn()
    assert captured["charset"] == "utf8mb4"
    assert captured["database"] == db.settings.mysql_db
    assert captured["autocommit"] is True


def test_get_conn_explicit_database_overrides(monkeypatch):
    """An explicit database name overrides the default database."""
    captured = {}

    def _connect(**kwargs):
        captured.update(kwargs)
        return _FakeConn()

    monkeypatch.setattr(db.pymysql, "connect", _connect)
    db.get_conn("other_db")
    assert captured["database"] == "other_db"


# ---------- Async wrappers ----------

async def test_async_wrappers_delegate_to_sync(monkeypatch):
    """The async wrappers end up in the synchronous primitives (to_thread)."""
    calls = []

    def _qa(sql, params=None):
        calls.append(("all", sql))
        return [{"id": 1}]

    def _q1(sql, params=None):
        calls.append(("one", sql))
        return {"id": 1}

    def _ex(sql, params=None):
        calls.append(("exec", sql))
        return 1

    def _exm(sql, seq):
        calls.append(("execmany", sql))
        return len(seq)

    monkeypatch.setattr(db, "query_all", _qa)
    monkeypatch.setattr(db, "query_one", _q1)
    monkeypatch.setattr(db, "execute", _ex)
    monkeypatch.setattr(db, "execute_many", _exm)

    assert await db.aquery_all("S1") == [{"id": 1}]
    assert await db.aquery_one("S2") == {"id": 1}
    assert await db.aexecute("S3") == 1
    assert await db.aexecute_many("S4", [(1,), (2,)]) == 2
    assert [c[0] for c in calls] == ["all", "one", "exec", "execmany"]

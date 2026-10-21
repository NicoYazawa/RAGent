"""MySQL data access layer — pymysql + asyncio.to_thread, utf8mb4 end to end.

MySQL is the single source of truth for metadata:
kb_database / kb_document / kb_chunk / chat_session / chat_message /
agent_decision_log / datasource_config plus the sales demo business table.

The schema is imported beforehand from ragent_init.sql at the project root; this layer does
not create tables.
"""
import asyncio
import datetime
import decimal
import json
from contextlib import asynccontextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from .config import settings

_JSON_FIELDS = {"citations", "steps", "config", "images"}


def get_conn(database: str | None = None) -> pymysql.connections.Connection:
    # database=None -> default database ragent_db; otherwise the given database
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=database or settings.mysql_db,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            out[k] = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            out[k] = int(v) if v == v.to_integral_value() else float(v)
        elif isinstance(v, (bytes, bytearray)):
            out[k] = v.decode("utf-8", "replace")
        elif k in _JSON_FIELDS and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except (ValueError, TypeError):
                out[k] = None
        else:
            out[k] = v
    return out


# ---------- Synchronous primitives (called through asyncio.to_thread) ----------

def query_all(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [_serialize(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | dict | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.lastrowid)


def execute_many(sql: str, seq: list[tuple]) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(sql, seq)
        return cur.rowcount


# ---------- Async wrappers ----------

async def aquery_all(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    return await asyncio.to_thread(query_all, sql, params)


async def aquery_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    return await asyncio.to_thread(query_one, sql, params)


async def aexecute(sql: str, params: tuple | dict | None = None) -> int:
    return await asyncio.to_thread(execute, sql, params)


async def aexecute_many(sql: str, seq: list[tuple]) -> int:
    return await asyncio.to_thread(execute_many, sql, seq)


def execute_transaction(statements: list[tuple[str, tuple]]) -> None:
    with get_conn() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, params)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


async def aexecute_transaction(statements: list[tuple[str, tuple]]) -> None:
    await asyncio.to_thread(execute_transaction, statements)


@asynccontextmanager
async def kb_write_lock(kb_id: int):
    """Coordinate knowledge-base writes across processes; a dedicated connection holds the lock,
and closing it releases the MySQL advisory lock automatically."""
    import hashlib

    name = f"ragent:{hashlib.sha256(settings.mysql_db.encode()).hexdigest()[:16]}:kb:{kb_id}"
    conn = await asyncio.to_thread(get_conn)
    try:
        def acquire():
            with conn.cursor() as cur:
                cur.execute("SELECT GET_LOCK(%s, 10) AS acquired", (name,))
                return cur.fetchone()["acquired"]

        if await asyncio.to_thread(acquire) != 1:
            raise TimeoutError("Knowledge base is busy; please retry shortly.")
        yield
    finally:
        await asyncio.to_thread(conn.close)

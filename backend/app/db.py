"""MySQL 数据访问层 — pymysql + asyncio.to_thread，全链路 utf8mb4

MySQL 为元数据唯一事实源：
kb_database / kb_document / kb_chunk / chat_session / chat_message /
agent_decision_log / datasource_config + sales 业务演示表

库表结构由项目根目录 ragent_init.sql 前置导入，本层不负责建表。
"""
import asyncio
import datetime
import decimal
import json
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from .config import settings

_JSON_FIELDS = {"citations", "steps", "config", "images"}


def get_conn(database: str | None = None) -> pymysql.connections.Connection:
    # database=None → 默认库 ragent_db → 指定库
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


# ---------- 同步原语（供 asyncio.to_thread 调用） ----------

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


# ---------- 异步包装 ----------

async def aquery_all(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    return await asyncio.to_thread(query_all, sql, params)


async def aquery_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    return await asyncio.to_thread(query_one, sql, params)


async def aexecute(sql: str, params: tuple | dict | None = None) -> int:
    return await asyncio.to_thread(execute, sql, params)


async def aexecute_many(sql: str, seq: list[tuple]) -> int:
    return await asyncio.to_thread(execute_many, sql, seq)

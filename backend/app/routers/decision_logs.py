"""决策日志路由 ：分页过滤查询 + 单条回放"""
from datetime import datetime, time

from fastapi import APIRouter, HTTPException

from .. import db
from ..i18n import t

router = APIRouter(prefix="/api/admin", tags=["decision-logs"])


@router.get("/decision-logs")
async def query_decision_logs(
    session_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    page_size: int = 8,
) -> dict:
    where = ["1=1"]
    params: list = []
    if session_id is not None:
        where.append("session_id=%s")
        params.append(session_id)
    if start:
        try:
            params.append(datetime.combine(datetime.fromisoformat(start), time.min))
            where.append("created_at >= %s")
        except ValueError:
            pass
    if end:
        try:
            params.append(datetime.combine(datetime.fromisoformat(end), time.max))
            where.append("created_at <= %s")
        except ValueError:
            pass
    cond = " AND ".join(where)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    total_row = await db.aquery_one(f"SELECT COUNT(*) AS n FROM agent_decision_log WHERE {cond}", tuple(params))
    total = int(total_row["n"]) if total_row else 0
    items = await db.aquery_all(
        f"SELECT * FROM agent_decision_log WHERE {cond} ORDER BY id DESC LIMIT %s OFFSET %s",
        tuple(params + [page_size, (page - 1) * page_size]),
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/decision-logs/{log_id}")
async def get_decision_log(log_id: int) -> dict:
    row = await db.aquery_one("SELECT * FROM agent_decision_log WHERE id=%s", (log_id,))
    if row is None:
        raise HTTPException(404, t("api.log_not_found"))
    return row

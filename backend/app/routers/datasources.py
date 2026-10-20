"""数据源配置路由 """
import json

from fastapi import APIRouter, HTTPException

from .. import db
from ..i18n import t
from ..models import DatasourceUpdate

router = APIRouter(prefix="/api/admin", tags=["datasources"])

ORDER = ["vector", "keyword", "database"]


@router.get("/datasources")
async def get_datasources() -> list[dict]:
    rows = await db.aquery_all("SELECT source_type, enabled, config, updated_at FROM datasource_config")
    by_type = {r["source_type"]: r for r in rows}
    out = []
    for s in ORDER:
        r = by_type.get(s)
        if r is None:
            continue
        out.append(
            {
                "source_type": s,
                "enabled": bool(r["enabled"]),
                "config": r.get("config") or {},
                "updated_at": r["updated_at"],
            }
        )
    return out


@router.put("/datasources")
async def update_datasources(body: DatasourceUpdate) -> dict:
    updated = 0
    for item in body.items:
        if item.source_type not in ORDER:
            raise HTTPException(400, t("api.unknown_ds_type", source=item.source_type))
        existing = await db.aquery_one(
            "SELECT id FROM datasource_config WHERE source_type=%s", (item.source_type,)
        )
        cfg = json.dumps(item.config, ensure_ascii=False)
        if existing is None:
            await db.aexecute(
                "INSERT INTO datasource_config (source_type, enabled, config) VALUES (%s, %s, %s)",
                (item.source_type, int(item.enabled), cfg),
            )
        else:
            await db.aexecute(
                "UPDATE datasource_config SET enabled=%s, config=%s WHERE source_type=%s",
                (int(item.enabled), cfg, item.source_type),
            )
        updated += 1
    return {"updated": updated}

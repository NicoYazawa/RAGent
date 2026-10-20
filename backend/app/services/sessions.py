"""会话服务 — 多轮上下文管理、历史消息、重答清理"""
import json

from .. import db
from ..services.chat_images import CHAT_IMAGE_DIR, CHAT_IMAGE_URL_PREFIX


async def create_session() -> dict:
    sid = await db.aexecute("INSERT INTO chat_session (title) VALUES ('新会话')")
    row = await db.aquery_one("SELECT * FROM chat_session WHERE id=%s", (sid,))
    return row  # type: ignore[return-value]


async def list_sessions() -> list[dict]:
    return await db.aquery_all("SELECT * FROM chat_session ORDER BY updated_at DESC, id DESC")


async def get_messages(session_id: int) -> list[dict]:
    return await db.aquery_all(
        "SELECT id, session_id, role, content, citations, images, decision_log_id, created_at"
        " FROM chat_message WHERE session_id=%s ORDER BY id ASC",
        (session_id,),
    )


async def delete_session(session_id: int) -> None:
    # 级联清理会话内消息引用的落盘图片（避免孤儿文件）
    rows = await db.aquery_all(
        "SELECT images FROM chat_message WHERE session_id=%s AND images IS NOT NULL", (session_id,)
    )
    for row in rows:
        for url in json.loads(row["images"]) if isinstance(row["images"], str) else (row["images"] or []):
            name = url.removeprefix(CHAT_IMAGE_URL_PREFIX)
            if url.startswith(CHAT_IMAGE_URL_PREFIX) and (CHAT_IMAGE_DIR / name).is_file():
                (CHAT_IMAGE_DIR / name).unlink(missing_ok=True)
    await db.aexecute("DELETE FROM chat_message WHERE session_id=%s", (session_id,))
    await db.aexecute("DELETE FROM chat_session WHERE id=%s", (session_id,))


async def purge_last_assistant(session_id: int) -> bool:
    """重新生成前清理：移除最后一条 assistant 消息及其决策日志"""
    row = await db.aquery_one(
        "SELECT id, decision_log_id FROM chat_message WHERE session_id=%s AND role='assistant' ORDER BY id DESC LIMIT 1",
        (session_id,),
    )
    if row is None:
        return False
    if row.get("decision_log_id"):
        await db.aexecute("DELETE FROM agent_decision_log WHERE id=%s", (row["decision_log_id"],))
    await db.aexecute("DELETE FROM chat_message WHERE id=%s", (row["id"],))
    return True

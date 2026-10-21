"""Chat router — the core SSE Q&A streaming endpoint."""
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse, StreamingResponse

from .. import db
from ..agent.orchestrator import run_ask
from ..i18n import current_locale, t
from ..models import AskRequest
from ..services import chat_images, sessions

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions", status_code=201)
async def create_session() -> dict:
    return await sessions.create_session()


@router.get("/sessions")
async def list_sessions() -> list[dict]:
    return await sessions.list_sessions()


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: int) -> list[dict]:
    sess = await db.aquery_one("SELECT id FROM chat_session WHERE id=%s", (session_id,))
    if sess is None:
        raise HTTPException(404, t("api.session_not_found"))
    return await sessions.get_messages(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int) -> dict:
    sess = await db.aquery_one("SELECT id FROM chat_session WHERE id=%s", (session_id,))
    if sess is None:
        raise HTTPException(404, t("api.session_not_found"))
    await sessions.delete_session(session_id)
    return {"deleted": session_id}


@router.delete("/sessions/{session_id}/last-assistant")
async def purge_last_assistant(session_id: int) -> dict:
    """Cleanup before regenerating: remove the last assistant message and its decision log."""
    removed = await sessions.purge_last_assistant(session_id)
    return {"removed": removed}


@router.get("/images/{name}")
async def get_chat_image(name: str) -> FileResponse:
    """Serve Q&A images statically (the in-app URLs referenced by chat_message.images)."""
    path = chat_images.image_path(name)
    if path is None:
        raise HTTPException(404, t("api.image_not_found"))
    ext = name.rsplit(".", 1)[-1]
    return FileResponse(path, media_type=chat_images.EXT_MIME[ext])


@router.post("/sessions/{session_id}/ask")
async def ask(session_id: int, body: AskRequest):
    sess = await db.aquery_one("SELECT id FROM chat_session WHERE id=%s", (session_id,))
    if sess is None:
        raise HTTPException(404, t("api.session_not_found"))
    try:
        image_urls = chat_images.save_images(body.images or [])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # The SSE generator only runs while the response streams, by which point the middleware
    # ContextVar may already be gone -> resolve the locale here, inside the route handler
    # (still within the middleware context), and pass it to run_ask explicitly
    locale = current_locale()
    gen = run_ask(session_id, body.question.strip(), body.kb_ids, body.skip_user_persist, image_urls, locale=locale)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

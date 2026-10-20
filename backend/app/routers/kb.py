"""知识库管理路由"""
import asyncio

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from .. import db
from ..i18n import t
from ..services import ingestion

router = APIRouter(prefix="/api/admin", tags=["kb"])


@router.get("/kb")
async def list_kbs() -> list[dict]:
    rows = await db.aquery_all(
        """SELECT k.*,
                  (SELECT COUNT(*) FROM kb_document d WHERE d.kb_id = k.id AND d.status = 'ready') AS doc_count,
                  (SELECT COALESCE(SUM(d.chunk_count), 0) FROM kb_document d WHERE d.kb_id = k.id AND d.status = 'ready') AS chunk_count
           FROM kb_database k ORDER BY k.id ASC"""
    )
    return rows


@router.post("/kb", status_code=201)
async def create_kb(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        raise HTTPException(400, t("api.kb_name_empty"))
    dup = await db.aquery_one("SELECT id FROM kb_database WHERE name=%s", (name,))
    if dup:
        raise HTTPException(409, t("api.kb_name_dup", name=name))
    kid = await db.aexecute("INSERT INTO kb_database (name, description) VALUES (%s, %s)", (name, description))
    row = await db.aquery_one(
        """SELECT k.*, 0 AS doc_count, 0 AS chunk_count FROM kb_database k WHERE k.id=%s""", (kid,)
    )
    return row  # type: ignore[return-value]


@router.get("/kb/{kb_id}/documents")
async def list_documents(kb_id: int) -> list[dict]:
    return await db.aquery_all(
        "SELECT id, kb_id, file_name, file_type, status, chunk_count, error_msg, created_at, updated_at"
        " FROM kb_document WHERE kb_id=%s ORDER BY created_at DESC, id DESC",
        (kb_id,),
    )


@router.post("/kb/{kb_id}/documents", status_code=202)
async def upload_document(kb_id: int, background: BackgroundTasks, file: UploadFile = File(...)) -> dict:
    kb = await db.aquery_one("SELECT id FROM kb_database WHERE id=%s", (kb_id,))
    if kb is None:
        raise HTTPException(404, t("api.kb_not_found"))
    content = await file.read()
    try:
        doc_id, _, _ = await asyncio.to_thread(ingestion.save_upload, kb_id, file.filename or "untitled", content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    background.add_task(ingestion.process_document, doc_id)
    doc = await db.aquery_one(
        "SELECT id, kb_id, file_name, file_type, status, chunk_count, error_msg, created_at, updated_at"
        " FROM kb_document WHERE id=%s",
        (doc_id,),
    )
    return doc  # type: ignore[return-value]


@router.delete("/kb/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: int, doc_id: int) -> dict:
    doc = await db.aquery_one("SELECT id FROM kb_document WHERE id=%s AND kb_id=%s", (doc_id, kb_id))
    if doc is None:
        raise HTTPException(404, t("api.doc_not_found"))
    await ingestion.delete_document(kb_id, doc_id)
    return {"deleted": doc_id}


@router.post("/kb/{kb_id}/documents/{doc_id}/retry", status_code=202)
async def retry_document(kb_id: int, doc_id: int, background: BackgroundTasks) -> dict:
    try:
        doc = await ingestion.reset_for_retry(kb_id, doc_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    background.add_task(ingestion.process_document, doc_id)
    return doc


@router.get("/kb/{kb_id}/documents/{doc_id}/chunks")
async def list_document_chunks(kb_id: int, doc_id: int, page: int = 1, page_size: int = 8) -> dict:
    doc = await db.aquery_one("SELECT * FROM kb_document WHERE id=%s AND kb_id=%s", (doc_id, kb_id))
    if doc is None:
        raise HTTPException(404, t("api.doc_not_found"))
    if doc["status"] != "ready":
        raise HTTPException(400, t("api.doc_not_ready"))
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    total_row = await db.aquery_one("SELECT COUNT(*) AS n FROM kb_chunk WHERE doc_id=%s", (doc_id,))
    total = int(total_row["n"]) if total_row else 0
    items = await db.aquery_all(
        "SELECT id, doc_id, chunk_no, section_path, content, token_count FROM kb_chunk"
        " WHERE doc_id=%s ORDER BY chunk_no ASC LIMIT %s OFFSET %s",
        (doc_id, page_size, (page - 1) * page_size),
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/chunks/by-citation")
async def get_chunk_by_citation(
    doc_name: str,
    chunk_no: int,
    doc_id: int | None = None,
    kb_id: int | None = None,
    chunk_uid: str | None = None,
) -> dict:
    """新引用按文档 ID 定位；旧引用仅在文件名唯一时回退，禁止猜测同名文档。"""
    fields = "id, kb_id, file_name, file_type, status, chunk_count, error_msg, created_at, updated_at"
    if doc_id is not None:
        doc = await db.aquery_one(f"SELECT {fields} FROM kb_document WHERE id=%s", (doc_id,))
        if doc and (doc["status"] != "ready" or (kb_id is not None and doc["kb_id"] != kb_id)):
            doc = None
    else:
        # 按最后一个点去扩展名，与入库时 rsplit('.', 1) 的语义相同。
        condition = "status='ready' AND LEFT(file_name, CHAR_LENGTH(file_name) - LOCATE('.', REVERSE(file_name)))=%s"
        params: tuple = (doc_name,)
        if kb_id is not None:
            condition += " AND kb_id=%s"
            params += (kb_id,)
        docs = await db.aquery_all(f"SELECT {fields} FROM kb_document WHERE {condition} ORDER BY id DESC LIMIT 2", params)
        if len(docs) > 1:
            raise HTTPException(409, t("api.citation_ambiguous", doc=doc_name))
        doc = docs[0] if docs else None
    if doc is None:
        raise HTTPException(404, t("api.citation_doc_missing", doc=doc_name))
    chunk_condition = "doc_id=%s AND chunk_no=%s"
    chunk_params: tuple = (doc["id"], chunk_no)
    if chunk_uid is not None:
        chunk_condition += " AND chunk_uid=%s"
        chunk_params += (chunk_uid,)
    chunk = await db.aquery_one(
        "SELECT id, doc_id, chunk_no, section_path, content, token_count FROM kb_chunk"
        f" WHERE {chunk_condition}",
        chunk_params,
    )
    if chunk is None:
        raise HTTPException(404, t("api.chunk_missing", doc=doc_name, no=chunk_no))
    return {"doc": doc, "chunk": chunk}

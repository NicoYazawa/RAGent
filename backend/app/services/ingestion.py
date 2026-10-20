"""知识库入库流水线 — 解析 → 切片 → Embedding → ES 入库

parsing → chunking → embedding → ready；任一步失败置 failed 并记录 error_msg，支持重试。
删除文档：先 ES（按 doc_id）后 MySQL。
"""
import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import db
from ..agent.embeddings import embed_texts
from ..config import UPLOAD_DIR
from ..es import elastic
from .chunker import chunk_blocks
from .parsers import parse_file

logger = logging.getLogger("agentic.ingestion")

ALLOWED_TYPES = ["md", "txt", "pdf", "docx"]
MAX_SIZE = 20 * 1024 * 1024
PROCESSING_STATUSES = {'parsing', 'chunking', 'embedding'}


class KnowledgeBaseBusy(ValueError):
    pass


class KnowledgeBaseMissing(ValueError):
    pass


def _remove_upload_directory(kb_id: int) -> None:
    root = UPLOAD_DIR.resolve()
    target = root / str(kb_id)
    if kb_id <= 0 or target.is_symlink() or target.resolve() != target:
        raise ValueError('Invalid knowledge base upload directory')
    if target.exists():
        shutil.rmtree(target)


async def delete_knowledge_base(kb_id: int) -> None:
    """先清理 ES 和文件，再事务删除元数据；任一失败允许保留库记录后重试。"""
    async with db.kb_write_lock(kb_id):
        if await db.aquery_one('SELECT id FROM kb_database WHERE id=%s', (kb_id,)) is None:
            raise KnowledgeBaseMissing()
        active = await db.aquery_one(
            "SELECT id FROM kb_document WHERE kb_id=%s AND status IN ('parsing','chunking','embedding') LIMIT 1",
            (kb_id,),
        )
        if active:
            raise KnowledgeBaseBusy()
        await elastic.delete_by_kb(kb_id)
        await asyncio.to_thread(_remove_upload_directory, kb_id)
        await db.aexecute_transaction([
            ('DELETE c FROM kb_chunk c INNER JOIN kb_document d ON c.doc_id=d.id WHERE d.kb_id=%s', (kb_id,)),
            ('DELETE FROM kb_document WHERE kb_id=%s', (kb_id,)),
            ('DELETE FROM kb_database WHERE id=%s', (kb_id,)),
        ])


def validate_upload(file_name: str, size: int) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext not in ALLOWED_TYPES:
        raise ValueError(f"不支持的文件类型 .{ext}（允许：md / txt / pdf / docx）")
    if size > MAX_SIZE:
        raise ValueError("文件大小超过 20MB 上限")
    return ext


def save_upload(kb_id: int, file_name: str, content: bytes) -> tuple[int, str, str]:
    """落盘 + 建 kb_document 记录（status=parsing），返回 (doc_id, file_path, file_type)"""
    ext = validate_upload(file_name, len(content))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file_name).name
    doc_id = db.execute(
        "INSERT INTO kb_document (kb_id, file_name, file_path, file_type, status) VALUES (%s, %s, %s, %s, 'parsing')",
        (kb_id, safe_name, "", ext),
    )
    dest = UPLOAD_DIR / str(kb_id) / f"{doc_id}_{safe_name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    db.execute("UPDATE kb_document SET file_path=%s WHERE id=%s", (str(dest), doc_id))
    return doc_id, str(dest), ext


async def _set_status(doc_id: int, status: str, error_msg: str | None = None, chunk_count: int | None = None) -> None:
    if error_msg is not None:
        await db.aexecute(
            "UPDATE kb_document SET status=%s, error_msg=%s WHERE id=%s", (status, error_msg[:500], doc_id)
        )
    elif chunk_count is not None:
        await db.aexecute(
            "UPDATE kb_document SET status=%s, chunk_count=%s, error_msg=NULL WHERE id=%s",
            (status, chunk_count, doc_id),
        )
    else:
        await db.aexecute("UPDATE kb_document SET status=%s, error_msg=NULL WHERE id=%s", (status, doc_id))


async def process_document(doc_id: int) -> None:
    """异步入库流水线（上传后由 BackgroundTasks 触发；失败可重试）"""
    doc = await db.aquery_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
    if doc is None:
        logger.error("文档 %s 不存在，跳过入库", doc_id)
        return
    try:
        async with db.kb_write_lock(int(doc['kb_id'])):
            doc = await db.aquery_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
            if doc is None:
                return
            await _set_status(doc_id, "parsing")
    except Exception as e:
        logger.exception("文档 %s 入库启动失败", doc_id)
        await _set_status(doc_id, "failed", str(e))
        return
    path = Path(doc["file_path"])
    if not path.exists():
        await _set_status(doc_id, "failed", f"源文件缺失：{doc['file_name']}（原上传文件已被清理）")
        return
    doc_name = doc["file_name"].rsplit(".", 1)[0]
    kb_id = int(doc["kb_id"])
    try:
        # 1. 解析
        blocks = await _parse(path, doc["file_type"])

        # 2. 切片（清旧切片，重试场景可重跑）
        await _set_status(doc_id, "chunking")
        await db.aexecute("DELETE FROM kb_chunk WHERE doc_id=%s", (doc_id,))
        await elastic.delete_by_doc(doc_id)
        chunks = chunk_blocks(blocks)
        if not chunks:
            raise ValueError("文档解析后无有效内容（空文档或扫描件）")

        # 3. 向量化（当前 Embedding 供应商，≤10 条/批）
        await _set_status(doc_id, "embedding")
        vectors = await embed_texts([c["content"] for c in chunks])

        # 4. ES bulk 写入 + MySQL 元数据
        now = datetime.now(timezone.utc).isoformat()
        es_docs = []
        rows: list[tuple] = []
        for c, vec in zip(chunks, vectors, strict=True):
            uid = str(uuid.uuid4())
            es_docs.append(
                {
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "chunk_uid": uid,
                    "doc_name": doc_name,
                    "section_path": c["section_path"],
                    "chunk_no": c["chunk_no"],
                    "content": c["content"],
                    "embedding": vec,
                    "created_at": now,
                }
            )
            rows.append((uid, doc_id, c["chunk_no"], c["section_path"], c["content"], c["token_count"]))
        await elastic.bulk_index(es_docs)
        await db.aexecute_many(
            "INSERT INTO kb_chunk (chunk_uid, doc_id, chunk_no, section_path, content, token_count)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
        await _set_status(doc_id, "ready", chunk_count=len(chunks))
        logger.info("文档 %s《%s》入库完成：%d 切片", doc_id, doc["file_name"], len(chunks))
    except Exception as e:
        logger.exception("文档 %s 入库失败：%s", doc_id, e)
        await _set_status(doc_id, "failed", f"{e}")


async def _parse(path: Path, file_type: str):
    from asyncio import to_thread

    return await to_thread(parse_file, path, file_type)


async def reset_for_retry(kb_id: int, doc_id: int) -> dict:
    """失败重试前置：仅 failed 状态可触发，重置状态后由后台任务重跑流水线"""
    doc = await db.aquery_one("SELECT * FROM kb_document WHERE id=%s AND kb_id=%s", (doc_id, kb_id))
    if doc is None:
        raise ValueError("文档不存在")
    if doc["status"] != "failed":
        raise ValueError("仅失败文档可重试")
    await _set_status(doc_id, "parsing")
    doc = await db.aquery_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
    return doc  # type: ignore[return-value]


async def delete_document(kb_id: int, doc_id: int) -> None:
    """删除：先 ES 后 MySQL（孤儿切片可由重建任务清理）"""
    await elastic.delete_by_doc(doc_id)
    await db.aexecute("DELETE FROM kb_chunk WHERE doc_id=%s", (doc_id,))
    await db.aexecute("DELETE FROM kb_document WHERE id=%s AND kb_id=%s", (doc_id, kb_id))

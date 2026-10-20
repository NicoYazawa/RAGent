"""一次性脚本：从 MySQL kb_chunk 全量回填 ES 索引

场景：Docker 栈重建后 ES 卷丢失（索引 0 文档），上传源文件也不在，
但 MySQL kb_chunk 的切片内容完整。经 app 自身的 embedding / bulk_index 重建，
chunk_uid 作 _id，幂等可重跑。

选型：源文件还在时优先用同目录 resync_all_chunks.py（走完整入库流水线）；
本脚本仅用于源文件丢失、但 MySQL 切片完好的场景。
"""
import asyncio
from datetime import datetime, timezone

from app import db
from app.agent.embeddings import embed_texts
from app.es import elastic


async def main() -> None:
    await elastic.ensure_index()
    rows = await db.aquery_all(
        "SELECT c.chunk_uid, c.doc_id, c.chunk_no, c.section_path, c.content, d.kb_id, d.file_name"
        " FROM kb_chunk c JOIN kb_document d ON d.id = c.doc_id ORDER BY c.doc_id, c.chunk_no"
    )
    print(f"MySQL kb_chunk rows: {len(rows)}")
    now = datetime.now(timezone.utc).isoformat()
    docs: list[dict] = []
    batch_size = 10
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        vecs = await embed_texts([r["content"] for r in batch])
        for r, v in zip(batch, vecs):
            docs.append(
                {
                    "kb_id": int(r["kb_id"]),
                    "doc_id": int(r["doc_id"]),
                    "chunk_uid": r["chunk_uid"],
                    "doc_name": r["file_name"].rsplit(".", 1)[0],
                    "section_path": r["section_path"] or "",
                    "chunk_no": int(r["chunk_no"]),
                    "content": r["content"],
                    "embedding": v,
                    "created_at": now,
                }
            )
        print(f"embedded {min(i + batch_size, len(rows))}/{len(rows)}")
    for j in range(0, len(docs), 100):
        await elastic.bulk_index(docs[j : j + 100])
    await elastic.client.post("/kb_chunks/_refresh")
    print(f"ES count now: {await elastic.count()}")
    await elastic.close()


asyncio.run(main())

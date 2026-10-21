"""One-off script: backfill the ES index from MySQL kb_chunk.

Scenario: after the Docker stack is rebuilt the ES volume is gone (index with 0 docs) and
the uploaded source files are gone too, but the chunk text in MySQL kb_chunk is intact.
Rebuild through the app's own embedding / bulk_index with chunk_uid as _id, which is
idempotent and re-runnable.

Choice of tool: when the source files still exist prefer resync_all_chunks.py in the same
directory (it runs the full ingestion pipeline); this script covers the case where the
source files are lost but the MySQL chunks are healthy.
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

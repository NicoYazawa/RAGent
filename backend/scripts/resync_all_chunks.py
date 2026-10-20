"""重切全部已入库文档：用章级感知切片器重建 kb_chunk 与 ES 索引（幂等，可重复执行）"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.services.ingestion import process_document  # noqa: E402


async def main() -> None:
    docs = await db.aquery_all("SELECT id, kb_id, file_name, status FROM kb_document ORDER BY id")
    if not docs:
        print("没有需要重切的文档")
        return
    for d in docs:
        print(f"重切 #{d['id']} 《{d['file_name']}》（原状态 {d['status']}，原切片将自动清理）...", flush=True)
        await process_document(d["id"])
        row = await db.aquery_one(
            "SELECT status, chunk_count, error_msg FROM kb_document WHERE id=%s", (d["id"],)
        )
        msg = f"，错误：{row['error_msg']}" if row["error_msg"] else ""
        print(f"  -> {row['status']}，{row['chunk_count']} 切片{msg}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

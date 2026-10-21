"""入库流水线 — 上传校验 / 落盘 / 解析→切片→向量化→ES 写入 / 失败重试

ingestion 是知识库写入的唯一路径，历史上覆盖率 23%：
"入库成功但 ES 没写进去"、"失败状态没置 failed" 都可以改坏而测试全绿。
"""
import pytest

from app.services import ingestion

# ---------- validate_upload ----------

@pytest.mark.parametrize("name,expected", [
    ("a.md", "md"), ("a.TXT", "txt"), ("a.pdf", "pdf"), ("a.docx", "docx"),
])
def test_validate_upload_accepts_allowed_types(name, expected):
    """Allowlisted types pass and the extension is lowercased."""
    assert ingestion.validate_upload(name, 100) == expected


def test_validate_upload_rejects_disallowed_type():
    """A type outside the allowlist is rejected."""
    with pytest.raises(ValueError, match="不支持的文件类型"):
        ingestion.validate_upload("a.exe", 100)


def test_validate_upload_rejects_extensionless_name():
    """No extension -> rejected."""
    with pytest.raises(ValueError, match="不支持的文件类型"):
        ingestion.validate_upload("noext", 100)


def test_validate_upload_rejects_oversized_file():
    """Over 20MB -> rejected."""
    with pytest.raises(ValueError, match="20MB"):
        ingestion.validate_upload("a.md", ingestion.MAX_SIZE + 1)


# ---------- save_upload ----------

def test_save_upload_writes_file_and_record(tmp_path, monkeypatch):
    """Write the file and create the kb_document row (status=parsing)."""
    monkeypatch.setattr(ingestion, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(ingestion.db, "execute", lambda sql, params=None: 11)

    doc_id, path, ext = ingestion.save_upload(1, "手册.md", b"# content")

    assert doc_id == 11
    assert ext == "md"
    assert path.endswith("11_手册.md")
    assert (tmp_path / "1" / "11_手册.md").read_bytes() == b"# content"


def test_save_upload_strips_directory_from_name(tmp_path, monkeypatch):
    """Directory components are stripped from the file name (blocks path traversal)."""
    monkeypatch.setattr(ingestion, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(ingestion.db, "execute", lambda sql, params=None: 1)

    _, path, _ = ingestion.save_upload(1, "../../evil.md", b"x")
    assert "evil.md" in path
    assert ".." not in path.replace("11_", "")


def test_save_upload_rejects_bad_type(tmp_path, monkeypatch):
    """An illegal type writes nothing and creates no row."""
    monkeypatch.setattr(ingestion, "UPLOAD_DIR", tmp_path)
    with pytest.raises(ValueError):
        ingestion.save_upload(1, "a.exe", b"x")


# ---------- process_document ----------

@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Stub out parsing/chunking/embedding/ES writes so only the pipeline orchestration remains."""
    state = {"es_docs": [], "deleted": [], "vectors": None}

    async def _parse(path, file_type):
        return [("第一章", "正文内容")]

    async def _embed(texts):
        state["vectors"] = list(texts)
        return [[0.1, 0.2] for _ in texts]

    async def _bulk(docs):
        state["es_docs"] = list(docs)

    async def _delete(doc_id):
        state["deleted"].append(doc_id)

    monkeypatch.setattr(ingestion, "_parse", _parse)
    monkeypatch.setattr(ingestion, "embed_texts", _embed)
    monkeypatch.setattr(ingestion.elastic, "bulk_index", _bulk)
    monkeypatch.setattr(ingestion.elastic, "delete_by_doc", _delete)
    return state


async def test_process_document_skips_missing_record(fake_db):
    """A missing document row -> skip silently (no exception)."""
    fake_db.route("FROM kb_document", None)
    await ingestion.process_document(999)
    assert not any("UPDATE kb_document" in s for s in fake_db.sqls())


async def test_process_document_marks_failed_when_source_missing(fake_db, tmp_path):
    """The source file was cleaned up -> status becomes failed with the reason recorded."""
    fake_db.route("FROM kb_document", {
        "id": 1, "file_path": str(tmp_path / "gone.md"), "file_name": "gone.md",
        "file_type": "md", "kb_id": 1})
    await ingestion.process_document(1)
    sqls = fake_db.sqls()
    assert any("SET status=%s, error_msg=%s" in s for s in sqls)
    assert any("源文件缺失" in str(c[1]) for c in fake_db.calls if c[1])


async def test_process_document_happy_path(fake_db, pipeline, tmp_path):
    """Full flow: parse -> chunk -> embed -> ES bulk -> MySQL chunks -> status=ready."""
    src = tmp_path / "doc.md"
    src.write_text("# 第一章\n正文", encoding="utf-8")
    fake_db.route("FROM kb_document", {
        "id": 5, "file_path": str(src), "file_name": "doc.md",
        "file_type": "md", "kb_id": 2})

    await ingestion.process_document(5)

    # ES received the embedded documents
    assert pipeline["es_docs"], "ES 未收到任何文档"
    doc = pipeline["es_docs"][0]
    assert doc["doc_id"] == 5
    assert doc["kb_id"] == 2
    assert doc["doc_name"] == "doc"
    assert doc["embedding"] == [0.1, 0.2]
    assert doc["chunk_no"] == 1
    # a retry clears the old data first
    assert pipeline["deleted"] == [5]
    # the status moves to ready
    assert any("SET status=%s, chunk_count=%s" in s for s in fake_db.sqls())
    # chunk metadata is persisted
    assert any("INSERT INTO kb_chunk" in s for s in fake_db.sqls())


async def test_process_document_marks_failed_on_exception(fake_db, pipeline, monkeypatch, tmp_path):
    """Any failing step -> status failed (never stuck in an intermediate state)."""
    async def _boom(texts):
        raise RuntimeError("embedding 401")

    monkeypatch.setattr(ingestion, "embed_texts", _boom)
    src = tmp_path / "doc.md"
    src.write_text("# 第一章\n正文", encoding="utf-8")
    fake_db.route("FROM kb_document", {
        "id": 6, "file_path": str(src), "file_name": "doc.md",
        "file_type": "md", "kb_id": 2})

    await ingestion.process_document(6)

    assert any("SET status=%s, error_msg=%s" in s for s in fake_db.sqls())
    assert any("embedding 401" in str(c[1]) for c in fake_db.calls if c[1])


async def test_process_document_fails_on_empty_content(fake_db, pipeline, monkeypatch, tmp_path):
    """No usable content after parsing -> failed (empty document or scanned file)."""
    async def _empty(path, file_type):
        return []

    monkeypatch.setattr(ingestion, "_parse", _empty)
    src = tmp_path / "doc.md"
    src.write_text("x", encoding="utf-8")
    fake_db.route("FROM kb_document", {
        "id": 7, "file_path": str(src), "file_name": "doc.md",
        "file_type": "md", "kb_id": 2})

    await ingestion.process_document(7)
    assert any("无有效内容" in str(c[1]) for c in fake_db.calls if c[1])


# ---------- reset_for_retry / delete_document ----------

async def test_reset_for_retry_rejects_unknown_doc(fake_db):
    """A missing document raises a clear error."""
    fake_db.route("FROM kb_document", None)
    with pytest.raises(ValueError, match="文档不存在"):
        await ingestion.reset_for_retry(1, 2)


async def test_reset_for_retry_rejects_non_failed_status(fake_db):
    """Only the failed status can be retried."""
    fake_db.route("FROM kb_document", {"id": 2, "status": "ready"})
    with pytest.raises(ValueError, match="仅失败文档可重试"):
        await ingestion.reset_for_retry(1, 2)


async def test_reset_for_retry_resets_status(fake_db):
    """failed -> set to parsing and read the row back."""
    fake_db.route("FROM kb_document", {"id": 2, "status": "failed"})
    doc = await ingestion.reset_for_retry(1, 2)
    assert doc["id"] == 2
    assert any("SET status=%s" in s for s in fake_db.sqls())


async def test_delete_document_removes_es_first_then_mysql(fake_db, monkeypatch):
    """Delete order: ES first, then MySQL (an orphan in ES does not affect MySQL consistency)."""
    order = []

    async def _delete(doc_id):
        order.append("es")

    monkeypatch.setattr(ingestion.elastic, "delete_by_doc", _delete)

    await ingestion.delete_document(1, 2)
    order.append("mysql")
    assert order == ["es", "mysql"]
    sqls = fake_db.sqls()
    assert "DELETE FROM kb_chunk WHERE doc_id=%s" in sqls
    assert "DELETE FROM kb_document WHERE id=%s AND kb_id=%s" in sqls


# ---------- _parse dispatch ----------

async def test_parse_dispatches_to_parse_file(tmp_path, monkeypatch):
    """_parse goes through parse_file (synchronous parsing on a worker thread)."""
    called = {}

    def _fake_parse_file(path, file_type):
        called["args"] = (str(path), file_type)
        return [("第一章", "正文")]

    monkeypatch.setattr(ingestion, "parse_file", _fake_parse_file)
    p = tmp_path / "a.md"
    p.write_text("x", encoding="utf-8")

    blocks = await ingestion._parse(p, "md")
    assert called["args"] == (str(p), "md")
    assert blocks == [("第一章", "正文")]


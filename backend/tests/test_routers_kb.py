"""知识库管理 API — 库 CRUD / 文档上传删除 / 切片分页 / 引用溯源

routers/kb.py 历史上覆盖率 29%：HTTP 状态码、重名冲突、
分页边界、404 分支都没有任何测试。
"""
import io

# ---------- 知识库 ----------

def test_list_kbs_returns_rows(api, fake_db):
    """知识库列表带 ready 文档数与切片数统计"""
    fake_db.route("FROM kb_database k", [
        {"id": 1, "name": "制度库", "doc_count": 3, "chunk_count": 120}])
    r = api.get("/api/admin/kb")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["name"] == "制度库"
    assert body[0]["chunk_count"] == 120


def test_create_kb_requires_name(api, fake_db):
    """空名称 → 400"""
    r = api.post("/api/admin/kb", json={"name": "   "})
    assert r.status_code == 400


def test_create_kb_rejects_duplicate_name(api, fake_db):
    """重名 → 409"""
    fake_db.route("SELECT id FROM kb_database", {"id": 3})
    r = api.post("/api/admin/kb", json={"name": "制度库"})
    assert r.status_code == 409


def test_create_kb_inserts_and_returns_row(api, fake_db):
    """创建成功 → 201 并回读整行"""
    fake_db.route("SELECT id FROM kb_database", None)
    fake_db.route("FROM kb_database k WHERE k.id", {"id": 9, "name": "新库", "doc_count": 0})
    r = api.post("/api/admin/kb", json={"name": "新库", "description": "描述"})
    assert r.status_code == 201
    assert r.json()["name"] == "新库"


# ---------- 文档 ----------

def test_list_documents(api, fake_db):
    """文档列表按创建时间倒序"""
    fake_db.route("FROM kb_document", [{"id": 1, "file_name": "a.md"}])
    r = api.get("/api/admin/kb/1/documents")
    assert r.status_code == 200
    assert r.json()[0]["file_name"] == "a.md"


def test_upload_document_rejects_unknown_kb(api, fake_db):
    """知识库不存在 → 404"""
    fake_db.route("SELECT id FROM kb_database", None)
    r = api.post("/api/admin/kb/9/documents",
                 files={"file": ("a.md", io.BytesIO(b"x"), "text/markdown")})
    assert r.status_code == 404


def test_upload_document_rejects_bad_type(api, fake_db, tmp_path, monkeypatch):
    """不支持的文件类型 → 400"""
    from app.services import ingestion

    monkeypatch.setattr(ingestion, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(ingestion.db, "execute", lambda sql, params=None: 1)
    fake_db.route("SELECT id FROM kb_database", {"id": 1})
    r = api.post("/api/admin/kb/1/documents",
                 files={"file": ("a.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert r.status_code == 400


def test_upload_document_accepts_valid_file(api, fake_db, tmp_path, monkeypatch):
    """合法上传 → 202 并返回文档记录"""
    from app.services import ingestion

    async def _no_pipeline(doc_id):
        return None

    monkeypatch.setattr(ingestion, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(ingestion.db, "execute", lambda sql, params=None: 12)
    monkeypatch.setattr(ingestion, "process_document", _no_pipeline)
    fake_db.route("SELECT id FROM kb_database", {"id": 1})
    fake_db.route("FROM kb_document WHERE id=%s", {"id": 12, "status": "parsing"})

    r = api.post("/api/admin/kb/1/documents",
                 files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")})
    assert r.status_code == 202
    assert r.json()["id"] == 12


def test_delete_document_404_when_missing(api, fake_db):
    """文档不存在 → 404"""
    fake_db.route("FROM kb_document WHERE id=%s AND kb_id=%s", None)
    r = api.delete("/api/admin/kb/1/documents/9")
    assert r.status_code == 404


def test_delete_document_success(api, fake_db, monkeypatch):
    """删除成功 → 200"""
    from app.services import ingestion

    async def _noop(kb_id, doc_id):
        return None

    monkeypatch.setattr(ingestion, "delete_document", _noop)
    fake_db.route("FROM kb_document WHERE id=%s AND kb_id=%s", {"id": 9})
    r = api.delete("/api/admin/kb/1/documents/9")
    assert r.status_code == 200
    assert r.json() == {"deleted": 9}


def test_retry_document_rejects_non_failed(api, fake_db, monkeypatch):
    """非 failed 文档重试 → 400"""
    from app.services import ingestion

    async def _raise(kb_id, doc_id):
        raise ValueError("仅失败文档可重试")

    monkeypatch.setattr(ingestion, "reset_for_retry", _raise)
    r = api.post("/api/admin/kb/1/documents/9/retry")
    assert r.status_code == 400


def test_retry_document_success(api, fake_db, monkeypatch):
    """重试成功 → 202 并回传文档行"""
    from app.services import ingestion

    async def _ok(kb_id, doc_id):
        return {"id": 9, "status": "parsing"}

    async def _no_pipeline(doc_id):
        return None

    monkeypatch.setattr(ingestion, "reset_for_retry", _ok)
    monkeypatch.setattr(ingestion, "process_document", _no_pipeline)
    r = api.post("/api/admin/kb/1/documents/9/retry")
    assert r.status_code == 202
    assert r.json()["id"] == 9


# ---------- 切片分页 ----------

def test_list_document_chunks_404_when_missing(api, fake_db):
    """文档不存在 → 404"""
    fake_db.route("FROM kb_document WHERE id=%s AND kb_id=%s", None)
    r = api.get("/api/admin/kb/1/documents/9/chunks")
    assert r.status_code == 404


def test_list_document_chunks_400_when_not_ready(api, fake_db):
    """文档未就绪 → 400"""
    fake_db.route("FROM kb_document WHERE id=%s AND kb_id=%s", {"id": 9, "status": "parsing"})
    r = api.get("/api/admin/kb/1/documents/9/chunks")
    assert r.status_code == 400


def test_list_document_chunks_returns_page(api, fake_db):
    """切片分页返回 items / total / page / page_size"""
    fake_db.route("FROM kb_document WHERE id=%s AND kb_id=%s", {"id": 9, "status": "ready"})
    # 通用路由先注册，具体路由后注册（后者优先）
    fake_db.route("FROM kb_chunk", [{"id": 1, "chunk_no": 1, "content": "甲"}])
    fake_db.route("COUNT(*) AS n FROM kb_chunk", {"n": 25})

    r = api.get("/api/admin/kb/1/documents/9/chunks?page=2&page_size=8")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 25
    assert body["page"] == 2
    assert body["page_size"] == 8
    assert body["items"][0]["content"] == "甲"


def test_list_document_chunks_clamps_pagination(api, fake_db):
    """分页参数越界被夹紧（page≥1，page_size 1..50）"""
    fake_db.route("FROM kb_document WHERE id=%s AND kb_id=%s", {"id": 9, "status": "ready"})
    fake_db.route("FROM kb_chunk", [])
    fake_db.route("COUNT(*) AS n FROM kb_chunk", {"n": 0})

    r = api.get("/api/admin/kb/1/documents/9/chunks?page=0&page_size=999")
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 50


# ---------- 引用溯源 ----------

def test_get_chunk_by_citation_404_when_doc_missing(api, fake_db):
    """引用定位：文档不存在 → 404"""
    fake_db.route("WHERE status='ready'", [])
    r = api.get("/api/admin/chunks/by-citation?doc_name=手册&chunk_no=1")
    assert r.status_code == 404


def test_get_chunk_by_citation_404_when_chunk_missing(api, fake_db):
    """引用定位：切片不存在 → 404"""
    fake_db.route("WHERE status='ready'", [{"id": 3, "file_name": "手册.md"}])
    fake_db.route("FROM kb_chunk", None)
    r = api.get("/api/admin/chunks/by-citation?doc_name=手册&chunk_no=7")
    assert r.status_code == 404


def test_get_chunk_by_citation_returns_doc_and_chunk(api, fake_db):
    """引用定位成功 → 同时返回文档与切片"""
    fake_db.route("WHERE status='ready'", [{"id": 3, "file_name": "手册.md"}])
    fake_db.route("FROM kb_chunk", {"id": 30, "chunk_no": 1, "content": "迟到认定"})
    r = api.get("/api/admin/chunks/by-citation?doc_name=手册&chunk_no=1")
    assert r.status_code == 200
    body = r.json()
    assert body["doc"]["id"] == 3
    assert body["chunk"]["content"] == "迟到认定"

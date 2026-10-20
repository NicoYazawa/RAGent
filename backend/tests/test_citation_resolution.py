"""Citation locators must identify the original document, never a newer namesake."""


def test_document_id_and_chunk_uid_take_precedence_over_name(api, fake_db):
    fake_db.route("FROM kb_document WHERE id=%s", {
        "id": 10, "kb_id": 2, "file_name": "manual.v2.md", "status": "ready",
    })
    fake_db.route("FROM kb_chunk", {"doc_id": 10, "chunk_no": 3, "chunk_uid": "original", "content": "original"})
    response = api.get("/api/admin/chunks/by-citation?doc_name=wrong&chunk_no=3&doc_id=10&kb_id=2&chunk_uid=original")
    assert response.status_code == 200
    assert response.json()["doc"]["id"] == 10
    chunk_sql, params = next((sql, params) for sql, params in fake_db.calls if "FROM kb_chunk" in sql)
    assert "chunk_uid=%s" in chunk_sql
    assert params == (10, 3, "original")


def test_missing_explicit_document_never_falls_back_to_name(api, fake_db):
    fake_db.route("FROM kb_document WHERE id=%s", None)
    response = api.get("/api/admin/chunks/by-citation?doc_name=manual&chunk_no=1&doc_id=99")
    assert response.status_code == 404
    assert all("SUBSTRING_INDEX" not in sql for sql in fake_db.sqls())


def test_citation_rejects_wrong_kb(api, fake_db):
    fake_db.route("FROM kb_document WHERE id=%s", {"id": 10, "kb_id": 2, "status": "ready"})
    response = api.get("/api/admin/chunks/by-citation?doc_name=manual&chunk_no=1&doc_id=10&kb_id=3")
    assert response.status_code == 404
    assert not any("FROM kb_chunk" in sql for sql in fake_db.sqls())


def test_legacy_same_name_is_ambiguous(api, fake_db):
    fake_db.route("WHERE status='ready'", [{"id": 10}, {"id": 20}])
    response = api.get("/api/admin/chunks/by-citation?doc_name=manual&chunk_no=1")
    assert response.status_code == 409


def test_legacy_multidot_filename_matches_full_stem(api, fake_db):
    def document(params):
        assert params == ("manual.v2",)
        return [{"id": 10, "file_name": "manual.v2.md"}]

    fake_db.route("WHERE status='ready'", document)
    fake_db.route("FROM kb_chunk", {"doc_id": 10, "chunk_no": 1})
    response = api.get("/api/admin/chunks/by-citation?doc_name=manual.v2&chunk_no=1")
    assert response.status_code == 200
    assert not any("SUBSTRING_INDEX(file_name, '.', 1)" in sql for sql in fake_db.sqls())


def test_stale_chunk_uid_does_not_resolve_reprocessed_chunk(api, fake_db):
    fake_db.route("FROM kb_document WHERE id=%s", {"id": 10, "kb_id": 2, "status": "ready"})
    fake_db.route("FROM kb_chunk", None)
    response = api.get("/api/admin/chunks/by-citation?doc_name=manual&chunk_no=1&doc_id=10&chunk_uid=old")
    assert response.status_code == 404

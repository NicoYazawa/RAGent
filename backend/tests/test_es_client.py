"""Elasticsearch 客户端 — 索引维度 / kNN / BM25 / kb_id 隔离 / bulk 写入

es.py 历史上覆盖率 40%：kb_id 隔离过滤、bulk 失败检测、索引维度读取
都可以改坏而测试全绿。其中 kb_id 隔离失效 = 跨知识库数据串库。
"""
import json

import httpx
import pytest

from app.es import INDEX, Elastic


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock.es")


def _es(handler) -> Elastic:
    es = Elastic()
    es.client = _client(handler)
    return es


# ---------- index_dims ----------

async def test_index_dims_reads_mapping():
    """Read the dense_vector dims from the mapping."""
    def handler(req):
        return httpx.Response(200, json={"kb_chunks": {"mappings": {"properties": {
            "embedding": {"type": "dense_vector", "dims": 1024}}}}})

    assert await _es(handler).index_dims() == 1024


async def test_index_dims_none_when_index_absent():
    """Index missing -> None."""
    def handler(req):
        return httpx.Response(404, json={})

    assert await _es(handler).index_dims() is None


async def test_index_dims_none_on_malformed_mapping():
    """Malformed mapping -> None (no exception that would break the startup self-check)."""
    def handler(req):
        return httpx.Response(200, json={"kb_chunks": {"mappings": {"properties": {}}}})

    assert await _es(handler).index_dims() is None


async def test_index_dims_raises_for_other_errors():
    """A non-404 error status -> raise (the caller degrades)."""
    def handler(req):
        return httpx.Response(500, text="boom")

    with pytest.raises(httpx.HTTPStatusError):
        await _es(handler).index_dims()


# ---------- kb_id isolation filter ----------

def test_kb_filter_match_all_when_no_ids():
    """No knowledge base given -> match_all."""
    assert Elastic._kb_filter(None) == {"match_all": {}}


def test_kb_filter_term_for_single_id():
    """One knowledge base -> term."""
    assert Elastic._kb_filter([3]) == {"term": {"kb_id": 3}}


def test_kb_filter_terms_for_multiple_ids():
    """Several knowledge bases -> terms."""
    assert Elastic._kb_filter([3, 7]) == {"terms": {"kb_id": [3, 7]}}


async def test_knn_search_sends_kb_filter():
    """The kNN request body must carry the kb_id filter (losing it means cross-base leakage)."""
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"hits": {"hits": []}})

    await _es(handler).knn_search([0.1], [5], k=3)
    assert seen["body"]["knn"]["filter"] == {"term": {"kb_id": 5}}
    assert "query" not in seen["body"]
    assert seen["body"]["knn"]["k"] == 3
    assert seen["body"]["size"] == 3


@pytest.mark.parametrize("ids, expected", [
    (None, {"match_all": {}}),
    ([3, 7], {"terms": {"kb_id": [3, 7]}}),
])
async def test_knn_filters_candidates_before_ranking(ids, expected):
    def handler(req):
        body = json.loads(req.content)
        assert body["knn"]["filter"] == expected
        assert "query" not in body
        return httpx.Response(200, json={"hits": {"hits": []}})

    await _es(handler).knn_search([0.1], ids)


async def test_knn_search_maps_hits():
    """Hits map to {_score -> score, ..._source}."""
    def handler(req):
        return httpx.Response(200, json={"hits": {"hits": [
            {"_score": 0.87, "_source": {"doc_name": "手册", "content": "c", "chunk_no": 2}}]}})

    hits = await _es(handler).knn_search([0.1], None, k=5)
    assert hits == [{"score": 0.87, "doc_name": "手册", "content": "c", "chunk_no": 2}]


async def test_knn_search_null_score_becomes_zero():
    """A null _score becomes 0.0."""
    def handler(req):
        return httpx.Response(200, json={"hits": {"hits": [{"_score": None, "_source": {}}]}})

    hits = await _es(handler).knn_search([0.1], None, k=5)
    assert hits[0]["score"] == 0.0


async def test_match_search_sends_bm25_body():
    """BM25 request body: multi_match with section_path boosting plus the kb filter."""
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"hits": {"hits": []}})

    await _es(handler).match_search("迟到", [1, 2], k=4)
    mm = seen["body"]["query"]["bool"]["must"]["multi_match"]
    assert mm["query"] == "迟到"
    assert mm["fields"] == ["content^1", "section_path^2"]
    assert seen["body"]["query"]["bool"]["filter"] == {"terms": {"kb_id": [1, 2]}}
    assert seen["body"]["size"] == 4


# ---------- Index creation / analyzer probing ----------

async def test_probe_analyzer_detects_ik():
    """IK analyzer available -> ik_max_word."""
    def handler(req):
        return httpx.Response(200, json={})

    assert await _es(handler).probe_analyzer() == "ik_max_word"


async def test_probe_analyzer_falls_back_to_standard():
    """IK unavailable (error or non-200) -> standard."""
    def handler(req):
        raise httpx.ConnectError("nope")

    assert await _es(handler).probe_analyzer() == "standard"

    def handler2(req):
        return httpx.Response(400, json={})

    assert await _es(handler2).probe_analyzer() == "standard"


async def test_ensure_index_skips_when_exists():
    """Index already exists -> do not recreate it."""
    called = {"put": 0}

    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(200)
        called["put"] += 1
        return httpx.Response(200, json={})

    await _es(handler).ensure_index()
    assert called["put"] == 0


async def test_ensure_index_creates_with_dims():
    """Index missing -> create it with the active embedding dims."""
    seen = {}

    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(404)
        if req.method == "PUT":
            seen["mapping"] = json.loads(req.content)
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    from app.config import settings

    await _es(handler).ensure_index()
    props = seen["mapping"]["mappings"]["properties"]
    assert props["embedding"]["dims"] == settings.resolved_embed_dims
    assert props["embedding"]["similarity"] == "cosine"
    assert props["kb_id"]["type"] == "integer"


async def test_ensure_index_raises_on_put_failure():
    """Index creation fails -> raise (lifespan turns it into a degraded startup)."""
    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(404)
        if req.method == "PUT":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={})

    with pytest.raises(httpx.HTTPStatusError):
        await _es(handler).ensure_index()


# ---------- bulk / delete / count / ping ----------

async def test_bulk_index_sends_ndjson():
    """The bulk request body is NDJSON with two lines per document."""
    seen = {}

    def handler(req):
        seen["body"] = req.content.decode("utf-8")
        return httpx.Response(200, json={"errors": False})

    await _es(handler).bulk_index([
        {"chunk_uid": "u1", "content": "甲"},
        {"chunk_uid": "u2", "content": "乙"},
    ])
    lines = [l for l in seen["body"].strip().split("\n") if l]
    assert len(lines) == 4
    assert json.loads(lines[0])["index"]["_index"] == INDEX
    assert json.loads(lines[0])["index"]["_id"] == "u1"
    assert json.loads(lines[1])["content"] == "甲"


async def test_bulk_index_raises_on_partial_failure():
    """A partial bulk failure must raise (otherwise data is lost silently)."""
    def handler(req):
        return httpx.Response(200, json={"errors": True, "items": [{"index": {"error": "x"}}]})

    with pytest.raises(RuntimeError, match="失败项"):
        await _es(handler).bulk_index([{"chunk_uid": "u1"}])


async def test_delete_by_doc_posts_delete_by_query():
    """Deleting by doc_id goes through _delete_by_query."""
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={})

    await _es(handler).delete_by_doc(9)
    assert "_delete_by_query" in seen["url"]
    assert seen["body"]["query"] == {"term": {"doc_id": 9}}
    assert seen["body"]["conflicts"] == "proceed"


async def test_count_returns_document_count():
    """count returns the total number of documents."""
    def handler(req):
        return httpx.Response(200, json={"count": 156})

    assert await _es(handler).count() == 156


async def test_count_defaults_to_zero():
    """A missing count field becomes 0."""
    def handler(req):
        return httpx.Response(200, json={})

    assert await _es(handler).count() == 0


async def test_ping_true_on_200():
    """ping：200 → True"""
    def handler(req):
        return httpx.Response(200, json={})

    assert await _es(handler).ping() is True


async def test_ping_false_on_error():
    """ping: connection error -> False (no exception, so health can degrade instead of 500)."""
    def handler(req):
        raise httpx.ConnectError("down")

    assert await _es(handler).ping() is False


async def test_ping_false_on_non_200():
    """ping: non-200 -> False."""
    def handler(req):
        return httpx.Response(503, json={})

    assert await _es(handler).ping() is False


async def test_close_releases_client():
    """close releases the httpx client."""
    es = _es(lambda r: httpx.Response(200, json={}))
    await es.close()
    assert es.client.is_closed

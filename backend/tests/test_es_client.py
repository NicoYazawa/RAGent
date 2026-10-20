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
    """从 mapping 读取 dense_vector 维度"""
    def handler(req):
        return httpx.Response(200, json={"kb_chunks": {"mappings": {"properties": {
            "embedding": {"type": "dense_vector", "dims": 1024}}}}})

    assert await _es(handler).index_dims() == 1024


async def test_index_dims_none_when_index_absent():
    """索引不存在 → None"""
    def handler(req):
        return httpx.Response(404, json={})

    assert await _es(handler).index_dims() is None


async def test_index_dims_none_on_malformed_mapping():
    """mapping 异常 → None（不得抛异常打断启动自检）"""
    def handler(req):
        return httpx.Response(200, json={"kb_chunks": {"mappings": {"properties": {}}}})

    assert await _es(handler).index_dims() is None


async def test_index_dims_raises_for_other_errors():
    """非 404 的错误状态码 → 抛错（由调用方降级）"""
    def handler(req):
        return httpx.Response(500, text="boom")

    with pytest.raises(httpx.HTTPStatusError):
        await _es(handler).index_dims()


# ---------- kb_id 隔离过滤 ----------

def test_kb_filter_match_all_when_no_ids():
    """不指定知识库 → match_all"""
    assert Elastic._kb_filter(None) == {"match_all": {}}


def test_kb_filter_term_for_single_id():
    """单库 → term"""
    assert Elastic._kb_filter([3]) == {"term": {"kb_id": 3}}


def test_kb_filter_terms_for_multiple_ids():
    """多库 → terms"""
    assert Elastic._kb_filter([3, 7]) == {"terms": {"kb_id": [3, 7]}}


async def test_knn_search_sends_kb_filter():
    """kNN 请求体必须带 kb_id 过滤（隔离失效 = 串库）"""
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
    """命中结果映射为 {_score→score, ..._source}"""
    def handler(req):
        return httpx.Response(200, json={"hits": {"hits": [
            {"_score": 0.87, "_source": {"doc_name": "手册", "content": "c", "chunk_no": 2}}]}})

    hits = await _es(handler).knn_search([0.1], None, k=5)
    assert hits == [{"score": 0.87, "doc_name": "手册", "content": "c", "chunk_no": 2}]


async def test_knn_search_null_score_becomes_zero():
    """_score 为 null → 0.0"""
    def handler(req):
        return httpx.Response(200, json={"hits": {"hits": [{"_score": None, "_source": {}}]}})

    hits = await _es(handler).knn_search([0.1], None, k=5)
    assert hits[0]["score"] == 0.0


async def test_match_search_sends_bm25_body():
    """BM25 请求体：multi_match + section_path 加权 + kb 过滤"""
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


# ---------- 索引创建 / 分词器探测 ----------

async def test_probe_analyzer_detects_ik():
    """IK 分词器可用 → ik_max_word"""
    def handler(req):
        return httpx.Response(200, json={})

    assert await _es(handler).probe_analyzer() == "ik_max_word"


async def test_probe_analyzer_falls_back_to_standard():
    """IK 不可用（报错/非 200）→ standard"""
    def handler(req):
        raise httpx.ConnectError("nope")

    assert await _es(handler).probe_analyzer() == "standard"

    def handler2(req):
        return httpx.Response(400, json={})

    assert await _es(handler2).probe_analyzer() == "standard"


async def test_ensure_index_skips_when_exists():
    """索引已存在 → 不重建"""
    called = {"put": 0}

    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(200)
        called["put"] += 1
        return httpx.Response(200, json={})

    await _es(handler).ensure_index()
    assert called["put"] == 0


async def test_ensure_index_creates_with_dims():
    """索引不存在 → 按当前 embedding 维度建索引"""
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
    """建索引失败 → 抛错（由 lifespan 降级为服务降级启动）"""
    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(404)
        if req.method == "PUT":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={})

    with pytest.raises(httpx.HTTPStatusError):
        await _es(handler).ensure_index()


# ---------- bulk / 删除 / 计数 / ping ----------

async def test_bulk_index_sends_ndjson():
    """bulk 请求体是 NDJSON，每条文档两行"""
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
    """bulk 部分失败必须报错（否则静默丢数据）"""
    def handler(req):
        return httpx.Response(200, json={"errors": True, "items": [{"index": {"error": "x"}}]})

    with pytest.raises(RuntimeError, match="失败项"):
        await _es(handler).bulk_index([{"chunk_uid": "u1"}])


async def test_delete_by_doc_posts_delete_by_query():
    """按 doc_id 删除走 _delete_by_query"""
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
    """count 返回文档总数"""
    def handler(req):
        return httpx.Response(200, json={"count": 156})

    assert await _es(handler).count() == 156


async def test_count_defaults_to_zero():
    """count 字段缺失 → 0"""
    def handler(req):
        return httpx.Response(200, json={})

    assert await _es(handler).count() == 0


async def test_ping_true_on_200():
    """ping：200 → True"""
    def handler(req):
        return httpx.Response(200, json={})

    assert await _es(handler).ping() is True


async def test_ping_false_on_error():
    """ping：连接异常 → False（不抛异常，health 才能降级而非 500）"""
    def handler(req):
        raise httpx.ConnectError("down")

    assert await _es(handler).ping() is False


async def test_ping_false_on_non_200():
    """ping：非 200 → False"""
    def handler(req):
        return httpx.Response(503, json={})

    assert await _es(handler).ping() is False


async def test_close_releases_client():
    """close 释放 httpx 客户端"""
    es = _es(lambda r: httpx.Response(200, json={}))
    await es.close()
    assert es.client.is_closed

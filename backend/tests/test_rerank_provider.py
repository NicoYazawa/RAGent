"""HttpRerank — DashScope / flat 两种形状的请求与解析契约"""
import json

import httpx
import pytest

from app.providers.base import RerankProvider
from app.providers.rerank_http import HttpRerank


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.local")


def _rerank(handler, shape: str = "dashscope") -> HttpRerank:
    return HttpRerank(
        name="qwen",
        model="gte-rerank-v2",
        base_url="https://mock.local",
        path="/api/v1/services/rerank/text-rerank/text-rerank" if shape == "dashscope" else "/rerank",
        api_key="sk-x",
        shape=shape,
        client=_client(handler),
    )


async def test_dashscope_shape_request_and_parse():
    """DashScope shape: nested input plus parameters.top_n; the response is output.results sorted by score."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"output": {"results": [
            {"index": 2, "relevance_score": 0.71},
            {"index": 0, "relevance_score": 0.93},
        ]}, "usage": {"total_tokens": 42}})

    rr = _rerank(handler)
    out = await rr.rerank("迟到怎么认定", ["doc0", "doc1", "doc2"], 2)

    assert seen["url"].endswith("/api/v1/services/rerank/text-rerank/text-rerank")
    assert seen["auth"] == "Bearer sk-x"
    assert seen["body"]["model"] == "gte-rerank-v2"
    assert seen["body"]["input"]["query"] == "迟到怎么认定"
    assert seen["body"]["input"]["documents"] == ["doc0", "doc1", "doc2"]
    assert seen["body"]["parameters"]["top_n"] == 2
    assert seen["body"]["parameters"]["return_documents"] is False
    assert out == [(0, 0.93), (2, 0.71)]


async def test_flat_shape_request_and_parse():
    """flat shape (same as SiliconFlow/Jina/Cohere): top-level fields plus top-level results."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.5}]})

    rr = _rerank(handler, shape="flat")
    out = await rr.rerank("q", ["doc0", "doc1"], 1)

    assert seen["body"]["model"] == "gte-rerank-v2"
    assert seen["body"]["query"] == "q"
    assert seen["body"]["documents"] == ["doc0", "doc1"]
    assert seen["body"]["top_n"] == 1
    assert out == [(1, 0.5)]


async def test_empty_results_returns_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"results": []}})

    assert await _rerank(handler).rerank("q", ["a"], 1) == []


async def test_empty_documents_skips_http():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"output": {"results": []}})

    assert await _rerank(handler).rerank("q", [], 1) == []
    assert called["n"] == 0  # no request is sent without candidates


async def test_non_200_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(httpx.HTTPStatusError):
        await _rerank(handler).rerank("q", ["a"], 1)


async def test_result_count_capped_by_top_n():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"results": [
            {"index": i, "relevance_score": 1.0 - i * 0.1} for i in range(5)
        ]}})

    out = await _rerank(handler).rerank("q", ["a", "b", "c", "d", "e"], 2)
    assert len(out) == 2
    assert out[0][0] == 0


def test_protocol_structural_match():
    assert isinstance(_rerank(lambda r: httpx.Response(200, json={})), RerankProvider)


async def test_malformed_result_item_is_skipped():
    """An entry with invalid (non-numeric) fields is skipped without affecting the others."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"results": [
            {"index": "not-a-number", "relevance_score": 0.5},
            {"index": 1, "relevance_score": 0.9},
        ]}})

    out = await _rerank(handler).rerank("q", ["a", "b"], 5)
    assert out == [(1, 0.9)]


async def test_negative_index_is_dropped():
    """A negative index is invalid (no out-of-range position is returned)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"results": [
            {"index": -1, "relevance_score": 0.9},
        ]}})

    assert await _rerank(handler).rerank("q", ["a"], 5) == []


def test_rerank_creates_its_own_client_when_not_injected():
    """Without an injected client one is built from base_url and reused."""
    rr = HttpRerank(name="qwen", model="gte-rerank-v2", base_url="https://api.example.com/v1",
                    path="/rerank", api_key="sk-x", shape="flat")
    client = rr._get_client()
    assert client is not None
    assert str(client.base_url).rstrip("/") == "https://api.example.com/v1"
    assert rr._get_client() is client


async def test_rerank_aclose_releases_owned_client():
    """A self-built client is closed and cleared by aclose."""
    rr = HttpRerank(name="qwen", model="gte-rerank-v2", base_url="https://api.example.com/v1",
                    path="/rerank", api_key="sk-x", shape="flat")
    client = rr._get_client()
    await rr.aclose()
    assert client.is_closed
    assert rr._client is None


async def test_rerank_aclose_keeps_injected_client():
    """An injected client is not closed by the facade (the caller owns it)."""
    rr = _rerank(lambda r: httpx.Response(200, json={"output": {"results": []}}))
    await rr.aclose()
    assert rr._client is not None

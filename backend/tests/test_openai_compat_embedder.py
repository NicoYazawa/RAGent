"""OpenAICompatEmbedder — 批处理 / 重试 / 截断 / dimensions 参数"""
import httpx
import pytest

from app.providers.openai_compat import OpenAICompatEmbedder


def _embedder(handler) -> OpenAICompatEmbedder:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.local")
    return OpenAICompatEmbedder("qwen", "text-embedding-v4", 1024, "https://mock.local", "sk-x", client=client)


def _resp(n: int) -> httpx.Response:
    return httpx.Response(200, json={"data": [
        {"index": i, "embedding": [float(i)] * 1024} for i in range(n)
    ]})


def test_embedder_creates_its_own_client_when_not_injected():
    """未注入 client 时按 base_url 自建（并复用同一实例）"""
    emb = OpenAICompatEmbedder("qwen", "text-embedding-v4", 1024,
                                "https://api.example.com/v1", "sk-x")
    client = emb._get_client()
    assert client is not None
    assert str(client.base_url).rstrip("/") == "https://api.example.com/v1"
    assert emb._get_client() is client


async def test_embedder_aclose_releases_owned_client():
    """自建 client 在 aclose 后被关闭并置空"""
    emb = OpenAICompatEmbedder("qwen", "text-embedding-v4", 1024,
                                "https://api.example.com/v1", "sk-x")
    client = emb._get_client()
    await emb.aclose()
    assert client.is_closed
    assert emb._client is None


async def test_embedder_aclose_keeps_injected_client():
    """注入的 client 不由门面关闭（所有权归调用方）"""
    emb = _embedder(lambda r: _resp(1))
    await emb.aclose()
    assert emb._client is not None


async def test_embed_texts_batches_of_ten():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        calls.append(len(body["input"]))
        return _resp(len(body["input"]))

    emb = _embedder(handler)
    vecs = await emb.embed_texts([f"t{i}" for i in range(25)])

    assert calls == [10, 10, 5]
    assert len(vecs) == 25
    # mock 按批次生成本地索引（0..n-1）：验证批内按 index 排序还原 + 批次顺序拼接
    assert vecs[0][0] == 0.0 and vecs[9][0] == 9.0
    assert vecs[20][0] == 0.0 and vecs[24][0] == 4.0


async def test_embed_query_single():
    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(1)

    vec = await _embedder(handler).embed_query("你好")
    assert len(vec) == 1024


async def test_request_body_shape():
    import json
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return _resp(1)

    await _embedder(handler).embed_query("ping")
    assert seen["body"]["model"] == "text-embedding-v4"
    assert seen["body"]["dimensions"] == 1024
    assert seen["body"]["encoding_format"] == "float"
    assert seen["auth"] == "Bearer sk-x"


async def test_long_text_truncated_and_empty_becomes_space():
    import json
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _resp(2)

    await _embedder(handler).embed_texts(["x" * 9000, ""])
    assert len(seen["body"]["input"][0]) == 6000
    assert seen["body"]["input"][1] == " "


async def test_batch_retries_once_then_raises():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, text="boom")

    with pytest.raises(httpx.HTTPStatusError):
        await _embedder(handler).embed_texts(["a", "b"])
    assert len(calls) == 2  # 首败 + 重试 1 次


async def test_batch_retry_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, text="transient")
        return _resp(1)

    vecs = await _embedder(handler).embed_texts(["a"])
    assert len(calls) == 2
    assert len(vecs) == 1

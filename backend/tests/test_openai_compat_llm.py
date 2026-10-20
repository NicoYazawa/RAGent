"""OpenAICompatLLM — httpx.MockTransport 驱动的请求 / 响应契约"""
import json

import httpx
import pytest

from app.providers.base import LLMCapabilities, Usage
from app.providers.openai_compat import OpenAICompatLLM


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.local")


def _full_caps() -> LLMCapabilities:
    return LLMCapabilities(vision=True, json_mode=True, stream_usage=True)


async def test_ainvoke_returns_text_and_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "你好"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5},
        })

    llm = OpenAICompatLLM("deepseek", "m1", "https://mock.local", "sk-x", _full_caps(), client=_mock_client(handler))
    text, usage = await llm.ainvoke([{"role": "user", "content": "hi"}], temperature=0.2, json_mode=True)

    assert text == "你好"
    assert usage == Usage(11, 5)
    assert seen["auth"] == "Bearer sk-x"
    assert seen["body"]["model"] == "m1"
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["response_format"] == {"type": "json_object"}


async def test_ainvoke_omits_response_format_when_unsupported():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    caps = LLMCapabilities(json_mode=False)
    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", caps, client=_mock_client(handler))
    text, usage = await llm.ainvoke([{"role": "user", "content": "hi"}], json_mode=True)

    assert "response_format" not in seen["body"]
    assert usage == Usage(0, 0)


async def test_ainvoke_passes_vision_blocks_through():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "图里是什么"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]}]
    await llm.ainvoke(msgs)

    content = seen["body"]["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


async def test_ainvoke_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await llm.ainvoke([{"role": "user", "content": "hi"}])


async def test_astream_yields_deltas_then_usage():
    sse = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":7,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    chunks = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]

    assert chunks == [("你", None), ("好", None), ("", Usage(7, 2))]


async def test_astream_requests_include_usage_when_supported():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text="data: [DONE]\n\n")

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    _ = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]

    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}


async def test_astream_omits_stream_options_when_unsupported():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text="data: [DONE]\n\n")

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", LLMCapabilities(), client=_mock_client(handler))
    _ = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]

    assert "stream_options" not in seen["body"]


async def test_astream_yields_zero_usage_when_vendor_silent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n')

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    chunks = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]

    assert chunks[-1] == ("", Usage(0, 0))


async def test_astream_usage_and_delta_same_chunk_not_dropped():
    """usage 与文本增量合包发送（部分网关）：delta 不得被丢弃，usage 照常上报"""
    sse = (
        'data: {"choices":[{"delta":{"content":"末段"}}],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse)

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    chunks = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]

    assert chunks == [("末段", None), ("", Usage(3, 1))]


async def test_astream_ignores_duplicate_usage_packages():
    """流中重复 usage 包只取首个（防门面 token 重复累加）"""
    sse = (
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":99,"completion_tokens":99}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse)

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(), client=_mock_client(handler))
    chunks = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]

    assert chunks == [("", Usage(3, 1))]


async def test_astream_skips_malformed_sse_line():
    """SSE 中的非法 JSON 行被跳过（不中断整条流）"""
    sse = (
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        "data: {不是合法 json}\n\n"
        'data: {"choices":[{"delta":{"content":"吗"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse)

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(),
                           client=_mock_client(handler))
    chunks = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]
    assert [c[0] for c in chunks if c[0]] == ["好", "吗"]


def test_llm_creates_its_own_client_when_not_injected():
    """未注入 client 时按 base_url 自建（并复用同一实例）"""
    llm = OpenAICompatLLM("x", "m", "https://api.example.com/v1", "k", _full_caps())
    client = llm._get_client()
    assert client is not None
    assert str(client.base_url).rstrip("/") == "https://api.example.com/v1"
    assert llm._get_client() is client


async def test_llm_aclose_releases_owned_client():
    """自建 client 在 aclose 后被关闭并置空"""
    llm = OpenAICompatLLM("x", "m", "https://api.example.com/v1", "k", _full_caps())
    client = llm._get_client()
    await llm.aclose()
    assert client.is_closed
    assert llm._client is None


async def test_llm_aclose_keeps_injected_client():
    """注入的 client 不由门面关闭（所有权归调用方）"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    llm = OpenAICompatLLM("x", "m", "https://mock.local", "k", _full_caps(),
                           client=_mock_client(handler))
    await llm.aclose()
    assert llm._client is not None

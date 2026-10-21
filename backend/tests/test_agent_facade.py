"""agent 门面 — judge / stream_generate / chat_messages / embed_* 契约（monkeypatch provider）"""
import pytest
from pydantic import BaseModel

from app.agent import embeddings, llm
from app.providers.base import LLMCapabilities, Usage


class _Out(BaseModel):
    intent: str = "kb_qa"


class _FakeLLM:
    """Structured fake provider that records its call arguments."""

    name = "fake"
    model = "fake-model"
    capabilities = LLMCapabilities(vision=True, json_mode=True, stream_usage=True)

    def __init__(self):
        self.ainvoke_calls = []
        self.astream_calls = []

    async def ainvoke(self, messages, *, temperature=0.2, json_mode=False):
        self.ainvoke_calls.append({"messages": messages, "temperature": temperature, "json_mode": json_mode})
        return '{"intent": "data_query"}', Usage(10, 20)

    async def astream(self, messages, *, temperature=0.7):
        self.astream_calls.append({"messages": messages, "temperature": temperature})
        yield "答案", None
        yield "片段", None
        yield "", Usage(5, 6)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = _FakeLLM()
    monkeypatch.setattr(llm, "get_llm", lambda: fake)
    return fake


async def test_judge_returns_schema_and_accumulates_usage(fake_llm):
    usage: dict = {}
    out = await llm.judge(_Out, "sys", "user", usage)
    assert isinstance(out, _Out)
    assert out.intent == "data_query"
    assert usage == {"prompt": 10, "completion": 20}
    call = fake_llm.ainvoke_calls[0]
    assert call["temperature"] == 0.2
    assert call["json_mode"] is True
    assert call["messages"][0] == {"role": "system", "content": "sys"}


async def test_judge_with_images_builds_vision_message(fake_llm):
    await llm.judge(_Out, "sys", "描述这张图", None, images=["data:image/png;base64,QQ=="])
    content = fake_llm.ainvoke_calls[0]["messages"][-1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,QQ=="


async def test_judge_usage_none_is_tolerated(fake_llm):
    out = await llm.judge(_Out, "sys", "user", None)
    assert out.intent == "data_query"


async def test_stream_generate_yields_deltas_and_accumulates_usage(fake_llm):
    usage: dict = {}
    deltas = [d async for d in llm.stream_generate([{"role": "user", "content": "q"}], usage)]
    assert deltas == ["答案", "片段"]
    assert usage == {"prompt": 5, "completion": 6}
    assert fake_llm.astream_calls[0]["temperature"] == 0.7


async def test_stream_generate_usage_none_is_tolerated(fake_llm):
    deltas = [d async for d in llm.stream_generate([{"role": "user", "content": "q"}])]
    assert deltas == ["答案", "片段"]


def test_chat_messages_shape_without_images():
    msgs = llm.chat_messages("sys", [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
    ], "当前问题")
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "第一问"}
    assert msgs[2] == {"role": "assistant", "content": "第一答"}
    assert msgs[3] == {"role": "user", "content": "当前问题"}


def test_chat_messages_annotates_history_images():
    msgs = llm.chat_messages("sys", [{"role": "user", "content": "看这张", "images": ["/a.png", "/b.png"]}], "q")
    assert "附图 ×2" in msgs[1]["content"]


def test_chat_messages_vision_last_message():
    msgs = llm.chat_messages("sys", [], "图里是什么", ["data:image/png;base64,AA=="])
    assert msgs[-1]["content"][1]["image_url"]["url"] == "data:image/png;base64,AA=="


class _FakeEmbedder:
    name = "fake"
    model = "fake-embed"
    dims = 4

    def __init__(self):
        self.calls = []

    async def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    async def embed_query(self, text):
        return (await self.embed_texts([text]))[0]


async def test_embed_texts_delegates(monkeypatch):
    fake = _FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda: fake)
    vecs = await embeddings.embed_texts(["a", "b"])
    assert vecs == [[0.1, 0.2, 0.3, 0.4], [0.1, 0.2, 0.3, 0.4]]
    assert fake.calls == [["a", "b"]]


async def test_embed_query_delegates(monkeypatch):
    fake = _FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda: fake)
    vec = await embeddings.embed_query("q")
    assert vec == [0.1, 0.2, 0.3, 0.4]

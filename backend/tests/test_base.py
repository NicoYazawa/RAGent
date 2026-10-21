"""Protocols and data structures in base.py — runtime_checkable assertions."""
from collections.abc import AsyncIterator

from app.providers.base import EmbeddingProvider, LLMCapabilities, LLMProvider, Message, Usage


def test_usage_defaults():
    u = Usage()
    assert (u.prompt_tokens, u.completion_tokens) == (0, 0)
    assert Usage(3, 4) == Usage(prompt_tokens=3, completion_tokens=4)


def test_capabilities_defaults_all_false():
    c = LLMCapabilities()
    assert (c.vision, c.json_mode, c.stream_usage) == (False, False, False)


class _FakeLLM:
    name = "fake"
    model = "fake-model"
    capabilities = LLMCapabilities(vision=True, json_mode=True, stream_usage=True)

    async def ainvoke(self, messages, *, temperature=0.2, json_mode=False):
        return "ok", Usage(1, 2)

    def astream(self, messages, *, temperature=0.7) -> AsyncIterator:
        raise NotImplementedError


class _FakeEmbedder:
    name = "fake"
    model = "fake-embed"
    dims = 8

    async def embed_texts(self, texts):
        return [[0.0] * 8 for _ in texts]

    async def embed_query(self, text):
        return [0.0] * 8


def test_protocols_structural_match():
    assert isinstance(_FakeLLM(), LLMProvider)
    assert isinstance(_FakeEmbedder(), EmbeddingProvider)
    assert Message is dict

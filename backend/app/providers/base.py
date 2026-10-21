"""Provider base abstractions — protocols, capability matrix and usage model.

Every AI capability (LLM chat / streaming generation / Embedding) is exposed through a
Protocol; the only implementation today is openai_compat (the OpenAI-compatible family),
with native implementations possible later. Messages use the OpenAI-compatible dict form
(a list of content blocks for multimodal vision), so no conversion is needed for httpx bodies.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

Message = dict  # {"role": "system"|"user"|"assistant", "content": str | list[dict]}


@dataclass(frozen=True)
class Usage:
    """Token usage of a single call (decision log / cost accounting)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class LLMCapabilities:
    """Model capability matrix — callers degrade accordingly (without json_mode the
    _extract_json regex is the fallback)."""

    vision: bool = False
    json_mode: bool = False
    stream_usage: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    """LLM provider protocol — serves both judge (structured decisions) and generate (streaming)."""

    name: str
    model: str
    capabilities: LLMCapabilities

    async def ainvoke(
        self, messages: list[Message], *, temperature: float = 0.2, json_mode: bool = False
    ) -> tuple[str, Usage]:
        """Non-streaming call; returns (text, usage)."""
        ...

    def astream(
        self, messages: list[Message], *, temperature: float = 0.7
    ) -> AsyncIterator[tuple[str, Usage | None]]:
        """Streaming call: yields (text delta, None) chunks, then ("", final usage) at the end.

        When a provider does not report usage, the final Usage is all zeros.
        """
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embedding provider protocol — batch and single-query entry points."""

    name: str
    model: str
    dims: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch (batch size / truncation / retries are the implementation's concern)."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        ...


@runtime_checkable
class RerankProvider(Protocol):
    """Rerank provider protocol — query + candidate documents -> (index, score) pairs sorted
    by relevance descending."""

    name: str
    model: str

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """Return [(document index, relevance score)] sorted by score descending, at most top_n.

        Bounds checking is the caller's job; provider errors propagate (the caller degrades
        to coarse ranking).
        """
        ...

"""Embedding facade — batches and single-query vectors (provider-agnostic, dispatched via providers).

Batch size (<=10), per-text truncation (6000 chars) and one retry per batch are handled
by the provider implementation.
"""
from ..providers import get_embedder


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts."""
    return await get_embedder().embed_texts(texts)


async def embed_query(text: str) -> list[float]:
    """Embed a single query."""
    return await get_embedder().embed_query(text)

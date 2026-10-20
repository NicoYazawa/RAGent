"""Embedding 门面 — 批量 / 单查询向量化（供应商无关，经 providers 层分发）

批大小（≤10）、单条截断（6000 字符）、批次重试（1 次）由 provider 实现负责。
"""
from ..providers import get_embedder


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化"""
    return await get_embedder().embed_texts(texts)


async def embed_query(text: str) -> list[float]:
    """单条查询向量化"""
    return await get_embedder().embed_query(text)

"""Provider 抽象基座 — 协议 + 能力矩阵 + 用量模型

所有 AI 能力（LLM 对话 / 流式生成 / Embedding）经 Protocol 暴露，
实现方当前仅 openai_compat（OpenAI 兼容协议族），后续可扩展 native 实现。
Message 采用 OpenAI 兼容 dict 格式（视觉多模态为 content 块列表），与 httpx 请求体零转换。
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

Message = dict  # {"role": "system"|"user"|"assistant", "content": str | list[dict]}


@dataclass(frozen=True)
class Usage:
    """单次调用的 token 用量（决策日志 / 成本统计）"""

    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class LLMCapabilities:
    """模型能力矩阵 — 调用方据此降级（无 json_mode 时靠 _extract_json 正则兜底）"""

    vision: bool = False
    json_mode: bool = False
    stream_usage: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 供应商协议 — 同时服务 judge（结构化判定）与 generate（流式生成）"""

    name: str
    model: str
    capabilities: LLMCapabilities

    async def ainvoke(
        self, messages: list[Message], *, temperature: float = 0.2, json_mode: bool = False
    ) -> tuple[str, Usage]:
        """非流式对话，返回 (文本, 用量)"""
        ...

    def astream(
        self, messages: list[Message], *, temperature: float = 0.7
    ) -> AsyncIterator[tuple[str, Usage | None]]:
        """流式对话：逐段 yield (文本增量, None)，末尾 yield ("", 最终用量)

        供应商不上报用量时末尾 Usage 为全 0。
        """
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embedding 供应商协议 — 批量 / 单查询两种入口"""

    name: str
    model: str
    dims: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量向量化（批大小 / 截断 / 重试由实现方负责）"""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """单条查询向量化"""
        ...


@runtime_checkable
class RerankProvider(Protocol):
    """精排供应商协议 — query + 候选文档 → 按相关度降序的 (索引, 分数) 列表"""

    name: str
    model: str

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """返回 [(文档索引, 相关度分数)]，按分数降序、长度 ≤ top_n

        索引越界防护由调用方负责；供应商异常直接抛出（调用方降级为粗排序）。
        """
        ...

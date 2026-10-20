"""Provider 抽象层门面 — 按 settings 解析当前生效的 LLM / Embedding / Rerank 供应商（带缓存）

Phase 1：供应商由 .env（LLM_PROVIDER / EMBED_PROVIDER / RERANK_PROVIDER）决定；
Phase 2：改为读 provider_config 表 + 按决策点路由，门面签名不变。
"""
from ..config import settings
from .base import EmbeddingProvider, LLMProvider, RerankProvider
from .openai_compat import OpenAICompatEmbedder, OpenAICompatLLM
from .registry import ProviderSpec, UnknownProviderError, get_spec
from .rerank_http import HttpRerank

_llm_singleton: LLMProvider | None = None
_embed_singleton: EmbeddingProvider | None = None
_rerank_singleton: RerankProvider | None = None


def _key_for(spec: ProviderSpec) -> str:
    """免密钥供应商（api_key_env 为空串）用占位；否则走 settings.api_key_for"""
    if not spec.api_key_env:
        return "not-needed"
    return settings.api_key_for(spec.api_key_env)


def _build_llm() -> LLMProvider:
    spec = get_spec(settings.llm_provider)
    if spec.kind != "openai_compat":
        raise UnknownProviderError(f"供应商 {spec.name} 的实现族 {spec.kind} 暂不支持")
    return OpenAICompatLLM(
        name=spec.name,
        model=settings.resolved_llm_model,
        base_url=settings.resolved_llm_base_url,
        api_key=_key_for(spec),
        capabilities=spec.llm_capabilities,
    )


def _build_embedder() -> EmbeddingProvider:
    spec = get_spec(settings.embed_provider)
    if spec.kind != "openai_compat":
        raise UnknownProviderError(f"供应商 {spec.name} 的实现族 {spec.kind} 暂不支持")
    return OpenAICompatEmbedder(
        name=spec.name,
        model=settings.resolved_embed_model,
        dims=settings.resolved_embed_dims,
        base_url=settings.resolved_embed_base_url,
        api_key=_key_for(spec),
    )


def get_llm() -> LLMProvider:
    """当前生效 LLM 供应商（进程内单例；配置变更后需 reset_providers）"""
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = _build_llm()
    return _llm_singleton


def get_embedder() -> EmbeddingProvider:
    """当前生效 Embedding 供应商（进程内单例）"""
    global _embed_singleton
    if _embed_singleton is None:
        _embed_singleton = _build_embedder()
    return _embed_singleton


def reset_providers() -> None:
    """清空缓存（测试 / 运行时切换供应商后调用）"""
    global _llm_singleton, _embed_singleton, _rerank_singleton
    _llm_singleton = None
    _embed_singleton = None
    _rerank_singleton = None


async def close_providers() -> None:
    """关闭供应商自建 httpx 客户端（lifespan 关闭期调用）"""
    for p in (_llm_singleton, _embed_singleton, _rerank_singleton):
        aclose = getattr(p, "aclose", None)
        if aclose is not None:
            await aclose()
    reset_providers()


def get_rerank() -> RerankProvider:
    """当前生效精排供应商（进程内单例）

    供应商未配置 rerank（registry.rerank_model 为空）或开关校验失败时抛
    UnknownProviderError——调用方（orchestrator）据此降级为粗排序。
    """
    global _rerank_singleton
    if _rerank_singleton is None:
        spec = get_spec(settings.rerank_provider)
        if not spec.rerank_model:
            raise UnknownProviderError(f"供应商 {spec.name} 未配置 rerank 模型（registry.rerank_model 为空）")
        _rerank_singleton = HttpRerank(
            name=spec.name,
            model=settings.resolved_rerank_model,
            base_url=settings.resolved_rerank_base_url,
            path=spec.rerank_path,
            api_key=_key_for(spec),
            shape=spec.rerank_shape,
        )
    return _rerank_singleton

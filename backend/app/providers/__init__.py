"""Provider abstraction facade — resolves the active LLM / Embedding / Rerank provider from settings (cached).

Phase 1: the provider is chosen by .env (LLM_PROVIDER / EMBED_PROVIDER / RERANK_PROVIDER).
Phase 2: switch to reading the provider_config table and routing per decision point, keeping
the facade signatures unchanged.
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
    """Keyless providers (empty api_key_env) get a placeholder; others go through settings.api_key_for."""
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
    """Active LLM provider (per-process singleton; call reset_providers after a config change)."""
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = _build_llm()
    return _llm_singleton


def get_embedder() -> EmbeddingProvider:
    """Active Embedding provider (per-process singleton)."""
    global _embed_singleton
    if _embed_singleton is None:
        _embed_singleton = _build_embedder()
    return _embed_singleton


def reset_providers() -> None:
    """Clear the cache (used by tests and after switching providers at runtime)."""
    global _llm_singleton, _embed_singleton, _rerank_singleton
    _llm_singleton = None
    _embed_singleton = None
    _rerank_singleton = None


async def close_providers() -> None:
    """Close the providers' own httpx clients (called during lifespan shutdown)."""
    for p in (_llm_singleton, _embed_singleton, _rerank_singleton):
        aclose = getattr(p, "aclose", None)
        if aclose is not None:
            await aclose()
    reset_providers()


def get_rerank() -> RerankProvider:
    """Active rerank provider (per-process singleton).

    Raises UnknownProviderError when the provider has no rerank model configured
    (registry.rerank_model is empty) or the switch check fails — the caller (orchestrator)
    then degrades to coarse ranking.
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

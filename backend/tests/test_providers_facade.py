"""providers 门面 — 按 settings 解析并缓存；reset 后按新配置重建

注意：仓库 backend/.env 显式设置了 LLM_MODEL / EMBED_MODEL / EMBED_DIMS（旧式显式配置，
按设计压过目录默认值）。凡验证"目录默认值"语义的用例，须同时清空这三个覆盖字段，
否则测到的是 .env 覆盖而非 catalog 回退。
"""
import pytest

from app import providers
from app.config import settings
from app.providers.base import EmbeddingProvider, LLMProvider
from app.providers.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM
from app.providers.registry import UnknownProviderError


def _clear_overrides(monkeypatch):
    """Clear the model/dims override fields so resolved_* falls back to the provider catalog defaults."""
    monkeypatch.setattr(settings, "llm_model", "", raising=False)
    monkeypatch.setattr(settings, "embed_model", "", raising=False)
    monkeypatch.setattr(settings, "embed_dims", 0, raising=False)


def test_get_llm_builds_from_settings(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "llm_provider", "deepseek", raising=False)
    llm = providers.get_llm()
    assert isinstance(llm, LLMProvider)
    assert isinstance(llm, OpenAICompatLLM)
    assert llm.name == "deepseek"
    assert llm.model == "deepseek-v4-flash-vision-exp"
    assert llm.capabilities.vision is True


def test_get_llm_cached_singleton(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek", raising=False)
    assert providers.get_llm() is providers.get_llm()


def test_get_llm_after_reset_reflects_new_provider(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "llm_provider", "moonshot", raising=False)
    llm = providers.get_llm()
    assert llm.name == "moonshot"
    assert llm.model == "moonshot-v1-32k"

    providers.reset_providers()
    monkeypatch.setattr(settings, "llm_provider", "zhipu", raising=False)
    llm2 = providers.get_llm()
    assert llm2.name == "zhipu"
    assert llm2.model == "glm-4-air"


def test_get_embedder_builds_from_settings(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "embed_provider", "qwen", raising=False)
    emb = providers.get_embedder()
    assert isinstance(emb, EmbeddingProvider)
    assert isinstance(emb, OpenAICompatEmbedder)
    assert (emb.name, emb.model, emb.dims) == ("qwen", "text-embedding-v4", 1024)


def test_get_embedder_keyless_provider_gets_placeholder_key(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "embed_provider", "ollama", raising=False)
    emb = providers.get_embedder()
    assert emb.name == "ollama"
    assert emb.dims == 768


def test_unknown_provider_raises_on_build(monkeypatch):
    import pytest

    from app.providers.registry import UnknownProviderError

    monkeypatch.setattr(settings, "llm_provider", "bogus", raising=False)
    with pytest.raises(UnknownProviderError):
        providers.get_llm()


async def test_close_providers_no_error():
    """Closing all providers never raises (idempotent) and clears the singletons."""
    providers.get_llm()
    await providers.close_providers()
    await providers.close_providers()  # closing twice is safe
    assert providers._llm_singleton is None
    assert providers._embed_singleton is None
    assert providers._rerank_singleton is None


def test_build_llm_rejects_unsupported_kind(monkeypatch):
    """An implementation family other than openai_compat -> a clear error (phase-2 extension point)."""
    from app.providers.registry import ProviderSpec

    spec = ProviderSpec(
        name="custom", label="自研", kind="custom", base_url="http://x",
        api_key_env="", default_llm_model="m", default_embed_model="e",
        default_embed_dims=8, llm_capabilities=None, rerank_model="", rerank_path="",
        rerank_shape="flat", rerank_base_url="",
    )
    monkeypatch.setattr(providers, "get_spec", lambda name: spec)
    monkeypatch.setattr(providers.settings, "llm_provider", "custom", raising=False)
    with pytest.raises(UnknownProviderError, match="实现族"):
        providers.get_llm()


def test_build_embedder_rejects_unsupported_kind(monkeypatch):
    """The embedding side rejects unknown implementation families too."""
    from app.providers.registry import ProviderSpec

    spec = ProviderSpec(
        name="custom", label="自研", kind="custom", base_url="http://x",
        api_key_env="", default_llm_model="m", default_embed_model="e",
        default_embed_dims=8, llm_capabilities=None, rerank_model="", rerank_path="",
        rerank_shape="flat", rerank_base_url="",
    )
    monkeypatch.setattr(providers, "get_spec", lambda name: spec)
    monkeypatch.setattr(providers.settings, "embed_provider", "custom", raising=False)
    with pytest.raises(UnknownProviderError, match="实现族"):
        providers.get_embedder()

"""Provider registry — vendor catalog.

A catalog entry declares "implementation family + defaults": kind picks the implementation
class, while the default model / dimensions can be overridden explicitly by .env
(LLM_MODEL / EMBED_MODEL / EMBED_DIMS). Secrets are not resolved here
(pydantic-settings already loaded .env, see config.api_key_for).
"""
from dataclasses import dataclass, field

from .base import LLMCapabilities


class UnknownProviderError(ValueError):
    """Unknown provider name — a .env configuration error, surfaced at startup."""


@dataclass(frozen=True)
class ProviderSpec:
    name: str                      # unique key: "deepseek" / "qwen" / "openai" ...
    label: str                     # display name (terminal self-check / health)
    kind: str                      # implementation family: "openai_compat"
    base_url: str                  # OpenAI-compatible base_url (including the version path)
    api_key_env: str               # secret environment variable; empty for keyless providers
    default_llm_model: str = ""
    default_embed_model: str = ""
    default_embed_dims: int = 0
    llm_capabilities: LLMCapabilities = field(default_factory=LLMCapabilities)
    # Rerank (optional; an empty rerank_model means the provider does not offer or configure rerank)
    rerank_base_url: str = ""
    rerank_path: str = ""
    rerank_model: str = ""
    rerank_shape: str = "dashscope"  # dashscope: nested input + output.results; flat: top-level fields + results


PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        label="DeepSeek",
        kind="openai_compat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        default_llm_model="deepseek-v4-flash-vision-exp",
        llm_capabilities=LLMCapabilities(vision=True, json_mode=True, stream_usage=True),
    ),
    "qwen": ProviderSpec(
        name="qwen",
        label="阿里云百炼 Qwen",
        kind="openai_compat",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_llm_model="qwen-plus",
        default_embed_model="text-embedding-v4",
        default_embed_dims=1024,
        llm_capabilities=LLMCapabilities(vision=True, json_mode=True, stream_usage=True),
        # Rerank uses Bailian's native text-rerank service (outside compatible-mode)
        rerank_base_url="https://dashscope.aliyuncs.com",
        rerank_path="/api/v1/services/rerank/text-rerank/text-rerank",
        rerank_model="gte-rerank-v2",
        rerank_shape="dashscope",
    ),
    "openai": ProviderSpec(
        name="openai",
        label="OpenAI",
        kind="openai_compat",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_llm_model="gpt-4o-mini",
        default_embed_model="text-embedding-3-small",
        default_embed_dims=1536,
        llm_capabilities=LLMCapabilities(vision=True, json_mode=True, stream_usage=True),
    ),
    "moonshot": ProviderSpec(
        name="moonshot",
        label="Moonshot Kimi",
        kind="openai_compat",
        base_url="https://api.moonshot.cn/v1",
        api_key_env="MOONSHOT_API_KEY",
        default_llm_model="moonshot-v1-32k",
        llm_capabilities=LLMCapabilities(),
    ),
    "zhipu": ProviderSpec(
        name="zhipu",
        label="智谱 GLM",
        kind="openai_compat",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="ZHIPU_API_KEY",
        default_llm_model="glm-4-air",
        llm_capabilities=LLMCapabilities(json_mode=True, stream_usage=True),
    ),
    "siliconflow": ProviderSpec(
        name="siliconflow",
        label="SiliconFlow 硅基流动",
        kind="openai_compat",
        base_url="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        default_llm_model="Qwen/Qwen2.5-7B-Instruct",
        default_embed_model="BAAI/bge-m3",
        default_embed_dims=1024,
        llm_capabilities=LLMCapabilities(json_mode=True, stream_usage=True),
        rerank_base_url="https://api.siliconflow.cn/v1",
        rerank_path="/rerank",
        rerank_model="BAAI/bge-reranker-v2-m3",
        rerank_shape="flat",
    ),
    "ollama": ProviderSpec(
        name="ollama",
        label="Ollama（本机）",
        kind="openai_compat",
        base_url="http://localhost:11434/v1",
        api_key_env="",  # keyless
        default_llm_model="llama3.1",
        default_embed_model="nomic-embed-text",
        default_embed_dims=768,
        llm_capabilities=LLMCapabilities(),
    ),
}


def get_spec(name: str) -> ProviderSpec:
    """Look up a catalog entry by name; raises UnknownProviderError with the available list."""
    spec = PROVIDERS.get((name or "").strip().lower())
    if spec is None:
        raise UnknownProviderError(f"未知供应商 '{name}'，可选：{', '.join(sorted(PROVIDERS))}")
    return spec

"""Provider 注册表 — 厂商目录

目录条目是"协议族 + 默认值"声明：kind 决定用哪个实现类构造，
默认模型 / 维度可被 .env 显式覆盖（LLM_MODEL / EMBED_MODEL / EMBED_DIMS）。
密钥不在此层解析（pydantic-settings 已加载 .env，见 config.api_key_for）。
"""
from dataclasses import dataclass, field

from .base import LLMCapabilities


class UnknownProviderError(ValueError):
    """未知供应商名 — .env 配置错误，启动期即暴露"""


@dataclass(frozen=True)
class ProviderSpec:
    name: str                      # 唯一键："deepseek" / "qwen" / "openai" ...
    label: str                     # 展示名（终端自检 / health）
    kind: str                      # 实现族："openai_compat"
    base_url: str                  # OpenAI 兼容 base_url（含版本路径）
    api_key_env: str               # 密钥环境变量名；免密钥供应商为空串
    default_llm_model: str = ""
    default_embed_model: str = ""
    default_embed_dims: int = 0
    llm_capabilities: LLMCapabilities = field(default_factory=LLMCapabilities)
    # rerank 精排（可选；rerank_model 为空表示该供应商不提供/未配置 rerank）
    rerank_base_url: str = ""
    rerank_path: str = ""
    rerank_model: str = ""
    rerank_shape: str = "dashscope"  # dashscope：input 嵌套 + output.results；flat：顶层字段 + results


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
        # rerank 走百炼原生 text-rerank 服务（不在 compatible-mode 下）
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
        api_key_env="",  # 免密钥
        default_llm_model="llama3.1",
        default_embed_model="nomic-embed-text",
        default_embed_dims=768,
        llm_capabilities=LLMCapabilities(),
    ),
}


def get_spec(name: str) -> ProviderSpec:
    """按名称取厂商目录条目；未知名抛 UnknownProviderError（附可选清单）"""
    spec = PROVIDERS.get((name or "").strip().lower())
    if spec is None:
        raise UnknownProviderError(f"未知供应商 '{name}'，可选：{', '.join(sorted(PROVIDERS))}")
    return spec

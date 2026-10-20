"""全局配置 — pydantic-settings 读取 backend/.env（密钥不入库不入仓）

供应商切换（Phase 1，env 驱动）：LLM_PROVIDER / EMBED_PROVIDER 选厂商目录条目，
LLM_MODEL / EMBED_MODEL / EMBED_DIMS 为空时回退目录默认值；历史变量
（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / *_BASE_URL）语义不变，继续生效。
"""
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from .providers.registry import ProviderSpec

BASE_DIR = Path(__file__).resolve().parent.parent

# Settings 显式密钥字段 → 环境变量名（api_key_for 查表；新增供应商时在此登记）
_API_KEY_FIELDS: dict[str, str] = {
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "DASHSCOPE_API_KEY": "dashscope_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "MOONSHOT_API_KEY": "moonshot_api_key",
    "ZHIPU_API_KEY": "zhipu_api_key",
    "SILICONFLOW_API_KEY": "siliconflow_api_key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # 供应商切换（Phase 1：.env 驱动；Phase 2 入库 + 管理页）
    llm_provider: str = "deepseek"   # 厂商目录键，见 providers/registry.py
    embed_provider: str = "qwen"     # 百炼 compatible-mode，密钥仍读 DASHSCOPE_API_KEY
    llm_base_url: str = ""           # 非空则覆盖目录 base_url（代理 / 网关场景）
    embed_base_url: str = ""

    # Rerank 精排（默认关；开启后粗排扩候选 → 精排截 top_n）
    rerank_enabled: bool = False
    rerank_provider: str = "qwen"    # 可选：qwen（gte-rerank-v2）/ siliconflow（bge-reranker-v2-m3）
    rerank_model: str = ""           # 留空 = 用目录默认
    rerank_base_url: str = ""        # 留空 = 用目录默认
    rerank_top_n: int = 8            # 精排后保留片段数
    rerank_candidates: int = 20      # 粗排（RRF）候选数，rerank 开启时生效

    # LLM（默认 deepseek-v4-flash-vision-exp，OpenAI 兼容，多模态视觉模型）
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""      # 留空 = 用目录 base_url
    llm_model: str = ""              # 留空 = 用目录默认模型
    openai_api_key: str = ""
    moonshot_api_key: str = ""
    zhipu_api_key: str = ""
    siliconflow_api_key: str = ""

    # Embedding（默认阿里云百炼 text-embedding-v4，OpenAI 兼容接口）
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""     # 留空 = 用目录 base_url
    embed_model: str = ""            # 留空 = 用目录默认模型
    embed_dims: int = 0              # 0 = 用目录默认维度

    # MySQL 8.x（utf8mb4）
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "ragent_db"

    # Elasticsearch 8.x/9.x
    es_url: str = "http://localhost:9200"
    es_user: str = "elastic"
    es_password: str = ""

    # CORS（逗号分隔的来源列表；容器/同源代理场景下可留空）
    cors_origins: str = "http://localhost:5173"

    # 问答图片（多模态）
    chat_image_max_count: int = 4
    chat_image_max_bytes: int = 5 * 1024 * 1024

    # 应用
    data_dir: str = "data"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 5
    fused_top_n: int = 8
    grade_pass: float = 7.0
    grade_partial: float = 5.0
    crag_max_rounds: int = 2
    reflect_max_rounds: int = 2
    overall_timeout: int = 120
    history_window: int = 8

    # ---------- 供应商解析（目录默认值 + .env 覆盖） ----------
    # 注意：get_spec 在此函数级 import——config 是最底层模块（db/es/main 均依赖），
    # 模块级 import providers 包会经 providers/__init__ 回导 config.settings 形成循环导入。

    @property
    def active_llm_spec(self) -> "ProviderSpec":
        from .providers.registry import get_spec

        return get_spec(self.llm_provider)

    @property
    def active_embed_spec(self) -> "ProviderSpec":
        from .providers.registry import get_spec

        return get_spec(self.embed_provider)

    @property
    def active_rerank_spec(self) -> "ProviderSpec":
        from .providers.registry import get_spec

        return get_spec(self.rerank_provider)

    @property
    def resolved_rerank_model(self) -> str:
        return self.rerank_model or self.active_rerank_spec.rerank_model

    @property
    def resolved_rerank_base_url(self) -> str:
        return self.rerank_base_url or self.active_rerank_spec.rerank_base_url

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or self.active_llm_spec.default_llm_model

    @property
    def resolved_embed_model(self) -> str:
        return self.embed_model or self.active_embed_spec.default_embed_model

    @property
    def resolved_embed_dims(self) -> int:
        return self.embed_dims or self.active_embed_spec.default_embed_dims

    @property
    def resolved_llm_base_url(self) -> str:
        return self.llm_base_url or self.deepseek_base_url or self.active_llm_spec.base_url

    @property
    def resolved_embed_base_url(self) -> str:
        return self.embed_base_url or self.dashscope_base_url or self.active_embed_spec.base_url

    def api_key_for(self, env_name: str) -> str:
        """按环境变量名取密钥：先查 Settings 显式字段（.env 加载），再查进程环境"""
        field_name = _API_KEY_FIELDS.get(env_name)
        if field_name:
            value = getattr(self, field_name, "")
            if value:
                return value
        return os.environ.get(env_name, "")


settings = Settings()

UPLOAD_DIR = BASE_DIR / settings.data_dir / "uploads"

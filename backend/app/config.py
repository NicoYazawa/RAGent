"""Global configuration — pydantic-settings reads backend/.env (secrets never enter the DB or the repo).

Provider switching (phase 1, environment driven): LLM_PROVIDER / EMBED_PROVIDER select a
catalog entry, while LLM_MODEL / EMBED_MODEL / EMBED_DIMS fall back to catalog defaults when
empty. Legacy variables (DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / *_BASE_URL) keep working with
unchanged semantics.
"""
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from .providers.registry import ProviderSpec

BASE_DIR = Path(__file__).resolve().parent.parent

# Explicit secret fields on Settings -> environment variable names (looked up by api_key_for;
# register new providers here)
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

    # Provider switching (phase 1: .env driven; phase 2: stored in DB + admin page)
    llm_provider: str = "deepseek"   # catalog key, see providers/registry.py
    embed_provider: str = "qwen"     # Bailian compatible-mode; the key still comes from DASHSCOPE_API_KEY
    llm_base_url: str = ""           # non-empty overrides the catalog base_url (proxy / gateway setups)
    embed_base_url: str = ""

    # Rerank (off by default; when enabled, coarse retrieval widens the candidate pool and rerank trims to top_n)
    rerank_enabled: bool = False
    rerank_provider: str = "qwen"    # options: qwen (gte-rerank-v2) / siliconflow (bge-reranker-v2-m3)
    rerank_model: str = ""           # empty = use the catalog default
    rerank_base_url: str = ""        # empty = use the catalog default
    rerank_top_n: int = 8            # chunks kept after reranking
    rerank_candidates: int = 20      # coarse (RRF) candidate count, only used when rerank is enabled

    # LLM (default deepseek-v4-flash-vision-exp, OpenAI compatible, multimodal vision model)
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""      # empty = use the catalog base_url
    llm_model: str = ""              # empty = use the catalog default model
    openai_api_key: str = ""
    moonshot_api_key: str = ""
    zhipu_api_key: str = ""
    siliconflow_api_key: str = ""

    # Embedding (default Alibaba Cloud Bailian text-embedding-v4, OpenAI compatible endpoint)
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""     # empty = use the catalog base_url
    embed_model: str = ""            # empty = use the catalog default model
    embed_dims: int = 0              # 0 = use the catalog default dimensions

    # MySQL 8.x (utf8mb4)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "ragent_db"

    # Elasticsearch 8.x/9.x
    es_url: str = "http://localhost:9200"
    es_user: str = "elastic"
    es_password: str = ""

    # CORS (comma-separated origin list; may stay empty behind a container or same-origin proxy)
    cors_origins: str = "http://localhost:5173"

    # Q&A images (multimodal)
    chat_image_max_count: int = 4
    chat_image_max_bytes: int = 5 * 1024 * 1024

    # Application
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

    # ---------- Provider resolution (catalog defaults + .env overrides) ----------
    # Note: get_spec is imported inside each function on purpose — config is the lowest layer
    # (db/es/main all depend on it) and a module-level import of the providers package would
    # come back through providers/__init__ to config.settings and create a circular import.

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
        """Look up a secret by environment variable name: explicit Settings fields first
        (loaded from .env), then the process environment."""
        field_name = _API_KEY_FIELDS.get(env_name)
        if field_name:
            value = getattr(self, field_name, "")
            if value:
                return value
        return os.environ.get(env_name, "")


settings = Settings()

UPLOAD_DIR = BASE_DIR / settings.data_dir / "uploads"

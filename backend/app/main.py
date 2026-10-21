"""RAGent backend entry point — FastAPI + SSE.

Startup: dependency self-checks (ES / LLM and Embedding provider keys / ES index dimensions,
failures are only reported to the terminal) -> create the ES index.
MySQL schema and base data (datasource_config / sales) are imported beforehand from
ragent_init.sql at the project root.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .es import elastic
from .i18n import LocaleMiddleware
from .providers import close_providers
from .routers import chat, datasources, decision_logs, kb, retrieval_test
from .startup_check import consistency_status, run_startup_checks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("agentic.main")


def parse_cors_origins(raw: str) -> list[str]:
    """Parse the CORS origin list and reject the ``*`` wildcard.

    Fail closed: with ``*`` allowed and ``allow_credentials=True``, Starlette echoes the
    request Origin into ``Access-Control-Allow-Origin`` together with
    ``Allow-Credentials: true``, so any site could call this service with credentials.
    Startup therefore fails fast, forcing the deployment to list frontend origins explicitly.
    """
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins:
        raise ValueError(
            "CORS_ORIGINS 禁止使用 '*'：与 allow_credentials=True 同时生效会让任意站点"
            "携带凭据跨域访问本服务。请显式列出允许的前端来源（逗号分隔）。"
        )
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_startup_checks()
    try:
        await elastic.ensure_index()
    except Exception as e:
        logger.error("ES 索引初始化失败，检索功能不可用（服务降级启动）：%s", e)
    yield
    await elastic.close()
    await close_providers()


app = FastAPI(title="RAGent API", version="1.0.0", lifespan=lifespan)

origins = parse_cors_origins(settings.cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LocaleMiddleware)

app.include_router(kb.router)
app.include_router(datasources.router)
app.include_router(decision_logs.router)
app.include_router(chat.router)
app.include_router(retrieval_test.router)


@app.get("/api/health")
async def health() -> dict:
    mysql_ok = True
    es_ok = await elastic.ping()
    try:
        await db.aquery_one("SELECT 1 AS ok")
    except Exception:
        mysql_ok = False
    index_dims: int | None = None
    dims_ok = True
    try:
        index_dims = await elastic.index_dims()
        dims_ok = index_dims is None or index_dims == settings.resolved_embed_dims
    except Exception:
        dims_ok = False
    consistency = await consistency_status()
    llm_spec = settings.active_llm_spec
    embed_spec = settings.active_embed_spec
    return {
        "status": "ok" if (mysql_ok and es_ok and dims_ok and consistency["match"] is not False) else "degraded",
        "version": app.version,
        "llm": {
            "provider": llm_spec.name,
            "label": llm_spec.label,
            "model": settings.resolved_llm_model,
            "capabilities": {
                "vision": llm_spec.llm_capabilities.vision,
                "json_mode": llm_spec.llm_capabilities.json_mode,
                "stream_usage": llm_spec.llm_capabilities.stream_usage,
            },
        },
        "embedding": {
            "provider": embed_spec.name,
            "label": embed_spec.label,
            "model": settings.resolved_embed_model,
            "dims": settings.resolved_embed_dims,
            "index_dims": index_dims,
            "dims_match": dims_ok,
        },
        "consistency": consistency,
        "mysql": mysql_ok,
        "elasticsearch": es_ok,
    }

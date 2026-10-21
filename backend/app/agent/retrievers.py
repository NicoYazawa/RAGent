"""Retrieval adapter layer — three Retriever implementations share
search(query, top_k) -> list[RetrieverResult].

Adding a data source is non-invasive: VectorRetriever / KeywordRetriever go through ES and
DBRetriever goes through read-only NL2SQL queries.
"""
import asyncio
import logging
import re
from typing import Any

from pydantic import BaseModel

from .. import db
from ..es import elastic
from . import prompts
from .embeddings import embed_query
from .llm import judge
from .rrf import RetrieverResult

logger = logging.getLogger("agentic.retrievers")


class SqlOut(BaseModel):
    sql: str = ""


def _es_hit_to_result(source: str, hit: dict) -> RetrieverResult:
    doc_name = hit.get("doc_name", "")
    section = hit.get("section_path", "")
    chunk_no = int(hit.get("chunk_no", 0))
    return RetrieverResult(
        source=source,
        score=round(float(hit.get("score") or 0.0), 4),
        title=f"{doc_name} · {section}" if section else doc_name,
        content=hit.get("content", ""),
        metadata={
            "doc_name": doc_name,
            "section_path": section,
            "chunk_no": chunk_no,
            "doc_id": hit.get("doc_id"),
            "kb_id": hit.get("kb_id"),
            "chunk_uid": hit.get("chunk_uid"),
        },
    )


class VectorRetriever:
    """Semantic retrieval: Bailian embeddings (query side) -> ES top-level kNN."""

    async def search(self, query: str, kb_ids: list[int] | None, top_k: int = 5) -> list[RetrieverResult]:
        vector = await embed_query(query)
        hits = await elastic.knn_search(vector, kb_ids, k=top_k)
        return [_es_hit_to_result("vector", h) for h in hits]


class KeywordRetriever:
    """Keyword retrieval: ES BM25 multi_match (content plus weighted section_path)."""

    async def search(self, query: str, kb_ids: list[int] | None, top_k: int = 5) -> list[RetrieverResult]:
        hits = await elastic.match_search(query, kb_ids, k=top_k)
        return [_es_hit_to_result("keyword", h) for h in hits]


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|merge|call|lock)\b",
    re.IGNORECASE,
)
# Statement separators and comment injection — the real injection vector, independent of
# the keyword blacklist. The keyword blacklist needs \b word boundaries, otherwise
# substrings such as update/create/delete inside common column names (updated_at /
# created_at / deleted_at) would be mistaken for write operations.
_FORBIDDEN_PUNCT = re.compile(r"(;|--|/\*)")


def validate_select(sql: str) -> str:
    """SELECT allowlist validation plus LIMIT 20 truncation."""
    sql = sql.strip().rstrip(";").strip()
    if not re.match(r"^select\s", sql, re.IGNORECASE):
        raise ValueError("仅允许 SELECT 查询")
    if _FORBIDDEN.search(sql) or _FORBIDDEN_PUNCT.search(sql):
        raise ValueError("SQL 含危险关键字，已拦截")
    m = re.search(r"limit\s+(\d+)", sql, re.IGNORECASE)
    if m:
        if int(m.group(1)) > 20:
            sql = sql[: m.start()] + "LIMIT 20"
    else:
        sql += " LIMIT 20"
    return sql


class DBRetriever:
    """Business data query: the LLM generates a SELECT from the sales schema -> executed by
    the read-only account (at most 20 rows)."""

    async def search(
        self, natural_question: str, top_k: int = 5, locale: str = "zh-CN"
    ) -> tuple[str, list[RetrieverResult]]:
        out = await judge(
            SqlOut, prompts.get_prompt("nl2sql_sys", locale), prompts.nl2sql_user(natural_question, locale)
        )
        sql = validate_select(out.sql)
        rows = await db.aquery_all(sql)
        zh = locale == "zh-CN"
        record = "记录" if zh else "record"
        sep = "，" if zh else ", "
        results: list[RetrieverResult] = []
        for i, row in enumerate(rows[:20]):
            product = str(row.get("product", row.get("region", record)))
            quarter = str(row.get("quarter", ""))
            region = row.get("region", "")
            snippet = sep.join(f"{k}={v}" for k, v in row.items() if k != "id")
            content = (
                f"业务数据库 sales 表查询结果：{snippet}"
                if zh
                else f"Business database sales table query results: {snippet}"
            )
            if region:
                content += f"（{region}区）" if zh else f" ({region} region)"
            results.append(
                RetrieverResult(
                    source="database",
                    score=round(1.0 - i * 0.01, 2),
                    title=f"{product} · {quarter}".strip(" ·"),
                    content=content,
                    # Citation attribution needs the SQL plus the raw rows as evidence
                    # (rows already went through _serialize and are JSON safe)
                    metadata={"db": True, "sql": sql, "rows": rows[:20]},
                )
            )
        return sql, results


vector_retriever = VectorRetriever()
keyword_retriever = KeywordRetriever()
db_retriever = DBRetriever()


async def enabled_sources() -> dict[str, bool]:
    """Read the enabled retrieval sources from datasource_config (M2 -> Q3 trimming)."""
    rows = await db.aquery_all("SELECT source_type, enabled FROM datasource_config")
    mapping = {r["source_type"]: bool(r["enabled"]) for r in rows}
    return {
        "vector": mapping.get("vector", True),
        "keyword": mapping.get("keyword", True),
        "database": mapping.get("database", True),
    }


async def gather_lanes(
    query: str, kb_ids: list[int] | None, top_k: int, sources: list[str]
) -> tuple[dict[str, list[RetrieverResult]], dict[str, str]]:
    """Recall in parallel across the enabled sources; returns (lanes, errors).

    errors: source -> error summary. A failing lane no longer silently becomes an empty
    lane — the caller (orchestrator) decides how to surface it: an SSE degraded event, the
    decision log and a generation-side disclaimer, kept distinct from "not covered by the
    knowledge base".
    """
    runners: dict[str, Any] = {}
    if "vector" in sources:
        runners["vector"] = vector_retriever.search(query, kb_ids, top_k)
    if "keyword" in sources:
        runners["keyword"] = keyword_retriever.search(query, kb_ids, top_k)
    keys = list(runners.keys())
    results = await asyncio.gather(*runners.values(), return_exceptions=True)
    lanes: dict[str, list[RetrieverResult]] = {}
    errors: dict[str, str] = {}
    for key, res in zip(keys, results, strict=True):
        if isinstance(res, BaseException):
            msg = f"{type(res).__name__}: {res}"
            logger.warning("检索路 %s 失败：%s", key, msg)
            lanes[key] = []
            errors[key] = msg[:200]
        else:
            lanes[key] = res
    return lanes, errors

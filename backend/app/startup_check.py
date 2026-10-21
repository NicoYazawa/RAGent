"""Startup self-check — ES connectivity + LLM/Embedding provider keys + ES index dims/data consistency.

Runs during lifespan startup (main.py calls run_startup_checks):
- five checks in parallel with a per-check timeout; keys are verified by a minimal real request
  (auth / balance / model name)
- failures only print a prominent hint to the terminal and never block startup
  (/api/health reports degraded instead)
"""
import asyncio
import sys
from typing import Literal

import httpx

from . import db
from .config import settings
from .es import elastic

_TIMEOUT = 15  # per-check timeout in seconds


def _print_block(text: str) -> None:
    """Write UTF-8 straight to the terminal so Chinese text is not mangled by a Windows GBK
    console or a redirected pipe."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(text, flush=True)


def _err_message(r: httpx.Response) -> str:
    """Extract error.message (truncated) from an OpenAI-compatible error body."""
    try:
        err = r.json().get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:160]
    except ValueError:
        pass
    return (r.text or "无错误详情")[:160]


async def check_es() -> tuple[bool, str]:
    try:
        r = await elastic.client.get("/")
    except httpx.HTTPError as e:
        return False, f"连接失败（{type(e).__name__}）— 请确认 Elasticsearch 已启动：{settings.es_url}"
    if r.status_code == 200:
        return True, f"连接正常（{settings.es_url}）"
    if r.status_code == 401:
        return False, "认证失败（HTTP 401）— 请检查 .env 中 ES_USER / ES_PASSWORD"
    return False, f"响应异常（HTTP {r.status_code}）— {settings.es_url}"


async def check_provider(kind: Literal["llm", "embedding"]) -> tuple[bool, str]:
    """Verify the active provider's key and model with a minimal real request
    (kind: "llm" | "embedding").

    Covers auth / balance / model name; the request body matches providers/openai_compat.py.
    """
    if kind == "llm":
        spec, base, model = settings.active_llm_spec, settings.resolved_llm_base_url, settings.resolved_llm_model
    else:
        spec, base, model = settings.active_embed_spec, settings.resolved_embed_base_url, settings.resolved_embed_model
    key = settings.api_key_for(spec.api_key_env) if spec.api_key_env else ""
    if spec.api_key_env and not key:
        return False, f"未配置 {spec.api_key_env} — 请在 backend/.env 中设置"
    suffix = f" / {settings.resolved_embed_dims} 维" if kind == "embedding" else ""
    try:
        async with httpx.AsyncClient(
            base_url=base,
            headers={"Authorization": f"Bearer {key or 'not-needed'}"},
            timeout=_TIMEOUT,
        ) as client:
            if kind == "llm":
                r = await client.post(
                    "/chat/completions",
                    json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                )
            else:
                r = await client.post(
                    "/embeddings",
                    json={
                        "model": model,
                        "input": ["ping"],
                        "dimensions": settings.resolved_embed_dims,
                        "encoding_format": "float",
                    },
                )
    except httpx.HTTPError as e:
        return False, f"请求失败（{type(e).__name__}）— 请检查网络与 {base}"
    if r.status_code == 200:
        return True, f"密钥有效（{model}{suffix}）"
    hint = {401: "密钥无效", 402: "账户余额不足", 404: "模型不存在（检查模型名）"}.get(r.status_code, "密钥不可用")
    return False, f"{hint}（HTTP {r.status_code}）：{_err_message(r)}"


async def check_embedding_dims() -> tuple[bool, str]:
    """ES index dims vs the active embedding provider dims (a mismatch guarantees that vector
    retrieval fails)."""
    dims = settings.resolved_embed_dims
    index_dims = await elastic.index_dims()
    if index_dims is None:
        return True, f"索引不存在，将按 {dims} 维创建（{settings.embed_provider}）"
    if index_dims == dims:
        return True, f"索引维度一致（{dims} 维，{settings.embed_provider}）"
    return False, (
        f"维度冲突：ES 索引为 {index_dims} 维，当前 {settings.embed_provider} 为 {dims} 维。"
        f"请切回原供应商，或重建索引并全量重新向量化（一键重建将在 Provider Phase 2 提供）"
    )


async def consistency_status() -> dict:
    """Consistency between the ES document count and the MySQL ready chunk count (shared by
    health and the startup self-check).

    Guards against silent failures such as "stack rebuilt without the ES volume": MySQL metadata
    says ready while ES is actually empty, and retrieval silently degrades to "not covered by the
    knowledge base". Returns match: True/False/None (None = comparison skipped).
    """
    out: dict = {"mysql_ready_chunks": None, "es_docs": None, "match": None, "detail": ""}
    try:
        row = await db.aquery_one("SELECT COALESCE(SUM(chunk_count), 0) AS n FROM kb_document WHERE status = 'ready'")
        out["mysql_ready_chunks"] = int(row["n"]) if row else 0
    except Exception as e:
        out["detail"] = f"MySQL 查询失败（{type(e).__name__}），跳过比对"
        return out
    try:
        index_missing = await elastic.index_dims() is None
    except Exception as e:
        # When ES is down index_dims raises: degrade to "skipped" rather than a 500 (health relies
        # on this function)
        out["detail"] = f"ES 查询失败（{type(e).__name__}），跳过比对"
        return out
    if index_missing:
        out["detail"] = "ES 索引不存在（将按当前维度创建），跳过比对"
        return out
    try:
        out["es_docs"] = await elastic.count()
    except Exception as e:
        out["detail"] = f"ES 查询失败（{type(e).__name__}），跳过比对"
        return out
    out["match"] = out["es_docs"] == out["mysql_ready_chunks"]
    if out["match"]:
        out["detail"] = f"一致（MySQL ready {out['mysql_ready_chunks']} 切片 = ES {out['es_docs']} 文档）"
    else:
        out["detail"] = (
            f"不一致：MySQL ready 切片 {out['mysql_ready_chunks']} ≠ ES 文档 {out['es_docs']}，"
            f"ES 数据可能丢失（如栈重建未保留卷）。恢复：源文件在用 backend/scripts/resync_all_chunks.py，"
            f"源文件不在用 backend/scripts/backfill_es_from_mysql.py，完成后重启服务。"
        )
    return out


async def check_es_mysql_consistency() -> tuple[bool | None, str]:
    """Startup self-check entry: a mismatch is FAIL; skipped states (query failed / index missing)
    return None (rendered with the [SKIP] badge)."""
    st = await consistency_status()
    return st["match"], st["detail"]


async def run_startup_checks() -> None:
    """Run the five checks in parallel and print a prominent terminal summary; an exception in the
    self-check itself never blocks startup."""
    try:
        results = await asyncio.gather(
            check_es(),
            check_provider("llm"),
            check_provider("embedding"),
            check_embedding_dims(),
            check_es_mysql_consistency(),
            return_exceptions=True,  # one failure must not swallow the other four diagnostics
        )
    except Exception as e:
        _print_block(f"[启动自检] 执行异常，已跳过：{type(e).__name__}: {e}")
        return
    names = [
        "Elasticsearch",
        f"{settings.active_llm_spec.label} LLM（{settings.llm_provider}）",
        f"{settings.active_embed_spec.label} Embedding（{settings.embed_provider}）",
        "ES 索引维度一致性",
        "ES/MySQL 数据一致性",
    ]
    checks: list[tuple[str, tuple[bool | None, str]]] = []
    for name, res in zip(names, results, strict=True):
        if isinstance(res, BaseException):
            checks.append((name, (False, f"检查自身异常（{type(res).__name__}）：{res}")))
        else:
            checks.append((name, res))
    bar = "=" * 76
    lines = [bar, "[启动自检]"]
    for name, (ok, detail) in checks:
        badge = "[OK]" if ok else ("[SKIP]" if ok is None else "[FAIL]")
        lines.append(f"  {badge:<7} {name}：{detail}")
    problems = [f"{name} — {detail}" for name, (ok, detail) in checks if ok is False]
    if problems:
        lines.append("-" * 76)
        lines.append("以下依赖异常（服务仍将启动，对应功能不可用）：")
        lines.extend(f"  * {p}" for p in problems)
    else:
        lines.append("全部依赖正常。")
    lines.append(bar)
    _print_block("\n".join(lines))

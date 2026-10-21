"""Retrieval test playground router — per-lane recall + application-level RRF fusion + the real grader.

Mirrors the Q3/Q4 pipeline: it reuses the retrieval adapters and the grader so the admin UI can
verify behavior directly.
"""
import logging
import time

from fastapi import APIRouter, HTTPException

from ..agent import orchestrator
from ..agent.retrievers import db_retriever, keyword_retriever, vector_retriever
from ..agent.rrf import RetrieverResult, item_key, rrf_fuse
from ..config import settings
from ..i18n import current_locale, t
from ..models import FuseRequest, LaneRequest

router = APIRouter(prefix="/api/admin/retrieval-test", tags=["playground"])

logger = logging.getLogger("agentic.playground")


def _hit(item: RetrieverResult) -> dict:
    return {
        "title": item.title,
        "snippet": item.content,
        "score": item.score,
        "meta": dict(item.metadata),
    }


@router.post("/lane")
async def test_lane(body: LaneRequest) -> dict:
    t0 = time.time()
    if body.source == "vector":
        results = await vector_retriever.search(body.query, body.kb_ids, body.top_k)
    elif body.source == "keyword":
        results = await keyword_retriever.search(body.query, body.kb_ids, body.top_k)
    elif body.source == "database":
        # For non-data questions NL2SQL may emit invalid or non-executable SQL: degrade to zero
        # hits instead of failing the other lanes
        try:
            _, results = await db_retriever.search(body.query, body.top_k, current_locale())
        except Exception as e:
            logger.warning("Playground database 路查询失败：%s", e)
            results = []
    else:
        raise HTTPException(400, t("api.unknown_source", source=body.source))
    return {
        "source": body.source,
        "latency_ms": int((time.time() - t0) * 1000),
        "hits": [_hit(r) for r in results],
    }


@router.post("/fuse")
async def test_fuse(body: FuseRequest) -> dict:
    lanes: dict[str, list[RetrieverResult]] = {}
    for lane in body.lanes:
        lanes[lane.source] = [
            RetrieverResult(
                source=lane.source,
                score=h.score,
                title=h.title,
                content=h.snippet,
                metadata=dict(h.meta),
            )
            for h in lane.hits
        ]
    query = body.query.strip() or "（综合各路检索查询）"
    # Same as orchestrator.rerank_params(): widen the candidate pool when reranking is on (pass
    # True explicitly; _apply_rerank degrades when the provider is unavailable)
    candidates = settings.fused_top_n
    if body.rerank and settings.rerank_enabled:
        _, candidates = orchestrator.rerank_params(True)
    fused = rrf_fuse(lanes, candidates)
    items = [f["item"] for f in fused]
    rrf_by_key = {item_key(f["item"]): f for f in fused}

    rerank_info = None
    if body.rerank and settings.rerank_enabled:
        items, rerank_info, rerank_err = await orchestrator._apply_rerank(query, items, current_locale())
        if rerank_err:
            rerank_info = {"error": rerank_err}

    ctx_blocks = orchestrator.build_context(items)
    score, verdict, reason = await orchestrator.do_grade(query, [], ctx_blocks, {}, current_locale())
    return {
        "fused": [
            {
                "key": item_key(it),
                "rrf": rrf_by_key[item_key(it)]["rrf"],
                "from_lanes": rrf_by_key[item_key(it)]["from_lanes"],
                "hit": _hit(it),
            }
            for it in items
        ],
        "rerank": rerank_info,
        "grade": {"score": score, "verdict": verdict, "reason": reason},
    }

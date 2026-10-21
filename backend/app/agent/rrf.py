"""Application-level RRF fusion — rrf(d) = sum of 1/(k + rank), k=60

ES built-in RRF requires a paid subscription and cannot fuse MySQL or web results inside
ES, so fusion runs in Python. Each lane is deduplicated first (adjacent chunks of the same
document are merged) and the top 8 fused items are kept for grading.
"""
from dataclasses import dataclass, field


@dataclass
class RetrieverResult:
    """Unified result protocol."""

    source: str  # vector / keyword / database / web
    score: float
    title: str
    content: str
    metadata: dict = field(default_factory=dict)  # doc_name / section_path / chunk_no / url / doc_id


def item_key(item: RetrieverResult) -> str:
    meta = item.metadata
    if meta.get("url"):
        return f"web:{meta['url']}"
    if meta.get("chunk_uid"):
        return f"chunk:{meta['chunk_uid']}"
    if meta.get("doc_id") is not None and meta.get("chunk_no") is not None:
        return f"doc:{meta['doc_id']}#{meta['chunk_no']}"
    if meta.get("doc_name") and meta.get("chunk_no") is not None:
        return f"chunk:{meta['doc_name']}#{meta['chunk_no']}"
    return f"db:{item.title}"


def dedupe_lane(items: list[RetrieverResult]) -> list[RetrieverResult]:
    """Deduplicate within one lane: merge adjacent chunks of the same document (keep the first
    so a single document cannot flood the ranking)."""
    kept: list[RetrieverResult] = []
    last_doc: tuple | None = None
    for it in items:
        meta = it.metadata
        doc = (
            ("id", meta["doc_id"]) if meta.get("doc_id") is not None
            else ("name", meta.get("kb_id"), meta["doc_name"]) if meta.get("doc_name") is not None
            else None
        )
        if doc is not None and doc == last_doc:
            continue
        kept.append(it)
        last_doc = doc
    return kept


def rrf_fuse(
    lanes: dict[str, list[RetrieverResult]],
    top_n: int = 8,
    k: int = 60,
) -> list[dict]:
    """Fuse several lanes: return [{item, rrf, from_lanes}] sorted by rrf, truncated to top_n."""
    acc: dict[str, dict] = {}
    for source, items in lanes.items():
        for rank, it in enumerate(dedupe_lane(items)):
            key = item_key(it)
            score = 1.0 / (k + rank + 1)
            slot = acc.get(key)
            if slot is None:
                acc[key] = {"item": it, "rrf": score, "from_lanes": {source}}
            else:
                slot["rrf"] += score
                slot["from_lanes"].add(source)
    fused = sorted(acc.values(), key=lambda x: x["rrf"], reverse=True)[:top_n]
    return [
        {"item": s["item"], "rrf": round(s["rrf"], 4), "from_lanes": sorted(s["from_lanes"])}
        for s in fused
    ]

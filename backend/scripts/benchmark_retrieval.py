"""Retrieval regression benchmark — A/B comparison over the gold question set (before/after rerank).

Measures retrieval ranking quality and per-stage latency without calling an LLM (cheap and
repeatable):
  - chunk-level / doc-level Recall@5 / Recall@8 / MRR / nDCG@8 (against the manual labels in goldset.json)
  - vector / keyword / rerank / end-to-end latency (avg / p50 / p95)
  - diagnostics: whether the gold chunk is in each lane's raw results (shows which lane rerank should keep)

A/B workflow (baseline first, then compare):
  # 1) save the baseline before the change
  python scripts/benchmark_retrieval.py --save reports/baseline-2026-10-19.json
  # 2) compare after the change (prints the delta table plus the per-question gains/losses)
  python scripts/benchmark_retrieval.py --diff reports/baseline-2026-10-19.json

rerank switch: --rerank / --no-rerank force the setting; otherwise settings.rerank_enabled
wins (a missing field counts as off). The rerank hook probes app.providers.get_rerank, so
once rerank is implemented this script takes part in the comparison with no changes.
"""
import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow running from outside backend/

from app.agent.retrievers import keyword_retriever, vector_retriever  # noqa: E402
from app.agent.rrf import item_key, rrf_fuse  # noqa: E402
from app.config import settings  # noqa: E402

GOLDSET = Path(__file__).parent / "goldset.json"


# ---------- Metrics ----------

def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    return 1.0 if set(ranked[:k]) & gold else 0.0


def first_gold_rank(ranked: list[str], gold: set[str]) -> int | None:
    for i, key in enumerate(ranked, 1):
        if key in gold:
            return i
    return None


def mrr(ranked: list[str], gold: set[str]) -> float:
    r = first_gold_rank(ranked, gold)
    return 1.0 / r if r else 0.0


def ndcg_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, key in enumerate(ranked[:k], 1) if key in gold)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / idcg if idcg > 0 else 0.0


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1)))]


# ---------- Gold question set ----------

def load_goldset() -> list[dict]:
    data = json.loads(GOLDSET.read_text(encoding="utf-8"))
    for q in data["questions"]:
        q["doc"] = q["doc"].rsplit(".", 1)[0]
        q["gold_chunk_keys"] = {f"chunk:{q['doc']}#{n}" for n in q["chunks"]}
        q["gold_doc_keys"] = {f"doc:{q['doc']}"}
    return data["questions"]


# ---------- Rerank hook (kicks in once rerank is implemented) ----------

async def apply_rerank(query: str, items: list, top_n: int):
    """Return (reordered items, info). Returns the input unchanged when rerank is missing or
    unconfigured (a run that explicitly asks for --rerank fails loudly)."""
    try:
        from app.providers import get_rerank  # exists once rerank is implemented
    except ImportError:
        return items, None
    provider = get_rerank()
    t0 = time.perf_counter()
    scored = await provider.rerank(query, [it.content for it in items], top_n)
    elapsed = (time.perf_counter() - t0) * 1000
    # Same as orchestrator._apply_rerank: drop out-of-range indices
    reordered = [items[i] for i, _ in scored if 0 <= i < len(items)]
    return reordered, {"model": getattr(provider, "model", "?"), "ms": round(elapsed, 1), "in": len(items), "out": len(reordered)}


# ---------- Per-question run ----------

async def run_question(q: dict, top_k: int, use_rerank: bool) -> dict:
    # Matches orchestrator.rerank_params(): with rerank on, deepen per-lane recall and widen the
    # candidate pool
    if use_rerank:
        lane_top_k = max(top_k, (settings.rerank_candidates + 1) // 2)
        candidates = settings.rerank_candidates
    else:
        lane_top_k, candidates = top_k, settings.fused_top_n

    t0 = time.perf_counter()
    vec_hits = await vector_retriever.search(q["q"], None, lane_top_k)
    t_vec = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    kw_hits = await keyword_retriever.search(q["q"], None, lane_top_k)
    t_kw = (time.perf_counter() - t0) * 1000

    lanes = {"vector": vec_hits, "keyword": kw_hits}
    fused = rrf_fuse(lanes, candidates)
    items = [f["item"] for f in fused]

    rerank_info = None
    t_rr = 0.0
    if use_rerank:
        items, rerank_info = await apply_rerank(q["q"], items, settings.rerank_top_n)
        t_rr = rerank_info["ms"] if rerank_info else 0.0

    chunk_keys = [item_key(it) for it in items]
    doc_keys = []
    for k in chunk_keys:
        doc_keys.append(k.split("#")[0].replace("chunk:", "doc:") if k.startswith("chunk:") else k)
    gold_rank = first_gold_rank(chunk_keys, q["gold_chunk_keys"])

    return {
        "id": q["id"],
        "q": q["q"],
        "tags": q["tags"],
        "gold": sorted(q["gold_chunk_keys"]),
        "gold_rank": gold_rank,  # None = not retrieved
        "chunk_keys": chunk_keys,
        "doc_keys": doc_keys,
        "metrics": {
            "recall@5": recall_at_k(chunk_keys, q["gold_chunk_keys"], 5),
            "recall@8": recall_at_k(chunk_keys, q["gold_chunk_keys"], 8),
            "mrr": mrr(chunk_keys, q["gold_chunk_keys"]),
            "ndcg@8": ndcg_at_k(chunk_keys, q["gold_chunk_keys"], 8),
            "doc_recall@5": recall_at_k(doc_keys, q["gold_doc_keys"], 5),
            "doc_recall@8": recall_at_k(doc_keys, q["gold_doc_keys"], 8),
            "doc_mrr": mrr(doc_keys, q["gold_doc_keys"]),
        },
        "timings": {
            "vector_ms": round(t_vec, 1),
            "keyword_ms": round(t_kw, 1),
            "rerank_ms": round(t_rr, 1),
            "total_ms": round(t_vec + t_kw + t_rr, 1),
        },
        "gold_in_lanes": {
            "vector": bool(set(item_key(h) for h in vec_hits) & q["gold_chunk_keys"]),
            "keyword": bool(set(item_key(h) for h in kw_hits) & q["gold_chunk_keys"]),
        },
        "rerank": rerank_info,
    }


# ---------- Summary and report ----------

def summarize(results: list[dict]) -> dict:
    keys = ["recall@5", "recall@8", "mrr", "ndcg@8", "doc_recall@5", "doc_recall@8", "doc_mrr"]
    agg = {k: round(statistics.mean(r["metrics"][k] for r in results), 4) for k in keys}
    for stage in ("vector_ms", "keyword_ms", "rerank_ms", "total_ms"):
        vals = [r["timings"][stage] for r in results]
        agg[f"{stage}_avg"] = round(statistics.mean(vals), 1)
        agg[f"{stage}_p50"] = round(pct(vals, 0.5), 1)
        agg[f"{stage}_p95"] = round(pct(vals, 0.95), 1)
    agg["n"] = len(results)
    agg["hit"] = sum(1 for r in results if r["gold_rank"])
    agg["rerank_on"] = any(r["rerank"] for r in results)
    return agg


def print_report(summary: dict) -> None:
    bar = "=" * 64
    print(bar)
    print(f"检索基准：{summary['n']} 题｜gold 命中 {summary['hit']}/{summary['n']}｜rerank {'ON' if summary['rerank_on'] else 'OFF'}")
    print(bar)
    rows = [
        ("chunk Recall@5", "recall@5"), ("chunk Recall@8", "recall@8"),
        ("chunk MRR", "mrr"), ("chunk nDCG@8", "ndcg@8"),
        ("doc Recall@5", "doc_recall@5"), ("doc Recall@8", "doc_recall@8"), ("doc MRR", "doc_mrr"),
    ]
    for label, key in rows:
        print(f"  {label:<16} {summary[key]:.4f}")
    print(f"  {'延迟 vector avg':<16} {summary['vector_ms_avg']:>8.1f} ms（p50 {summary['vector_ms_p50']:.0f} / p95 {summary['vector_ms_p95']:.0f}）")
    print(f"  {'延迟 keyword avg':<16} {summary['keyword_ms_avg']:>8.1f} ms（p50 {summary['keyword_ms_p50']:.0f} / p95 {summary['keyword_ms_p95']:.0f}）")
    if summary["rerank_on"]:
        print(f"  {'延迟 rerank avg':<16} {summary['rerank_ms_avg']:>8.1f} ms（p50 {summary['rerank_ms_p50']:.0f} / p95 {summary['rerank_ms_p95']:.0f}）")
    print(f"  {'延迟 total avg':<16} {summary['total_ms_avg']:>8.1f} ms（p50 {summary['total_ms_p50']:.0f} / p95 {summary['total_ms_p95']:.0f}）")
    print(bar)


def print_diff(baseline: dict, current: dict) -> None:
    b, c = baseline["summary"], current["summary"]
    bar = "=" * 64
    print(bar)
    print(f"A/B 对比（基线 {baseline.get('tag', '?')} → 当前 {current.get('tag', '?')}）")
    print(bar)
    print(f"  {'指标':<16} {'基线':>8} {'当前':>8} {'Δ':>8}")
    for key in ("recall@5", "recall@8", "mrr", "ndcg@8", "doc_recall@5", "doc_recall@8", "doc_mrr"):
        delta = c[key] - b[key]
        flag = " ✅" if delta > 0.005 else (" ❌" if delta < -0.005 else "")
        print(f"  {key:<16} {b[key]:>8.4f} {c[key]:>8.4f} {delta:>+8.4f}{flag}")
    print(f"  {'total avg(ms)':<16} {b['total_ms_avg']:>8.1f} {c['total_ms_avg']:>8.1f} {c['total_ms_avg'] - b['total_ms_avg']:>+8.1f}")
    # Per-question gains and regressions
    b_ranks = {r["id"]: r["gold_rank"] for r in baseline["results"]}
    improved, regressed = [], []
    for r in current["results"]:
        old, new = b_ranks.get(r["id"]), r["gold_rank"]
        if old == new:
            continue
        old_v = old if old else 999
        new_v = new if new else 999
        (improved if new_v < old_v else regressed).append((r["id"], old, new))
    print(f"\n  进退步：改善 {len(improved)} 题，退化 {len(regressed)} 题")
    for qid, old, new in regressed:
        print(f"    ❌ {qid}: gold rank {old} → {new}")
    for qid, old, new in improved:
        print(f"    ✅ {qid}: gold rank {old} → {new}")
    print(bar)


async def main() -> None:
    parser = argparse.ArgumentParser(description="检索回归基准（金标准集 A/B）")
    parser.add_argument("--top-k", type=int, default=5, help="单路召回深度（默认 5）")
    rerank_group = parser.add_mutually_exclusive_group()
    rerank_group.add_argument("--rerank", dest="rerank", action="store_true", help="强制开启精排")
    rerank_group.add_argument("--no-rerank", dest="rerank", action="store_false", help="强制关闭精排（基线）")
    parser.set_defaults(rerank=getattr(settings, "rerank_enabled", False))
    parser.add_argument("--save", type=str, default="", help="保存本次结果 JSON（基线用）")
    parser.add_argument("--diff", type=str, default="", help="与历史结果 JSON 对比")
    parser.add_argument("--tag", type=str, default="", help="本次运行标签（写入保存文件）")
    args = parser.parse_args()

    questions = load_goldset()
    print(f"金标准集 {len(questions)} 题｜rerank={'ON' if args.rerank else 'OFF'}｜top_k={args.top_k}")
    results = []
    for i, q in enumerate(questions, 1):
        r = await run_question(q, args.top_k, args.rerank)
        results.append(r)
        rank = r["gold_rank"] or "未命中"
        print(f"  [{i:>2}/{len(questions)}] {r['id']:<12} gold rank: {rank}", end="\r")
    print()

    current = {"tag": args.tag or ("rerank" if args.rerank else "baseline"), "config": {"top_k": args.top_k, "rerank": args.rerank}, "results": results, "summary": summarize(results)}
    print_report(current["summary"])

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存：{args.save}")
    if args.diff:
        baseline = json.loads(Path(args.diff).read_text(encoding="utf-8"))
        print_diff(baseline, current)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

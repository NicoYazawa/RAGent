"""rerank 管线接线 — 候选深度扩展 / 精排事件 / 失败降级（打穿 _run 全链路）"""
import json

import pytest

from app.agent import orchestrator
from app.agent.rrf import RetrieverResult
from app.config import settings


def _parse_events(raw_list: list[str]) -> list[tuple[str, dict]]:
    out = []
    for raw in raw_list:
        lines = raw.strip().split("\n")
        out.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return out


class _FakeRerank:
    """Records calls and returns the given order; raises when exc is set (to test degradation)."""

    name = "qwen"
    model = "gte-rerank-v2"

    def __init__(self, order=None, exc=None):
        self._order = order or []
        self._exc = exc
        self.calls = []

    async def rerank(self, query, documents, top_n):
        self.calls.append({"query": query, "documents": documents, "top_n": top_n})
        if self._exc:
            raise self._exc
        return self._order


@pytest.fixture
def rerank_run(monkeypatch):
    captured = {"gen_msgs": None, "steps_json": None, "gather_top_k": None}

    async def _aquery_all(sql, params=None):
        return []

    async def _aquery_one(sql, params=None):
        if "chat_session" in sql:
            return {"title": "新会话"}
        return {"n": 0}

    async def _aexecute(sql, params=None):
        if "agent_decision_log" in sql:
            captured["steps_json"] = params[4]
        return 1

    monkeypatch.setattr(orchestrator.db, "aquery_all", _aquery_all)
    monkeypatch.setattr(orchestrator.db, "aquery_one", _aquery_one)
    monkeypatch.setattr(orchestrator.db, "aexecute", _aexecute)

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        name = schema.__name__
        if name == "RouterOut":
            return orchestrator.RouterOut(intent="kb_qa", confidence=0.9)
        if name == "PlannerOut":
            return orchestrator.PlannerOut(rewritten_query="迟到怎么认定")
        if name == "CragOut":
            return orchestrator.CragOut(failure_reason="x", action="give_up", new_queries=[])
        if name == "ReflectOut":
            return orchestrator.ReflectOut(result="pass")
        raise AssertionError(f"未预期的判定：{name}")

    async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
        return 9.0, "pass", "ok"

    async def _enabled():
        return {"vector": True, "keyword": True, "database": True}

    items = [
        RetrieverResult(source="vector", score=0.9, title="甲", content="片段甲：迟到认定标准",
                        metadata={"doc_name": "考勤制度", "chunk_no": 3}),
        RetrieverResult(source="keyword", score=0.8, title="乙", content="片段乙：处罚标准",
                        metadata={"doc_name": "考勤制度", "chunk_no": 4}),
    ]

    async def _gather(query, kb_ids, top_k, sources):
        captured["gather_top_k"] = top_k
        return {"vector": items[:1], "keyword": items[1:]}, {}

    async def _stream(messages, usage=None):
        captured["gen_msgs"] = messages
        yield "答案"

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    monkeypatch.setattr(orchestrator, "do_grade", _grade)
    monkeypatch.setattr(orchestrator, "enabled_sources", _enabled)
    monkeypatch.setattr(orchestrator, "gather_lanes", _gather)
    monkeypatch.setattr(orchestrator, "stream_generate", _stream)
    captured["items"] = items
    return captured


def _patch_rerank(monkeypatch, fake):
    monkeypatch.setattr(orchestrator, "get_rerank", lambda: fake)
    monkeypatch.setattr(settings, "rerank_enabled", True, raising=False)


async def test_rerank_on_expands_candidates_and_reorders(rerank_run, monkeypatch):
    """Enabled: per-lane top_k grows to candidates/2, rerank reorders the results and an SSE rerank
    event is emitted."""
    fake = _FakeRerank(order=[(1, 0.95), (0, 0.55)])  # B moves ahead of A
    _patch_rerank(monkeypatch, fake)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    # candidate depth: candidates=20 -> per-lane top_k=max(5, 10)=10
    assert rerank_run["gather_top_k"] == 10
    # rerank was called with the full question as the query
    assert fake.calls and fake.calls[0]["query"] == "迟到是怎么认定和处罚的？"
    assert fake.calls[0]["top_n"] == settings.rerank_top_n
    # the SSE rerank event
    rr_events = [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    assert rr_events, "开启精排必须产出 source=rerank 的检索事件"
    assert rr_events[0]["hit_count"] == 2
    assert rr_events[0]["rerank"]["model"] == "gte-rerank-v2"
    # the decision log contains the rerank step
    assert '"source": "rerank"' in rerank_run["steps_json"]
    # the generation context follows the rerank order (B before A)
    gen_text = json.dumps(rerank_run["gen_msgs"], ensure_ascii=False)
    assert gen_text.index("片段乙") < gen_text.index("片段甲")
    assert [t for t, _ in events][-1] == "done"


async def test_rerank_off_no_rerank_event(rerank_run, monkeypatch):
    """Disabled: candidate depth stays fused_top_n, no rerank event and the coarse order is kept."""
    monkeypatch.setattr(settings, "rerank_enabled", False, raising=False)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    assert rerank_run["gather_top_k"] == settings.retrieval_top_k
    assert not [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    gen_text = json.dumps(rerank_run["gen_msgs"], ensure_ascii=False)
    assert gen_text.index("片段甲") < gen_text.index("片段乙")


async def test_rerank_failure_degrades_to_rrf_order(rerank_run, monkeypatch):
    """A rerank failure: keep the coarse order, emit a degraded event and do not break the chain."""
    fake = _FakeRerank(exc=RuntimeError("upstream 500"))
    _patch_rerank(monkeypatch, fake)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])
    types = [t for t, _ in events]

    degraded = [d for t, d in events if t == "retrieve" and d.get("degraded") and d.get("rerank_error")]
    assert degraded, "精排失败必须产出 degraded 事件"
    gen_text = json.dumps(rerank_run["gen_msgs"], ensure_ascii=False)
    assert gen_text.index("片段甲") < gen_text.index("片段乙")  # the coarse order is kept
    assert '"degraded"' in rerank_run["steps_json"]
    assert types[-1] == "done"


async def test_rerank_failure_trips_circuit_breaker(rerank_run, monkeypatch):
    """Circuit break: after a rerank failure the CRAG re-query round does not call the failed provider
    again (Important 2 regression)."""
    fake = _FakeRerank(exc=RuntimeError("upstream 500"))
    _patch_rerank(monkeypatch, fake)

    async def _grade_fail(question, sub_queries, ctx_blocks, usage, locale=None):
        return 0.0, "fail", "无命中"

    crag_calls = {"n": 0}

    async def _judge2(schema, system, user, usage, attempts=2, images=None):
        name = schema.__name__
        if name == "CragOut":
            crag_calls["n"] += 1
            if crag_calls["n"] == 1:
                return orchestrator.CragOut(failure_reason="语义偏差", action="rewrite_retry", new_queries=["迟到 认定 处罚"])
            return orchestrator.CragOut(failure_reason="仍失败", action="give_up", new_queries=[])
        if name == "RouterOut":
            return orchestrator.RouterOut(intent="kb_qa", confidence=0.9)
        if name == "PlannerOut":
            return orchestrator.PlannerOut(rewritten_query="迟到怎么认定")
        if name == "ReflectOut":
            return orchestrator.ReflectOut(result="pass")
        raise AssertionError(name)

    monkeypatch.setattr(orchestrator, "do_grade", _grade_fail)
    monkeypatch.setattr(orchestrator, "_judge_retry", _judge2)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    # a first-round failure breaks the circuit: the CRAG re-query round (second gather) skips rerank
    assert len(fake.calls) == 1, f"熔断失效，精排被重复调用 {len(fake.calls)} 次"
    assert crag_calls["n"] == 2  # rewrite_retry -> re-retrieve -> give_up
    assert [t for t, _ in events][-1] == "done"


async def test_reflect_reflow_also_reranks(rerank_run, monkeypatch):
    """Reflect backflow also reranks (events carry the 「反思回流·」 prefix) with the same candidate depth."""
    fake = _FakeRerank(order=[(1, 0.95), (0, 0.55)])
    _patch_rerank(monkeypatch, fake)

    reflect_calls = {"n": 0}

    async def _judge2(schema, system, user, usage, attempts=2, images=None):
        name = schema.__name__
        if name == "ReflectOut":
            reflect_calls["n"] += 1
            if reflect_calls["n"] == 1:
                return orchestrator.ReflectOut(result="fail", missing_info="缺少处罚标准")
            return orchestrator.ReflectOut(result="pass")
        if name == "RouterOut":
            return orchestrator.RouterOut(intent="kb_qa", confidence=0.9)
        if name == "PlannerOut":
            return orchestrator.PlannerOut(rewritten_query="迟到怎么认定")
        if name == "CragOut":
            return orchestrator.CragOut(failure_reason="x", action="give_up", new_queries=[])
        raise AssertionError(name)

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge2)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    rr_events = [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    assert len(rr_events) == 2, "主链路 + 反思回流各应有一次精排"
    assert any(d["detail"].startswith("反思回流·") for d in rr_events)
    assert len(fake.calls) == 2
    assert [t for t, _ in events][-1] == "done"


async def test_rerank_on_but_provider_unavailable_keeps_default_depth(rerank_run, monkeypatch):
    """Provider unavailable: candidate depth stays at its default (no pointless extra ES load) and the
    coarse order is used (Important 1 regression)."""
    from app.providers.registry import UnknownProviderError

    def _boom():
        raise UnknownProviderError("供应商 deepseek 未配置 rerank 模型")

    monkeypatch.setattr(orchestrator, "get_rerank", _boom)
    monkeypatch.setattr(settings, "rerank_enabled", True, raising=False)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    assert rerank_run["gather_top_k"] == settings.retrieval_top_k  # not deepened to 10
    assert not [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    assert [t for t, _ in events][-1] == "done"

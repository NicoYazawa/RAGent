"""编排层主流程 — 闲聊旁路 / NL2SQL 旁路 / 总结 / 补充检索 / CRAG / 异常收尾

覆盖 _run 的分支走向：哪些 intent 走哪条路、失败时如何降级收尾。
"""
import json

import pytest

from app.agent import orchestrator
from app.agent.rrf import RetrieverResult


def _parse_events(raw_list):
    out = []
    for raw in raw_list:
        lines = raw.strip().split("\n")
        out.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return out


class Harness:
    """Scriptable fake environment: controls judge results, retrieval results and generated output."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.calls = {"gather": [], "judge": [], "stream": 0, "db_rows": []}
        self.intent = "kb_qa"
        self.confidence = 0.9
        self.grade_score = 9.0
        self.grade_verdict = "pass"
        self.crag_actions = []
        self.reflect_results = []
        self.items = [RetrieverResult(source="vector", score=0.9, title="甲", content="片段甲",
                                      metadata={"doc_name": "手册", "chunk_no": 1})]
        self.lane_errors = {}
        self.sources = ["vector", "keyword"]
        self._install()

    def _install(self):
        m = self.monkeypatch

        async def _aquery_all(sql, params=None):
            return []

        async def _aquery_one(sql, params=None):
            if "chat_session" in sql:
                return {"title": "新会话"}
            if "kb_document" in sql:
                return {"n": 0}
            return {"n": 0}

        async def _aexecute(sql, params=None):
            return 1

        m.setattr(orchestrator.db, "aquery_all", _aquery_all)
        m.setattr(orchestrator.db, "aquery_one", _aquery_one)
        m.setattr(orchestrator.db, "aexecute", _aexecute)

        async def _judge(schema, system, user, usage, attempts=2, images=None):
            self.calls["judge"].append(schema.__name__)
            name = schema.__name__
            if name == "RouterOut":
                return orchestrator.RouterOut(intent=self.intent, confidence=self.confidence)
            if name == "PlannerOut":
                return orchestrator.PlannerOut(rewritten_query="迟到怎么认定")
            if name == "CragOut":
                action = self.crag_actions.pop(0) if self.crag_actions else "give_up"
                return orchestrator.CragOut(failure_reason="语义偏差", action=action,
                                           new_queries=["迟到 认定 处罚"])
            if name == "ReflectOut":
                result = self.reflect_results.pop(0) if self.reflect_results else "pass"
                return orchestrator.ReflectOut(result=result, missing_info="缺少处罚标准")
            if name == "GraderOut":
                return orchestrator.GraderOut(score=self.grade_score, reason="理由")
            raise AssertionError(f"未预期的判定：{name}")

        async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
            return self.grade_score, self.grade_verdict, "理由"

        async def _enabled():
            return {"vector": True, "keyword": True, "database": True}

        async def _gather(query, kb_ids, top_k, sources):
            self.calls["gather"].append({"query": query, "top_k": top_k, "sources": sources, "kb_ids": kb_ids})
            return {"vector": self.items, "keyword": []}, dict(self.lane_errors)

        async def _stream(messages, usage=None):
            self.calls["stream"] += 1
            yield "答案"

        m.setattr(orchestrator, "_judge_retry", _judge)
        m.setattr(orchestrator, "do_grade", _grade)
        m.setattr(orchestrator, "enabled_sources", _enabled)
        m.setattr(orchestrator, "gather_lanes", _gather)
        m.setattr(orchestrator, "stream_generate", _stream)


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


# ---------- Chitchat bypass ----------

async def test_chitchat_skips_retrieval(h):
    """Chitchat: no retrieval, stream the answer directly."""
    h.intent = "chitchat"
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "你好", None)])

    types = [t for t, _ in events]
    assert types[0] == "router"
    assert "retrieve" not in types
    assert types[-1] == "done"
    assert h.calls["gather"] == []
    assert h.calls["stream"] == 1


# ---------- NL2SQL bypass ----------

async def test_data_query_uses_nl2sql_directly(h, monkeypatch):
    """Data query: skip rewriting and go straight to database retrieval."""
    h.intent = "data_query"
    rows = [RetrieverResult(source="database", score=1.0, title="Q1", content="销售额 100",
                            metadata={"db": True, "sql": "SELECT ...", "rows": [{"id": 1}]})]

    async def _db_search(question, top_k=5, locale="zh-CN"):
        return "SELECT product FROM sales", rows

    monkeypatch.setattr(orchestrator.db_retriever, "search", _db_search)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "一季度销售额", None)])
    types = [t for t, _ in events]
    assert "rewrite" not in types
    db_events = [d for t, d in events if t == "retrieve" and d.get("source") == "database"]
    assert db_events
    assert db_events[0]["hit_count"] == 1
    assert types[-1] == "done"
    assert h.calls["gather"] == []


async def test_data_query_falls_back_to_documents_when_grade_not_pass(h, monkeypatch):
    """When NL2SQL results do not pass, documents must be retrieved instead of assuming the knowledge
    base lacks the answer."""
    h.intent = "data_query"
    h.grade_score = 2.0
    h.grade_verdict = "fail"
    rows = [RetrieverResult(source="database", score=1.0, title="Q1", content="销售额",
                            metadata={"db": True, "sql": "SELECT 1", "rows": []})]

    async def _db_search(question, top_k=5, locale="zh-CN"):
        return "SELECT 1", rows

    monkeypatch.setattr(orchestrator.db_retriever, "search", _db_search)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "销售额", None)])
    assert any(t == "grade" and d.get("verdict") == "fail" for t, d in events)
    assert h.calls["gather"]


@pytest.mark.parametrize("db_verdict, db_score", [("fail", 0.0), ("partial", 6.0)])
@pytest.mark.parametrize("question", [
    "最近来的候选人的具体信息有哪些",
    "这份合同约定的付款期限是几天",
    "设备告警代码的含义和处理方法是什么",
])
async def test_unrelated_database_evidence_falls_back_to_document_search(h, monkeypatch, db_verdict, db_score, question):
    h.intent = "data_query"  # Any misclassified domain can recover via document retrieval.
    h.items = [RetrieverResult("keyword", 0.9, "document", "DOCUMENT_EVIDENCE", {
        "doc_name": "document", "doc_id": 30, "kb_id": 9, "chunk_uid": "chunk-30", "chunk_no": 1,
    })]
    db_calls = []
    grades = iter([(db_score, db_verdict, "unrelated database"), (9.0, "pass", "document found")])

    async def db_search(query, top_k=5, locale="zh-CN"):
        db_calls.append(query)
        return "SELECT 1", [RetrieverResult("database", 1, "sales", "UNRELATED_SALES_SENTINEL", {"db": True})]

    async def grade(*args):
        return next(grades)

    async def stream(messages, usage=None):
        context = json.dumps(messages)
        assert "DOCUMENT_EVIDENCE" in context
        assert "UNRELATED_SALES_SENTINEL" not in context
        yield "document fact [1]"

    monkeypatch.setattr(orchestrator.db_retriever, "search", db_search)
    monkeypatch.setattr(orchestrator, "do_grade", grade)
    monkeypatch.setattr(orchestrator, "stream_generate", stream)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, question, [9])])
    assert db_calls == [question]
    assert h.calls["gather"][0]["kb_ids"] == [9]
    assert any(kind == "router" and payload.get("intent") == "kb_qa" for kind, payload in events)
    citation = next(payload for kind, payload in events if kind == "citation")
    assert citation["citations"][0]["doc_id"] == 30
    assert citation["citations"][0]["ref_id"] == 1
    assert events[-1][0] == "done"


async def test_disabled_database_cannot_be_selected_even_if_router_requests_it(h, monkeypatch):
    h.intent = "data_query"

    async def enabled():
        return {"vector": True, "keyword": True, "database": False}

    async def forbidden_query(*args, **kwargs):
        pytest.fail("Disabled data source must not be queried")

    monkeypatch.setattr(orchestrator, "enabled_sources", enabled)
    monkeypatch.setattr(orchestrator.db_retriever, "search", forbidden_query)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "question", [9])])
    assert next(payload for kind, payload in events if kind == "router")["intent"] == "kb_qa"
    assert h.calls["gather"][0]["kb_ids"] == [9]
    assert events[-1][0] == "done"


# ---------- Summarization (lightweight retrieval) ----------

async def test_summarize_uses_vector_only(h):
    """The summarization path enables the vector lane only."""
    h.intent = "summarize"
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "总结一下这批文档", None)])
    assert h.calls["gather"], "总结仍需检索"
    assert h.calls["gather"][0]["sources"] == ["vector"]
    assert "rewrite" not in [t for t, _ in events]


# ---------- Supplementary retrieval (partial) ----------

async def test_partial_triggers_single_supplement(h):
    """partial -> one supplementary retrieval, then re-grade."""
    h.grade_verdict = "partial"
    h.grade_score = 6.0
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    correct = [d for t, d in events if t == "correct"]
    assert correct
    assert correct[0]["action"] == "rewrite_retry"
    assert correct[0]["round"] == 1
    assert len(h.calls["gather"]) == 2  # main retrieval plus one supplement


# ---------- CRAG correction ----------

async def test_crag_rewrite_retry_requeries(h):
    """fail -> CRAG rewrites the query and re-retrieves."""
    h.grade_verdict = "fail"
    h.grade_score = 2.0
    h.crag_actions = ["rewrite_retry"]
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    correct = [d for t, d in events if t == "correct"]
    assert correct
    assert correct[0]["action"] == "rewrite_retry"
    rewrites = [d for t, d in events if t == "rewrite"]
    assert rewrites, "CRAG 改写必须产出 rewrite 事件"
    assert rewrites[-1]["rewritten_query"] == "迟到 认定 处罚"


async def test_crag_give_up_emits_kb_not_covered(h):
    """CRAG give_up -> a give_up event plus the knowledge-gap notice."""
    h.grade_verdict = "fail"
    h.grade_score = 2.0
    h.crag_actions = ["give_up"]
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    correct = [d for t, d in events if t == "correct"]
    assert correct[0]["action"] == "give_up"
    assert [t for t, _ in events][-1] == "done"


async def test_crag_exhausted_rounds_gives_up(h):
    """CRAG rounds exhausted -> finish with give_up."""
    h.grade_verdict = "fail"
    h.grade_score = 2.0
    h.crag_actions = ["rewrite_retry", "rewrite_retry", "rewrite_retry"]
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    types = [t for t, _ in events]
    assert types[-1] == "done"
    correct = [d for t, d in events if t == "correct"]
    assert correct[-1]["action"] == "give_up"


# ---------- Session and user messages ----------

async def test_session_title_updated_on_first_turn(h, monkeypatch):
    """The session title is derived from the first question (18 chars plus an ellipsis)."""
    long_q = "迟到到底应该怎么认定和处罚才合规呢请说明"
    seen = {}

    async def _aexecute(sql, params=None):
        if "UPDATE chat_session SET title" in sql:
            seen["title"] = params[0]
        return 1

    monkeypatch.setattr(orchestrator.db, "aexecute", _aexecute)
    _parse_events([ev async for ev in orchestrator.run_ask(1, long_q, None)])
    assert seen["title"].endswith("…")
    assert len(seen["title"]) == 19


async def test_skip_user_persist_does_not_insert_user_message(h, monkeypatch):
    """Regeneration (skip_user_persist) does not store the user message again."""
    inserts = []

    async def _aexecute(sql, params=None):
        if "INSERT INTO chat_message" in sql and "'user'" in sql:
            inserts.append(sql)
        return 1

    monkeypatch.setattr(orchestrator.db, "aexecute", _aexecute)
    events = _parse_events([
        ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None, skip_user_persist=True)
    ])
    assert inserts == []  # the user message was not stored twice
    assert [t for t, _ in events][-1] == "done"


# ---------- Error and timeout wrap-up ----------

async def test_timeout_emits_504_error_event(h, monkeypatch):
    """Overall timeout -> an error event (code=504) and the chain raises nothing."""
    monkeypatch.setattr(orchestrator.settings, "overall_timeout", 0, raising=False)

    async def _slow(*a, **k):
        import asyncio
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr(orchestrator, "enabled_sources", _slow)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    errors = [d for t, d in events if t == "error"]
    assert errors
    assert errors[0]["code"] == 504


async def test_session_missing_emits_404_error_event(h, monkeypatch):
    """Missing session -> an error event (code=404)."""
    async def _aquery_one(sql, params=None):
        if "chat_session" in sql:
            return None
        return {"n": 0}

    monkeypatch.setattr(orchestrator.db, "aquery_one", _aquery_one)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    errors = [d for t, d in events if t == "error"]
    assert errors
    assert errors[0]["code"] == 404


async def test_unexpected_error_emits_500_error_event(h, monkeypatch):
    """Unexpected exception -> an error event (code=500)."""

    async def _boom(*a, **k):
        raise RuntimeError("内部炸了")

    monkeypatch.setattr(orchestrator, "enabled_sources", _boom)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    errors = [d for t, d in events if t == "error"]
    assert errors
    assert errors[0]["code"] == 500
    assert "内部炸了" in errors[0]["message"]


# ---------- Q&A with images ----------

async def test_image_question_forced_to_kb_qa(h, monkeypatch):
    """Questions with images are forced onto the knowledge Q&A main chain (no chitchat/data-query bypass)."""
    h.intent = "chitchat"
    monkeypatch.setattr(orchestrator, "to_data_urls", lambda urls: ["data:image/png;base64,AA=="])

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        if schema.__name__ == "RouterOut":
            return orchestrator.RouterOut(intent="chitchat", confidence=0.9,
                                           image_note="一张考勤表")
        if schema.__name__ == "PlannerOut":
            return orchestrator.PlannerOut(rewritten_query="迟到怎么认定")
        if schema.__name__ == "ReflectOut":
            return orchestrator.ReflectOut(result="pass")
        if schema.__name__ == "CragOut":
            return orchestrator.CragOut(action="give_up")
        raise AssertionError(schema.__name__)

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    events = _parse_events([
        ev async for ev in orchestrator.run_ask(1, "这个怎么算", None,
                                               image_urls=["/api/chat/images/a.png"])
    ])
    routers = [d for t, d in events if t == "router"]
    assert routers[0]["intent"] == "kb_qa"
    assert h.calls["gather"], "附图问题仍需检索知识库"


# ---------- Reflect backflow (Self-RAG) ----------

async def test_reflect_exhausted_rounds_breaks_and_appends_note(h, monkeypatch):
    """Reflection rounds exhausted -> stop the backflow and append a note to the answer."""
    monkeypatch.setattr(orchestrator.settings, "reflect_max_rounds", 1, raising=False)
    h.reflect_results = ["fail"]

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    reflect = [d for t, d in events if t == "reflect"]
    assert reflect and reflect[-1]["result"] == "fail"
    # only one retrieval happened (no backflow), because the loop breaks at max_rounds
    assert len(h.calls["gather"]) == 1


async def test_reflect_backflow_refetches_with_missing_info(h):
    """Reflection fails -> one targeted supplementary retrieval carrying the missing info."""
    h.reflect_results = ["fail", "pass"]
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    reflect = [d for t, d in events if t == "reflect"]
    assert [r["result"] for r in reflect] == ["fail", "pass"]
    assert len(h.calls["gather"]) == 2
    # the supplementary query carries the missing info
    assert "缺少处罚标准" in h.calls["gather"][1]["query"]


async def test_reflection_replaces_answer_and_citations(h, monkeypatch):
    h.reflect_results = ["fail", "pass"]
    saved = []
    outputs = iter(["OLD [1]", "NEW [1] invalid [9]"])

    async def stream(messages, usage=None):
        yield next(outputs)

    async def execute(sql, params=None):
        if "'assistant'" in sql:
            saved.append(params[1])
        return 1

    monkeypatch.setattr(orchestrator, "stream_generate", stream)
    monkeypatch.setattr(orchestrator.db, "aexecute", execute)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "question", [7])])
    text = ""
    for event_type, payload in events:
        if event_type == "generate":
            text = payload["delta"] if payload.get("replace") else text + payload["delta"]
        if event_type == "citation":
            text = payload["answer"]
            assert payload["citations"][0]["ref_id"] == 1
    assert text == "NEW [1] invalid "
    assert saved == [text]
    assert all(call.get("kb_ids") == [7] for call in h.calls["gather"])


async def test_final_stream_matches_persisted_exhaustion_warning(h, monkeypatch):
    h.reflect_results = ["fail"]
    monkeypatch.setattr(orchestrator.settings, "reflect_max_rounds", 1)
    saved = []

    async def execute(sql, params=None):
        if "'assistant'" in sql:
            saved.append(params[1])
        return 1

    monkeypatch.setattr(orchestrator.db, "aexecute", execute)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "question", None)])
    final = next(payload for kind, payload in events if kind == "citation")
    assert final["answer"] == saved[0]
    assert "Self-RAG" in final["answer"]


async def test_reflect_backflow_in_data_query_hits_database(h, monkeypatch):
    """For data_query the reflect backflow returns to the database instead of the knowledge base."""
    h.intent = "data_query"
    h.grade_score = 9.0
    h.grade_verdict = "pass"
    h.reflect_results = ["fail", "pass"]
    captured = {}

    async def _db_search(question, top_k=5, locale="zh-CN"):
        captured["q"] = question
        return "SELECT 1", [RetrieverResult(source="database", score=1.0, title="Q", content="行",
                                        metadata={"db": True, "sql": "SELECT 1", "rows": []})]

    monkeypatch.setattr(orchestrator.db_retriever, "search", _db_search)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "销售额", None)])
    db_events = [d for t, d in events if t == "retrieve" and d.get("source") == "database"]
    assert len(db_events) >= 2  # main retrieval plus reflect backflow
    assert "缺少处罚标准" in captured["q"]
    assert h.calls["gather"] == []  # no knowledge-base retrieval happened


async def test_reflect_backflow_rerank_failure_breaks_circuit(h, monkeypatch):
    """A rerank failure during backflow -> circuit break (later backflow rounds skip rerank)."""
    h.reflect_results = ["fail", "fail"]
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True, raising=False)
    monkeypatch.setattr(orchestrator, "_rerank_ready", lambda: True)

    calls = {"n": 0}

    async def _apply(query, items, locale=None):
        calls["n"] += 1
        if calls["n"] == 1:  # rerank succeeded on the main chain
            return items, {"model": "m", "ms": 1.0, "in": len(items), "out": len(items)}, ""
        return items, None, "精排失败（boom）"  # rerank failed during backflow

    monkeypatch.setattr(orchestrator, "_apply_rerank", _apply)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到怎么认定", None)])
    errors = [d for t, d in events if t == "retrieve" and d.get("rerank_error")]
    assert errors, "精排失败必须以 degraded retrieve 事件上报"
    assert calls["n"] == 2, "熔断后不得再调用精排"


# ---------- Routing fallback ----------

async def test_invalid_intent_falls_back_to_kb_qa(h):
    """An invalid intent falls back to kb_qa in code."""
    h.intent = "not-a-valid-intent"
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "问题", None)])
    routers = [d for t, d in events if t == "router"]
    assert routers[0]["intent"] == "kb_qa"
    assert h.calls["gather"], "兜底后应走知识库检索"


# ---------- Persistence failure while handling an error ----------

async def test_timeout_persist_failure_does_not_break_stream(h, monkeypatch):
    """For a timeout, a failing persist still does not block the error event."""

    async def _timeout(*a, **k):
        raise TimeoutError("整体超时")

    async def _aexecute(sql, params=None):
        # only the final persist fails while storing the user message succeeds, so the timeout branch is reached
        if "INSERT INTO chat_message" in sql and "'assistant'" in sql:
            raise RuntimeError("落库失败")
        return 1

    monkeypatch.setattr(orchestrator, "enabled_sources", _timeout)
    monkeypatch.setattr(orchestrator.db, "aexecute", _aexecute)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "问题", None)])
    errors = [d for t, d in events if t == "error"]
    assert errors and errors[0]["code"] == 504


async def test_error_persist_failure_does_not_break_stream(h, monkeypatch):
    """When handling an exception, a failing persist still does not block the error event."""

    async def _boom(*a, **k):
        raise RuntimeError("链路炸了")

    async def _aexecute(sql, params=None):
        if "INSERT INTO chat_message" in sql and "'assistant'" in sql:
            raise RuntimeError("落库也失败")
        return 1

    monkeypatch.setattr(orchestrator, "enabled_sources", _boom)
    monkeypatch.setattr(orchestrator.db, "aexecute", _aexecute)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "问题", None)])
    errors = [d for t, d in events if t == "error"]
    assert errors and errors[0]["code"] == 500

"""检索降级可观测 — gather_lanes 错误上报 + orchestrator 降级标记

场景回归：2026-10-19 事故中「检索路异常（ES 挂 / Embedding 401）」与
「知识库真的没有」在前端呈现完全一样（都走 CRAG give_up 的「知识库未覆盖」）。
本组测试保证：路级异常被显式上报（SSE degraded 事件 + 决策日志 + 生成侧声明），
与知识库缺失可区分。
"""
import json

import pytest

from app.agent import orchestrator, retrievers
from app.agent.rrf import RetrieverResult

# ---------- gather_lanes：错误不再静默变空路 ----------

async def test_gather_lanes_reports_lane_errors(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("HTTPStatusError: embedding 401")

    async def _ok(*a, **k):
        return [RetrieverResult(source="keyword", score=1.0, title="t", content="c", metadata={"doc_name": "d", "chunk_no": 1})]

    monkeypatch.setattr(retrievers.vector_retriever, "search", _boom)
    monkeypatch.setattr(retrievers.keyword_retriever, "search", _ok)
    lanes, errors = await retrievers.gather_lanes("q", None, 5, ["vector", "keyword"])

    assert lanes["vector"] == []  # 失败路仍给空列表，管线不中断
    assert len(lanes["keyword"]) == 1
    assert "vector" in errors
    assert "401" in errors["vector"]


async def test_gather_lanes_no_errors_on_success(monkeypatch):
    async def _ok(*a, **k):
        return []

    monkeypatch.setattr(retrievers.vector_retriever, "search", _ok)
    monkeypatch.setattr(retrievers.keyword_retriever, "search", _ok)
    lanes, errors = await retrievers.gather_lanes("q", None, 5, ["vector", "keyword"])

    assert errors == {}
    assert lanes == {"vector": [], "keyword": []}


async def test_gather_lanes_empty_sources():
    lanes, errors = await retrievers.gather_lanes("q", None, 5, [])
    assert (lanes, errors) == ({}, {})


# ---------- 声明文案：降级 vs 知识库未覆盖 ----------

def test_degraded_note_contains_sources_and_warning():
    note = orchestrator.degraded_note({"vector": "HTTPStatusError: 401", "keyword": "ConnectError"})
    assert "检索服务异常" in note
    assert "vector" in note and "keyword" in note


def test_give_up_disclaimer_without_errors_is_kb_only():
    d = orchestrator.give_up_disclaimer({})
    assert "知识库未覆盖" in d
    assert "检索服务异常" not in d


def test_give_up_disclaimer_with_errors_prepends_degraded_note():
    d = orchestrator.give_up_disclaimer({"vector": "HTTPStatusError: 401"})
    assert d.index("检索服务异常") < d.index("知识库未覆盖")


# ---------- 端到端：检索路异常 → degraded 事件 + 日志 + 生成侧声明 ----------

def _parse_events(raw_list: list[str]) -> list[tuple[str, dict]]:
    out = []
    for raw in raw_list:
        lines = raw.strip().split("\n")
        out.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return out


@pytest.fixture
def degraded_run(monkeypatch):
    """打穿 _run 全链路：DB / 决策点 / gather_lanes / stream_generate 全部 mock"""
    captured = {"gen_msgs": None, "steps_json": None}

    async def _aquery_all(sql, params=None):
        return []  # 无历史

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
            return orchestrator.CragOut(failure_reason="检索服务异常", action="give_up", new_queries=[])
        if name == "ReflectOut":
            return orchestrator.ReflectOut(result="pass")
        raise AssertionError(f"未预期的判定：{name}")

    async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
        return 0.0, "fail", "无命中"

    async def _enabled():
        return {"vector": True, "keyword": True, "database": True}

    async def _gather(query, kb_ids, top_k, sources):
        return {"vector": [], "keyword": []}, {"vector": "HTTPStatusError: embedding 401"}

    async def _stream(messages, usage=None):
        captured["gen_msgs"] = messages
        yield "答案"

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    monkeypatch.setattr(orchestrator, "do_grade", _grade)
    monkeypatch.setattr(orchestrator, "enabled_sources", _enabled)
    monkeypatch.setattr(orchestrator, "gather_lanes", _gather)
    monkeypatch.setattr(orchestrator, "stream_generate", _stream)
    return captured


async def test_run_marks_retrieval_degraded_end_to_end(degraded_run):
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])
    types = [t for t, _ in events]

    # 1. SSE 出现 degraded 检索事件（带失败路与原因）
    degraded = [d for t, d in events if t == "retrieve" and d.get("degraded")]
    assert degraded, "检索路异常必须产生 degraded 事件"
    assert "vector" in degraded[0]["errors"]
    assert "401" in degraded[0]["errors"]["vector"]

    # 2. 决策日志记录了降级步骤
    assert degraded_run["steps_json"] is not None
    assert '"degraded"' in degraded_run["steps_json"]

    # 3. 生成侧声明区分「检索服务异常」与「知识库未覆盖」
    gen_text = json.dumps(degraded_run["gen_msgs"], ensure_ascii=False)
    assert "检索服务异常" in gen_text

    # 4. 链路正常收尾
    assert types[-1] == "done"


async def test_run_without_lane_errors_has_no_degraded_event(monkeypatch, degraded_run):
    """对照：检索正常（仅无命中）时不打 degraded，声明保持纯知识库未覆盖"""
    async def _gather_ok(query, kb_ids, top_k, sources):
        return {"vector": [], "keyword": []}, {}

    monkeypatch.setattr(orchestrator, "gather_lanes", _gather_ok)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    assert not [d for t, d in events if t == "retrieve" and d.get("degraded")]
    gen_text = json.dumps(degraded_run["gen_msgs"], ensure_ascii=False)
    assert "知识库未覆盖" in gen_text
    assert "检索服务异常" not in gen_text


async def test_reflect_reflow_also_marks_degraded(monkeypatch, degraded_run):
    """反思回流期的检索异常同样打 degraded（前缀「反思回流·」），且 errors 跨轮累积"""
    reflect_calls = {"n": 0}

    async def _judge2(schema, system, user, usage, attempts=2, images=None):
        name = schema.__name__
        if name == "ReflectOut":
            reflect_calls["n"] += 1
            if reflect_calls["n"] == 1:
                return orchestrator.ReflectOut(result="fail", missing_info="缺少迟到认定标准")
            return orchestrator.ReflectOut(result="pass")
        if name == "RouterOut":
            return orchestrator.RouterOut(intent="kb_qa", confidence=0.9)
        if name == "PlannerOut":
            return orchestrator.PlannerOut(rewritten_query="迟到怎么认定")
        if name == "CragOut":
            return orchestrator.CragOut(failure_reason="x", action="give_up", new_queries=[])
        raise AssertionError(f"未预期的判定：{name}")

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge2)
    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])
    types = [t for t, _ in events]

    # 反思失败必须产出 result=fail 的 reflect 事件（此前此处是非空元组恒真断言，等于没断言）
    reflect_fail = [d for t, d in events if t == "reflect" and d.get("result") == "fail"]
    assert reflect_fail, "反思不通过时必须产出 result=fail 的 reflect 事件"
    reflow = [d for t, d in events if t == "retrieve" and d.get("degraded") and d["detail"].startswith("反思回流·")]
    assert reflow, "反思回流期的检索异常必须打带前缀的 degraded 事件"
    assert '"degraded"' in degraded_run["steps_json"]
    assert types[-1] == "done"

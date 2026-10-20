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
    """记录调用并返回指定排序；exc 非空时抛异常（测降级）"""

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
    """开启后：单路 top_k 扩到 candidates/2，精排重排生效，SSE 出 rerank 事件"""
    fake = _FakeRerank(order=[(1, 0.95), (0, 0.55)])  # 乙 提到 甲 前
    _patch_rerank(monkeypatch, fake)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    # 候选深度：candidates=20 → 单路 top_k=max(5, 10)=10
    assert rerank_run["gather_top_k"] == 10
    # 精排被调用，query 用完整问题
    assert fake.calls and fake.calls[0]["query"] == "迟到是怎么认定和处罚的？"
    assert fake.calls[0]["top_n"] == settings.rerank_top_n
    # SSE rerank 事件
    rr_events = [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    assert rr_events, "开启精排必须产出 source=rerank 的检索事件"
    assert rr_events[0]["hit_count"] == 2
    assert rr_events[0]["rerank"]["model"] == "gte-rerank-v2"
    # 决策日志含精排步骤
    assert '"source": "rerank"' in rerank_run["steps_json"]
    # 生成侧上下文按精排结果重排（乙在甲前）
    gen_text = json.dumps(rerank_run["gen_msgs"], ensure_ascii=False)
    assert gen_text.index("片段乙") < gen_text.index("片段甲")
    assert [t for t, _ in events][-1] == "done"


async def test_rerank_off_no_rerank_event(rerank_run, monkeypatch):
    """关闭时：候选深度不变（fused_top_n），无 rerank 事件，顺序保持粗排"""
    monkeypatch.setattr(settings, "rerank_enabled", False, raising=False)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    assert rerank_run["gather_top_k"] == settings.retrieval_top_k
    assert not [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    gen_text = json.dumps(rerank_run["gen_msgs"], ensure_ascii=False)
    assert gen_text.index("片段甲") < gen_text.index("片段乙")


async def test_rerank_failure_degrades_to_rrf_order(rerank_run, monkeypatch):
    """精排调用失败：降级保留粗排序，产出 degraded 事件，链路不中断"""
    fake = _FakeRerank(exc=RuntimeError("upstream 500"))
    _patch_rerank(monkeypatch, fake)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])
    types = [t for t, _ in events]

    degraded = [d for t, d in events if t == "retrieve" and d.get("degraded") and d.get("rerank_error")]
    assert degraded, "精排失败必须产出 degraded 事件"
    gen_text = json.dumps(rerank_run["gen_msgs"], ensure_ascii=False)
    assert gen_text.index("片段甲") < gen_text.index("片段乙")  # 保留粗排序
    assert '"degraded"' in rerank_run["steps_json"]
    assert types[-1] == "done"


async def test_rerank_failure_trips_circuit_breaker(rerank_run, monkeypatch):
    """熔断：精排失败后，CRAG 重查轮不再重复调用已失败的 provider（Important 2 回归）"""
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

    # 第一轮失败即熔断：CRAG 重查轮（第二次 gather）不再调用精排
    assert len(fake.calls) == 1, f"熔断失效，精排被重复调用 {len(fake.calls)} 次"
    assert crag_calls["n"] == 2  # rewrite_retry → 重查 → give_up
    assert [t for t, _ in events][-1] == "done"


async def test_reflect_reflow_also_reranks(rerank_run, monkeypatch):
    """反思回流期同样走精排（带「反思回流·」前缀事件），且候选深度一致"""
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
    """provider 不可用：候选深度保持默认（不无意义加深 ES 负载），走粗排（Important 1 回归）"""
    from app.providers.registry import UnknownProviderError

    def _boom():
        raise UnknownProviderError("供应商 deepseek 未配置 rerank 模型")

    monkeypatch.setattr(orchestrator, "get_rerank", _boom)
    monkeypatch.setattr(settings, "rerank_enabled", True, raising=False)

    events = _parse_events([ev async for ev in orchestrator.run_ask(1, "迟到是怎么认定和处罚的？", None)])

    assert rerank_run["gather_top_k"] == settings.retrieval_top_k  # 未被加深到 10
    assert not [d for t, d in events if t == "retrieve" and d.get("source") == "rerank"]
    assert [t for t, _ in events][-1] == "done"

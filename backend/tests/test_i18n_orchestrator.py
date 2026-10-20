"""SSE/API 文案双语化 — 目录完整性 + run_ask 语言参数 + 渲染"""
import re
from pathlib import Path

from app.agent import orchestrator
from app.i18n import MESSAGES


def test_catalog_key_parity():
    """zh/en 目录 key 集合必须一致

    注：conftest 已隔离全局 MESSAGES（用例注入的临时 key 会在用例后还原），
    因此这里不再需要跳过 "test." 前缀——真实 key 若以 test. 开头也应被校验。
    """
    for key, entry in MESSAGES.items():
        assert set(entry.keys()) == {"zh-CN", "en-US"}, f"key {key} 语言不全"


def test_all_orchestrator_sse_keys_exist():
    """orchestrator 用到的 key 必须已在目录中（防改文案漏翻译）"""
    src = Path(orchestrator.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r't\("(sse\.[a-z0-9.]+)"', src))
    assert used, "orchestrator 中未发现 sse.* key"
    missing = used - set(MESSAGES)
    assert not missing, f"目录缺失：{missing}"


def test_all_orchestrator_error_disclaimer_keys_exist():
    """error./disclaimer./cite. 字面量 key 也必须存在"""
    src = Path(orchestrator.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r't\("((?:error|disclaimer|cite)\.[a-z0-9.]+)"', src))
    assert used, "orchestrator 中未发现 error/disclaimer/cite key"
    missing = used - set(MESSAGES)
    assert not missing, f"目录缺失：{missing}"


def test_run_ask_accepts_locale_param():
    import inspect

    sig = inspect.signature(orchestrator.run_ask)
    assert "locale" in sig.parameters


async def test_sse_events_localized(monkeypatch):
    """英文 locale 下决策链 detail 为英文（打穿 _run，mock 决策点）"""
    from app.agent.rrf import RetrieverResult

    async def _aquery_all(sql, params=None):
        return []

    async def _aquery_one(sql, params=None):
        return {"title": "新会话"} if "chat_session" in sql else {"n": 0}

    async def _aexecute(sql, params=None):
        return 1

    monkeypatch.setattr(orchestrator.db, "aquery_all", _aquery_all)
    monkeypatch.setattr(orchestrator.db, "aquery_one", _aquery_one)
    monkeypatch.setattr(orchestrator.db, "aexecute", _aexecute)

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        name = schema.__name__
        if name == "RouterOut":
            return orchestrator.RouterOut(intent="kb_qa", confidence=0.9)
        if name == "PlannerOut":
            return orchestrator.PlannerOut(rewritten_query="late arrival policy")
        if name == "CragOut":
            return orchestrator.CragOut(failure_reason="x", action="give_up", new_queries=[])
        if name == "ReflectOut":
            return orchestrator.ReflectOut(result="pass")
        raise AssertionError(name)

    async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
        return 9.0, "pass", "ok"

    async def _enabled():
        return {"vector": True, "keyword": True, "database": True}

    items = [RetrieverResult(source="vector", score=0.9, title="t", content="c", metadata={"doc_name": "d", "chunk_no": 1})]

    async def _gather(query, kb_ids, top_k, sources):
        return {"vector": items, "keyword": []}, {}

    async def _stream(messages, usage=None):
        yield "Answer"

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    monkeypatch.setattr(orchestrator, "do_grade", _grade)
    monkeypatch.setattr(orchestrator, "enabled_sources", _enabled)
    monkeypatch.setattr(orchestrator, "gather_lanes", _gather)
    monkeypatch.setattr(orchestrator, "stream_generate", _stream)

    events = []
    async for ev in orchestrator.run_ask(1, "How is lateness handled?", None, locale="en-US"):
        events.append(ev)
    details = " ".join(events)
    assert "Vector retrieval" in details  # 英文 detail
    assert "相关度" not in details  # 不得出现中文 detail
    assert "9.0" in details  # 分数照常渲染

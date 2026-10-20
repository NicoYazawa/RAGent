"""编排层纯函数 — 上下文构建 / 引用抽取 / 序号剔除 / 评分阈值 / 精排参数

这些函数决定了"答案里带什么引用、片段怎么排"，历史上未被单测覆盖。
"""
import json

import pytest

from app.agent import orchestrator
from app.agent.orchestrator import (
    GraderOut,
    RetrieverResult,
    RunState,
    _apply_rerank,
    _judge_retry,
    _rerank_ready,
    build_context,
    degraded_note,
    do_grade,
    extract_citations,
    give_up_disclaimer,
    intent_label,
    rerank_params,
    sse,
    strip_invalid_refs,
    verdict_icon,
)


def _item(doc_name="手册", section="第一章", chunk_no=1, content="内容", db=False, meta=None):
    m = {"doc_name": doc_name, "section_path": section, "chunk_no": chunk_no}
    if db:
        m.update({"db": True, "sql": "SELECT 1", "rows": [{"id": 1}]})
    if meta:
        m.update(meta)
    return RetrieverResult(source="database" if db else "vector", score=0.9,
                           title=doc_name, content=content, metadata=m)


# ---------- 文案映射 ----------

def test_intent_label_localized():
    """意图标签随语言切换"""
    assert "知识问答" in intent_label("kb_qa", "zh-CN")
    assert "Knowledge" in intent_label("kb_qa", "en-US")


def test_verdict_icon_localized():
    """评分徽标随语言切换"""
    assert verdict_icon("pass", "zh-CN") != verdict_icon("pass", "en-US")
    assert "通过" in verdict_icon("pass", "zh-CN")


def test_sse_event_format():
    """SSE 文本格式：event 行 + data 行 + 空行结尾"""
    raw = sse("retrieve", 3, "命中 2 条", source="vector", hit_count=2)
    lines = raw.strip().split("\n")
    assert lines[0] == "event: retrieve"
    payload = json.loads(lines[1][len("data: "):])
    assert payload["step"] == 3
    assert payload["detail"] == "命中 2 条"
    assert payload["source"] == "vector"
    assert payload["hit_count"] == 2
    assert "ts" in payload


# ---------- RunState ----------

def test_run_state_question_full_without_vision_note():
    """无图注时 question_full == 原问题"""
    st = RunState(1, "迟到怎么认定")
    assert st.question_full == "迟到怎么认定"


def test_run_state_question_full_appends_vision_note_zh():
    """中文提问 + 图注 → 中文合并格式"""
    st = RunState(1, "回答这个问题")
    st.vision_note = "一张考勤表"
    assert "用户附图" in st.question_full
    assert "一张考勤表" in st.question_full


def test_run_state_question_full_appends_vision_note_en():
    """英文提问 + 图注 → 英文合并格式"""
    st = RunState(1, "Answer this")
    st.lang = "en-US"
    st.vision_note = "a form"
    assert "User attached an image" in st.question_full


def test_run_state_mark_records_steps():
    """mark 记录步骤与耗时"""
    st = RunState(1, "q")
    st.mark(1, "router", "判定", {"intent": "kb_qa"})
    assert len(st.steps) == 1
    assert st.steps[0]["type"] == "router"
    assert st.steps[0]["payload"]["intent"] == "kb_qa"
    assert st.steps[0]["elapsed_ms"] >= 0


def test_run_state_gen_end_appends_generate_step():
    """生成结束记录 generate 步骤（无答案时不记录）"""
    st = RunState(1, "q")
    st.gen_start()
    st.answer = "答案内容"
    st.gen_end()
    assert st.steps[-1]["type"] == "generate"
    assert st.steps[-1]["payload"]["chars"] == 4


def test_run_state_gen_end_skipped_without_answer():
    """没有答案时 gen_end 不产生步骤"""
    st = RunState(1, "q")
    st.gen_start()
    st.gen_end()
    assert st.steps == []


def test_run_state_elapsed_ms_non_negative():
    """elapsed_ms 不为负"""
    st = RunState(1, "q")
    assert st.elapsed_ms >= 0


# ---------- build_context ----------

def test_build_context_zh_header():
    """中文上下文头部含文档名 / 章节 / 切片号"""
    blocks = build_context([_item()], "zh-CN")
    assert len(blocks) == 1
    assert "《手册》" in blocks[0]
    assert "第一章" in blocks[0]
    assert "切片#1" in blocks[0]


def test_build_context_en_header():
    """英文上下文头部"""
    blocks = build_context([_item()], "en-US")
    assert '"手册"' in blocks[0]
    assert "chunk #1" in blocks[0]


def test_build_context_db_branch():
    """db 来源的片段走业务数据库头部"""
    blocks = build_context([_item(db=True)], "zh-CN")
    assert "业务数据库" in blocks[0]
    assert "sales 表查询结果" in blocks[0]


def test_build_context_truncates_long_content():
    """超长片段正文被截断（控制上下文体积）"""
    long = "字" * 900
    blocks = build_context([_item(content=long)], "zh-CN")
    body = blocks[0].split("\n", 1)[1]
    assert len(body) == 600


def test_build_context_empty_items():
    """无片段 → 空上下文"""
    assert build_context([], "zh-CN") == []


# ---------- 引用抽取 ----------

def test_extract_citations_maps_valid_refs():
    """合法序号 → 片段元数据"""
    items = [_item(doc_name="手册", chunk_no=1), _item(doc_name="制度", chunk_no=2)]
    cites = extract_citations("依据[1]和[2]", items, "zh-CN")
    assert len(cites) == 2
    assert cites[0]["doc_name"] == "手册"
    assert cites[1]["chunk_no"] == 2


def test_extract_citations_skips_out_of_range():
    """越界序号被剔除"""
    items = [_item()]
    assert extract_citations("见[5]", items, "zh-CN") == []


def test_extract_citations_dedupes_repeated_refs():
    """重复序号只保留一次"""
    items = [_item(), _item(doc_name="制度", chunk_no=2)]
    cites = extract_citations("[1] [1] [2]", items, "zh-CN")
    assert len(cites) == 2


def test_extract_citations_db_branch_carries_sql_and_rows():
    """db 引用携带 SQL 与原始行（前端走数据查询证据视图）"""
    cites = extract_citations("[1]", [_item(db=True)], "zh-CN")
    assert cites[0]["source_type"] == "db"
    assert cites[0]["sql"] == "SELECT 1"
    assert cites[0]["rows"] == [{"id": 1}]


def test_extract_citations_no_refs():
    """答案无引用 → 空列表"""
    assert extract_citations("没有引用", [_item()], "zh-CN") == []


def test_extract_citations_preserves_sparse_out_of_order_numbers_and_identity():
    items = [_item(doc_name=str(i), chunk_no=i) for i in range(1, 4)]
    items[2].metadata.update(doc_id=30, kb_id=2, chunk_uid="chunk-30")
    cites = extract_citations("third [3], first [1], third [3]", items)
    assert [c["ref_id"] for c in cites] == [3, 1]
    assert cites[0]["doc_id"] == 30
    assert cites[0]["kb_id"] == 2
    assert cites[0]["chunk_uid"] == "chunk-30"


def test_database_citation_preserves_reference_number():
    cites = extract_citations("[2]", [_item(), _item(db=True)])
    assert cites[0]["ref_id"] == 2


# ---------- 非法序号剔除 ----------

def test_strip_invalid_refs_removes_out_of_range():
    """越界序号从答案正文剔除（不留残文明文）"""
    assert strip_invalid_refs("看[1]和[3]", [_item()]) == "看[1]和"


def test_strip_invalid_refs_keeps_valid():
    """合法序号保留"""
    assert strip_invalid_refs("看[1]", [_item()]) == "看[1]"


def test_strip_invalid_refs_without_items():
    """无片段时所有序号被剔除"""
    assert strip_invalid_refs("看[1]", []) == "看"


# ---------- 降级声明 ----------

def test_degraded_note_lists_sources():
    """降级声明列出失败路"""
    note = degraded_note({"vector": "401", "keyword": "ConnectError"}, "zh-CN")
    assert "检索服务异常" in note
    assert "vector" in note and "keyword" in note


def test_degraded_note_english():
    """英文降级声明"""
    note = degraded_note({"vector": "401"}, "en-US")
    assert "Retrieval service error" in note


def test_give_up_disclaimer_only_kb_when_no_errors():
    """无检索异常 → 只有知识库未覆盖声明"""
    d = give_up_disclaimer({}, "zh-CN")
    assert "知识库未覆盖" in d
    assert "检索服务异常" not in d


def test_give_up_disclaimer_prepends_degraded():
    """有检索异常 → 降级声明在前"""
    d = give_up_disclaimer({"vector": "401"}, "zh-CN")
    assert d.index("检索服务异常") < d.index("知识库未覆盖")


# ---------- 精排参数 ----------

def test_rerank_params_disabled(monkeypatch):
    """关闭时 → 默认深度"""
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", False, raising=False)
    top_k, candidates = rerank_params()
    assert top_k == orchestrator.settings.retrieval_top_k
    assert candidates == orchestrator.settings.fused_top_n


def test_rerank_params_enabled_expands_depth(monkeypatch):
    """开启时 → 单路加深、候选池扩大"""
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True, raising=False)
    top_k, candidates = rerank_params()
    assert candidates == orchestrator.settings.rerank_candidates
    assert top_k == max(orchestrator.settings.retrieval_top_k,
                        (orchestrator.settings.rerank_candidates + 1) // 2)


def test_rerank_params_explicit_override(monkeypatch):
    """显式传参优先于 settings"""
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True, raising=False)
    top_k, candidates = rerank_params(False)
    assert top_k == orchestrator.settings.retrieval_top_k


def test_rerank_ready_false_when_provider_unavailable(monkeypatch):
    """provider 不可构建 → 未就绪"""
    def _boom():
        raise RuntimeError("未配置 rerank")

    monkeypatch.setattr(orchestrator, "get_rerank", _boom)
    assert _rerank_ready() is False


def test_rerank_ready_true_when_provider_builds(monkeypatch):
    """provider 可构建 → 就绪"""
    monkeypatch.setattr(orchestrator, "get_rerank", lambda: object())
    assert _rerank_ready() is True


# ---------- _apply_rerank ----------

async def test_apply_rerank_reorders_items(monkeypatch):
    """精排按返回顺序重排片段"""

    class _P:
        name, model = "qwen", "gte-rerank-v2"

        async def rerank(self, query, documents, top_n):
            return [(1, 0.9), (0, 0.5)]

    monkeypatch.setattr(orchestrator, "get_rerank", lambda: _P())
    items = [_item(chunk_no=1), _item(chunk_no=2)]
    out, info, err = await _apply_rerank("q", items, "zh-CN")
    assert [i.metadata["chunk_no"] for i in out] == [2, 1]
    assert info["model"] == "gte-rerank-v2"
    assert info["in"] == 2 and info["out"] == 2
    assert err == ""


async def test_apply_rerank_filters_out_of_range_index(monkeypatch):
    """越界索引被过滤（不抛异常）"""

    class _P:
        name, model = "qwen", "m"

        async def rerank(self, query, documents, top_n):
            return [(0, 0.9), (99, 0.5)]

    monkeypatch.setattr(orchestrator, "get_rerank", lambda: _P())
    out, info, err = await _apply_rerank("q", [_item()], "zh-CN")
    assert len(out) == 1
    assert info["out"] == 1


async def test_apply_rerank_unavailable_keeps_order(monkeypatch):
    """provider 不可用 → 保留原顺序 + 错误信息"""

    def _boom():
        raise RuntimeError("no provider")

    monkeypatch.setattr(orchestrator, "get_rerank", _boom)
    items = [_item(chunk_no=1)]
    out, info, err = await _apply_rerank("q", items, "zh-CN")
    assert out == items
    assert info is None
    assert "精排不可用" in err


async def test_apply_rerank_failure_keeps_order(monkeypatch):
    """精排调用失败 → 保留原顺序 + 错误信息"""

    class _P:
        name, model = "qwen", "m"

        async def rerank(self, query, documents, top_n):
            raise RuntimeError("upstream 500")

    monkeypatch.setattr(orchestrator, "get_rerank", lambda: _P())
    items = [_item(chunk_no=1)]
    out, info, err = await _apply_rerank("q", items, "zh-CN")
    assert out == items
    assert "精排失败" in err


async def test_apply_rerank_empty_result_keeps_order(monkeypatch):
    """精排返回空 → 保留原顺序"""

    class _P:
        name, model = "qwen", "m"

        async def rerank(self, query, documents, top_n):
            return []

    monkeypatch.setattr(orchestrator, "get_rerank", lambda: _P())
    items = [_item(chunk_no=1)]
    out, info, err = await _apply_rerank("q", items, "zh-CN")
    assert out == items
    assert "精排返回空结果" in err


# ---------- Grader ----------

async def test_do_grade_without_context_fails(monkeypatch):
    """无上下文 → 直接 fail（不调用 LLM）"""

    async def _boom(*a, **k):
        raise AssertionError("不应调用 LLM")

    monkeypatch.setattr(orchestrator, "_judge_retry", _boom)
    score, verdict, reason = await do_grade("q", [], [], {}, "zh-CN")
    assert score == 0.0
    assert verdict == "fail"
    assert reason


async def test_do_grade_thresholds(monkeypatch):
    """评分阈值：≥7 pass / ≥5 partial / <5 fail"""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        return GraderOut(score=score, reason="r")

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    from app.config import settings

    for score, expected in [
        (settings.grade_pass, "pass"),
        (settings.grade_pass - 0.1, "partial"),
        (settings.grade_partial, "partial"),
        (settings.grade_partial - 0.1, "fail"),
    ]:
        _, verdict, _ = await do_grade("q", [], ["ctx"], {}, "zh-CN")
        assert verdict == expected, f"score={score} 期望 {expected}"


async def test_do_grade_clamps_score_range(monkeypatch):
    """评分被夹到 0..10"""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        return GraderOut(score=99.0, reason="r")

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    score, verdict, _ = await do_grade("q", [], ["ctx"], {}, "zh-CN")
    assert score == 10.0
    assert verdict == "pass"


async def test_do_grade_uses_default_reason(monkeypatch):
    """LLM 未给 reason → 用默认文案"""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        return GraderOut(score=8.0, reason="")

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    _, _, reason = await do_grade("q", [], ["ctx"], {}, "zh-CN")
    assert reason


# ---------- _judge_retry ----------

async def test_judge_retry_succeeds_on_second_attempt(monkeypatch):
    """首次失败后重试成功"""
    calls = {"n": 0}

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("临时故障")
        return GraderOut(score=9.0, reason="ok")

    monkeypatch.setattr(orchestrator, "judge", _judge)
    out = await _judge_retry(GraderOut, "sys", "user", {})
    assert out.score == 9.0
    assert calls["n"] == 2


async def test_judge_retry_raises_after_all_attempts(monkeypatch):
    """全部尝试失败 → 抛出最后一次异常"""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        raise RuntimeError("持续故障")

    monkeypatch.setattr(orchestrator, "judge", _judge)
    with pytest.raises(RuntimeError, match="持续故障"):
        await _judge_retry(GraderOut, "sys", "user", {})

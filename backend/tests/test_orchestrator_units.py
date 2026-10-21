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


# ---------- Copy mapping ----------

def test_intent_label_localized():
    """Intent labels follow the language."""
    assert "知识问答" in intent_label("kb_qa", "zh-CN")
    assert "Knowledge" in intent_label("kb_qa", "en-US")


def test_verdict_icon_localized():
    """Grade badges follow the language."""
    assert verdict_icon("pass", "zh-CN") != verdict_icon("pass", "en-US")
    assert "通过" in verdict_icon("pass", "zh-CN")


def test_sse_event_format():
    """SSE text format: event line + data line + trailing blank line."""
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
    """Without an image note question_full equals the original question."""
    st = RunState(1, "迟到怎么认定")
    assert st.question_full == "迟到怎么认定"


def test_run_state_question_full_appends_vision_note_zh():
    """Chinese question plus image note -> the Chinese merged format."""
    st = RunState(1, "回答这个问题")
    st.vision_note = "一张考勤表"
    assert "用户附图" in st.question_full
    assert "一张考勤表" in st.question_full


def test_run_state_question_full_appends_vision_note_en():
    """English question plus image note -> the English merged format."""
    st = RunState(1, "Answer this")
    st.lang = "en-US"
    st.vision_note = "a form"
    assert "User attached an image" in st.question_full


def test_run_state_mark_records_steps():
    """mark records a step and its elapsed time."""
    st = RunState(1, "q")
    st.mark(1, "router", "判定", {"intent": "kb_qa"})
    assert len(st.steps) == 1
    assert st.steps[0]["type"] == "router"
    assert st.steps[0]["payload"]["intent"] == "kb_qa"
    assert st.steps[0]["elapsed_ms"] >= 0


def test_run_state_gen_end_appends_generate_step():
    """gen_end records the generate step (nothing when there is no answer)."""
    st = RunState(1, "q")
    st.gen_start()
    st.answer = "答案内容"
    st.gen_end()
    assert st.steps[-1]["type"] == "generate"
    assert st.steps[-1]["payload"]["chars"] == 4


def test_run_state_gen_end_skipped_without_answer():
    """Without an answer gen_end produces no step."""
    st = RunState(1, "q")
    st.gen_start()
    st.gen_end()
    assert st.steps == []


def test_run_state_elapsed_ms_non_negative():
    """elapsed_ms is never negative."""
    st = RunState(1, "q")
    assert st.elapsed_ms >= 0


# ---------- build_context ----------

def test_build_context_zh_header():
    """The Chinese context header carries doc name / section / chunk number."""
    blocks = build_context([_item()], "zh-CN")
    assert len(blocks) == 1
    assert "《手册》" in blocks[0]
    assert "第一章" in blocks[0]
    assert "切片#1" in blocks[0]


def test_build_context_en_header():
    """The English context header."""
    blocks = build_context([_item()], "en-US")
    assert '"手册"' in blocks[0]
    assert "chunk #1" in blocks[0]


def test_build_context_db_branch():
    """A chunk from the db source uses the business-database header."""
    blocks = build_context([_item(db=True)], "zh-CN")
    assert "业务数据库" in blocks[0]
    assert "sales 表查询结果" in blocks[0]


def test_build_context_truncates_long_content():
    """Over-long chunk bodies are truncated to bound the context size."""
    long = "字" * 900
    blocks = build_context([_item(content=long)], "zh-CN")
    body = blocks[0].split("\n", 1)[1]
    assert len(body) == 600


def test_build_context_empty_items():
    """No chunks -> empty context."""
    assert build_context([], "zh-CN") == []


# ---------- Citation extraction ----------

def test_extract_citations_maps_valid_refs():
    """A valid marker -> chunk metadata."""
    items = [_item(doc_name="手册", chunk_no=1), _item(doc_name="制度", chunk_no=2)]
    cites = extract_citations("依据[1]和[2]", items, "zh-CN")
    assert len(cites) == 2
    assert cites[0]["doc_name"] == "手册"
    assert cites[1]["chunk_no"] == 2


def test_extract_citations_skips_out_of_range():
    """Out-of-range markers are dropped."""
    items = [_item()]
    assert extract_citations("见[5]", items, "zh-CN") == []


def test_extract_citations_dedupes_repeated_refs():
    """A repeated marker is kept only once."""
    items = [_item(), _item(doc_name="制度", chunk_no=2)]
    cites = extract_citations("[1] [1] [2]", items, "zh-CN")
    assert len(cites) == 2


def test_extract_citations_db_branch_carries_sql_and_rows():
    """A db citation carries the SQL and raw rows (the frontend shows the data-query evidence view)."""
    cites = extract_citations("[1]", [_item(db=True)], "zh-CN")
    assert cites[0]["source_type"] == "db"
    assert cites[0]["sql"] == "SELECT 1"
    assert cites[0]["rows"] == [{"id": 1}]


def test_extract_citations_no_refs():
    """An answer without citations -> empty list."""
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


# ---------- Stripping invalid markers ----------

def test_strip_invalid_refs_removes_out_of_range():
    """Out-of-range markers are removed from the answer body (no leftover plain text)."""
    assert strip_invalid_refs("看[1]和[3]", [_item()]) == "看[1]和"


def test_strip_invalid_refs_keeps_valid():
    """Valid markers are kept."""
    assert strip_invalid_refs("看[1]", [_item()]) == "看[1]"


def test_strip_invalid_refs_without_items():
    """Without chunks every marker is stripped."""
    assert strip_invalid_refs("看[1]", []) == "看"


# ---------- Degradation notices ----------

def test_degraded_note_lists_sources():
    """The degradation notice lists the failing lanes."""
    note = degraded_note({"vector": "401", "keyword": "ConnectError"}, "zh-CN")
    assert "检索服务异常" in note
    assert "vector" in note and "keyword" in note


def test_degraded_note_english():
    """The English degradation notice."""
    note = degraded_note({"vector": "401"}, "en-US")
    assert "Retrieval service error" in note


def test_give_up_disclaimer_only_kb_when_no_errors():
    """No lane error -> only the knowledge-gap notice."""
    d = give_up_disclaimer({}, "zh-CN")
    assert "知识库未覆盖" in d
    assert "检索服务异常" not in d


def test_give_up_disclaimer_prepends_degraded():
    """A lane error -> the degradation notice comes first."""
    d = give_up_disclaimer({"vector": "401"}, "zh-CN")
    assert d.index("检索服务异常") < d.index("知识库未覆盖")


# ---------- Rerank parameters ----------

def test_rerank_params_disabled(monkeypatch):
    """Off -> default depth."""
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", False, raising=False)
    top_k, candidates = rerank_params()
    assert top_k == orchestrator.settings.retrieval_top_k
    assert candidates == orchestrator.settings.fused_top_n


def test_rerank_params_enabled_expands_depth(monkeypatch):
    """On -> deeper per-lane recall and a wider candidate pool."""
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True, raising=False)
    top_k, candidates = rerank_params()
    assert candidates == orchestrator.settings.rerank_candidates
    assert top_k == max(orchestrator.settings.retrieval_top_k,
                        (orchestrator.settings.rerank_candidates + 1) // 2)


def test_rerank_params_explicit_override(monkeypatch):
    """An explicit argument wins over settings."""
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True, raising=False)
    top_k, candidates = rerank_params(False)
    assert top_k == orchestrator.settings.retrieval_top_k


def test_rerank_ready_false_when_provider_unavailable(monkeypatch):
    """The provider cannot be built -> not ready."""
    def _boom():
        raise RuntimeError("未配置 rerank")

    monkeypatch.setattr(orchestrator, "get_rerank", _boom)
    assert _rerank_ready() is False


def test_rerank_ready_true_when_provider_builds(monkeypatch):
    """The provider can be built -> ready."""
    monkeypatch.setattr(orchestrator, "get_rerank", lambda: object())
    assert _rerank_ready() is True


# ---------- _apply_rerank ----------

async def test_apply_rerank_reorders_items(monkeypatch):
    """Rerank reorders the chunks by the returned order."""

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
    """Out-of-range indices are filtered out without raising."""

    class _P:
        name, model = "qwen", "m"

        async def rerank(self, query, documents, top_n):
            return [(0, 0.9), (99, 0.5)]

    monkeypatch.setattr(orchestrator, "get_rerank", lambda: _P())
    out, info, err = await _apply_rerank("q", [_item()], "zh-CN")
    assert len(out) == 1
    assert info["out"] == 1


async def test_apply_rerank_unavailable_keeps_order(monkeypatch):
    """Provider unavailable -> keep the original order plus an error message."""

    def _boom():
        raise RuntimeError("no provider")

    monkeypatch.setattr(orchestrator, "get_rerank", _boom)
    items = [_item(chunk_no=1)]
    out, info, err = await _apply_rerank("q", items, "zh-CN")
    assert out == items
    assert info is None
    assert "精排不可用" in err


async def test_apply_rerank_failure_keeps_order(monkeypatch):
    """The rerank call fails -> keep the original order plus an error message."""

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
    """Rerank returns nothing -> keep the original order."""

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
    """No context -> fail immediately (no LLM call)."""

    async def _boom(*a, **k):
        raise AssertionError("不应调用 LLM")

    monkeypatch.setattr(orchestrator, "_judge_retry", _boom)
    score, verdict, reason = await do_grade("q", [], [], {}, "zh-CN")
    assert score == 0.0
    assert verdict == "fail"
    assert reason


async def test_do_grade_thresholds(monkeypatch):
    """Score thresholds: >=7 pass / >=5 partial / <5 fail."""

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
    """The score is clamped to 0..10."""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        return GraderOut(score=99.0, reason="r")

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    score, verdict, _ = await do_grade("q", [], ["ctx"], {}, "zh-CN")
    assert score == 10.0
    assert verdict == "pass"


async def test_do_grade_uses_default_reason(monkeypatch):
    """The LLM gave no reason -> use the default copy."""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        return GraderOut(score=8.0, reason="")

    monkeypatch.setattr(orchestrator, "_judge_retry", _judge)
    _, _, reason = await do_grade("q", [], ["ctx"], {}, "zh-CN")
    assert reason


# ---------- _judge_retry ----------

async def test_judge_retry_succeeds_on_second_attempt(monkeypatch):
    """The first attempt fails and the retry succeeds."""
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
    """All attempts fail -> the last exception is raised."""

    async def _judge(schema, system, user, usage, attempts=2, images=None):
        raise RuntimeError("持续故障")

    monkeypatch.setattr(orchestrator, "judge", _judge)
    with pytest.raises(RuntimeError, match="持续故障"):
        await _judge_retry(GraderOut, "sys", "user", {})

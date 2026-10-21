"""RAGent orchestration layer — the main SSE Q&A flow driven by six decision points.

The event protocol matches frontend types.ts exactly: the ten event types router / rewrite /
retrieve / grade / correct / generate / reflect / citation / done / error. Decision-chain
steps and SSE events are persisted to agent_decision_log from the same source (M3).
"""
import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncGenerator

from pydantic import BaseModel

from .. import db
from ..config import settings
from ..i18n import current_locale, t
from ..providers import get_rerank
from ..services.chat_images import to_data_urls
from . import prompts
from .llm import chat_messages, detect_lang, judge, stream_generate
from .retrievers import db_retriever, enabled_sources, gather_lanes
from .rrf import RetrieverResult, rrf_fuse

logger = logging.getLogger("agentic.orchestrator")

VALID_INTENTS = ("chitchat", "kb_qa", "data_query", "summarize")


def intent_label(intent: str, locale: str | None = None) -> str:
    """Intent -> display copy (follows the active language)."""
    return t(f"intent.{intent}", locale)


def verdict_icon(verdict: str, locale: str | None = None) -> str:
    """Grade verdict -> badge copy (follows the active language)."""
    return t(f"sse.grade.icon.{verdict}", locale)


# ---------- Structured output schemas ----------

class RouterOut(BaseModel):
    intent: str = "kb_qa"
    confidence: float = 0.8
    image_note: str = ""  # Key points the Router extracts from an attached image (used for retrieval/grading)


class PlannerOut(BaseModel):
    rewritten_query: str = ""
    sub_queries: list[str] = []
    need_hyde: bool = False
    hyde_doc: str = ""


class GraderOut(BaseModel):
    score: float = 0.0
    reason: str = ""


class CragOut(BaseModel):
    failure_reason: str = ""
    action: str = "rewrite_retry"
    new_queries: list[str] = []


class ReflectOut(BaseModel):
    result: str = "pass"
    missing_info: str = ""


async def _judge_retry(
    schema: type[BaseModel], system: str, user: str, usage: dict, attempts: int = 2, images: list[str] | None = None
):
    """LLM decision call, retried once on failure; images feed the vision decision (Router image reading)."""
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            return await judge(schema, system, user, usage, images=images)
        except Exception as e:
            last_err = e
            logger.warning("judge 调用失败将重试：%s", e)
    raise last_err  # type: ignore[misc]


def sse(etype: str, step: int, detail: str = "", **fields) -> str:
    """Build the SSE event text (event:/data: lines terminated by \n\n, matching the frontend SseParser)."""
    payload = {"step": step, "ts": int(time.time() * 1000), "detail": detail, **fields}
    return f"event: {etype}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------- Run state (events and log share one source) ----------

class RunState:
    def __init__(self, session_id: int, question: str, image_urls: list[str] | None = None) -> None:
        self.session_id = session_id
        self.question = question
        self.locale = current_locale()  # UI/request language (SSE copy and API errors follow it; answers follow the question)
        self.lang = detect_lang(question)  # question language -> LLM prompt language
        self.image_urls = image_urls or []  # in-app URLs (persisted in chat_message.images)
        self.image_data_urls = to_data_urls(self.image_urls)  # base64 data URLs (fed to the vision model)
        self.vision_note = ""  # Image key points extracted by the Router (the image semantics for text-only decisions)
        self.usage: dict[str, int] = {"prompt": 0, "completion": 0}
        self.steps: list[dict] = []
        self.answer = ""
        self.citations: list[dict] = []
        self.correct_count = 0
        self.reflect_fail_count = 0
        self.retrieval_errors: dict[str, str] = {}  # accumulated lane errors (source -> summary), kept apart from "not covered"
        # rerank run state (computed from settings at the start of _run; reused during reflect backflow)
        self.rerank_on: bool = False
        self.lane_top_k: int = settings.retrieval_top_k
        self.fused_candidates: int = settings.fused_top_n
        self.started = time.time()
        self._step_t0 = time.time()
        self._gen_t0: float | None = None

    def mark(self, step: int, type_: str, detail: str, payload: dict) -> None:
        now = time.time()
        self.steps.append(
            {
                "step": step,
                "type": type_,
                "detail": detail,
                "payload": payload,
                "elapsed_ms": max(0, int((now - self._step_t0) * 1000)),
            }
        )
        self._step_t0 = now

    def gen_start(self) -> None:
        self._gen_t0 = time.time()

    def gen_end(self) -> None:
        if self._gen_t0 is not None and self.answer:
            now = time.time()
            self.steps.append(
                {
                    "step": 6,
                    "type": "generate",
                    "detail": t("sse.generate.done", self.locale, n=len(self.answer)),
                    "payload": {"chars": len(self.answer)},
                    "elapsed_ms": max(0, int((now - self._gen_t0) * 1000)),
                }
            )
            self._gen_t0 = None
            self._step_t0 = now

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((time.time() - self.started) * 1000))

    @property
    def question_full(self) -> str:
        """Full question used by planning/grading/correction: with an image, the Router's
        extracted key points are merged in.

        The user text may be nothing but "answer this question" while the real semantics live
        in the image, so the text-only decision points (Planner/Grader/CRAG/Reflect) must work
        from question_full to retrieve and grade properly. The generation side keeps the plain
        question (the model can look at the image directly).
        """
        if self.vision_note:
            if self.lang == "zh-CN":
                return f"{self.question}\n（用户附图，图中内容要点：{self.vision_note}）"
            return f"{self.question}\n(User attached an image; key points: {self.vision_note})"
        return self.question

    async def persist(self) -> tuple[int, int]:
        """Persist the assistant message and the decision log."""
        rounds = max(1, self.correct_count + self.reflect_fail_count)
        content = self.answer or t("error.no_answer_persisted", self.locale)
        msg_id = await db.aexecute(
            "INSERT INTO chat_message (session_id, role, content, citations) VALUES (%s, 'assistant', %s, %s)",
            (self.session_id, content, json.dumps(self.citations, ensure_ascii=False) if self.citations else None),
        )
        log_id = await db.aexecute(
            "INSERT INTO agent_decision_log (session_id, message_id, question, final_answer, steps, total_rounds, elapsed_ms)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                self.session_id,
                msg_id,
                self.question,
                content,
                json.dumps(self.steps, ensure_ascii=False),
                rounds,
                self.elapsed_ms,
            ),
        )
        await db.aexecute("UPDATE chat_message SET decision_log_id=%s WHERE id=%s", (log_id, msg_id))
        await db.aexecute("UPDATE chat_session SET updated_at=NOW() WHERE id=%s", (self.session_id,))
        return msg_id, log_id


# ---------- Context and citations ----------

def build_context(items: list[RetrieverResult], locale: str = "zh-CN") -> list[str]:
    zh = locale == "zh-CN"
    blocks: list[str] = []
    for i, it in enumerate(items, 1):
        meta = it.metadata
        if meta.get("db"):
            header = (
                f"[{i}] 业务数据库 sales 表查询结果（来自业务数据库）"
                if zh
                else f"[{i}] Business database sales table query results (from the business database)"
            )
            blocks.append(f"{header}\n{it.content[:500]}")
        else:
            if zh:
                header = f"[{i}] 《{meta.get('doc_name', '')}》{meta.get('section_path', '')}（切片#{meta.get('chunk_no', 0)}）"
            else:
                header = f'[{i}] "{meta.get("doc_name", "")}" {meta.get("section_path", "")} (chunk #{meta.get("chunk_no", 0)})'
            blocks.append(f"{header}\n{it.content[:600]}")
    return blocks


def extract_citations(answer: str, items: list[RetrieverResult], locale: str | None = None) -> list[dict]:
    """Map trailing [n] markers to chunk metadata, dropping invalid indices."""
    seen: set[int] = set()
    out: list[dict] = []
    for m in re.finditer(r"\[(\d+)\]", answer):
        idx = int(m.group(1))
        if not (1 <= idx <= len(items)) or idx in seen:
            continue
        seen.add(idx)
        meta = items[idx - 1].metadata
        if meta.get("db"):
            # An NL2SQL citation has no document chunk to locate: it carries the SQL plus the result rows
            # and the frontend switches to the "data query evidence" view
            out.append(
                {
                    "ref_id": idx,
                    "source_type": "db",
                    "doc_name": t("cite.db_doc_name", locale),
                    "section_path": t("cite.db_section", locale),
                    "chunk_no": 0,
                    "sql": meta.get("sql", ""),
                    "rows": meta.get("rows", []),
                }
            )
        else:
            out.append(
                {
                    "ref_id": idx,
                    "doc_name": meta.get("doc_name", ""),
                    "section_path": meta.get("section_path", ""),
                    "chunk_no": meta.get("chunk_no", 0),
                    **{key: meta[key] for key in ("doc_id", "kb_id", "chunk_uid") if meta.get(key) is not None},
                }
            )
    return out


def strip_invalid_refs(answer: str, items: list[RetrieverResult]) -> str:
    """Strip [n] markers from the answer that map to no valid chunk (so they are not rendered as plain text)."""
    valid = {i + 1 for i in range(len(items))}

    def _repl(m: re.Match) -> str:
        return m.group(0) if int(m.group(1)) in valid else ""

    return re.sub(r"\[(\d+)\]", _repl, answer)


# ---------- Retrieval degradation notices (distinct from "not covered"; incident follow-up, 2026-10-19) ----------

def degraded_note(errors: dict[str, str], locale: str | None = None) -> str:
    """Generation-side notice for a lane error: suggests a service failure rather than a knowledge gap."""
    sep = "；" if (locale or current_locale()) == "zh-CN" else "; "
    parts = sep.join(f"{src}（{msg[:80]}）" for src, msg in errors.items())
    return t("disclaimer.degraded", locale, parts=parts)


def give_up_disclaimer(errors: dict[str, str], locale: str | None = None) -> str:
    """Generation-side notice for a CRAG give_up: a degradation note first when a lane failed, then the
    knowledge-gap notice."""
    base = t("disclaimer.give_up_base", locale)
    if errors:
        return degraded_note(errors, locale) + "\n\n" + base
    return base


async def _emit_lane_errors(st: RunState, errors: dict[str, str], prefix: str = "") -> AsyncGenerator[str, None]:
    """A lane error -> an SSE degraded event plus a decision-log step from the same source (silent when clean)."""
    if not errors:
        return
    st.retrieval_errors.update(errors)
    sep = "；" if st.locale == "zh-CN" else "; "
    sources = sep.join(t("sse.retrieve.lane_src_fail", st.locale, src=src) for src in errors)
    detail = t("sse.retrieve.lane_error", st.locale, prefix=prefix, sources=sources)
    yield sse("retrieve", 3, detail, degraded=True, errors=errors)
    st.mark(3, "retrieve", detail, {"degraded": True, "errors": errors})


# ---------- Rerank (coarse then fine; a failure degrades to the coarse order) ----------

def _rerank_ready() -> bool:
    """Pre-check the rerank switch: it counts as enabled only when the provider can be built
    (otherwise this run stays coarse)."""
    try:
        get_rerank()
        return True
    except Exception as e:
        logger.warning("rerank 已开启但 provider 不可用，本次走粗排：%s", e)
        return False


def rerank_params(rerank_on: bool | None = None) -> tuple[int, int]:
    """Return (per-lane recall depth, RRF candidate count) for the rerank switch; when off these
    are the current defaults.

    rerank_on defaults to settings.rerank_enabled; a caller that already validated provider
    availability should pass it explicitly (so candidate depth is not needlessly widened when
    the provider is unavailable).
    """
    if rerank_on is None:
        rerank_on = settings.rerank_enabled
    if not rerank_on:
        return settings.retrieval_top_k, settings.fused_top_n
    # Coarse then fine: deepen per-lane recall, let RRF build the candidate pool, then rerank down to top_n
    return max(settings.retrieval_top_k, (settings.rerank_candidates + 1) // 2), settings.rerank_candidates


async def _apply_rerank(
    query: str, items: list[RetrieverResult], locale: str | None = None
) -> tuple[list[RetrieverResult], dict | None, str]:
    """Rerank: returns (reordered items, info, failure detail); any failure keeps the coarse order and
    never breaks the chain."""
    try:
        provider = get_rerank()
    except Exception as e:
        return items, None, t("sse.retrieve.rerank_unavailable", locale, err=type(e).__name__)
    t0 = time.perf_counter()
    try:
        scored = await provider.rerank(query, [it.content for it in items], settings.rerank_top_n)
    except Exception as e:
        logger.warning("rerank 调用失败，降级粗排序：%s", e)
        return items, None, t("sse.retrieve.rerank_failed_msg", locale, err=type(e).__name__)
    if not scored:
        return items, None, t("sse.retrieve.rerank_empty", locale)
    reordered = [items[i] for i, _ in scored if 0 <= i < len(items)]
    if len(reordered) != len(scored):
        logger.warning("rerank 返回越界索引，已过滤：%s", scored)
    info = {
        "model": provider.model,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
        "in": len(items),
        "out": len(reordered),
    }
    return reordered, info, ""


async def _run_rerank(
    st: RunState, query: str, items: list[RetrieverResult], prefix: str = ""
) -> tuple[list[RetrieverResult], dict | None, str, list[str]]:
    """Rerank and build the SSE events plus decision-log steps; returns (items, info, err, events).

    events are the SSE strings to yield (the caller loops over them), preserving the streaming
    semantics of _run.
    """
    items, info, err = await _apply_rerank(query, items, st.locale)
    events: list[str] = []
    if info:
        detail = t(
            "sse.retrieve.rerank_ok",
            st.locale,
            prefix=prefix,
            in_=info["in"],
            out=info["out"],
            model=info["model"],
            ms=info["ms"],
        )
        events.append(sse("retrieve", 3, detail, source="rerank", hit_count=info["out"], rerank=info))
        st.mark(3, "retrieve", detail, {"source": "rerank", "hit_count": info["out"], "rerank": info})
    elif err:
        fail_detail = t("sse.retrieve.rerank_failed", st.locale, prefix=prefix, err=err)
        events.append(sse("retrieve", 3, fail_detail, degraded=True, rerank_error=err))
        st.mark(3, "retrieve", fail_detail, {"degraded": True, "rerank_error": err})
    return items, info, err, events


async def do_grade(
    question: str, sub_queries: list[str], ctx_blocks: list[str], usage: dict, locale: str | None = None
) -> tuple[float, str, str]:
    """(4) Grader: 0-10 score plus threshold verdict (>=7 pass / >=5 partial / <5 fail)."""
    if not ctx_blocks:
        return 0.0, "fail", t("sse.grade.no_hits", locale)
    g = await _judge_retry(
        GraderOut,
        prompts.get_prompt("grader_sys", locale or "zh-CN"),
        prompts.grader_user(question, sub_queries, ctx_blocks, locale or "zh-CN"),
        usage,
    )
    score = round(min(10.0, max(0.0, float(g.score))), 1)
    verdict = "pass" if score >= settings.grade_pass else ("partial" if score >= settings.grade_partial else "fail")
    return score, verdict, g.reason or t("sse.grade.reason_none", locale)


# ---------- Generation + Self-RAG + citations + done wrap-up ----------

async def _generate_and_finish(
    st: RunState,
    history: list[dict],
    kb_ids: list[int] | None,
    ctx_blocks: list[str],
    items: list[RetrieverResult],
    disclaimer: str = "",
    supp_db: bool = False,
) -> AsyncGenerator[dict, None]:
    # (6) Generation (streaming; with an image the last human message holds multimodal content blocks)
    gen_user = prompts.generate_user(st.question, ctx_blocks, history, disclaimer, st.lang)
    msgs = chat_messages(prompts.get_prompt("generate_sys", st.lang), history, gen_user, st.image_data_urls)
    st.gen_start()
    async for delta in stream_generate(msgs, st.usage):
        st.answer += delta
        yield sse("generate", 6, "", delta=delta)
    st.gen_end()

    # (6) Self-RAG reflection (failing answers flow back for supplementary retrieval, at most 2 rounds;
    # graded on question_full so image semantics are complete)
    round_i = 0
    reflect_passed = False
    while round_i < settings.reflect_max_rounds:
        round_i += 1
        rf = await _judge_retry(
            ReflectOut,
            prompts.get_prompt("reflect_sys", st.lang),
            prompts.reflect_user(st.question_full, st.answer, ctx_blocks, st.lang),
            st.usage,
        )
        if rf.result == "pass":
            reflect_passed = True
            suffix = t("sse.reflect.pass_suffix", st.locale, n=round_i) if round_i > 1 else ""
            detail = t("sse.reflect.pass", st.locale, suffix=suffix)
            yield sse("reflect", 6, detail, result="pass", round=round_i)
            st.mark(6, "reflect", detail, {"result": "pass", "round": round_i})
            break
        st.reflect_fail_count += 1
        missing = rf.missing_info or t("sse.reflect.missing_default", st.locale)
        detail = t("sse.reflect.fail", st.locale, missing=missing)
        yield sse("reflect", 6, detail, result="fail", round=round_i, missing_info=rf.missing_info)
        st.mark(6, "reflect", detail, {"result": "fail", "round": round_i, "missing_info": rf.missing_info})
        if round_i >= settings.reflect_max_rounds:
            break
        # Reflect backflow: targeted supplementary retrieval (missing info merged into the query; data_query
        # goes back to the database, everything else to the knowledge base) -> re-grade -> regenerate
        supp_q = f"{st.question_full} {rf.missing_info}".strip()
        if supp_db:
            sql, db_rows = await db_retriever.search(supp_q, locale=st.lang)
            detail = t("sse.retrieve.reflow_nl2sql", st.locale, sql=sql[:60], n=len(db_rows))
            yield sse("retrieve", 3, detail, source="database", hit_count=len(db_rows))
            st.mark(3, "retrieve", detail, {"source": "database", "hit_count": len(db_rows), "sql": sql})
            lanes = {"database": db_rows}
        else:
            lanes, lane_errors = await gather_lanes(supp_q, kb_ids, st.lane_top_k, ["vector", "keyword"])
            async for ev in _emit_lane_errors(st, lane_errors, prefix=t("sse.retrieve.prefix.reflow", st.locale)):
                yield ev
        for src in ("vector", "keyword"):
            if src in lanes:
                hits = lanes[src]
                label = t("sse.retrieve.reflow_targeted", st.locale) if src == "vector" else t("sse.retrieve.reflow_keyword", st.locale)
                detail = t("sse.retrieve.reflow_hits", st.locale, label=label, n=len(hits))
                yield sse("retrieve", 3, detail, source=src, hit_count=len(hits))
                st.mark(3, "retrieve", detail, {"source": src, "hit_count": len(hits)})
        fused = rrf_fuse(lanes, st.fused_candidates)
        items = [f["item"] for f in fused]
        if st.rerank_on and "database" not in lanes:
            items, rr_info, rr_err, rr_events = await _run_rerank(st, st.question_full, items, prefix="反思回流·")
            for ev in rr_events:
                yield ev
            if rr_err:
                st.rerank_on = False  # circuit break: later backflow rounds stop calling it
        ctx_blocks = build_context(items, st.lang)
        score, verdict, reason = await do_grade(st.question_full, [], ctx_blocks, st.usage, st.locale)
        detail = t(
            "sse.grade.score",
            st.locale,
            score=score,
            icon=verdict_icon(verdict, st.locale),
            suffix=t("sse.grade.suffix.reflow", st.locale),
        )
        yield sse("grade", 4, detail, score=score, verdict=verdict, reason=reason)
        st.mark(4, "grade", detail, {"score": score, "verdict": verdict, "reason": reason})
        gen_user = prompts.generate_user(st.question, ctx_blocks, history, disclaimer, st.lang)
        msgs = chat_messages(prompts.get_prompt("generate_sys", st.lang), history, gen_user, st.image_data_urls)
        # Citation numbers of a new round map only to the new context; the old answer must not survive
        # or be interpreted against the new chunks.
        st.answer = ""
        yield sse("generate", 6, "", delta="", replace=True)
        st.gen_start()
        async for delta in stream_generate(msgs, st.usage):
            st.answer += delta
            yield sse("generate", 6, "", delta=delta)
        st.gen_end()
    if not reflect_passed and round_i >= settings.reflect_max_rounds:
        st.answer += t("sse.reflect.exhausted_note", st.locale)

    # (7) Citation attribution (invalid markers were already stripped from the answer)
    st.answer = strip_invalid_refs(st.answer, items)
    st.citations = extract_citations(st.answer, items, st.locale)
    cite_detail = (
        t("sse.citation.with", st.locale, n=len(st.citations))
        if st.citations
        else t("sse.citation.without", st.locale)
    )
    # Send the answer after invalid citations are stripped, together with the self-check note, so the
    # streamed display matches what is persisted.
    yield sse("citation", 7, cite_detail, citations=st.citations, answer=st.answer)
    st.mark(7, "citation", cite_detail, {"citations": st.citations})

    msg_id, _ = await st.persist()
    yield sse(
        "done",
        0,
        "",
        message_id=msg_id,
        elapsed_ms=st.elapsed_ms,
        token_usage={"prompt": st.usage.get("prompt", 0), "completion": st.usage.get("completion", 0)},
    )


# ---------- Main Q&A flow ----------

async def _run(st: RunState, kb_ids: list[int] | None, skip_user_persist: bool) -> AsyncGenerator[dict, None]:
    session_id = st.session_id
    question = st.question

    # Q8 multi-turn context (history is read before the user message is stored so the current question
    # is not part of it; images feed the attachment markers)
    history = list(
        reversed(
            await db.aquery_all(
                "SELECT role, content, images FROM chat_message WHERE session_id=%s ORDER BY id DESC LIMIT %s",
                (session_id, settings.history_window),
            )
        )
    )
    if not skip_user_persist:
        await db.aexecute(
            "INSERT INTO chat_message (session_id, role, content, images) VALUES (%s, 'user', %s, %s)",
            (session_id, question, json.dumps(st.image_urls, ensure_ascii=False) if st.image_urls else None),
        )
    sess = await db.aquery_one("SELECT title FROM chat_session WHERE id=%s", (session_id,))
    if sess is None:
        raise ValueError(t("error.session_missing", st.locale))
    if sess["title"] == "新会话":
        await db.aexecute(
            "UPDATE chat_session SET title=%s WHERE id=%s",
            (question[:18] + ("…" if len(question) > 18 else ""), session_id),
        )

    # Constrain routing with the currently enabled data-source capabilities instead of letting the model
    # guess which business tables exist.
    src_enabled = await enabled_sources()
    # (1) Router intent routing (with an image it reads the image for key points; image questions are
    # always kb_qa: retrieve the knowledge base first, then answer with the image)
    r = await _judge_retry(
        RouterOut,
        prompts.get_prompt("router_sys", st.lang),
        prompts.router_user(question, history, len(st.image_data_urls), st.lang, database_enabled=src_enabled["database"]),
        st.usage,
        images=st.image_data_urls,
    )
    if r.intent not in VALID_INTENTS:
        r.intent = "kb_qa"
    if r.intent == "data_query" and not src_enabled["database"]:
        r.intent = "kb_qa"
    # Code-level override: messages with images never take the chitchat/data-query bypass; they always
    # use the main retrieval chain plus vision generation
    if st.image_data_urls:
        r.intent = "kb_qa"
        st.vision_note = (r.image_note or "").strip()
    r.confidence = min(1.0, max(0.0, float(r.confidence)))
    detail = t("sse.router.judging", st.locale, intent=intent_label(r.intent, st.locale))
    if st.image_data_urls:
        note_txt = st.vision_note[:40] + ("…" if len(st.vision_note) > 40 else "")
        detail += t("sse.router.image_note", st.locale, note=note_txt or t("sse.router.no_note", st.locale))
    yield sse("router", 1, detail, intent=r.intent, confidence=round(r.confidence, 2))
    st.mark(
        1,
        "router",
        detail,
        {"intent": r.intent, "confidence": r.confidence, "has_images": bool(st.image_data_urls), "vision_note": st.vision_note},
    )

    # ---- Chitchat bypass: stream a direct answer (no retrieval) ----
    if r.intent == "chitchat":
        st.gen_start()
        msgs = chat_messages(prompts.get_prompt("chat_sys", st.lang), history, question, st.image_data_urls)
        async for delta in stream_generate(msgs, st.usage):
            st.answer += delta
            yield sse("generate", 0, "", delta=delta)
        st.gen_end()
        msg_id, _ = await st.persist()
        yield sse(
            "done",
            0,
            "",
            message_id=msg_id,
            elapsed_ms=st.elapsed_ms,
            token_usage={"prompt": st.usage.get("prompt", 0), "completion": st.usage.get("completion", 0)},
        )
        return

    # ---- Data-query bypass: NL2SQL straight to DBRetriever (rewriting skipped) ----
    if r.intent == "data_query":
        sql, rows = await db_retriever.search(st.question_full, locale=st.lang)
        n = len(rows)
        sql_txt = sql if len(sql) <= 72 else sql[:72] + "…"
        detail = t("sse.retrieve.nl2sql_direct", st.locale, sql=sql_txt, n=n)
        yield sse("retrieve", 3, detail, source="database", hit_count=n)
        st.mark(3, "retrieve", detail, {"source": "database", "hit_count": n, "sql": sql})

        items = rows
        ctx_blocks = build_context(items, st.lang)
        disclaimer = ""
        score, verdict, reason = await do_grade(st.question_full, [], ctx_blocks, st.usage, st.locale)
        detail = t("sse.grade.score", st.locale, score=score, icon=verdict_icon(verdict, st.locale), suffix="")
        yield sse("grade", 4, detail, score=score, verdict=verdict, reason=reason)
        st.mark(4, "grade", detail, {"score": score, "verdict": verdict, "reason": reason})
        if verdict == "pass":
            async for ev in _generate_and_finish(st, history, kb_ids, ctx_blocks, items, disclaimer, supp_db=True):
                yield ev
            return
        # Irrelevant or insufficient database evidence does not prove the document library lacks the
        # answer; fall back to the full knowledge-base chain and keep the unrelated SQL results out of
        # the generation context and the final citations.
        r.intent = "kb_qa"
        detail = t("sse.router.db_fallback", st.locale)
        payload = {"intent": r.intent, "confidence": r.confidence, "fallback_from": "data_query", "reason": reason}
        yield sse("router", 1, detail, **payload)
        st.mark(1, "router", detail, payload)

    # ---- Knowledge Q&A / summarization main chain ----
    rerank_on = settings.rerank_enabled and _rerank_ready()
    st.rerank_on = rerank_on
    # When the provider is unavailable rerank_on=False and the candidate depth stays at its default
    # (Important 1 fix)
    st.lane_top_k, st.fused_candidates = rerank_params(rerank_on)
    top_k = st.lane_top_k
    candidates = st.fused_candidates
    sub_queries: list[str] = []
    hyde_used = False
    vector_query = st.question_full

    if r.intent == "kb_qa":
        # (2) Planner query planning (rewrite / decompose / HyDE; with an image it rewrites from the
        # extracted key points so retrieval carries the semantics)
        p = await _judge_retry(
            PlannerOut,
            prompts.get_prompt("planner_sys", st.lang),
            prompts.planner_user(st.question_full, history, st.lang),
            st.usage,
        )
        main_query = p.rewritten_query or st.question_full
        sub_queries = [q for q in p.sub_queries if q][:3]
        hyde_used = bool(p.need_hyde and p.hyde_doc)
        vector_query = p.hyde_doc if hyde_used else main_query
        detail = (
            t("sse.rewrite.split", st.locale, n=len(sub_queries))
            if sub_queries
            else t(
                "sse.rewrite.main",
                st.locale,
                hyde=t("sse.rewrite.hyde_on", st.locale) if hyde_used else t("sse.rewrite.hyde_off", st.locale),
            )
        )
        yield sse("rewrite", 2, detail, rewritten_query=main_query, sub_queries=sub_queries, hyde_used=hyde_used)
        st.mark(2, "rewrite", detail, {"rewritten_query": main_query, "sub_queries": sub_queries, "hyde_used": hyde_used})
    else:
        main_query = question

    # Knowledge-base source set (summarize takes the lightweight semantic path, vector lane only)
    kb_sources = [s for s in ("vector", "keyword") if src_enabled.get(s)]
    if r.intent == "summarize":
        kb_sources = ["vector"] if src_enabled.get("vector") else kb_sources[:1]

    # (3)(4)(5) Retrieve -> fuse -> grade (one supplementary retrieval for partial / CRAG correction up to 2 rounds)
    retrieval_round = 0
    supplemented = False
    crag_round = 0
    disclaimer = ""
    ctx_blocks: list[str] = []
    items: list[RetrieverResult] = []

    while True:
        retrieval_round += 1
        lanes, lane_errors = await gather_lanes(vector_query, kb_ids, top_k, kb_sources)
        async for ev in _emit_lane_errors(st, lane_errors):
            yield ev
        for src in ("vector", "keyword"):
            if src in lanes:
                hits = lanes[src]
                label = t("sse.retrieve.vector", st.locale) if src == "vector" else t("sse.retrieve.keyword", st.locale)
                prefix = (
                    ""
                    if retrieval_round == 1
                    else (t("sse.retrieve.prefix.requery", st.locale) if crag_round else t("sse.retrieve.prefix.supplement", st.locale))
                )
                detail = t("sse.retrieve.hits", st.locale, prefix=prefix, label=label, n=len(hits))
                yield sse("retrieve", 3, detail, source=src, hit_count=len(hits))
                st.mark(3, "retrieve", detail, {"source": src, "hit_count": len(hits)})

        fused = rrf_fuse(lanes, candidates)
        items = [f["item"] for f in fused]
        if rerank_on:
            items, rr_info, rr_err, rr_events = await _run_rerank(st, st.question_full, items)
            for ev in rr_events:
                yield ev
            if rr_err:
                # Circuit break: later steps in this run (CRAG re-query / reflect backflow) stop calling
                # the failed provider
                rerank_on = False
                st.rerank_on = False
        ctx_blocks = build_context(items, st.lang)

        score, verdict, reason = await do_grade(st.question_full, sub_queries, ctx_blocks, st.usage, st.locale)
        suffix = t("sse.grade.suffix.round", st.locale, n=retrieval_round) if retrieval_round > 1 else ""
        detail = t("sse.grade.score", st.locale, score=score, icon=verdict_icon(verdict, st.locale), suffix=suffix)
        yield sse("grade", 4, detail, score=score, verdict=verdict, reason=reason)
        st.mark(4, "grade", detail, {"score": score, "verdict": verdict, "reason": reason})

        if verdict == "pass":
            break

        # partial: run one supplementary retrieval (once only)
        if verdict == "partial" and not supplemented and kb_sources:
            supplemented = True
            st.correct_count += 1
            c_detail = t("sse.correct.supplement", st.locale)
            yield sse("correct", 5, c_detail, action="rewrite_retry", round=1)
            st.mark(5, "correct", c_detail, {"action": "rewrite_retry", "round": 1})
            vector_query = main_query
            continue

        # fail (or still failing after the partial supplement) -> CRAG correction
        if crag_round >= settings.crag_max_rounds:
            st.correct_count += 1
            final_round = max(crag_round, 1)
            c_detail = t("sse.correct.exhausted", st.locale, n=final_round)
            yield sse("correct", 5, c_detail, action="give_up", round=final_round)
            st.mark(5, "correct", c_detail, {"action": "give_up", "round": final_round})
            disclaimer = give_up_disclaimer(st.retrieval_errors, st.locale)
            ctx_blocks = []
            items = []
            break

        crag_round += 1
        diag = await _judge_retry(
            CragOut,
            prompts.get_prompt("crag_sys", st.lang),
            prompts.crag_user(st.question_full, reason, ctx_blocks, st.lang),
            st.usage,
        )
        action = diag.action

        if action == "give_up":
            st.correct_count += 1
            c_detail = t("sse.correct.give_up", st.locale, reason=diag.failure_reason, n=crag_round)
            yield sse("correct", 5, c_detail, action="give_up", round=crag_round)
            st.mark(5, "correct", c_detail, {"action": "give_up", "round": crag_round, "reason": diag.failure_reason})
            disclaimer = give_up_disclaimer(st.retrieval_errors, st.locale)
            ctx_blocks = []
            items = []
            break

        # rewrite_retry: CRAG rewrites the query and re-retrieves
        st.correct_count += 1
        c_detail = t("sse.correct.rewrite_retry", st.locale, reason=diag.failure_reason, n=crag_round)
        yield sse("correct", 5, c_detail, action="rewrite_retry", round=crag_round)
        st.mark(5, "correct", c_detail, {"action": "rewrite_retry", "round": crag_round, "reason": diag.failure_reason})
        new_q = diag.new_queries[0] if diag.new_queries else f"{main_query} 相关 原理 方案"
        main_query = new_q
        vector_query = new_q
        rw_detail = t("sse.rewrite.crag", st.locale, reason=diag.failure_reason)
        yield sse("rewrite", 2, rw_detail, rewritten_query=new_q, sub_queries=sub_queries, hyde_used=hyde_used)
        st.mark(2, "rewrite", rw_detail, {"rewritten_query": new_q, "sub_queries": sub_queries, "hyde_used": hyde_used})

    async for ev in _generate_and_finish(st, history, kb_ids, ctx_blocks, items, disclaimer):
        yield ev


async def run_ask(
    session_id: int,
    question: str,
    kb_ids: list[int] | None,
    skip_user_persist: bool = False,
    image_urls: list[str] | None = None,
    locale: str | None = None,
) -> AsyncGenerator[dict, None]:
    """SSE Q&A flow entry point: the whole run is bounded by overall_timeout (120s); failures emit an
    error event.

    image_urls: in-app image URLs (output of chat_images.save_images), persisted with the message
    and converted to data URLs for the vision model.
    locale: UI/request language (None -> the ContextVar default zh-CN); it only affects SSE copy and
    API errors, while the answer language follows the question.
    """
    st = RunState(session_id, question, image_urls)
    if locale:
        st.locale = locale
    try:
        async with asyncio.timeout(settings.overall_timeout):
            async for ev in _run(st, kb_ids, skip_user_persist):
                yield ev
    except (TimeoutError, asyncio.TimeoutError):
        secs = settings.overall_timeout
        detail = t("error.timeout", st.locale, n=secs)
        yield sse("error", 0, detail, code=504, message=t("error.timeout_detail", st.locale, n=secs))
        try:
            await st.persist()
        except Exception:
            logger.exception("超时场景落库失败")
    except ValueError as e:
        yield sse("error", 0, str(e), code=404, message=str(e))
    except Exception as e:
        logger.exception("问答链路异常：%s", e)
        msg = f"{e}" or t("error.internal", st.locale)
        yield sse("error", 0, t("error.chain_broken", st.locale), code=500, message=msg[:300])
        try:
            await st.persist()
        except Exception:
            logger.exception("异常场景落库失败")

"""RAGent 编排层 — 六大决策点驱动的 SSE 问答主流程

事件协议严格对齐前端 types.ts：router / rewrite / retrieve / grade / correct /
generate / reflect / citation / done / error 十类事件；
决策链 steps 与 SSE 事件同源落库 agent_decision_log（M3）。
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
    """意图 → 展示文案（随语言切换）"""
    return t(f"intent.{intent}", locale)


def verdict_icon(verdict: str, locale: str | None = None) -> str:
    """评分判定 → 徽标文案（随语言切换）"""
    return t(f"sse.grade.icon.{verdict}", locale)


# ---------- 结构化输出 Schema ----------

class RouterOut(BaseModel):
    intent: str = "kb_qa"
    confidence: float = 0.8
    image_note: str = ""  # 带图时由 Router 视觉提取的图中内容要点（供检索/评估使用）


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
    """LLM 判定调用，失败重试 1 次；images 供视觉判定（Router 读图）"""
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            return await judge(schema, system, user, usage, images=images)
        except Exception as e:
            last_err = e
            logger.warning("judge 调用失败将重试：%s", e)
    raise last_err  # type: ignore[misc]


def sse(etype: str, step: int, detail: str = "", **fields) -> str:
    """构造 SSE 事件文本（event:/data: 行，\n\n 结尾，与前端 SseParser 协议一致）"""
    payload = {"step": step, "ts": int(time.time() * 1000), "detail": detail, **fields}
    return f"event: {etype}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------- 运行态（事件与日志同源） ----------

class RunState:
    def __init__(self, session_id: int, question: str, image_urls: list[str] | None = None) -> None:
        self.session_id = session_id
        self.question = question
        self.locale = current_locale()  # UI/请求语言（SSE 文案与 API 错误跟随；答案语言跟随提问）
        self.lang = detect_lang(question)  # 提问语言 → LLM 提示词语言
        self.image_urls = image_urls or []  # 站内 URL（落库 chat_message.images）
        self.image_data_urls = to_data_urls(self.image_urls)  # base64 data URL（喂给视觉模型）
        self.vision_note = ""  # Router 视觉提取的图中内容要点（纯文本决策点的图片语义来源）
        self.usage: dict[str, int] = {"prompt": 0, "completion": 0}
        self.steps: list[dict] = []
        self.answer = ""
        self.citations: list[dict] = []
        self.correct_count = 0
        self.reflect_fail_count = 0
        self.retrieval_errors: dict[str, str] = {}  # 检索路异常累积（source -> 摘要），与「知识库未覆盖」区分
        # rerank 运行态（_run 开篇按 settings 计算；反思回流期复用同一组参数）
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
        """规划/评估/纠正用完整问题：带图时并入 Router 视觉提取的图中要点

        用户文字可能只是"回答这个问题"，真正语义在图中——纯文本决策点
        （Planner/Grader/CRAG/Reflect）必须基于 question_full 才能检索与评估到位；
        生成侧仍用原 question（模型可直接看图）。
        """
        if self.vision_note:
            if self.lang == "zh-CN":
                return f"{self.question}\n（用户附图，图中内容要点：{self.vision_note}）"
            return f"{self.question}\n(User attached an image; key points: {self.vision_note})"
        return self.question

    async def persist(self) -> tuple[int, int]:
        """落库：assistant 消息 + 决策日志"""
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


# ---------- 上下文与引用 ----------

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
    """句尾 [n] 序号 → 片段元数据映射，非法序号剔除"""
    seen: set[int] = set()
    out: list[dict] = []
    for m in re.finditer(r"\[(\d+)\]", answer):
        idx = int(m.group(1))
        if not (1 <= idx <= len(items)) or idx in seen:
            continue
        seen.add(idx)
        meta = items[idx - 1].metadata
        if meta.get("db"):
            # NL2SQL 引用无文档切片可定位：携带 SQL + 结果行，前端改走「数据查询证据」视图
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
    """剔除答案中未映射到合法片段的 [n] 序号（避免渲染为残留明文）"""
    valid = {i + 1 for i in range(len(items))}

    def _repl(m: re.Match) -> str:
        return m.group(0) if int(m.group(1)) in valid else ""

    return re.sub(r"\[(\d+)\]", _repl, answer)


# ---------- 检索降级声明（与「知识库未覆盖」区分，2026-10-19 事故改进） ----------

def degraded_note(errors: dict[str, str], locale: str | None = None) -> str:
    """检索路异常时的生成侧声明：提示可能是服务故障而非知识库缺失"""
    sep = "；" if (locale or current_locale()) == "zh-CN" else "; "
    parts = sep.join(f"{src}（{msg[:80]}）" for src, msg in errors.items())
    return t("disclaimer.degraded", locale, parts=parts)


def give_up_disclaimer(errors: dict[str, str], locale: str | None = None) -> str:
    """CRAG give_up 的生成侧声明：有检索路异常时前置降级说明，再附知识库未覆盖说明"""
    base = t("disclaimer.give_up_base", locale)
    if errors:
        return degraded_note(errors, locale) + "\n\n" + base
    return base


async def _emit_lane_errors(st: RunState, errors: dict[str, str], prefix: str = "") -> AsyncGenerator[str, None]:
    """检索路异常 → SSE degraded 事件 + 决策日志同源落库（无异常时静默）"""
    if not errors:
        return
    st.retrieval_errors.update(errors)
    sep = "；" if st.locale == "zh-CN" else "; "
    sources = sep.join(t("sse.retrieve.lane_src_fail", st.locale, src=src) for src in errors)
    detail = t("sse.retrieve.lane_error", st.locale, prefix=prefix, sources=sources)
    yield sse("retrieve", 3, detail, degraded=True, errors=errors)
    st.mark(3, "retrieve", detail, {"degraded": True, "errors": errors})


# ---------- Rerank 精排（先粗排后精排；失败降级保留粗排序） ----------

def _rerank_ready() -> bool:
    """rerank 开关前置校验：provider 可构建才算启用（否则本次走粗排）"""
    try:
        get_rerank()
        return True
    except Exception as e:
        logger.warning("rerank 已开启但 provider 不可用，本次走粗排：%s", e)
        return False


def rerank_params(rerank_on: bool | None = None) -> tuple[int, int]:
    """按 rerank 开关返回 (单路召回深度, RRF 候选数)；关闭时即现行默认值

    rerank_on 缺省时跟随 settings.rerank_enabled；调用方已做 provider 可用性校验时
    应显式传入（避免 provider 不可用时候选深度被无意义加深）。
    """
    if rerank_on is None:
        rerank_on = settings.rerank_enabled
    if not rerank_on:
        return settings.retrieval_top_k, settings.fused_top_n
    # 先粗排后精排：单路加深召回，RRF 出候选池，再精排截 top_n
    return max(settings.retrieval_top_k, (settings.rerank_candidates + 1) // 2), settings.rerank_candidates


async def _apply_rerank(
    query: str, items: list[RetrieverResult], locale: str | None = None
) -> tuple[list[RetrieverResult], dict | None, str]:
    """精排：返回 (重排后 items, info, 失败详情)；任一失败都保留粗排序，不中断链路"""
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
    """精排 + 构造 SSE 事件与决策日志步骤；返回 (items, info, err, events)

    events 为待 yield 的 SSE 字符串（调用方 for 循环 yield），保持 _run 的事件流式语义。
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
    """④ Grader：0-10 打分 + 阈值判定（≥7 pass / ≥5 partial / <5 fail）"""
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


# ---------- 生成 + Self-RAG + 引用 + done 收尾 ----------

async def _generate_and_finish(
    st: RunState,
    history: list[dict],
    kb_ids: list[int] | None,
    ctx_blocks: list[str],
    items: list[RetrieverResult],
    disclaimer: str = "",
    supp_db: bool = False,
) -> AsyncGenerator[dict, None]:
    # ⑥ 生成（流式；带图时末条 human 消息为视觉多模态 content 块）
    gen_user = prompts.generate_user(st.question, ctx_blocks, history, disclaimer, st.lang)
    msgs = chat_messages(prompts.get_prompt("generate_sys", st.lang), history, gen_user, st.image_data_urls)
    st.gen_start()
    async for delta in stream_generate(msgs, st.usage):
        st.answer += delta
        yield sse("generate", 6, "", delta=delta)
    st.gen_end()

    # ⑥ Self-RAG 反思（不达标回流补检，≤2 次；基于 question_full 评估，带图语义完整）
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
        # 反思回流：定向补检（缺失信息并入查询；data_query 场景回数据库，其余回知识库）→ 重新评估 → 重新生成
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
                st.rerank_on = False  # 熔断：后续回流不再调用
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
        # 新轮次的序号只对应新上下文；旧答案不得保留或按新片段解释。
        st.answer = ""
        yield sse("generate", 6, "", delta="", replace=True)
        st.gen_start()
        async for delta in stream_generate(msgs, st.usage):
            st.answer += delta
            yield sse("generate", 6, "", delta=delta)
        st.gen_end()
    if not reflect_passed and round_i >= settings.reflect_max_rounds:
        st.answer += t("sse.reflect.exhausted_note", st.locale)

    # ⑦ 引用溯源（非法序号已从答案剔除）
    st.answer = strip_invalid_refs(st.answer, items)
    st.citations = extract_citations(st.answer, items, st.locale)
    cite_detail = (
        t("sse.citation.with", st.locale, n=len(st.citations))
        if st.citations
        else t("sse.citation.without", st.locale)
    )
    # 同步清理非法引用后的正文及自检警示，确保流式显示与落库一致。
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


# ---------- 问答主流程 ----------

async def _run(st: RunState, kb_ids: list[int] | None, skip_user_persist: bool) -> AsyncGenerator[dict, None]:
    session_id = st.session_id
    question = st.question

    # Q8 多轮上下文（取历史先于落用户消息，避免把当前问题算进历史；images 供附图标记）
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

    # ① Router 意图路由（带图时直接读图提取图中要点；带图问题一律 kb_qa：先检索知识库，再结合图片回答）
    r = await _judge_retry(
        RouterOut,
        prompts.get_prompt("router_sys", st.lang),
        prompts.router_user(question, history, len(st.image_data_urls), st.lang),
        st.usage,
        images=st.image_data_urls,
    )
    if r.intent not in VALID_INTENTS:
        r.intent = "kb_qa"
    # 代码层兜底强制：附图消息不走闲聊/数据查询旁路，统一主链检索 + 视觉生成
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

    # ---- 闲聊旁路：直接流式回答（不检索） ----
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

    # ---- 数据查询旁路：NL2SQL 直达 DBRetriever（跳过改写） ----
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
        if verdict != "pass":
            disclaimer = t("disclaimer.db_insufficient", st.locale)
        async for ev in _generate_and_finish(st, history, kb_ids, ctx_blocks, items, disclaimer, supp_db=True):
            yield ev
        return

    # ---- 知识问答 / 总结主链路 ----
    src_enabled = await enabled_sources()
    rerank_on = settings.rerank_enabled and _rerank_ready()
    st.rerank_on = rerank_on
    # provider 不可用时 rerank_on=False，候选深度保持默认（Important 1 修复）
    st.lane_top_k, st.fused_candidates = rerank_params(rerank_on)
    top_k = st.lane_top_k
    candidates = st.fused_candidates
    sub_queries: list[str] = []
    hyde_used = False
    vector_query = st.question_full

    if r.intent == "kb_qa":
        # ② Planner 查询规划（改写 / 拆解 / HyDE；带图时基于图中要点改写，检索才有语义）
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

    # kb 检索源集合（summarize 走轻量语义检索，只开向量路）
    kb_sources = [s for s in ("vector", "keyword") if src_enabled.get(s)]
    if r.intent == "summarize":
        kb_sources = ["vector"] if src_enabled.get("vector") else kb_sources[:1]

    # ③④⑤ 检索 → 融合 → 评估（partial 补检 / CRAG 纠正 ≤2 轮）
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
                # 熔断：本轮后续（CRAG 重查/反思回流）不再调用已失败的 provider
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

        # partial：补充检索一次（仅一次）
        if verdict == "partial" and not supplemented and kb_sources:
            supplemented = True
            st.correct_count += 1
            c_detail = t("sse.correct.supplement", st.locale)
            yield sse("correct", 5, c_detail, action="rewrite_retry", round=1)
            st.mark(5, "correct", c_detail, {"action": "rewrite_retry", "round": 1})
            vector_query = main_query
            continue

        # fail（或 partial 补检后仍不通过）→ CRAG 纠正
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

        # rewrite_retry：CRAG 改写查询重查
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
    """SSE 问答流入口：整体受 overall_timeout（120s）约束，异常推 error 事件

    image_urls：站内图片 URL（chat_images.save_images 产物），随消息落库并转 data URL 喂给视觉模型。
    locale：UI/请求语言（None → ContextVar 缺省 zh-CN）；只影响 SSE 文案与 API 错误，答案语言跟随提问。
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

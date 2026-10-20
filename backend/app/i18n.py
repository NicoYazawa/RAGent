"""后端国际化 — 语言协商 / 消息目录 / ContextVar 中间件（C 方案：Accept-Language）

SSE 决策链文本、API 错误消息、LLM 提示词的选择都经这里；
UI 静态文案在前端 vue-i18n，不经过本模块。
"""
import logging
from contextvars import ContextVar
from typing import Literal

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("agentic.i18n")

Locale = Literal["zh-CN", "en-US"]
SUPPORTED = ("zh-CN", "en-US")
DEFAULT_LOCALE: Locale = "zh-CN"

# key -> {"zh-CN": ..., "en-US": ...}；Task 9/10 注入 sse/api/prompt 文案
MESSAGES: dict[str, dict[str, str]] = {
    # —— ① Router 意图标签 ——
    "intent.chitchat": {"zh-CN": "闲聊（前置拦截，不触发检索）", "en-US": "Chitchat (intercepted, no retrieval)"},
    "intent.kb_qa": {"zh-CN": "知识问答", "en-US": "Knowledge-Base Q&A"},
    "intent.data_query": {"zh-CN": "数据查询（跳过改写，直达数据库检索）", "en-US": "Data Query (skip rewriting, straight to database retrieval)"},
    "intent.summarize": {"zh-CN": "总结（走生成侧，轻量检索）", "en-US": "Summarization (generation side, lightweight retrieval)"},
    # —— ② 路由事件 ——
    "sse.router.judging": {"zh-CN": "正在判断问题类型 → {intent}", "en-US": "Classifying intent → {intent}"},
    "sse.router.db_fallback": {"zh-CN": "业务数据库证据不足，转为知识问答并检索已上传文档", "en-US": "Business-database evidence is insufficient; switching to knowledge-base Q&A and retrieving uploaded documents"},
    "sse.router.image_note": {"zh-CN": "（附图问答，图中要点：{note}）", "en-US": "(Image-based Q&A, key points in the image: {note})"},
    "sse.router.no_note": {"zh-CN": "未提取到", "en-US": "not extracted"},
    # —— ③ 改写事件 ——
    "sse.rewrite.split": {"zh-CN": "拆解为 {n} 个子问题", "en-US": "Split into {n} sub-queries"},
    "sse.rewrite.main": {"zh-CN": "改写主查询（HyDE {hyde}）", "en-US": "Rewrote the main query (HyDE {hyde})"},
    "sse.rewrite.hyde_on": {"zh-CN": "已生成", "en-US": "generated"},
    "sse.rewrite.hyde_off": {"zh-CN": "未启用", "en-US": "not enabled"},
    "sse.rewrite.crag": {"zh-CN": "CRAG 改写：{reason}", "en-US": "CRAG rewrite: {reason}"},
    # —— ④ 检索事件（label/prefix/hits 组合） ——
    "sse.retrieve.vector": {"zh-CN": "向量语义检索", "en-US": "Vector retrieval"},
    "sse.retrieve.keyword": {"zh-CN": "关键词 BM25 检索", "en-US": "Keyword (BM25) retrieval"},
    "sse.retrieve.prefix.requery": {"zh-CN": "重查·", "en-US": "Re-query · "},
    "sse.retrieve.prefix.supplement": {"zh-CN": "补充·", "en-US": "Supplement · "},
    "sse.retrieve.prefix.reflow": {"zh-CN": "反思回流·", "en-US": "Reflect Backflow · "},
    "sse.retrieve.hits": {"zh-CN": "{prefix}{label}：命中 {n} 条", "en-US": "{prefix}{label}: {n} hits"},
    "sse.retrieve.reflow_targeted": {"zh-CN": "反思回流·定向补检", "en-US": "Reflect Backflow · targeted re-retrieval"},
    "sse.retrieve.reflow_keyword": {"zh-CN": "反思回流·关键词补检", "en-US": "Reflect Backflow · keyword re-retrieval"},
    "sse.retrieve.reflow_hits": {"zh-CN": "{label}：命中 {n} 条", "en-US": "{label}: {n} hits"},
    "sse.retrieve.reflow_nl2sql": {"zh-CN": "反思回流·NL2SQL 补查：{sql}（命中 {n} 行）", "en-US": "Reflect Backflow · NL2SQL re-query: {sql} ({n} rows)"},
    "sse.retrieve.nl2sql_direct": {"zh-CN": "NL2SQL 生成并执行：{sql}（命中 {n} 行）", "en-US": "NL2SQL generated and executed: {sql} ({n} rows)"},
    "sse.retrieve.lane_error": {"zh-CN": "{prefix}检索服务异常：{sources}", "en-US": "{prefix}Retrieval service error: {sources}"},
    "sse.retrieve.lane_src_fail": {"zh-CN": "{src} 路失败", "en-US": "{src} lane failed"},
    # —— ④b 精排事件 ——
    "sse.retrieve.rerank_ok": {"zh-CN": "{prefix}精排 {in_} → {out}（{model}，{ms}ms）", "en-US": "{prefix}Reranked {in_} → {out} ({model}, {ms}ms)"},
    "sse.retrieve.rerank_failed": {"zh-CN": "⚠️ {prefix}{err}", "en-US": "⚠️ {prefix}{err}"},
    "sse.retrieve.rerank_unavailable": {"zh-CN": "精排不可用（{err}），保留粗排序", "en-US": "Rerank unavailable ({err}), keeping coarse ranking"},
    "sse.retrieve.rerank_failed_msg": {"zh-CN": "精排失败（{err}），保留粗排序", "en-US": "Rerank failed ({err}), keeping coarse ranking"},
    "sse.retrieve.rerank_empty": {"zh-CN": "精排返回空结果，保留粗排序", "en-US": "Rerank returned no results, keeping coarse ranking"},
    # —— ⑤ 评分事件 ——
    "sse.grade.score": {"zh-CN": "相关度 {score} {icon}{suffix}", "en-US": "Relevance {score} {icon}{suffix}"},
    "sse.grade.icon.pass": {"zh-CN": "✓ 通过", "en-US": "✓ Pass"},
    "sse.grade.icon.partial": {"zh-CN": "⚠️ 部分相关", "en-US": "⚠️ Partially relevant"},
    "sse.grade.icon.fail": {"zh-CN": "✗ 不及格", "en-US": "✗ Fail"},
    "sse.grade.suffix.round": {"zh-CN": "（第 {n} 轮）", "en-US": " (round {n})"},
    "sse.grade.suffix.reflow": {"zh-CN": "（反思回流后）", "en-US": " (after reflect backflow)"},
    "sse.grade.no_hits": {"zh-CN": "所有启用数据源均无命中，建议改写查询重试（CRAG rewrite_retry）", "en-US": "No hits from any enabled source; try rewriting the query (CRAG rewrite_retry)"},
    "sse.grade.reason_none": {"zh-CN": "无", "en-US": "n/a"},
    # —— ⑥ 纠正事件 ——
    "sse.correct.supplement": {"zh-CN": "触发纠正：证据不完整 → 补充检索一次（第 1 轮）", "en-US": "Correction triggered: incomplete evidence → supplementary retrieval once (round 1)"},
    "sse.correct.exhausted": {"zh-CN": "纠正轮次耗尽 → 放弃检索，带声明直接生成（第 {n} 轮）", "en-US": "Correction rounds exhausted → giving up retrieval, generating with a disclaimer (round {n})"},
    "sse.correct.give_up": {"zh-CN": "触发纠正：{reason} → 放弃检索，带声明直接生成（第 {n} 轮）", "en-US": "Correction triggered: {reason} → giving up retrieval, generating with a disclaimer (round {n})"},
    "sse.correct.rewrite_retry": {"zh-CN": "触发纠正：{reason} → 改写查询重查（第 {n} 轮）", "en-US": "Correction triggered: {reason} → rewriting the query and re-retrieving (round {n})"},
    # —— ⑦ 反思事件 ——
    "sse.reflect.pass": {"zh-CN": "自检通过 ✓{suffix}", "en-US": "Self-check passed ✓{suffix}"},
    "sse.reflect.pass_suffix": {"zh-CN": "（第 {n} 次反思）", "en-US": " (reflection #{n})"},
    "sse.reflect.fail": {"zh-CN": "自检不达标 ✗ → {missing}，回流补充检索", "en-US": "Self-check failed ✗ → {missing}, triggering supplementary retrieval"},
    "sse.reflect.missing_default": {"zh-CN": "答案不完整", "en-US": "the answer is incomplete"},
    "sse.reflect.exhausted_note": {"zh-CN": "\n\n> ⚠️ 说明：本答案经过 Self-RAG 多轮自检仍未完全达标，请结合引用出处核实关键信息。", "en-US": "\n\n> ⚠️ Note: this answer still did not fully pass Self-RAG after multiple rounds; verify key facts against the citations."},
    # —— ⑧ 引用事件 ——
    "sse.citation.with": {"zh-CN": "引用 {n} 条出处", "en-US": "{n} citations attributed"},
    "sse.citation.without": {"zh-CN": "无知识库引用（推断生成）", "en-US": "No knowledge-base citations (inferred)"},
    "cite.db_doc_name": {"zh-CN": "业务数据库 sales 表（NL2SQL 只读）", "en-US": "Business database sales table (NL2SQL read-only)"},
    "cite.db_section": {"zh-CN": "查询结果集", "en-US": "Query result set"},
    # —— ⑨ 生成侧 ——
    "sse.generate.done": {"zh-CN": "答案生成完成（{n} 字）", "en-US": "Answer generation complete ({n} chars)"},
    "disclaimer.db_insufficient": {"zh-CN": "注意：业务数据库查询结果与问题相关度不足，请如实说明数据可能不完整。", "en-US": "Note: the business-database results may not be relevant enough; state honestly that the data may be incomplete."},
    "disclaimer.degraded": {"zh-CN": "⚠️ 检索服务异常：{parts}。本轮无检索结果可能是服务故障而非知识库缺失，请在回答开头用引用块声明「检索服务异常，以下内容为模型基于通用知识推断」，并建议用户检查 Elasticsearch / Embedding 服务状态后重新提问。不要标注引用序号。", "en-US": "⚠️ Retrieval service error: {parts}. Empty results this round may be a service failure rather than a knowledge gap. Start the answer with a blockquote declaring \"Retrieval service error — the following is inferred from general knowledge\" and suggest checking the Elasticsearch / Embedding services. Do not add citation markers."},
    "disclaimer.give_up_base": {"zh-CN": "注意：知识库检索评估未通过（CRAG give_up）。请在回答开头用引用块声明「知识库未覆盖」，说明以下内容为模型基于通用知识推断，建议用户上传相关文档后重新提问。不要标注引用序号。", "en-US": "Note: retrieval grading failed (CRAG give_up). Start the answer with a blockquote declaring \"Not covered by the knowledge base\", explain that the following is inferred from general knowledge, and suggest uploading relevant documents. Do not add citation markers."},
    # —— ⑩ API 错误消息 ——
    "api.session_not_found": {"zh-CN": "会话不存在", "en-US": "Session not found."},
    "api.doc_not_found": {"zh-CN": "文档不存在", "en-US": "Document not found."},
    "api.kb_not_found": {"zh-CN": "知识库不存在", "en-US": "Knowledge base not found."},
    "api.kb_busy": {"zh-CN": "知识库内有文档正在入库，请等待处理完成后再删除", "en-US": "Documents are being processed. Wait until ingestion finishes before deleting."},
    "api.log_not_found": {"zh-CN": "决策日志不存在", "en-US": "Decision log not found."},
    "api.image_not_found": {"zh-CN": "图片不存在", "en-US": "Image not found."},
    "api.unknown_source": {"zh-CN": "未知检索源：{source}", "en-US": "Unknown retrieval source: {source}"},
    "api.unknown_ds_type": {"zh-CN": "未知数据源类型：{source}", "en-US": "Unknown data source type: {source}"},
    "api.doc_not_ready": {"zh-CN": "文档尚未完成入库，暂无切片", "en-US": "The document has not finished ingestion, so no chunks are available yet."},
    "api.only_failed_retry": {"zh-CN": "仅失败文档可重试", "en-US": "Only failed documents can be retried."},
    "api.chunk_missing": {"zh-CN": "《{doc}》不存在切片 #{no}，可能文档已重新入库", "en-US": "\"{doc}\" has no chunk #{no}; the document may have been re-ingested."},
    "api.citation_doc_missing": {"zh-CN": "未找到文档《{doc}》：可能已被删除或未完成入库", "en-US": "Document \"{doc}\" not found: it may have been deleted or is still ingesting."},
    "api.citation_ambiguous": {"zh-CN": "存在多个同名文档《{doc}》，历史引用无法唯一定位，请重新提问获取新引用", "en-US": "Multiple documents named \"{doc}\" exist. This legacy citation is ambiguous; ask again to obtain a new citation."},
    "api.kb_name_dup": {"zh-CN": "知识库名称「{name}」已存在（name 唯一约束）", "en-US": "Knowledge base name \"{name}\" already exists (unique constraint)."},
    "api.kb_name_empty": {"zh-CN": "知识库名称不能为空", "en-US": "Knowledge base name cannot be empty."},
    "api.session_create_failed": {"zh-CN": "会话创建失败", "en-US": "Session creation failed."},
    "api.doc_delete_failed": {"zh-CN": "文档删除失败", "en-US": "Failed to delete the document."},
    # —— ⑩b 鉴权 ——
    # —— ⑪ 链路级错误 ——
    "error.no_answer_persisted": {"zh-CN": "（本次问答链路异常中断，未生成答案，详见决策日志）", "en-US": "(The Q&A chain was interrupted by an error; no answer was generated — see the decision log)"},
    "error.timeout": {"zh-CN": "单轮问答总耗时超过 {n}s 上限，链路中断", "en-US": "The Q&A round exceeded the {n}s overall limit and was interrupted."},
    "error.timeout_detail": {"zh-CN": "全链路超时（{n}s）：已按约束中断并清理会话状态", "en-US": "Overall timeout ({n}s): interrupted per constraint and session state cleaned up."},
    "error.chain_broken": {"zh-CN": "链路异常中断", "en-US": "The pipeline was interrupted by an error."},
    "error.internal": {"zh-CN": "服务内部异常", "en-US": "Internal service error."},
    "error.session_missing": {"zh-CN": "会话不存在", "en-US": "Session not found."},
}

_locale_ctx: ContextVar[str] = ContextVar("locale", default=DEFAULT_LOCALE)


def resolve_locale(accept_language: str | None) -> Locale:
    """解析 Accept-Language；不支持/缺失回落 zh-CN"""
    if not accept_language:
        return DEFAULT_LOCALE
    for part in accept_language.split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        if tag.startswith("zh"):
            return "zh-CN"
        if tag.startswith("en"):
            return "en-US"
    return DEFAULT_LOCALE


def current_locale() -> str:
    return _locale_ctx.get()


def set_locale(v: str) -> None:
    _locale_ctx.set(v if v in SUPPORTED else DEFAULT_LOCALE)


def t(key: str, locale: str | None = None, **params) -> str:
    """按语言取文案；缺 en 回落 zh；再缺返回 key 并告警"""
    loc = locale or current_locale()
    entry = MESSAGES.get(key)
    if entry is None:
        logger.warning("i18n 缺失 key：%s", key)
        return key
    text = entry.get(loc) or entry.get(DEFAULT_LOCALE)
    if text is None:
        logger.warning("i18n key %s 无任何语言文案", key)
        return key
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError, ValueError) as e:
            logger.warning("i18n 文案格式化失败 %s：%s", key, e)
    return text


class LocaleMiddleware(BaseHTTPMiddleware):
    """请求入口解析 Accept-Language → ContextVar（异步生成器内可见）"""

    async def dispatch(self, request: Request, call_next) -> Response:
        set_locale(resolve_locale(request.headers.get("accept-language")))
        return await call_next(request)

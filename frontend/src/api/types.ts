/* ============================================================
 * 类型定义
 * 第 5 章（接口/SSE 协议）与第 6 章（数据设计）
 * 字段命名保持与后端协议一致（snake_case）
 * ============================================================ */

/* ---------- 通用枚举 ---------- */

/** Q1 意图四分类 */
export type IntentType = 'chitchat' | 'kb_qa' | 'data_query' | 'summarize'

/** 三类检索源 */
export type RetrievalSource = 'vector' | 'keyword' | 'database'

/** 文档入库五态 */
export type DocStatus = 'parsing' | 'chunking' | 'embedding' | 'ready' | 'failed'

/* ---------- SSE 事件协议（5.3 节） ---------- */

interface SseBase {
  /** 决策点序号 */
  step: number
  /** 毫秒时间戳 */
  ts: number
  /** 人类可读摘要（直接用于侧栏渲染） */
  detail: string
}

export interface RouterEvent extends SseBase {
  type: 'router'
  intent: IntentType
  confidence: number
}

export interface RewriteEvent extends SseBase {
  type: 'rewrite'
  rewritten_query: string
  sub_queries: string[]
  hyde_used: boolean
}

export interface RetrieveEvent extends SseBase {
  type: 'retrieve'
  source?: RetrievalSource | 'rerank'
  hit_count?: number
  /** 检索路异常（ES/Embedding 故障）：与「知识库未覆盖」区分的降级标记 */
  degraded?: boolean
  errors?: Record<string, string>
  /** 精排失败时的降级说明（source=rerank 成功时不存在） */
  rerank_error?: string
  /** 精排信息（source=rerank 时）：模型 / 耗时 / 输入输出条数；失败时为 { error } */
  rerank?: { model: string; ms: number; in: number; out: number } | { error: string }
}

export interface GradeEvent extends SseBase {
  type: 'grade'
  score: number
  verdict: 'pass' | 'partial' | 'fail'
  reason: string
}

export interface CorrectEvent extends SseBase {
  type: 'correct'
  action: 'rewrite_retry' | 'give_up'
  round: number
}

export interface GenerateEvent extends SseBase {
  type: 'generate'
  /** token 增量 */
  delta: string
  /** 新生成轮次，清空被反思否决的旧正文 */
  replace?: boolean
}

export interface ReflectEvent extends SseBase {
  type: 'reflect'
  result: 'pass' | 'fail'
  round: number
  /** fail 时描述缺失信息 */
  missing_info?: string
}

export interface Citation {
  /** 答案中的原始 [n] 编号；历史消息可能没有 */
  ref_id?: number
  doc_id?: number
  kb_id?: number
  chunk_uid?: string
  doc_name: string
  section_path: string
  chunk_no: number
  /** db 来源（NL2SQL）：生成 SQL + 查询结果行，改走「数据查询证据」视图 */
  source_type?: 'db'
  sql?: string
  rows?: Record<string, string | number | null>[]
}

export interface CitationEvent extends SseBase {
  type: 'citation'
  citations: Citation[]
  /** 经过引用清理后的最终正文，与持久化内容一致 */
  answer?: string
}

export interface TokenUsage {
  prompt: number
  completion: number
}

export interface DoneEvent extends SseBase {
  type: 'done'
  message_id: number
  elapsed_ms: number
  token_usage: TokenUsage
}

export interface ErrorEvent extends SseBase {
  type: 'error'
  code: number
  message: string
}

export type SseEvent =
  | RouterEvent
  | RewriteEvent
  | RetrieveEvent
  | GradeEvent
  | CorrectEvent
  | GenerateEvent
  | ReflectEvent
  | CitationEvent
  | DoneEvent
  | ErrorEvent

export type SseEventType = SseEvent['type']

/** 决策步骤卡片 UI 态 */
export type StepVisual = 'pending' | 'done' | 'warn'

/* ---------- 实体（6.2 节数据表映射） ---------- */

export interface KnowledgeBase {
  id: number
  name: string
  description: string
  doc_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface KbDocument {
  id: number
  kb_id: number
  file_name: string
  file_type: 'md' | 'txt' | 'pdf' | 'docx'
  status: DocStatus
  chunk_count: number
  error_msg?: string
  created_at: string
  updated_at: string
}

/** 切片明细（6.2 节 kb_chunk 元数据 / ES kb_chunks 索引） */
export interface KbChunk {
  id: number
  doc_id: number
  /** 切片序号（1 起，与引用溯源 chunk_no 同源） */
  chunk_no: number
  /** 章节标题路径（切片时保留） */
  section_path: string
  /** 切片正文（chunk_size=500 字 / overlap=50 字） */
  content: string
  token_count: number
}

export interface ChatSession {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  /** 用户消息附带图片（data URL 或站内 URL，多模态问答） */
  images?: string[]
  decision_log_id?: number
  created_at: string
}

/** 决策链单步（与 SSE 事件同源同构，6.2 steps 结构） */
export interface DecisionStep {
  step: number
  type: SseEventType
  detail: string
  payload: Record<string, unknown>
  elapsed_ms: number
}

export interface DecisionLog {
  id: number
  session_id: number
  message_id: number
  question: string
  final_answer: string
  steps: DecisionStep[]
  total_rounds: number
  elapsed_ms: number
  created_at: string
}

export interface DatasourceItem {
  source_type: RetrievalSource
  enabled: boolean
  config: Record<string, string>
  updated_at: string
}

/* ---------- 检索测试 Playground ---------- */

/** 单路召回命中项 */
export interface RetrievalHit {
  title: string
  snippet: string
  /** 原始相关度分（向量 cosine / BM25 / 行匹配度，量纲随路不同） */
  score: number
  meta: {
    doc_name?: string
    section_path?: string
    chunk_no?: number
  }
}

/** 单路召回结果 */
export interface RetrievalLane {
  source: RetrievalSource
  latency_ms: number
  hits: RetrievalHit[]
}

/** RRF 融合后条目：rrf = Σ 1/(60 + rank)，from_lanes 标注命中的路 */
export interface FusedItem {
  key: string
  rrf: number
  from_lanes: RetrievalSource[]
  hit: RetrievalHit
}

/** Grader 模拟评分 */
export interface RetrievalGrade {
  score: number
  verdict: 'pass' | 'partial' | 'fail'
  reason: string
}

export interface RetrievalTestResult {
  lanes: RetrievalLane[]
  fused: FusedItem[]
  grade: RetrievalGrade
}

/* ---------- 分页与查询 ---------- */

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface DecisionLogQuery {
  session_id?: number
  start?: string
  end?: string
  page: number
  page_size: number
}

/** 问答 SSE 流处理回调 */
export interface SseHandlers {
  onEvent: (event: SseEvent) => void
  signal?: AbortSignal
}

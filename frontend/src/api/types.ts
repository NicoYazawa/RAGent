/* ============================================================
 * Type definitions
 * Chapter 5 (API/SSE protocol) and chapter 6 (data design)
 * Field names match the backend protocol (snake_case)
 * ============================================================ */

/* ---------- Shared enums ---------- */

/** Q1 intent, four classes */
export type IntentType = 'chitchat' | 'kb_qa' | 'data_query' | 'summarize'

/** Three retrieval sources */
export type RetrievalSource = 'vector' | 'keyword' | 'database'

/** Five document ingestion states */
export type DocStatus = 'parsing' | 'chunking' | 'embedding' | 'ready' | 'failed'

/* ---------- SSE event protocol (section 5.3) ---------- */

interface SseBase {
  /** Decision point ordinal */
  step: number
  /** Millisecond timestamp */
  ts: number
  /** Human-readable summary (rendered directly in the sidebar) */
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
  /** A retrieval-lane error (ES/Embedding failure): the degraded marker that separates it from "not covered" */
  degraded?: boolean
  errors?: Record<string, string>
  /** Degradation note when reranking fails (absent when source=rerank succeeds) */
  rerank_error?: string
  /** Rerank info (when source=rerank): model / time / in-out counts; { error } on failure */
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
  /** Token delta */
  delta: string
  /** A new generation round that clears the answer rejected by reflection */
  replace?: boolean
}

export interface ReflectEvent extends SseBase {
  type: 'reflect'
  result: 'pass' | 'fail'
  round: number
  /** Describes the missing information on fail */
  missing_info?: string
}

export interface Citation {
  /** The raw [n] markers in the answer; older messages may lack them */
  ref_id?: number
  doc_id?: number
  kb_id?: number
  chunk_uid?: string
  doc_name: string
  section_path: string
  chunk_no: number
  /** db source (NL2SQL): the generated SQL plus result rows, shown in the "data query evidence" view */
  source_type?: 'db'
  sql?: string
  rows?: Record<string, string | number | null>[]
}

export interface CitationEvent extends SseBase {
  type: 'citation'
  citations: Citation[]
  /** Final body after citation cleanup, identical to what is persisted */
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

/** UI state of a decision step card */
export type StepVisual = 'pending' | 'done' | 'warn'

/* ---------- Entities (section 6.2 table mapping) ---------- */

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

/** Chunk details (section 6.2 kb_chunk metadata / ES kb_chunks index) */
export interface KbChunk {
  id: number
  doc_id: number
  /** Chunk ordinal (1-based, same source as chunk_no in citations) */
  chunk_no: number
  /** Section heading path (preserved when chunking) */
  section_path: string
  /** Chunk body (chunk_size=500 chars / overlap=50 chars) */
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
  /** Images attached to a user message (data URL or in-app URL, multimodal Q&A) */
  images?: string[]
  decision_log_id?: number
  created_at: string
}

/** One decision-chain step (same source and shape as the SSE events, section 6.2 steps) */
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

/* ---------- Retrieval test playground ---------- */

/** A single-lane hit */
export interface RetrievalHit {
  title: string
  snippet: string
  /** Raw relevance score (vector cosine / BM25 / row match; the scale differs per lane) */
  score: number
  meta: {
    doc_name?: string
    section_path?: string
    chunk_no?: number
  }
}

/** Single-lane recall result */
export interface RetrievalLane {
  source: RetrievalSource
  latency_ms: number
  hits: RetrievalHit[]
}

/** A fused item: rrf = sum of 1/(60 + rank), from_lanes lists the lanes that hit */
export interface FusedItem {
  key: string
  rrf: number
  from_lanes: RetrievalSource[]
  hit: RetrievalHit
}

/** Grader scoring */
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

/* ---------- Pagination and queries ---------- */

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

/** Q&A SSE stream callbacks */
export interface SseHandlers {
  onEvent: (event: SseEvent) => void
  signal?: AbortSignal
}

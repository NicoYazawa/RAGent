import type {
  Citation,
  DecisionLog,
  DecisionLogQuery,
  DatasourceItem,
  FusedItem,
  KbChunk,
  KbDocument,
  KnowledgeBase,
  Page,
  RetrievalGrade,
  RetrievalLane,
  RetrievalSource,
} from './types'
import { useI18n } from 'vue-i18n'
import { apiJson, jsonInit } from './http'

/* ============================================================
 * Admin API
 * ============================================================ */

/** GET /api/admin/kb */
export async function listKbs(): Promise<KnowledgeBase[]> {
  return apiJson<KnowledgeBase[]>('/api/admin/kb')
}

/** POST /api/admin/kb */
export async function createKb(name: string, description: string): Promise<KnowledgeBase> {
  return apiJson<KnowledgeBase>('/api/admin/kb', jsonInit('POST', { name, description }))
}

export async function deleteKb(kbId: number): Promise<void> {
  await apiJson(`/api/admin/kb/${kbId}`, { method: 'DELETE' })
}

/** GET /api/admin/kb/{kb_id}/documents */
export async function listDocuments(kbId: number): Promise<KbDocument[]> {
  return apiJson<KbDocument[]>(`/api/admin/kb/${kbId}/documents`)
}

/** POST /api/admin/kb/{kb_id}/documents (multipart upload, 202 asynchronous ingestion) */
export async function uploadDocument(kbId: number, file: File): Promise<KbDocument> {
  const fd = new FormData()
  fd.append('file', file)
  return apiJson<KbDocument>(`/api/admin/kb/${kbId}/documents`, { method: 'POST', body: fd })
}

/** DELETE /api/admin/kb/{kb_id}/documents/{doc_id} (ES first, then MySQL) */
export async function deleteDocument(kbId: number, docId: number): Promise<void> {
  await apiJson(`/api/admin/kb/${kbId}/documents/${docId}`, { method: 'DELETE' })
}

/** GET /api/admin/kb/{kb_id}/documents/{doc_id}/chunks (chunk details, paginated) */
export async function listDocumentChunks(kbId: number, docId: number, page: number, pageSize = 8): Promise<Page<KbChunk>> {
  return apiJson<Page<KbChunk>>(`/api/admin/kb/${kbId}/documents/${docId}/chunks?page=${page}&page_size=${pageSize}`)
}

/** GET /api/admin/chunks/by-citation?doc_name=&chunk_no= (locate a single chunk for a citation) */
export async function getChunkByCitation(
  docName: string,
  chunkNo: number,
  locator: Pick<Citation, 'doc_id' | 'kb_id' | 'chunk_uid'> = {},
): Promise<{ doc: KbDocument; chunk: KbChunk }> {
  let query = `doc_name=${encodeURIComponent(docName)}&chunk_no=${chunkNo}`
  for (const key of ['doc_id', 'kb_id', 'chunk_uid'] as const) {
    if (locator[key] !== undefined) query += `&${key}=${encodeURIComponent(String(locator[key]))}`
  }
  return apiJson<{ doc: KbDocument; chunk: KbChunk }>(
    `/api/admin/chunks/by-citation?${query}`,
  )
}

/** POST /api/admin/kb/{kb_id}/documents/{doc_id}/retry */
export async function retryDocument(kbId: number, docId: number): Promise<KbDocument> {
  return apiJson<KbDocument>(`/api/admin/kb/${kbId}/documents/${docId}/retry`, { method: 'POST' })
}

/** GET /api/admin/datasources */
export async function getDatasources(): Promise<DatasourceItem[]> {
  return apiJson<DatasourceItem[]>('/api/admin/datasources')
}

/** PUT /api/admin/datasources */
export async function updateDatasources(items: DatasourceItem[]): Promise<{ updated: number }> {
  return apiJson<{ updated: number }>('/api/admin/datasources', jsonInit('PUT', { items }))
}

/** GET /api/admin/decision-logs (filters: session ID, time range, plus pagination) */
export async function queryDecisionLogs(query: DecisionLogQuery): Promise<Page<DecisionLog>> {
  const params = new URLSearchParams()
  if (query.session_id != null) params.set('session_id', String(query.session_id))
  if (query.start) params.set('start', query.start)
  if (query.end) params.set('end', query.end)
  params.set('page', String(query.page))
  params.set('page_size', String(query.page_size))
  return apiJson<Page<DecisionLog>>(`/api/admin/decision-logs?${params.toString()}`)
}

/** GET /api/admin/decision-logs/{log_id} */
export async function getDecisionLog(logId: number): Promise<DecisionLog> {
  return apiJson<DecisionLog>(`/api/admin/decision-logs/${logId}`)
}

/* ============================================================
 * Retrieval test playground — per-lane recall / application-level RRF / the real grader
 * Calls POST /api/admin/retrieval-test/{lane,fuse}
 * ============================================================ */

/** Single-lane recall (one call per lane, through the backend retrieval adapters) */
export async function testRetrieveLane(query: string, source: RetrievalSource, topK = 5, kbIds?: number[]): Promise<RetrievalLane> {
  return apiJson<RetrievalLane>(
    '/api/admin/retrieval-test/lane',
    jsonInit('POST', { query, source, top_k: topK, kb_ids: kbIds ?? null }),
  )
}

/** Application-level RRF fusion (k=60) plus grader scoring (LLM-as-judge) */
export async function fuseAndGrade(lanes: RetrievalLane[], query = ''): Promise<{ fused: FusedItem[]; grade: RetrievalGrade }> {
  return apiJson<{ fused: FusedItem[]; grade: RetrievalGrade }>(
    '/api/admin/retrieval-test/fuse',
    jsonInit('POST', { query, lanes }),
  )
}

/** Data-source type to display metadata (follows the language) */
export function sourceMeta(source: RetrievalSource): { label: string; short: string; desc: string; icon: string; color: string } {
  const { t } = useI18n({ useScope: 'global' })
  const icon: Record<RetrievalSource, string> = { vector: 'search', keyword: 'zap', database: 'db' }
  const color: Record<RetrievalSource, string> = { vector: 'text-src-vector', keyword: 'text-src-keyword', database: 'text-src-db' }
  return {
    label: t(`datasource.meta.${source}.label`),
    short: t(`datasource.meta.${source}.short`),
    desc: t(`datasource.meta.${source}.desc`),
    icon: icon[source],
    color: color[source],
  }
}

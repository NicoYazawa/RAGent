import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 管理端 API —— 知识库 / 数据源 / 决策日志 / 检索测试。
 * 关键契约：
 *   - 路径与后端路由一一对应（含分页与过滤参数）
 *   - 上传走 multipart（FormData），不设 Content-Type（交给浏览器带 boundary）
 *   - 引用溯源查询的 doc_name 需 URL 编码
 *   - sourceMeta 的文案随语言切换，icon/color 为固定映射
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('../http', async () => {
  const actual = await vi.importActual<typeof import('../http')>('../http')
  return { ...actual, apiJson: vi.fn(), jsonInit: actual.jsonInit }
})

import {
  createKb,
  deleteDocument,
  fuseAndGrade,
  getChunkByCitation,
  getDatasources,
  getDecisionLog,
  listDocumentChunks,
  listDocuments,
  listKbs,
  queryDecisionLogs,
  retryDocument,
  sourceMeta,
  testRetrieveLane,
  updateDatasources,
  uploadDocument,
} from '../admin'
import { apiJson } from '../http'

const mockApiJson = apiJson as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockApiJson.mockResolvedValue({})
})

describe('admin api · 知识库', () => {
  it('getChunkByCitation includes stable document and chunk identity', async () => {
    await getChunkByCitation('manual.v2', 3, { doc_id: 10, kb_id: 2, chunk_uid: 'a b' })
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/chunks/by-citation?doc_name=manual.v2&chunk_no=3&doc_id=10&kb_id=2&chunk_uid=a%20b')
  })
  it('listKbs 走 GET /api/admin/kb', async () => {
    await listKbs()
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/kb')
  })

  it('createKb 走 POST 并带 name/description', async () => {
    await createKb('制度库', '描述')
    const [path, init] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/kb')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ name: '制度库', description: '描述' })
  })

  it('listDocuments 带 kb id', async () => {
    await listDocuments(3)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/kb/3/documents')
  })

  it('uploadDocument 用 FormData 上传文件', async () => {
    const file = new File(['x'], 'a.md', { type: 'text/markdown' })
    await uploadDocument(3, file)
    const [path, init] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/kb/3/documents')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBe(file)
  })

  it('deleteDocument 走 DELETE 并带 kb/doc 两个 id', async () => {
    await deleteDocument(3, 7)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/kb/3/documents/7', { method: 'DELETE' })
  })

  it('listDocumentChunks 默认每页 8 条', async () => {
    await listDocumentChunks(3, 7, 2)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/kb/3/documents/7/chunks?page=2&page_size=8')
  })

  it('listDocumentChunks 支持自定义 page_size', async () => {
    await listDocumentChunks(3, 7, 1, 20)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/kb/3/documents/7/chunks?page=1&page_size=20')
  })

  it('retryDocument 走 POST retry', async () => {
    await retryDocument(3, 7)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/kb/3/documents/7/retry', { method: 'POST' })
  })

  it('getChunkByCitation 对 doc_name 做 URL 编码', async () => {
    await getChunkByCitation('考勤 制度.md', 12)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/chunks/by-citation?doc_name=%E8%80%83%E5%8B%A4%20%E5%88%B6%E5%BA%A6.md&chunk_no=12')
  })
})

describe('admin api · 数据源', () => {
  it('getDatasources 走 GET', async () => {
    await getDatasources()
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/datasources')
  })

  it('updateDatasources 走 PUT 并带 items', async () => {
    const items = [{ source_type: 'vector' as const, enabled: true, config: {}, updated_at: '' }]
    await updateDatasources(items)
    const [path, init] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/datasources')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body)).toEqual({ items })
  })
})

describe('admin api · 决策日志', () => {
  it('queryDecisionLogs 带全部过滤参数', async () => {
    await queryDecisionLogs({ session_id: 12, start: '2026-01-01', end: '2026-02-01', page: 2, page_size: 20 })
    const [path] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/decision-logs?session_id=12&start=2026-01-01&end=2026-02-01&page=2&page_size=20')
  })

  it('queryDecisionLogs 省略可选过滤参数', async () => {
    await queryDecisionLogs({ page: 1, page_size: 10 })
    const [path] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/decision-logs?page=1&page_size=10')
  })

  it('session_id 为 0 时也要带上（不按假值丢弃）', async () => {
    await queryDecisionLogs({ session_id: 0, page: 1, page_size: 10 })
    const [path] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/decision-logs?session_id=0&page=1&page_size=10')
  })

  it('getDecisionLog 带 log id', async () => {
    await getDecisionLog(5)
    expect(mockApiJson).toHaveBeenCalledWith('/api/admin/decision-logs/5')
  })
})

describe('admin api · 检索测试 Playground', () => {
  it('testRetrieveLane 默认 top_k=5 且 kb_ids 为 null', async () => {
    await testRetrieveLane('年假怎么算', 'vector')
    const [path, init] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/retrieval-test/lane')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ query: '年假怎么算', source: 'vector', top_k: 5, kb_ids: null })
  })

  it('testRetrieveLane 支持指定 top_k 与 kb_ids', async () => {
    await testRetrieveLane('q', 'keyword', 3, [1, 2])
    const [, init] = mockApiJson.mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({ query: 'q', source: 'keyword', top_k: 3, kb_ids: [1, 2] })
  })

  it('fuseAndGrade 走 POST fuse 并带 lanes', async () => {
    const lanes = [{ source: 'vector' as const, latency_ms: 5, hits: [] }]
    await fuseAndGrade(lanes, 'q')
    const [path, init] = mockApiJson.mock.calls[0]
    expect(path).toBe('/api/admin/retrieval-test/fuse')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ query: 'q', lanes })
  })

  it('fuseAndGrade 默认 query 为空串', async () => {
    await fuseAndGrade([])
    const [, init] = mockApiJson.mock.calls[0]
    expect(JSON.parse(init.body).query).toBe('')
  })
})

describe('sourceMeta（数据源展示元数据）', () => {
  it('vector 源的 icon/color 固定映射', () => {
    const meta = sourceMeta('vector')
    expect(meta.icon).toBe('search')
    expect(meta.color).toBe('text-src-vector')
  })

  it('keyword 源的 icon/color 固定映射', () => {
    const meta = sourceMeta('keyword')
    expect(meta.icon).toBe('zap')
    expect(meta.color).toBe('text-src-keyword')
  })

  it('database 源的 icon/color 固定映射', () => {
    const meta = sourceMeta('database')
    expect(meta.icon).toBe('db')
    expect(meta.color).toBe('text-src-db')
  })

  it('文案取自语言包（非 key 本身）', () => {
    const meta = sourceMeta('vector')
    expect(meta.label).not.toBe('datasource.meta.vector.label')
    expect(meta.label.length).toBeGreaterThan(0)
    expect(meta.short.length).toBeGreaterThan(0)
    expect(meta.desc.length).toBeGreaterThan(0)
  })
})


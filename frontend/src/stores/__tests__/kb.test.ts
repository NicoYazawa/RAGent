import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/admin', () => ({
  listKbs: vi.fn(),
  listDocuments: vi.fn(),
  createKb: vi.fn(),
  deleteKb: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  retryDocument: vi.fn(),
  getDatasources: vi.fn(),
  updateDatasources: vi.fn(),
  queryDecisionLogs: vi.fn(),
  getDecisionLog: vi.fn(),
}))

import * as adminApi from '@/api/admin'
import { useKbStore } from '../kb'

const mockAdmin = adminApi as unknown as Record<string, ReturnType<typeof vi.fn>>

const kb = (id: number) => ({ id, name: `库${id}`, doc_count: 0, chunk_count: 0 }) as any
const doc = (id: number, status: string) => ({ id, file_name: `d${id}.md`, status }) as any

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.useFakeTimers()
  // 清掉上一个用例遗留的轮询定时器（store 没有暴露 stopPolling）
  vi.clearAllTimers()
})

describe('kb store', () => {
  it('删除后忽略旧轮询返回的库和文档', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([])
    mockAdmin.deleteKb.mockResolvedValue(undefined)
    const s = useKbStore()
    await s.init()
    await Promise.resolve()
    let resolveKbs!: (value: any[]) => void
    let resolveDocs!: (value: any[]) => void
    mockAdmin.listKbs.mockReturnValueOnce(new Promise(r => { resolveKbs = r }))
    mockAdmin.listDocuments.mockReturnValueOnce(new Promise(r => { resolveDocs = r }))
    const pending = s.refresh()
    await s.removeKb(1)
    resolveKbs([kb(1)])
    resolveDocs([doc(1, 'ready')])
    await pending
    expect(s.kbs).toEqual([])
    expect(s.documents).toEqual([])
    expect(s.selectedKbId).toBeNull()
  })
  it('删除成功后选择剩余知识库，失败时保留数据', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1), kb(2)])
    mockAdmin.listDocuments.mockResolvedValue([])
    const s = useKbStore()
    await s.init()
    mockAdmin.deleteKb.mockRejectedValueOnce(new Error('busy'))
    await expect(s.removeKb(1)).rejects.toThrow('busy')
    expect(s.kbs).toHaveLength(2)
    expect(s.selectedKbId).toBe(1)
    mockAdmin.deleteKb.mockResolvedValue(undefined)
    await s.removeKb(1)
    expect(s.selectedKbId).toBe(2)
    expect(s.kbs.map(k => k.id)).toEqual([2])
    await s.removeKb(2)
    expect(s.selectedKbId).toBeNull()
    expect(s.documents).toEqual([])
  })
  it('init 加载知识库并自动选中第一个', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1), kb(2)])
    mockAdmin.listDocuments.mockResolvedValue([])
    const s = useKbStore()
    await s.init()
    expect(s.kbs).toHaveLength(2)
    expect(s.selectedKbId).toBe(1)
    expect(s.selectedKb?.name).toBe('库1')
    expect(s.loading).toBe(false)
  })

  it('init 在无知识库时保持未选中', async () => {
    mockAdmin.listKbs.mockResolvedValue([])
    const s = useKbStore()
    await s.init()
    expect(s.selectedKbId).toBeNull()
    expect(s.selectedKb).toBeNull()
  })

  it('processingCount 只统计入库中的文档', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([
      doc(1, 'parsing'),
      doc(2, 'chunking'),
      doc(3, 'embedding'),
      doc(4, 'ready'),
      doc(5, 'failed'),
    ])
    const s = useKbStore()
    await s.init()
    expect(s.processingCount).toBe(3)
    expect(s.failedCount).toBe(1)
  })

  it('refresh 在未选中知识库时清空文档列表且不发起无效请求', async () => {
    mockAdmin.listKbs.mockResolvedValue([])
    const s = useKbStore()
    await s.refresh()
    expect(s.documents).toEqual([])
    // 不得以空/0 的知识库 id 发起请求
    const calledWith = mockAdmin.listDocuments.mock.calls.map((c) => c[0])
    expect(calledWith).not.toContain(null)
    expect(calledWith).not.toContain(0)
  })

  it('文档加载失败时 refreshing 被复位', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockRejectedValue(new Error('boom'))
    const s = useKbStore()
    s.selectedKbId = 1
    await expect(s.refresh()).rejects.toThrow('boom')
    expect(s.documentsRefreshing).toBe(false)
  })

  it('createKb 创建后刷新并选中新库', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.createKb.mockResolvedValue(kb(9))
    const s = useKbStore()
    await s.init()
    await s.createKb('新库', '描述')
    expect(mockAdmin.createKb).toHaveBeenCalledWith('新库', '描述')
    expect(s.selectedKbId).toBe(9)
    expect(s.creating).toBe(false)
  })

  it('upload 未选知识库时直接返回错误', async () => {
    const s = useKbStore()
    const r = await s.upload([new File(['x'], 'a.md')])
    expect(r.ok).toBe(0)
    expect(r.errors).toHaveLength(1)
    expect(mockAdmin.uploadDocument).not.toHaveBeenCalled()
  })

  it('upload 逐个上传并汇总成功数与失败原因', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([])
    mockAdmin.uploadDocument
      .mockResolvedValueOnce({ id: 1 })
      .mockRejectedValueOnce(new Error('格式不支持'))
    const s = useKbStore()
    await s.init()

    const r = await s.upload([new File(['x'], 'a.md'), new File(['y'], 'b.exe')])
    expect(r.ok).toBe(1)
    expect(r.errors).toHaveLength(1)
    expect(r.errors[0]).toContain('b.exe')
    expect(r.errors[0]).toContain('格式不支持')
  })

  it('removeDoc 未选知识库时不做任何事', async () => {
    const s = useKbStore()
    await s.removeDoc(1)
    expect(mockAdmin.deleteDocument).not.toHaveBeenCalled()
  })

  it('removeDoc 删除后刷新列表', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([])
    const s = useKbStore()
    await s.init()
    await s.removeDoc(7)
    expect(mockAdmin.deleteDocument).toHaveBeenCalledWith(1, 7)
  })

  it('retryDoc 未选知识库时不做任何事', async () => {
    const s = useKbStore()
    await s.retryDoc(1)
    expect(mockAdmin.retryDocument).not.toHaveBeenCalled()
  })

  it('retryDoc 触发重试并刷新', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([])
    const s = useKbStore()
    await s.init()
    await s.retryDoc(7)
    expect(mockAdmin.retryDocument).toHaveBeenCalledWith(1, 7)
  })

  it('轮询只在存在入库中文档时刷新', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([doc(1, 'parsing')])
    const s = useKbStore()
    await s.init()
    const before = mockAdmin.listDocuments.mock.calls.length
    await vi.advanceTimersByTimeAsync(2500)
    expect(mockAdmin.listDocuments.mock.calls.length).toBeGreaterThan(before)
  })

  it('轮询在无入库中文档时保持静默', async () => {
    mockAdmin.listKbs.mockResolvedValue([kb(1)])
    mockAdmin.listDocuments.mockResolvedValue([doc(1, 'ready')])
    const s = useKbStore()
    await s.init()
    const before = mockAdmin.listDocuments.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(mockAdmin.listDocuments.mock.calls.length).toBe(before)
  })
})

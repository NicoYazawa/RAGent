import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { DatasourceItem, KbDocument, KnowledgeBase } from '@/api/types'

/**
 * 知识库管理页 / 检索测试 Playground：
 *   - KbManageView：库列表切换、文档状态统计、新建知识库（含名称校验与错误提示）、上传/重试/删除
 *   - PlaygroundView：按数据源开关裁剪召回 → RRF 融合 → Grader 评分，全链路状态
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>()
  return {
    ...actual,
    listKbs: vi.fn(),
    listDocuments: vi.fn(),
    createKb: vi.fn(),
    deleteDocument: vi.fn(),
    retryDocument: vi.fn(),
    uploadDocument: vi.fn(),
    listDocumentChunks: vi.fn(),
    getDatasources: vi.fn(),
    updateDatasources: vi.fn(),
    testRetrieveLane: vi.fn(),
    fuseAndGrade: vi.fn(),
  }
})

import KbManageView from '@/views/KbManageView.vue'
import PlaygroundView from '@/views/PlaygroundView.vue'
import {
  listKbs,
  listDocuments,
  createKb,
  deleteDocument,
  retryDocument,
  getDatasources,
  testRetrieveLane,
  fuseAndGrade,
} from '@/api/admin'

const mockListKbs = listKbs as unknown as ReturnType<typeof vi.fn>
const mockListDocs = listDocuments as unknown as ReturnType<typeof vi.fn>
const mockCreateKb = createKb as unknown as ReturnType<typeof vi.fn>
const mockDeleteDoc = deleteDocument as unknown as ReturnType<typeof vi.fn>
const mockRetryDoc = retryDocument as unknown as ReturnType<typeof vi.fn>
const mockGetDatasources = getDatasources as unknown as ReturnType<typeof vi.fn>
const mockLane = testRetrieveLane as unknown as ReturnType<typeof vi.fn>
const mockFuse = fuseAndGrade as unknown as ReturnType<typeof vi.fn>

const kb: KnowledgeBase = {
  id: 1,
  name: '制度库',
  description: '企业制度',
  doc_count: 2,
  chunk_count: 30,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const doc = (over: Partial<KbDocument> = {}): KbDocument => ({
  id: 7,
  kb_id: 1,
  file_name: '考勤制度.md',
  file_type: 'md',
  status: 'ready',
  chunk_count: 12,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

const ds = (source_type: DatasourceItem['source_type'], enabled: boolean): DatasourceItem => ({
  source_type,
  enabled,
  config: {},
  updated_at: '2026-01-01T00:00:00Z',
})

const mountOpts = { global: { stubs: { teleport: true } } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockListKbs.mockResolvedValue([kb])
  mockListDocs.mockResolvedValue([doc()])
  mockCreateKb.mockResolvedValue({ ...kb, id: 2, name: '新库' })
  mockDeleteDoc.mockResolvedValue(undefined)
  mockRetryDoc.mockResolvedValue(doc({ status: 'parsing' }))
  mockGetDatasources.mockResolvedValue([ds('vector', true), ds('keyword', true), ds('database', false)])
  mockLane.mockResolvedValue({
    source: 'vector',
    latency_ms: 12,
    hits: [{ title: '命中片段', snippet: '内容', score: 0.9, meta: { doc_name: 'a.md', chunk_no: 3 } }],
  })
  mockFuse.mockResolvedValue({
    fused: [{ key: 'a.md#3', rrf: 0.0325, from_lanes: ['vector', 'keyword'], hit: { title: '命中片段', snippet: '内容', score: 0.9, meta: { doc_name: 'a.md', chunk_no: 3 } } }],
    grade: { score: 8.5, verdict: 'pass', reason: '结果相关' },
  })
})

describe('KbManageView', () => {
  it('挂载时初始化知识库 store', async () => {
    mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    expect(mockListKbs).toHaveBeenCalled()
  })

  it('展示知识库列表并默认选中第一个', async () => {
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('制度库')
    expect(w.text()).toContain('企业制度')
  })

  it('展示文档列表与统计', async () => {
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('考勤制度.md')
    expect(w.text()).toContain('12')
  })

  it('统计入库中与失败文档数量', async () => {
    mockListDocs.mockResolvedValue([doc({ id: 1, status: 'parsing' }), doc({ id: 2, status: 'failed' })])
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('1 个入库中')
    expect(w.text()).toContain('1 个失败')
  })

  it('无文档时展示空态', async () => {
    mockListDocs.mockResolvedValue([])
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('暂无文档')
  })

  it('点击知识库切换选中项', async () => {
    mockListKbs.mockResolvedValue([kb, { ...kb, id: 2, name: '技术库' }])
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('技术库'))!.trigger('click')
    await vi.waitFor(() => {
      expect(mockListDocs).toHaveBeenLastCalledWith(2)
    })
  })

  it('新建知识库：名称为空时报错', async () => {
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('新建'))!.trigger('click')
    await w.vm.$nextTick()
    const createBtn = w.findAll('button').find((b) => b.text() === '创建')!
    await createBtn.trigger('click')
    await w.vm.$nextTick()
    expect(w.text()).toContain('请输入知识库名称')
    expect(mockCreateKb).not.toHaveBeenCalled()
  })

  it('新建知识库：成功关闭弹窗并刷新列表', async () => {
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('新建'))!.trigger('click')
    await w.vm.$nextTick()
    await w.findAll('input')[0].setValue('新库')
    await w.findAll('button').find((b) => b.text() === '创建')!.trigger('click')
    await vi.waitFor(() => {
      expect(mockCreateKb).toHaveBeenCalledWith('新库', expect.any(String))
    })
  })

  it('新建知识库失败时展示错误信息', async () => {
    mockCreateKb.mockRejectedValue(new Error('库名已存在'))
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('新建'))!.trigger('click')
    await w.vm.$nextTick()
    await w.findAll('input')[0].setValue('新库')
    await w.findAll('button').find((b) => b.text() === '创建')!.trigger('click')
    await vi.waitFor(() => {
      expect(w.text()).toContain('库名已存在')
    })
  })

  it('删除文档调用后端并刷新', async () => {
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('button[title="删除文档（先 ES 后 MySQL）"]').trigger('click')
    await vi.waitFor(() => {
      expect(mockDeleteDoc).toHaveBeenCalledWith(1, 7)
    })
  })

  it('失败文档可重试', async () => {
    mockListDocs.mockResolvedValue([doc({ status: 'failed', error_msg: '解析失败' })])
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('button[title="失败重试（从失败阶段续传）"]').trigger('click')
    await vi.waitFor(() => {
      expect(mockRetryDoc).toHaveBeenCalledWith(1, 7)
    })
  })

  it('点击切片数打开切片抽屉', async () => {
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('12'))!.trigger('click')
    await w.vm.$nextTick()
    expect(w.findComponent({ name: 'ChunkDrawer' }).props('open')).toBe(true)
  })

  it('未选知识库时上传按钮禁用', async () => {
    mockListKbs.mockResolvedValue([])
    const w = mount(KbManageView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    const uploadBtn = w.findAll('button').find((b) => b.text().includes('上传文档'))!
    expect(uploadBtn.attributes('disabled')).toBeDefined()
  })
})

describe('PlaygroundView', () => {
  it('挂载时读取数据源开关并只保留已启用的源', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(mockGetDatasources).toHaveBeenCalled()
    expect(w.text()).toContain('数据库')
  })

  it('空态展示当前召回配置与检索链路', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('向量')
    expect(w.text()).toContain('RRF')
  })

  it('运行前查询为空时按钮禁用', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    const runBtn = w.findAll('button').find((b) => b.text().includes('执行检索'))!
    expect(runBtn.attributes('disabled')).toBeDefined()
  })

  it('运行后各路召回并展示命中', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('input[type="text"]').setValue('年假怎么算')
    await w.findAll('button').find((b) => b.text().includes('执行检索'))!.trigger('click')
    await vi.waitFor(() => {
      expect(mockFuse).toHaveBeenCalled()
    })
    expect(mockLane).toHaveBeenCalledTimes(2) // 只对启用的 vector/keyword 召回
    expect(mockLane).toHaveBeenCalledWith('年假怎么算', 'vector', 5)
    expect(w.text()).toContain('命中片段')
  })

  it('融合结果展示 RRF 分与来源路', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('input[type="text"]').setValue('q')
    await w.findAll('button').find((b) => b.text().includes('执行检索'))!.trigger('click')
    await vi.waitFor(() => {
      expect(w.text()).toContain('0.0325')
    })
  })

  it('Grader 评分与结论展示', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('input[type="text"]').setValue('q')
    await w.findAll('button').find((b) => b.text().includes('执行检索'))!.trigger('click')
    await vi.waitFor(() => {
      expect(w.text()).toContain('8.5')
    })
    expect(w.text()).toContain('结果相关')
  })

  it('某一路失败时展示失败态且继续融合其他路', async () => {
    mockLane.mockImplementation(async (_q: string, s: string) => {
      if (s === 'keyword') throw new Error('关键词库不可用')
      return { source: 'vector', latency_ms: 5, hits: [] }
    })
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('input[type="text"]').setValue('q')
    await w.findAll('button').find((b) => b.text().includes('执行检索'))!.trigger('click')
    await vi.waitFor(() => {
      expect(w.text()).toContain('关键词库不可用')
    })
    expect(mockFuse).toHaveBeenCalledTimes(1)
    const lanesArg = mockFuse.mock.calls[0][0] as unknown[]
    expect(lanesArg).toHaveLength(1) // 只把成功的路送进融合
  })

  it('可以切换 top_k', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text() === 'k=8')!.trigger('click')
    await w.find('input[type="text"]').setValue('q')
    await w.findAll('button').find((b) => b.text().includes('执行检索'))!.trigger('click')
    await vi.waitFor(() => {
      expect(mockLane).toHaveBeenCalledWith('q', 'vector', 8)
    })
  })

  it('点击示例 chip 会填充并立即执行', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('混合检索'))!.trigger('click')
    await vi.waitFor(() => {
      expect(mockLane).toHaveBeenCalled()
    })
  })

  it('回车键触发运行', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('input[type="text"]').setValue('q')
    await w.find('input[type="text"]').trigger('keydown.enter')
    await vi.waitFor(() => {
      expect(mockLane).toHaveBeenCalled()
    })
  })

  it('关闭的数据源在工具栏提示', async () => {
    const w = mount(PlaygroundView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('已停用')
  })
})



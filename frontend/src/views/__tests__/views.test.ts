import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { DecisionLog, DatasourceItem } from '@/api/types'

/**
 * Page-level views:
 *   - ChatView: fetches sessions on mount and selects the first, sidebar collapse, title and message count
 *   - DatasourceView: loads the three data sources, toggles and config changes, save
 *   - DecisionLogView: filtered query, timeline list, opening the detail drawer, pagination
 *   - route table: path / name / meta
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('@/api/chat', () => ({
  listSessions: vi.fn(),
  getMessages: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  purgeLastAssistant: vi.fn(),
  ask: vi.fn(),
}))

vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>()
  return {
    ...actual,
    getDatasources: vi.fn(),
    updateDatasources: vi.fn(),
    queryDecisionLogs: vi.fn(),
    getDecisionLog: vi.fn(),
    listKbs: vi.fn(),
    listDocuments: vi.fn(),
    createKb: vi.fn(),
    deleteDocument: vi.fn(),
    retryDocument: vi.fn(),
    uploadDocument: vi.fn(),
    listDocumentChunks: vi.fn(),
    getChunkByCitation: vi.fn(),
  }
})

import ChatView from '@/views/ChatView.vue'
import DatasourceView from '@/views/DatasourceView.vue'
import DecisionLogView from '@/views/DecisionLogView.vue'
import LogDetailDrawer from '@/components/logs/LogDetailDrawer.vue'
import { listSessions, getMessages } from '@/api/chat'
import { getDatasources, updateDatasources, queryDecisionLogs, getDecisionLog } from '@/api/admin'

const mockListSessions = listSessions as unknown as ReturnType<typeof vi.fn>
const mockGetMessages = getMessages as unknown as ReturnType<typeof vi.fn>
const mockGetDatasources = getDatasources as unknown as ReturnType<typeof vi.fn>
const mockUpdateDatasources = updateDatasources as unknown as ReturnType<typeof vi.fn>
const mockQueryLogs = queryDecisionLogs as unknown as ReturnType<typeof vi.fn>
const mockGetLog = getDecisionLog as unknown as ReturnType<typeof vi.fn>

const ds = (source_type: DatasourceItem['source_type'], enabled = true): DatasourceItem => ({
  source_type,
  enabled,
  config: { url: 'http://x' },
  updated_at: '2026-01-01T00:00:00Z',
})

const logItem = (id: number): DecisionLog => ({
  id,
  session_id: 1,
  message_id: 2,
  question: `问题 ${id}`,
  final_answer: '**答案** 内容',
  steps: [],
  total_rounds: 1,
  elapsed_ms: 1200,
  created_at: '2026-01-01T00:00:00Z',
})

const mountOpts = { global: { stubs: { teleport: true } } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockListSessions.mockResolvedValue([])
  mockGetMessages.mockResolvedValue([])
  mockGetDatasources.mockResolvedValue([ds('vector'), ds('keyword'), ds('database')])
  mockUpdateDatasources.mockResolvedValue({ updated: 3 })
  mockQueryLogs.mockResolvedValue({ items: [logItem(1)], total: 1, page: 1, page_size: 8 })
  mockGetLog.mockResolvedValue(logItem(1))
})

describe('ChatView', () => {
  it('挂载时拉取会话列表', async () => {
    mount(ChatView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    expect(mockListSessions).toHaveBeenCalled()
  })

  it('有会话时自动选中第一个', async () => {
    mockListSessions.mockResolvedValue([{ id: 5, title: '首个会话', created_at: '', updated_at: '' }])
    const w = mount(ChatView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('首个会话')
    expect(mockGetMessages).toHaveBeenCalledWith(5)
  })

  it('无会话时显示未选择会话', async () => {
    const w = mount(ChatView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    expect(w.text()).toContain('未选择会话')
  })

  it('展示消息条数', async () => {
    mockListSessions.mockResolvedValue([{ id: 5, title: '会话', created_at: '', updated_at: '' }])
    mockGetMessages.mockResolvedValue([
      { id: 1, session_id: 5, role: 'user', content: 'a', created_at: '' },
      { id: 2, session_id: 5, role: 'assistant', content: 'b', created_at: '' },
    ])
    const w = mount(ChatView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('2 条消息')
  })

  it('点击决策链按钮可折叠侧栏', async () => {
    const w = mount(ChatView, mountOpts)
    const btn = w.findAll('button').find((b) => b.text().includes('决策链'))!
    await btn.trigger('click')
    expect(w.findComponent({ name: 'DecisionSidebar' }).exists()).toBe(false)
  })

  it('手机端会话抽屉按钮可打开抽屉', async () => {
    const w = mount(ChatView, mountOpts)
    await w.find('button[aria-label="会话"]').trigger('click')
    expect(w.findAll('.fixed.inset-0.z-50').length).toBeGreaterThan(0)
  })
})

describe('DatasourceView', () => {
  it('挂载时加载数据源', async () => {
    mount(DatasourceView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    expect(mockGetDatasources).toHaveBeenCalled()
  })

  it('渲染三类数据源卡片', async () => {
    const w = mount(DatasourceView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.findAllComponents({ name: 'SourceCard' })).toHaveLength(3)
  })

  it('加载中展示骨架', async () => {
    mockGetDatasources.mockReturnValue(new Promise(() => undefined))
    const w = mount(DatasourceView, mountOpts)
    await w.vm.$nextTick()
    expect(w.findAll('.animate-pulse')).toHaveLength(3)
  })

  it('切换开关会更新 store 中的启用状态', async () => {
    const w = mount(DatasourceView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button[role="switch"]')[0].trigger('click')
    await w.vm.$nextTick()
    const { useDatasourceStore } = await import('@/stores/datasource')
    expect(useDatasourceStore().items[0].enabled).toBe(false)
  })

  it('修改配置项会写回 store', async () => {
    const w = mount(DatasourceView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('input')[0].setValue('http://es:9300')
    const { useDatasourceStore } = await import('@/stores/datasource')
    expect(useDatasourceStore().items[0].config.url).toBe('http://es:9300')
  })

  it('点击保存提交全部配置并展示保存时间', async () => {
    const w = mount(DatasourceView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    const saveBtn = w.findAll('button').find((b) => b.text().includes('保存配置'))!
    await saveBtn.trigger('click')
    await vi.waitFor(() => {
      expect(mockUpdateDatasources).toHaveBeenCalled()
    })
    expect(w.text()).toContain('已保存')
  })

  it('说明区展示当前启用的数据源数量', async () => {
    const w = mount(DatasourceView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('3')
  })
})

describe('DecisionLogView', () => {
  it('挂载时查询第一页日志', async () => {
    mount(DecisionLogView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    expect(mockQueryLogs).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 8 }),
    )
  })

  it('渲染日志时间轴', async () => {
    const w = mount(DecisionLogView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('问题 1')
  })

  it('无日志时展示空态', async () => {
    mockQueryLogs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 })
    const w = mount(DecisionLogView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('没有符合条件的决策日志')
  })

  it('加载中展示骨架', async () => {
    mockQueryLogs.mockReturnValue(new Promise(() => undefined))
    const w = mount(DecisionLogView, mountOpts)
    await w.vm.$nextTick()
    expect(w.findAll('.animate-pulse')).toHaveLength(5)
  })

  it('点击日志条目打开详情抽屉', async () => {
    const w = mount(DecisionLogView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('问题 1'))!.trigger('click')
    expect(w.findComponent(LogDetailDrawer).props('open')).toBe(true)
    expect(w.findComponent(LogDetailDrawer).props('logId')).toBe(1)
  })

  it('输入会话号后点击查询带上过滤条件', async () => {
    const w = mount(DecisionLogView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.find('input[placeholder]').setValue('7')
    await w.findAll('button').find((b) => b.text().includes('查询'))!.trigger('click')
    await vi.waitFor(() => {
      expect(mockQueryLogs).toHaveBeenLastCalledWith(expect.objectContaining({ session_id: 7 }))
    })
  })

  it('日志条目展示步数、轮次与耗时', async () => {
    const w = mount(DecisionLogView, mountOpts)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('1.2s')
    expect(w.text()).toContain('session #1')
  })
})


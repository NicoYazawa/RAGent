import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { DecisionLog, DecisionStep } from '@/api/types'

/**
 * 决策日志回放：
 *   - LogDetailDrawer：打开拉详情、Tab 切换（回放 / 最终答案）、元信息
 *   - StepPlayer：上一步 / 播放暂停 / 下一步 / 重置 / 倍速；steps → 决策卡（含回流轮次与告警态）
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('@/api/admin', () => ({
  getDecisionLog: vi.fn(),
  queryDecisionLogs: vi.fn(),
  listKbs: vi.fn(),
  listDocuments: vi.fn(),
  createKb: vi.fn(),
  deleteDocument: vi.fn(),
  retryDocument: vi.fn(),
  uploadDocument: vi.fn(),
  getDatasources: vi.fn(),
  updateDatasources: vi.fn(),
  listDocumentChunks: vi.fn(),
  getChunkByCitation: vi.fn(),
}))

import LogDetailDrawer from '../LogDetailDrawer.vue'
import StepPlayer from '../StepPlayer.vue'
import { getDecisionLog } from '@/api/admin'

const mockGetLog = getDecisionLog as unknown as ReturnType<typeof vi.fn>

const step = (over: Partial<DecisionStep> = {}): DecisionStep => ({
  step: 1,
  type: 'router',
  detail: '路由',
  payload: {},
  elapsed_ms: 10,
  ...over,
})

const log: DecisionLog = {
  id: 8,
  session_id: 3,
  message_id: 9,
  question: '年假几天',
  final_answer: '**答案**：5 天',
  steps: [step(), step({ step: 3, type: 'retrieve', detail: '检索到 3 条' })],
  total_rounds: 1,
  elapsed_ms: 1200,
  created_at: '2026-01-01T00:00:00Z',
}

const mountOpts = { global: { stubs: { teleport: true } } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockGetLog.mockResolvedValue(log)
})

describe('LogDetailDrawer', () => {
  it('打开时按 id 拉取详情', async () => {
    mount(LogDetailDrawer, { props: { open: true, logId: 8 }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    expect(mockGetLog).toHaveBeenCalledWith(8)
  })

  it('未打开或无 id 时不拉取', () => {
    mount(LogDetailDrawer, { props: { open: false, logId: 8 }, ...mountOpts })
    mount(LogDetailDrawer, { props: { open: true, logId: null }, ...mountOpts })
    expect(mockGetLog).not.toHaveBeenCalled()
  })

  it('加载中展示骨架', () => {
    mockGetLog.mockReturnValue(new Promise(() => undefined))
    const w = mount(LogDetailDrawer, { props: { open: true, logId: 8 }, ...mountOpts })
    expect(w.findAll('.animate-pulse')).toHaveLength(5)
  })

  it('展示问题、会话/消息号、步数与耗时', async () => {
    const w = mount(LogDetailDrawer, { props: { open: true, logId: 8 }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('年假几天')
    expect(w.text()).toContain('session #3')
    expect(w.text()).toContain('msg #9')
    expect(w.text()).toContain('1.2s')
  })

  it('默认展示回放 Tab', async () => {
    const w = mount(LogDetailDrawer, { props: { open: true, logId: 8 }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.findComponent(StepPlayer).exists()).toBe(true)
  })

  it('切到答案 Tab 展示最终答案 Markdown', async () => {
    const w = mount(LogDetailDrawer, { props: { open: true, logId: 8 }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('最终答案'))!.trigger('click')
    expect(w.findComponent(StepPlayer).exists()).toBe(false)
    expect(w.html()).toContain('<strong')
  })
})

describe('StepPlayer', () => {
  const steps = [
    step({ step: 1, type: 'router', detail: '路由' }),
    step({ step: 4, type: 'grade', detail: '评估', payload: { verdict: 'partial' } }),
    step({ step: 5, type: 'correct', detail: '纠正', payload: { round: 1 } }),
  ]

  it('未开始时展示回放提示', () => {
    const w = mount(StepPlayer, { props: { steps } })
    expect(w.text()).toContain('点击播放')
  })

  it('点击下一步逐步展示卡片', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    await w.find('button[aria-label="下一步"]').trigger('click')
    expect(w.text()).toContain('路由')
    expect(w.text()).not.toContain('纠正')
  })

  it('第一步时上一步按钮禁用', () => {
    const w = mount(StepPlayer, { props: { steps } })
    expect(w.find('button[aria-label="上一步"]').attributes('disabled')).toBeDefined()
  })

  it('走到末尾时下一步按钮禁用', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    const next = w.find('button[aria-label="下一步"]')
    await next.trigger('click')
    await next.trigger('click')
    await next.trigger('click')
    expect(w.find('button[aria-label="下一步"]').attributes('disabled')).toBeDefined()
  })

  it('上一步可回退', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    const next = w.find('button[aria-label="下一步"]')
    await next.trigger('click')
    await next.trigger('click')
    await w.find('button[aria-label="上一步"]').trigger('click')
    expect(w.text()).toContain('路由')
    expect(w.text()).not.toContain('评估')
  })

  it('重置回到起点', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    await w.find('button[aria-label="下一步"]').trigger('click')
    await w.find('button[title="重置回放"]').trigger('click')
    expect(w.text()).toContain('点击播放')
  })

  it('倍速按钮循环切换 1x/2x/4x', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    const speed = w.find('button[title="回放速度"]')
    expect(speed.text()).toBe('1x')
    await speed.trigger('click')
    expect(speed.text()).toBe('2x')
    await speed.trigger('click')
    expect(speed.text()).toBe('4x')
    await speed.trigger('click')
    expect(speed.text()).toBe('1x')
  })

  it('播放后按间隔推进步骤，到末尾自动暂停', async () => {
    vi.useFakeTimers()
    try {
      const w = mount(StepPlayer, { props: { steps } })
      await w.find('button[aria-label="播放"]').trigger('click')
      await vi.advanceTimersByTimeAsync(1000)
      expect(w.text()).toContain('路由')
      await vi.advanceTimersByTimeAsync(1000)
      expect(w.text()).toContain('评估')
      await vi.advanceTimersByTimeAsync(1000)
      expect(w.text()).toContain('纠正')
      await vi.advanceTimersByTimeAsync(1000)
      // 走完后自动暂停（按钮回到「播放」）
      expect(w.find('button[aria-label="播放"]').exists()).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('播放中点击暂停按钮停止推进', async () => {
    vi.useFakeTimers()
    try {
      const w = mount(StepPlayer, { props: { steps } })
      await w.find('button[aria-label="播放"]').trigger('click')
      await vi.advanceTimersByTimeAsync(1000)
      await w.find('button[aria-label="暂停"]').trigger('click')
      await vi.advanceTimersByTimeAsync(3000)
      expect(w.text()).not.toContain('纠正')
    } finally {
      vi.useRealTimers()
    }
  })

  it('grade 非 pass 的步骤显示为告警态', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    const next = w.find('button[aria-label="下一步"]')
    await next.trigger('click')
    await next.trigger('click')
    expect(w.html()).toContain('text-warn')
  })

  it('回流轮次在 correct 步骤上体现', async () => {
    const w = mount(StepPlayer, { props: { steps } })
    const next = w.find('button[aria-label="下一步"]')
    await next.trigger('click')
    await next.trigger('click')
    await next.trigger('click')
    expect(w.text()).toContain('R1')
  })
})


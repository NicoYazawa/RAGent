import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { ChatSession } from '@/api/types'
import type { DecisionCard } from '@/stores/chat'

/**
 * 决策步骤卡 / 会话列表 —— 展示层契约：
 *   - 卡片按 step 选标题、按状态切样式、回流轮次缩进、仅在有真实时间戳时显示时钟
 *   - 不同事件类型展示对应关键指标（置信度 / 命中数 / 评分 / 纠正动作 / 反思结果 / 引用数）
 *   - 会话列表：加载骨架 / 空态 / 当前项高亮 / 新建 / 切换 / 删除
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

import DecisionStepCard from '../DecisionStepCard.vue'
import SessionList from '../SessionList.vue'
import { useChatStore } from '@/stores/chat'

const card = (over: Partial<DecisionCard> = {}): DecisionCard => ({
  uid: 1,
  step: 1,
  type: 'router',
  status: 'done',
  detail: '识别为知识库问答',
  payload: {},
  ts: 0,
  round: 0,
  elapsedMs: 0,
  ...over,
})

const session = (id: number, updatedAt = new Date().toISOString()): ChatSession => ({
  id,
  title: `会话${id}`,
  created_at: updatedAt,
  updated_at: updatedAt,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('DecisionStepCard', () => {
  it('step>0 时用管线环节标题', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ step: 1 }) } })
    expect(w.text()).toContain('意图路由')
  })

  it('step=0 时用「流程」标题并显示 × 序号', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ step: 0, type: 'done' }) } })
    expect(w.text()).toContain('流程')
    expect(w.text()).toContain('[×]')
  })

  it('pending 状态显示转圈并隐藏耗时', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ status: 'pending', elapsedMs: 50 }) } })
    expect(w.find('.animate-spin').exists()).toBe(true)
    expect(w.text()).not.toContain('50ms')
  })

  it('warn 状态使用警告色', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ status: 'warn' }) } })
    expect(w.html()).toContain('text-warn')
  })

  it('回流轮次大于 0 时缩进并显示 R 标记', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ round: 2 }) } })
    expect(w.html()).toContain('ml-5')
    expect(w.text()).toContain('R2')
  })

  it('轮次为 0 时不缩进', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ round: 0 }) } })
    expect(w.html()).not.toContain('ml-5')
  })

  it('有耗时且非 pending 时展示耗时', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ elapsedMs: 120 }) } })
    expect(w.text()).toContain('120ms')
  })

  it('ts 为真实时间戳时显示时钟，回放卡（ts=0）不显示', () => {
    const withClock = mount(DecisionStepCard, { props: { card: card({ ts: Date.now() }) } })
    expect(withClock.text()).toMatch(/\d{2}:\d{2}:\d{2}/)
    const withoutClock = mount(DecisionStepCard, { props: { card: card({ ts: 0 }) } })
    expect(withoutClock.text()).not.toMatch(/\d{2}:\d{2}:\d{2}/)
  })

  it('router 卡片展示意图与置信度', () => {
    const w = mount(DecisionStepCard, {
      props: { card: card({ type: 'router', payload: { intent: 'kb_qa', confidence: 0.87 } }) },
    })
    expect(w.text()).toContain('kb_qa')
    expect(w.text()).toContain('87%')
  })

  it('retrieve 卡片展示来源与命中数', () => {
    const w = mount(DecisionStepCard, {
      props: { card: card({ type: 'retrieve', payload: { source: 'vector', hit_count: 5 } }) },
    })
    expect(w.text()).toContain('向量')
    expect(w.text()).toContain('命中 5 条')
  })

  it('retrieve 无来源时不展示来源标签', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ type: 'retrieve', payload: { hit_count: 5 } }) } })
    expect(w.text()).not.toContain('命中 5 条')
  })

  it('grade 卡片展示评分', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ type: 'grade', payload: { score: 0.75 } }) } })
    expect(w.text()).toContain('0.8')
  })

  it('correct 卡片展示纠正动作', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ type: 'correct', payload: { action: 'rewrite_retry' } }) } })
    expect(w.text()).toContain('rewrite_retry')
  })

  it('reflect 卡片展示反思结果', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ type: 'reflect', payload: { result: 'pass' } }) } })
    expect(w.text()).toContain('pass')
  })

  it('citation 卡片展示引用条数', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ type: 'citation', payload: { citations: [{}, {}] } }) } })
    expect(w.text()).toContain('2 条引用')
  })

  it('error 卡片不展示关键指标区', () => {
    const w = mount(DecisionStepCard, { props: { card: card({ type: 'error', status: 'warn' }) } })
    expect(w.text()).not.toContain('置信度')
  })
})

describe('SessionList', () => {
  it('加载中展示骨架屏', () => {
    const store = useChatStore()
    store.sessionsLoading = true
    const w = mount(SessionList)
    expect(w.findAll('.animate-pulse')).toHaveLength(4)
  })

  it('无会话时展示空态与「创建第一个会话」', () => {
    const w = mount(SessionList)
    expect(w.text()).toContain('暂无会话')
    expect(w.text()).toContain('创建第一个会话')
  })

  it('渲染会话列表并高亮当前会话', async () => {
    const store = useChatStore()
    store.sessions = [session(1), session(2)]
    store.currentSessionId = 2
    const w = mount(SessionList)
    await w.vm.$nextTick()
    expect(w.text()).toContain('会话1')
    expect(w.text()).toContain('会话2')
    const active = w.findAll('button').filter((b) => b.classes().includes('bg-raise'))
    expect(active).toHaveLength(1)
    expect(active[0].text()).toContain('会话2')
  })

  it('底部展示会话数量', async () => {
    const store = useChatStore()
    store.sessions = [session(1), session(2)]
    const w = mount(SessionList)
    await w.vm.$nextTick()
    expect(w.text()).toContain('2 个会话')
  })

  it('点击会话触发切换', async () => {
    const store = useChatStore()
    store.sessions = [session(1)]
    const spy = vi.spyOn(store, 'selectSession').mockResolvedValue(undefined)
    const w = mount(SessionList)
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text().includes('会话1'))!.trigger('click')
    expect(spy).toHaveBeenCalledWith(1)
  })

  it('点击删除图标触发删除（不触发切换）', async () => {
    const store = useChatStore()
    store.sessions = [session(1)]
    const remove = vi.spyOn(store, 'removeSession').mockResolvedValue(undefined)
    const select = vi.spyOn(store, 'selectSession').mockResolvedValue(undefined)
    const w = mount(SessionList)
    await w.vm.$nextTick()
    await w.find('[aria-label="删除会话"]').trigger('click')
    expect(remove).toHaveBeenCalledWith(1)
    expect(select).not.toHaveBeenCalled()
  })

  it('点击新建按钮创建会话', async () => {
    const store = useChatStore()
    const spy = vi.spyOn(store, 'newSession').mockResolvedValue(undefined)
    const w = mount(SessionList)
    await w.findAll('button').find((b) => b.text().includes('新建'))!.trigger('click')
    expect(spy).toHaveBeenCalled()
  })

  it('空态里的「创建第一个会话」也能创建', async () => {
    const store = useChatStore()
    const spy = vi.spyOn(store, 'newSession').mockResolvedValue(undefined)
    const w = mount(SessionList)
    await w.findAll('button').find((b) => b.text().includes('创建第一个会话'))!.trigger('click')
    expect(spy).toHaveBeenCalled()
  })

  it('今天的会话显示时间', async () => {
    const store = useChatStore()
    store.sessions = [session(1, new Date().toISOString())]
    const w = mount(SessionList)
    await w.vm.$nextTick()
    expect(w.text()).toMatch(/\d{2}:\d{2}/)
  })

  it('昨天的会话显示「昨天」', async () => {
    const store = useChatStore()
    const yesterday = new Date(Date.now() - 86400000).toISOString()
    store.sessions = [session(1, yesterday)]
    const w = mount(SessionList)
    await w.vm.$nextTick()
    expect(w.text()).toContain('昨天')
  })

  it('更早的会话显示日期', async () => {
    const store = useChatStore()
    const old = new Date(Date.now() - 5 * 86400000).toISOString()
    store.sessions = [session(1, old)]
    const w = mount(SessionList)
    await w.vm.$nextTick()
    expect(w.text()).toMatch(/\d+\/\d+/)
  })
})


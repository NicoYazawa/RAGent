import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { ChatMessage, DatasourceItem, KbDocument } from '@/api/types'
import type { DecisionCard } from '@/stores/chat'

/**
 * Mid-level presentational components — interaction contracts:
 *   - StatusBadge: five states with their copy/style and a progress dot while ingesting
 *   - DocumentRow: chunks when ready, retry when failed, delete in any state
 *   - ScoreRing: score to colour tier and arc length (normalized 0-10 and clamped)
 *   - MessageActions: copy / open the decision chain / regenerate
 *   - StepTimingBar: aggregates time per stage, turns warn-coloured, legend shows the first 5
 *   - SourceCard: emits toggle and config-change events
 *   - SideRail / AppLayout: nav items, active-page highlight, theme and language switching
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/chat' }),
  RouterLink: { name: 'RouterLink', props: ['to'], template: '<a :href="to"><slot /></a>' },
  RouterView: { name: 'RouterView', template: '<div class="router-view" />' },
}))

vi.mock('@/utils/decisionExport', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/decisionExport')>()
  return { ...actual, copyText: vi.fn() }
})

import StatusBadge from '@/components/kb/StatusBadge.vue'
import DocumentRow from '@/components/kb/DocumentRow.vue'
import ScoreRing from '@/components/chat/ScoreRing.vue'
import MessageActions from '@/components/chat/MessageActions.vue'
import StepTimingBar from '@/components/chat/StepTimingBar.vue'
import SourceCard from '@/components/admin/SourceCard.vue'
import SideRail from '@/components/layout/SideRail.vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import BaseTooltip from '@/components/ui/BaseTooltip.vue'
import { copyText } from '@/utils/decisionExport'
import { useThemeStore } from '@/stores/theme'
import { useLocaleStore } from '@/stores/locale'

const mockCopyText = copyText as unknown as ReturnType<typeof vi.fn>

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

const card = (over: Partial<DecisionCard> = {}): DecisionCard => ({
  uid: 1,
  step: 1,
  type: 'router',
  status: 'done',
  detail: '',
  payload: {},
  ts: 0,
  round: 0,
  elapsedMs: 100,
  ...over,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockCopyText.mockResolvedValue(true)
})

describe('StatusBadge', () => {
  it('ready 状态显示完成文案与成功色', () => {
    const w = mount(StatusBadge, { props: { status: 'ready' } })
    expect(w.text()).toContain('就绪')
    expect(w.html()).toContain('text-ok')
  })

  it('failed 状态显示失败文案与危险色', () => {
    const w = mount(StatusBadge, { props: { status: 'failed' } })
    expect(w.text()).toContain('失败')
    expect(w.html()).toContain('text-danger')
  })

  it('parsing / chunking / embedding 各自有独立配色', () => {
    expect(mount(StatusBadge, { props: { status: 'parsing' } }).html()).toContain('text-accent')
    expect(mount(StatusBadge, { props: { status: 'chunking' } }).html()).toContain('text-src-keyword')
    expect(mount(StatusBadge, { props: { status: 'embedding' } }).html()).toContain('text-src-vector')
  })

  it('入库中显示旋转指示器与四步进度点', () => {
    const w = mount(StatusBadge, { props: { status: 'chunking' } })
    expect(w.find('.animate-spin').exists()).toBe(true)
    expect(w.findAll('.h-1.w-3')).toHaveLength(4)
  })

  it('完成态不显示进度点', () => {
    const w = mount(StatusBadge, { props: { status: 'ready' } })
    expect(w.findAll('.h-1.w-3')).toHaveLength(0)
  })

  it('failed 时进度点标记为危险色', () => {
    const w = mount(StatusBadge, { props: { status: 'failed' } })
    expect(w.html()).toContain('bg-danger/60')
  })
})

describe('DocumentRow', () => {
  it('ready 时展示切片数并可打开切片明细', async () => {
    const w = mount(DocumentRow, { props: { docs: doc() } })
    expect(w.text()).toContain('12')
    const btn = w.findAll('button').find((b) => b.text().includes('12'))!
    await btn.trigger('click')
    expect(w.emitted('chunks')?.[0][0]).toMatchObject({ id: 7 })
  })

  it('chunking 状态展示切片处理中文案', () => {
    const w = mount(DocumentRow, { props: { docs: doc({ status: 'chunking', chunk_count: 0 }) } })
    expect(w.text()).toContain('切片')
    expect(w.findAll('button').filter((b) => b.text().includes('—'))).toHaveLength(0)
  })

  it('其他状态展示占位符', () => {
    const w = mount(DocumentRow, { props: { docs: doc({ status: 'parsing' }) } })
    expect(w.text()).toContain('—')
  })

  it('failed 状态展示错误详情并可重试', async () => {
    const w = mount(DocumentRow, { props: { docs: doc({ status: 'failed', error_msg: 'PDF 解析失败' }) } })
    expect(w.text()).toContain('PDF 解析失败')
    await w.find('button[title="失败重试（从失败阶段续传）"]').trigger('click')
    expect(w.emitted('retry')?.[0]).toEqual([7])
  })

  it('删除按钮抛出 remove', async () => {
    const w = mount(DocumentRow, { props: { docs: doc() } })
    await w.find('button[title="删除文档（先 ES 后 MySQL）"]').trigger('click')
    expect(w.emitted('remove')?.[0]).toEqual([7])
  })

  it('渲染文件类型与更新时间', () => {
    const w = mount(DocumentRow, { props: { docs: doc() } })
    expect(w.text()).toContain('md')
    expect(w.text()).toContain('/')
  })
})

describe('ScoreRing', () => {
  it('高分用强调色', () => {
    const w = mount(ScoreRing, { props: { score: 8.5 } })
    expect(w.html()).toContain('var(--color-accent)')
  })

  it('中等分用警告色', () => {
    const w = mount(ScoreRing, { props: { score: 6 } })
    expect(w.html()).toContain('var(--color-warn)')
  })

  it('低分用危险色', () => {
    const w = mount(ScoreRing, { props: { score: 3 } })
    expect(w.html()).toContain('var(--color-danger)')
  })

  it('显示一位小数', () => {
    const w = mount(ScoreRing, { props: { score: 7.25 } })
    expect(w.text()).toBe('7.3')
  })

  it('超出上限的分数被裁剪（弧长不超过整圈）', () => {
    const w = mount(ScoreRing, { props: { score: 99 } })
    const circ = 2 * Math.PI * 20 * 0.75
    expect(w.html()).toContain(`stroke-dasharray="${circ} ${circ}"`)
  })

  it('负分被裁剪为 0', () => {
    const w = mount(ScoreRing, { props: { score: -5 } })
    const circ = 2 * Math.PI * 20 * 0.75
    expect(w.html()).toContain(`stroke-dasharray="0 ${circ}"`)
  })

  it('支持自定义尺寸', () => {
    const w = mount(ScoreRing, { props: { score: 5, size: 80 } })
    expect(w.find('svg').attributes('width')).toBe('80')
  })
})

describe('MessageActions', () => {
  const msg = (over: Partial<ChatMessage> = {}): ChatMessage => ({
    id: 1,
    session_id: 1,
    role: 'assistant',
    content: '答案正文',
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  })

  it('复制成功时提示已复制', async () => {
    const w = mount(MessageActions, { props: { message: msg() } })
    await w.find('button').trigger('click')
    await w.vm.$nextTick()
    expect(mockCopyText).toHaveBeenCalledWith('答案正文')
    expect(w.findComponent(BaseTooltip).props('content')).toBe('已复制')
  })

  it('复制失败时不显示已复制提示', async () => {
    mockCopyText.mockResolvedValue(false)
    const w = mount(MessageActions, { props: { message: msg() } })
    await w.find('button').trigger('click')
    await w.vm.$nextTick()
    expect(w.findComponent(BaseTooltip).props('content')).toBe('复制全文')
  })

  it('有 decision_log_id 时展示决策链入口', async () => {
    const w = mount(MessageActions, { props: { message: msg({ decision_log_id: 3 }) } })
    const btn = w.findAll('button').find((b) => b.text().includes('决策链'))!
    await btn.trigger('click')
    expect(w.emitted('viewDecision')).toBeTruthy()
  })

  it('无 decision_log_id 时不展示决策链入口', () => {
    const w = mount(MessageActions, { props: { message: msg() } })
    expect(w.text()).not.toContain('决策链')
  })

  it('canRegenerate 时展示重新生成入口', async () => {
    const w = mount(MessageActions, { props: { message: msg(), canRegenerate: true } })
    const btn = w.findAll('button').find((b) => b.text().includes('重新生成'))!
    await btn.trigger('click')
    expect(w.emitted('regenerate')).toBeTruthy()
  })

  it('默认不展示重新生成入口', () => {
    const w = mount(MessageActions, { props: { message: msg() } })
    expect(w.text()).not.toContain('重新生成')
  })
})

describe('StepTimingBar', () => {
  it('无耗时卡片时不渲染', () => {
    const w = mount(StepTimingBar, { props: { cards: [card({ elapsedMs: 0 })] } })
    expect(w.text()).toBe('')
  })

  it('按环节聚合耗时并给出总耗时', () => {
    const w = mount(StepTimingBar, {
      props: {
        cards: [card({ type: 'router', elapsedMs: 100 }), card({ type: 'router', elapsedMs: 50 }), card({ type: 'grade', elapsedMs: 50 })],
      },
    })
    expect(w.text()).toContain('耗时分布')
    expect(w.html()).toContain('200ms')
  })

  it('warn 卡片使用警告色', () => {
    const w = mount(StepTimingBar, { props: { cards: [card({ type: 'grade', status: 'warn', elapsedMs: 100 })] } })
    expect(w.html()).toContain('var(--color-warn)')
  })

  it('图例最多显示 5 段', () => {
    const types = ['router', 'rewrite', 'retrieve', 'grade', 'correct', 'generate', 'reflect']
    const w = mount(StepTimingBar, { props: { cards: types.map((t, i) => card({ type: t as DecisionCard['type'], elapsedMs: (i + 1) * 10 })) } })
    // 7 segments in the bar and at most 5 legend entries
    expect(w.findAll('.h-1\\.5\\.w-1\\.5').length).toBeLessThanOrEqual(5)
  })

  it('按管线顺序排序分段', () => {
    const w = mount(StepTimingBar, {
      props: { cards: [card({ type: 'generate', elapsedMs: 10 }), card({ type: 'router', elapsedMs: 10 })] },
    })
    const titles = w.findAll('[title]').map((e) => e.attributes('title') ?? '')
    expect(titles[0]).toContain('路由')
  })
})

describe('SourceCard', () => {
  const item = (over: Partial<DatasourceItem> = {}): DatasourceItem => ({
    source_type: 'vector',
    enabled: true,
    config: { url: 'http://es:9200' },
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  })

  it('展示数据源名称与类型', () => {
    const w = mount(SourceCard, { props: { item: item() } })
    expect(w.text()).toContain('vector')
  })

  it('开关变更抛出 toggle', async () => {
    const w = mount(SourceCard, { props: { item: item() } })
    await w.find('button[role="switch"]').trigger('click')
    expect(w.emitted('toggle')?.[0]).toEqual([false])
  })

  it('配置项变更抛出 updateConfig', async () => {
    const w = mount(SourceCard, { props: { item: item() } })
    await w.find('input').setValue('http://es:9300')
    expect(w.emitted('updateConfig')?.[0]).toEqual(['url', 'http://es:9300'])
  })

  it('禁用时配置输入框不可编辑', () => {
    const w = mount(SourceCard, { props: { item: item({ enabled: false }) } })
    expect(w.find('input').attributes('disabled')).toBeDefined()
  })

  it('禁用时展示 Disabled 文案', () => {
    const w = mount(SourceCard, { props: { item: item({ enabled: false }) } })
    expect(w.text()).toContain('Disabled')
  })
})

describe('SideRail', () => {
  const routerStubs = {
    'router-link': { props: ['to'], template: '<a :href="to"><slot /></a>' },
  }

  it('渲染五个导航项', () => {
    const w = mount(SideRail, { global: { stubs: routerStubs } })
    expect(w.findAll('a[href]').length).toBeGreaterThanOrEqual(5)
  })

  it('当前路径对应的导航项高亮', () => {
    const w = mount(SideRail, { global: { stubs: routerStubs } })
    const active = w.findAll('a[href="/chat"]').filter((a) => a.classes().includes('text-ink'))
    expect(active.length).toBeGreaterThan(0)
  })

  it('点击主题按钮切换主题', async () => {
    const theme = useThemeStore()
    const before = theme.mode
    const w = mount(SideRail, { global: { stubs: routerStubs } })
    const themeBtn = w.findAll('button').find((b) => b.attributes('aria-label') === '切换到亮色模式' || b.attributes('aria-label') === '切换到暗色模式')!
    await themeBtn.trigger('click')
    expect(theme.mode).not.toBe(before)
  })

  it('点击语言按钮切换语言', async () => {
    const locale = useLocaleStore()
    const before = locale.locale
    const w = mount(SideRail, { global: { stubs: routerStubs } })
    const btn = w.findAll('button').find((b) => b.text() === '中' || b.text() === 'EN')!
    await btn.trigger('click')
    expect(locale.locale).not.toBe(before)
  })
})

describe('AppLayout', () => {
  it('渲染侧边栏与路由出口', () => {
    const w = mount(AppLayout, {
      global: { stubs: { 'router-view': { template: '<div class="router-view" />' } } },
    })
    expect(w.find('.router-view').exists()).toBe(true)
    expect(w.find('aside').exists()).toBe(true)
  })
})


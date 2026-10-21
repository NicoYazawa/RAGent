import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { ChatMessage, Citation } from '@/api/types'

/**
 * Message stream / decision sidebar — the two main interaction lines of this project:
 *   - MessageList: empty-state sample questions, user bubbles (with images), assistant bubbles linked to citation cards, image preview
 *   - DecisionSidebar: timeline/flowchart modes, history replay, export, errors and statistics
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

vi.mock('@/utils/decisionExport', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/decisionExport')>()
  return { ...actual, copyText: vi.fn(), downloadDecisionJson: vi.fn() }
})

import MessageList from '../MessageList.vue'
import DecisionSidebar from '../DecisionSidebar.vue'
import CitationChunkDrawer from '../CitationChunkDrawer.vue'
import ImageViewer from '@/components/ui/ImageViewer.vue'
import { useChatStore } from '@/stores/chat'
import { copyText, downloadDecisionJson } from '@/utils/decisionExport'

const mockCopyText = copyText as unknown as ReturnType<typeof vi.fn>
const mockDownload = downloadDecisionJson as unknown as ReturnType<typeof vi.fn>

const cite = (over: Partial<Citation> = {}): Citation => ({
  doc_name: '考勤制度.md',
  section_path: '第三章',
  chunk_no: 7,
  ...over,
})

const msg = (over: Partial<ChatMessage> = {}): ChatMessage => ({
  id: 1,
  session_id: 1,
  role: 'user',
  content: '内容',
  created_at: '2026-01-01T00:00:00Z',
  ...over,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockCopyText.mockResolvedValue(true)
})

describe('MessageList', () => {
  it('labels and targets sparse reference cards with their original numbers', async () => {
    const store = useChatStore()
    store.messages = [msg({ role: 'assistant', content: 'third [3]', citations: [cite({ ref_id: 3 })] })]
    const w = mount(MessageList)
    const card = w.find('#cite-card-0-3')
    expect(card.exists()).toBe(true)
    await card.trigger('click')
    expect(w.findComponent(CitationChunkDrawer).props('citation')?.ref_id).toBe(3)
  })

  it('keeps legacy sparse citations linked to their answer markers', () => {
    useChatStore().messages = [msg({ role: 'assistant', content: 'third [3]', citations: [cite()] })]
    expect(mount(MessageList).find('#cite-card-0-3').exists()).toBe(true)
  })
  it('空状态展示欢迎语与示例问题', () => {
    const w = mount(MessageList)
    expect(w.text()).toContain('RAGent')
    expect(w.findAll('button').length).toBeGreaterThanOrEqual(6)
  })

  it('点击示例问题把问题填入输入框', async () => {
    const ta = document.createElement('textarea')
    ta.id = 'chat-textarea'
    document.body.appendChild(ta)
    const w = mount(MessageList)
    const sample = w.findAll('button').find((b) => b.text().includes('迟到'))!
    await sample.trigger('click')
    expect(ta.value).toContain('迟到')
    document.body.removeChild(ta)
  })

  it('渲染用户消息', () => {
    const store = useChatStore()
    store.messages = [msg({ role: 'user', content: '年假几天' })]
    const w = mount(MessageList)
    expect(w.text()).toContain('年假几天')
  })

  it('渲染助手消息的 Markdown', () => {
    const store = useChatStore()
    store.messages = [msg({ id: 2, role: 'assistant', content: '**结论**：5 天' })]
    const w = mount(MessageList)
    expect(w.html()).toContain('<strong')
    expect(w.text()).toContain('结论')
  })

  it('用户消息带附图时渲染缩略图', () => {
    const store = useChatStore()
    store.messages = [msg({ role: 'user', images: ['a.png', 'b.png'] })]
    const w = mount(MessageList)
    expect(w.findAll('img').filter((i) => i.attributes('src') === 'a.png')).toHaveLength(1)
  })

  it('附图加载失败时显示失效占位', async () => {
    const store = useChatStore()
    store.messages = [msg({ role: 'user', images: ['broken.png'] })]
    const w = mount(MessageList)
    await w.find('img[src="broken.png"]').trigger('error')
    expect(w.text()).toContain('图片已失效')
  })

  it('点击附图打开图片预览', async () => {
    const store = useChatStore()
    store.messages = [msg({ role: 'user', images: ['a.png'] })]
    const w = mount(MessageList, { global: { stubs: { teleport: true } } })
    await w.find('img[src="a.png"]').trigger('click')
    const viewer = w.findComponent(ImageViewer)
    expect(viewer.props('open')).toBe(true)
    expect(viewer.props('images')).toEqual(['a.png'])
  })

  it('助手消息带引用时渲染引用卡片', () => {
    const store = useChatStore()
    store.messages = [msg({ id: 2, role: 'assistant', content: '见[1]', citations: [cite()] })]
    const w = mount(MessageList)
    expect(w.text()).toContain('来自《考勤制度.md》')
    expect(w.text()).toContain('#7')
  })

  it('db 类型引用展示 SQL 实时结果标签', () => {
    const store = useChatStore()
    store.messages = [
      msg({ id: 2, role: 'assistant', content: 'x', citations: [cite({ source_type: 'db', doc_name: 'NL2SQL' })] }),
    ]
    const w = mount(MessageList)
    expect(w.text()).toContain('SQL 实时结果')
  })

  it('点击引用卡片打开切片抽屉', async () => {
    const store = useChatStore()
    store.messages = [msg({ id: 2, role: 'assistant', content: '见[1]', citations: [cite()] })]
    const w = mount(MessageList, { global: { stubs: { teleport: true } } })
    await w.find('#cite-card-0-1').trigger('click')
    const drawer = w.findComponent(CitationChunkDrawer)
    expect(drawer.props('open')).toBe(true)
    expect((drawer.props('citation') as Citation).chunk_no).toBe(7)
  })

  it('流式输出时展示思考点', () => {
    const store = useChatStore()
    store.streaming = true
    const w = mount(MessageList)
    expect(w.findAll('.thinking-dot')).toHaveLength(3)
  })

  it('流式输出有文本时展示文本', () => {
    const store = useChatStore()
    store.streaming = true
    store.streamingText = '正在生成的内容'
    const w = mount(MessageList)
    expect(w.text()).toContain('正在生成的内容')
    expect(w.findAll('.thinking-dot')).toHaveLength(0)
  })

  it('只有最后一条助手消息可重新生成', () => {
    const store = useChatStore()
    store.messages = [
      msg({ id: 2, role: 'assistant', content: '第一个答案' }),
      msg({ id: 3, role: 'assistant', content: '第二个答案' }),
    ]
    const w = mount(MessageList)
    const regen = w.findAll('button').filter((b) => b.text().includes('重新生成'))
    expect(regen).toHaveLength(1)
  })
})

describe('DecisionSidebar', () => {
  it('空闲状态显示 Idle', () => {
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('Idle')
  })

  it('流式中显示 Live', () => {
    const store = useChatStore()
    store.streaming = true
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('Live')
  })

  it('无卡片时展示空态提示', () => {
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('Agent 决策链将在此实时展开')
  })

  it('渲染决策卡列表', () => {
    const store = useChatStore()
    store.cards = [
      { uid: 1, step: 1, type: 'router', status: 'done', detail: '路由', payload: {}, ts: 0, round: 0, elapsedMs: 10 },
    ]
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('路由')
  })

  it('渲染 pending 等待卡', () => {
    const store = useChatStore()
    store.pendingCard = { uid: 2, step: 0, type: 'generate', status: 'pending', detail: '正在处理', payload: {}, ts: 0, round: 0, elapsedMs: 0 }
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('正在处理')
  })

  it('切换到流程图模式', async () => {
    const w = mount(DecisionSidebar)
    await w.findAll('button').find((b) => b.text() === '流程图')!.trigger('click')
    expect(w.findComponent({ name: 'DecisionPipeline' }).exists()).toBe(true)
  })

  it('无卡片时复制与导出按钮禁用', () => {
    const w = mount(DecisionSidebar)
    const btns = w.findAll('button[disabled]')
    expect(btns.length).toBeGreaterThanOrEqual(2)
  })

  it('有卡片时可复制 Markdown', async () => {
    const store = useChatStore()
    store.cards = [
      { uid: 1, step: 1, type: 'router', status: 'done', detail: '路由', payload: {}, ts: 0, round: 0, elapsedMs: 10 },
    ]
    const w = mount(DecisionSidebar)
    const copyBtn = w.find('button[title="复制决策链 Markdown"]')
    await copyBtn.trigger('click')
    expect(mockCopyText).toHaveBeenCalled()
  })

  it('有卡片时可导出 JSON', async () => {
    const store = useChatStore()
    store.cards = [
      { uid: 1, step: 1, type: 'router', status: 'done', detail: '路由', payload: {}, ts: 0, round: 0, elapsedMs: 10 },
    ]
    const w = mount(DecisionSidebar)
    await w.find('button[title="导出决策链 JSON"]').trigger('click')
    expect(mockDownload).toHaveBeenCalled()
  })

  it('回看态展示回放横幅与历史统计', async () => {
    const store = useChatStore()
    store.viewingLog = {
      id: 8,
      question: '旧问题',
      cards: [{ uid: 1, step: 1, type: 'router', status: 'done', detail: '路由', payload: {}, ts: 0, round: 0, elapsedMs: 10 }],
      elapsedMs: 1500,
      totalRounds: 2,
    }
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('Replay')
    expect(w.text()).toContain('旧问题')
    expect(w.text()).toContain('1.5s')
  })

  it('回看态点击退出按钮清除回看', async () => {
    const store = useChatStore()
    store.viewingLog = {
      id: 8,
      question: '旧问题',
      cards: [],
      elapsedMs: 0,
      totalRounds: 0,
    }
    const spy = vi.spyOn(store, 'exitViewing')
    const w = mount(DecisionSidebar)
    await w.find('button[title="退出回放，回到实时决策流"]').trigger('click')
    expect(spy).toHaveBeenCalled()
  })

  it('异常时展示链路中断提示与错误详情', () => {
    const store = useChatStore()
    store.streamError = '502：上游不可用'
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('链路异常中断')
    expect(w.text()).toContain('502：上游不可用')
  })

  it('完成后展示耗时/token/轮次统计', () => {
    const store = useChatStore()
    store.doneStats = { elapsed_ms: 2500, prompt: 100, completion: 200, rounds: 1 }
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('2.5s')
    expect(w.text()).toContain('300')
  })

  it('空闲时展示评分环（存在 grade 卡时）', () => {
    const store = useChatStore()
    store.cards = [
      { uid: 1, step: 4, type: 'grade', status: 'done', detail: '评估', payload: { score: 0.8 }, ts: 0, round: 0, elapsedMs: 10 },
    ]
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('0.8')
  })

  it('空闲时无 grade 卡则展示等待提示', () => {
    const w = mount(DecisionSidebar)
    expect(w.text()).toContain('等待下一次提问')
  })
})


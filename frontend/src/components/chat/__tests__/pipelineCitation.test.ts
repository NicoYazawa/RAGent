import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { Citation } from '@/api/types'
import type { DecisionCard } from '@/stores/chat'

/**
 * Pipeline flowchart / citation drawer:
 *   - DecisionPipeline: four node states, per-stage metric copy, backflow edges, chitchat bypass, skip reasons
 *   - CitationChunkDrawer: knowledge-base citations locate the chunk text, db citations show SQL and rows, plus the error state
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('@/api/admin', () => ({
  getChunkByCitation: vi.fn(),
}))

import DecisionPipeline from '../DecisionPipeline.vue'
import CitationChunkDrawer from '../CitationChunkDrawer.vue'
import { getChunkByCitation } from '@/api/admin'

const mockGetChunk = getChunkByCitation as unknown as ReturnType<typeof vi.fn>

const card = (over: Partial<DecisionCard> = {}): DecisionCard => ({
  uid: 1,
  step: 1,
  type: 'router',
  status: 'done',
  detail: '',
  payload: {},
  ts: 0,
  round: 0,
  elapsedMs: 0,
  ...over,
})

const cite = (over: Partial<Citation> = {}): Citation => ({
  doc_name: '考勤制度.md',
  section_path: '第三章',
  chunk_no: 7,
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  mockGetChunk.mockResolvedValue({
    doc: {
      id: 3,
      kb_id: 1,
      file_name: '考勤制度.md',
      file_type: 'md',
      status: 'ready',
      chunk_count: 12,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    chunk: { id: 9, doc_id: 3, chunk_no: 7, section_path: '第三章', content: '切片正文内容', token_count: 42 },
  })
})

describe('DecisionPipeline', () => {
  const base = { cards: [] as DecisionCard[], streaming: false, activeStage: 0, pending: null }

  it('渲染 7 个管线环节', () => {
    const w = mount(DecisionPipeline, { props: { ...base } })
    const labels = w.findAll('.font-medium').map((e) => e.text())
    expect(labels).toContain('意图路由')
    expect(labels).toContain('引用溯源')
    expect(labels).toHaveLength(7)
  })

  it('有卡片时该环节为完成态', () => {
    const w = mount(DecisionPipeline, { props: { ...base, cards: [card({ type: 'router' })] } })
    expect(w.html()).toContain('text-ok')
  })

  it('warn 卡片对应环节为告警态', () => {
    const w = mount(DecisionPipeline, { props: { ...base, cards: [card({ type: 'grade', status: 'warn' })] } })
    expect(w.html()).toContain('border-warn/40')
  })

  it('流式中当前环节为激活态并展示 pending 文案', () => {
    const pending = card({ type: 'generate', status: 'pending', detail: '正在生成答案' })
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [], streaming: true, activeStage: 6, pending },
    })
    expect(w.html()).toContain('glow-edge')
    expect(w.text()).toContain('正在生成答案')
  })

  it('router 节点展示意图与置信度', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'router', payload: { intent: 'kb_qa', confidence: 0.9 } })] },
    })
    expect(w.text()).toContain('kb_qa · 90%')
  })

  it('retrieve 节点统计多路命中（精排卡不计入路数）', () => {
    const w = mount(DecisionPipeline, {
      props: {
        ...base,
        cards: [
          card({ type: 'retrieve', payload: { source: 'vector', hit_count: 3 } }),
          card({ type: 'retrieve', payload: { source: 'keyword', hit_count: 2 } }),
          card({ type: 'retrieve', payload: { source: 'rerank', hit_count: 10 } }),
        ],
      },
    })
    expect(w.text()).toContain('2 路命中 · 5 条')
  })

  it('grade 节点展示评分', () => {
    const w = mount(DecisionPipeline, { props: { ...base, cards: [card({ type: 'grade', payload: { score: 0.8 } })] } })
    expect(w.text()).toContain('0.8 分')
  })

  it('correct 节点展示纠正动作', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'correct', payload: { action: 'rewrite_retry' } })] },
    })
    expect(w.text()).toContain('rewrite_retry')
  })

  it('生成/反思节点展示字数与自检结果', () => {
    const w = mount(DecisionPipeline, {
      props: {
        ...base,
        cards: [
          card({ type: 'generate', payload: { chars: 42 } }),
          card({ type: 'reflect', payload: { result: 'pass' } }),
        ],
      },
    })
    expect(w.text()).toContain('42字')
    expect(w.text()).toContain('自检 pass')
  })

  it('citation 节点展示引用条数', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'citation', payload: { citations: [{}, {}] } })] },
    })
    expect(w.text()).toContain('2 条引用')
  })

  it('correct 卡片画出 CRAG 回流回边', () => {
    const w = mount(DecisionPipeline, { props: { ...base, cards: [card({ type: 'correct' })] } })
    expect(w.text()).toContain('R·纠正回流')
  })

  it('reflect fail 画出反思回流回边', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'reflect', payload: { result: 'fail' } })] },
    })
    expect(w.text()).toContain('R·反思回流')
  })

  it('闲聊意图展示直答旁路与跳过原因', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'router', payload: { intent: 'chitchat' } })] },
    })
    expect(w.text()).toContain('闲聊直答')
    expect(w.text()).toContain('闲聊直答 · 跳过改写')
    expect(w.text()).toContain('闲聊直答 · 跳过检索')
  })

  it('数据查询意图展示跳过改写的旁路原因', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'router', payload: { intent: 'data_query' } })] },
    })
    expect(w.text()).toContain('数据查询 · 直达检索')
    expect(w.text()).toContain('数据旁路 · 不走纠正')
  })

  it('总结模式展示未改写原因', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'router', payload: { intent: 'summarize' } })] },
    })
    expect(w.text()).toContain('总结模式 · 未改写')
  })

  it('知识库问答在纠正环节展示「评分达标 · 无需纠正」', () => {
    const w = mount(DecisionPipeline, {
      props: { ...base, cards: [card({ type: 'router', payload: { intent: 'kb_qa' } })] },
    })
    expect(w.text()).toContain('评分达标 · 无需纠正')
  })

  it('流式进行中不展示跳过原因', () => {
    const w = mount(DecisionPipeline, {
      props: { cards: [card({ type: 'router', payload: { intent: 'chitchat' } })], streaming: true, activeStage: 1, pending: null },
    })
    expect(w.text()).not.toContain('闲聊直答 · 跳过改写')
  })
})

describe('CitationChunkDrawer', () => {
  it.each(['success', 'failure'])('ignores a stale citation request %s after switching sources', async (outcome) => {
    const response = await mockGetChunk()
    let resolveFirst!: (value: typeof response) => void
    let rejectFirst!: (error: Error) => void
    const first = new Promise((resolve, reject) => { resolveFirst = resolve; rejectFirst = reject })
    const second = { ...response, chunk: { ...response.chunk, content: 'B CONTENT' } }
    mockGetChunk.mockReturnValueOnce(first).mockResolvedValueOnce(second)
    const w = mount(CitationChunkDrawer, { props: { open: true, citation: cite({ doc_id: 1 }) }, ...mountOpts })
    await w.setProps({ citation: cite({ doc_id: 2 }) })
    await flushPromises()
    expect(w.text()).toContain('B CONTENT')
    if (outcome === 'success') resolveFirst({ ...response, chunk: { ...response.chunk, content: 'A CONTENT' } })
    else rejectFirst(new Error('A failure'))
    await flushPromises()
    expect(w.text()).toContain('B CONTENT')
    expect(w.text()).not.toContain('A CONTENT')
    expect(w.text()).not.toContain('A failure')
  })
  it('passes stable document and chunk identity to the citation API', () => {
    const citation = cite({ doc_id: 10, kb_id: 2, chunk_uid: 'original' })
    mount(CitationChunkDrawer, { props: { open: true, citation }, ...mountOpts })
    expect(mockGetChunk).toHaveBeenCalledWith(citation.doc_name, citation.chunk_no, {
      doc_id: 10, kb_id: 2, chunk_uid: 'original',
    })
  })
  const mountOpts = { global: { stubs: { teleport: true } } }

  it('知识库引用按 doc_name + chunk_no 定位切片', async () => {
    mount(CitationChunkDrawer, { props: { open: true, citation: cite() }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    expect(mockGetChunk).toHaveBeenCalledWith('考勤制度.md', 7)
  })

  it('加载完成后展示切片正文与元信息', async () => {
    const w = mount(CitationChunkDrawer, { props: { open: true, citation: cite() }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('切片正文内容')
    expect(w.text()).toContain('42 tok')
    expect(w.text()).toContain('#7')
  })

  it('加载中展示骨架', () => {
    mockGetChunk.mockReturnValue(new Promise(() => undefined))
    const w = mount(CitationChunkDrawer, { props: { open: true, citation: cite() }, ...mountOpts })
    expect(w.findAll('.animate-pulse')).toHaveLength(2)
  })

  it('查询失败展示错误信息', async () => {
    mockGetChunk.mockRejectedValue(new Error('切片不存在'))
    const w = mount(CitationChunkDrawer, { props: { open: true, citation: cite() }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('切片不存在')
  })

  it('db 引用不查切片库，直接展示 SQL 与结果行', async () => {
    const w = mount(CitationChunkDrawer, {
      props: {
        open: true,
        citation: cite({
          source_type: 'db',
          doc_name: 'NL2SQL',
          sql: 'SELECT count(*) FROM sales',
          rows: [{ id: 1, product: '键盘', qty: 100 }],
        }),
      },
      ...mountOpts,
    })
    await new Promise((r) => setTimeout(r, 0))
    expect(mockGetChunk).not.toHaveBeenCalled()
    expect(w.text()).toContain('SELECT count(*) FROM sales')
    expect(w.text()).toContain('键盘')
  })

  it('db 引用无 SQL 时展示历史遗留说明', async () => {
    const w = mount(CitationChunkDrawer, {
      props: { open: true, citation: cite({ source_type: 'db', doc_name: 'NL2SQL' }) },
      ...mountOpts,
    })
    await new Promise((r) => setTimeout(r, 0))
    expect(w.text()).toContain('业务数据库实时查询')
  })

  it('结果表忽略 id 列并把空值显示为占位符', async () => {
    const w = mount(CitationChunkDrawer, {
      props: {
        open: true,
        citation: cite({
          source_type: 'db',
          doc_name: 'NL2SQL',
          sql: 'SELECT 1',
          rows: [{ id: 9, product: '', qty: 3 }],
        }),
      },
      ...mountOpts,
    })
    await new Promise((r) => setTimeout(r, 0))
    const headers = w.findAll('th').map((e) => e.text())
    expect(headers).toEqual(['product', 'qty'])
    expect(w.text()).toContain('—')
  })

  it('关闭时不查询切片', () => {
    mount(CitationChunkDrawer, { props: { open: false, citation: cite() }, ...mountOpts })
    expect(mockGetChunk).not.toHaveBeenCalled()
  })
})


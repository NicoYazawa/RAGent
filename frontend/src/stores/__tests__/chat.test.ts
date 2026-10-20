import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ChatMessage, ChatSession, SseEvent } from '@/api/types'

/**
 * 问答 Store —— SSE 事件 → 决策卡状态机 是前端最核心的状态逻辑。
 * 关键契约：
 *   - 卡片四态：pending / done / warn；warn 由 grade!=pass、correct、reflect fail、error、retrieve degraded 触发
 *   - 回流轮次：correct 提升 round，reflect fail 再 +1（侧栏缩进）
 *   - done 事件结算生成卡耗时并统计轮次
 *   - error 事件写 streamError，并以「链路异常中断」落一条 assistant 消息
 *   - 中断（AbortError）不上抛，也不覆盖本地已渲染的部分答案
 *   - 重新生成会先删掉旧 assistant 消息并请求后端清理，再以 skipUserPersist 重走流
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

vi.mock('@/api/admin', () => ({
  getDecisionLog: vi.fn(),
}))

import { useChatStore } from '../chat'
import * as chatApi from '@/api/chat'
import { getDecisionLog } from '@/api/admin'

const mockList = chatApi.listSessions as unknown as ReturnType<typeof vi.fn>
const mockGetMessages = chatApi.getMessages as unknown as ReturnType<typeof vi.fn>
const mockCreateSession = chatApi.createSession as unknown as ReturnType<typeof vi.fn>
const mockDeleteSession = chatApi.deleteSession as unknown as ReturnType<typeof vi.fn>
const mockPurge = chatApi.purgeLastAssistant as unknown as ReturnType<typeof vi.fn>
const mockAsk = chatApi.ask as unknown as ReturnType<typeof vi.fn>
const mockGetLog = getDecisionLog as unknown as ReturnType<typeof vi.fn>

const session = (id: number): ChatSession => ({
  id,
  title: `会话${id}`,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
})

const message = (id: number, role: 'user' | 'assistant', content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  id,
  session_id: 1,
  role,
  content,
  created_at: '2026-01-01T00:00:00Z',
  ...extra,
})

/** 构造 SSE 事件（ts 用当前时间，elapsed 计算才有意义） */
const ev = (over: Record<string, unknown>): SseEvent =>
  ({ step: 0, ts: Date.now(), detail: '', ...over }) as unknown as SseEvent

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockList.mockResolvedValue([])
  mockGetMessages.mockResolvedValue([])
  mockCreateSession.mockResolvedValue(session(99))
  mockDeleteSession.mockResolvedValue(undefined)
  mockPurge.mockResolvedValue(undefined)
  mockAsk.mockResolvedValue(undefined)
  mockGetLog.mockResolvedValue({
    id: 1,
    session_id: 1,
    message_id: 1,
    question: 'q',
    final_answer: 'a',
    steps: [],
    total_rounds: 0,
    elapsed_ms: 0,
    created_at: '2026-01-01T00:00:00Z',
  })
})

describe('chat store · 会话管理', () => {
  it('loadSessions 填充列表并复位 loading', async () => {
    mockList.mockResolvedValue([session(1), session(2)])
    const s = useChatStore()
    const p = s.loadSessions()
    expect(s.sessionsLoading).toBe(true)
    await p
    expect(s.sessions).toHaveLength(2)
    expect(s.sessionsLoading).toBe(false)
  })

  it('loadSessions 失败时也复位 loading（finally）', async () => {
    mockList.mockRejectedValue(new Error('boom'))
    const s = useChatStore()
    await expect(s.loadSessions()).rejects.toThrow('boom')
    expect(s.sessionsLoading).toBe(false)
  })

  it('selectSession 加载消息、设置当前会话并清空决策卡', async () => {
    mockGetMessages.mockResolvedValue([message(1, 'user', '你好')])
    const s = useChatStore()
    s.cards = [{ uid: 99, step: 1, type: 'router', status: 'done', detail: 'x', payload: {}, ts: 0, round: 0, elapsedMs: 0 }]
    await s.selectSession(7)
    expect(s.currentSessionId).toBe(7)
    expect(s.messages).toHaveLength(1)
    expect(s.cards).toEqual([])
    expect(s.pendingCard).toBeNull()
    expect(s.activeStage).toBe(0)
  })

  it('selectSession 退出历史决策链回看态', async () => {
    const s = useChatStore()
    await s.viewDecisionLog(1)
    expect(s.viewingLog).not.toBeNull()
    await s.selectSession(7)
    expect(s.viewingLog).toBeNull()
  })

  it('selectSession 在流式中先中断当前流', async () => {
    let signal: AbortSignal | undefined
    mockAsk.mockImplementation(async (_id: number, _q: string, _on: unknown, sig?: AbortSignal) => {
      signal = sig
      await new Promise(() => undefined) // 挂起，模拟进行中的流
    })
    const s = useChatStore()
    await s.selectSession(1)
    void s.send('问题')
    await new Promise((r) => setTimeout(r, 0))
    expect(s.streaming).toBe(true)
    await s.selectSession(2)
    expect(signal?.aborted).toBe(true)
  })

  it('currentSession 指向选中会话，未选中时为 null', async () => {
    mockList.mockResolvedValue([session(1), session(2)])
    const s = useChatStore()
    await s.loadSessions()
    expect(s.currentSession).toBeNull()
    await s.selectSession(2)
    expect(s.currentSession?.id).toBe(2)
  })

  it('newSession 创建后置顶并自动选中', async () => {
    mockCreateSession.mockResolvedValue(session(5))
    mockList.mockResolvedValue([session(1)])
    const s = useChatStore()
    await s.loadSessions()
    await s.newSession()
    expect(mockCreateSession).toHaveBeenCalledTimes(1)
    expect(s.sessions[0].id).toBe(5)
    expect(s.currentSessionId).toBe(5)
  })

  it('removeSession 删除当前会话后切到第一个剩余会话', async () => {
    mockList.mockResolvedValue([session(1), session(2)])
    const s = useChatStore()
    await s.loadSessions()
    await s.selectSession(1)
    await s.removeSession(1)
    expect(mockDeleteSession).toHaveBeenCalledWith(1)
    expect(s.sessions.map((x) => x.id)).toEqual([2])
    expect(s.currentSessionId).toBe(2)
  })

  it('removeSession 删除非当前会话时保持当前选择', async () => {
    mockList.mockResolvedValue([session(1), session(2)])
    const s = useChatStore()
    await s.loadSessions()
    await s.selectSession(1)
    await s.removeSession(2)
    expect(s.currentSessionId).toBe(1)
    expect(s.sessions.map((x) => x.id)).toEqual([1])
  })

  it('removeSession 删除最后一个会话后清空当前会话与消息', async () => {
    mockList.mockResolvedValue([session(1)])
    const s = useChatStore()
    await s.loadSessions()
    await s.selectSession(1)
    await s.removeSession(1)
    expect(s.currentSessionId).toBeNull()
    expect(s.messages).toEqual([])
    expect(s.sessions).toEqual([])
  })
})

describe('chat store · 事件 → 决策卡', () => {
  it('replaces a rejected answer and reconciles the final canonical answer', async () => {
    const s = await run([
      ev({ type: 'generate', step: 6, delta: 'OLD [1]' }),
      ev({ type: 'reflect', step: 6, result: 'fail', round: 1 }),
      ev({ type: 'generate', step: 6, delta: '', replace: true }),
      ev({ type: 'generate', step: 6, delta: 'NEW [3] invalid [9]' }),
      ev({ type: 'citation', step: 7, answer: 'NEW [3] invalid ', citations: [{ ref_id: 3, doc_name: 'new', section_path: '', chunk_no: 1 }] }),
    ])
    expect(s.streamingText).toBe('NEW [3] invalid ')
    expect(s.messages.at(-1)?.content).toBe('NEW [3] invalid ')
    expect(s.messages.at(-1)?.citations?.[0].ref_id).toBe(3)
  })
  /** 用一串事件驱动一次流，返回 store */
  async function run(events: SseEvent[], setup?: (s: ReturnType<typeof useChatStore>) => void): Promise<ReturnType<typeof useChatStore>> {
    const s = useChatStore()
    setup?.(s)
    mockAsk.mockImplementation(async (_id: number, _q: string, onEvent: (e: SseEvent) => void) => {
      for (const e of events) onEvent(e)
    })
    await s.send('问题')
    return s
  }

  it('router 事件生成 done 卡片并推进 pending 提示', async () => {
    const s = await run([ev({ type: 'router', step: 1, intent: 'kb_qa', confidence: 0.9, detail: '识别为知识库问答' })])
    expect(s.cards).toHaveLength(1)
    expect(s.cards[0].type).toBe('router')
    expect(s.cards[0].status).toBe('done')
    expect(s.cards[0].detail).toBe('识别为知识库问答')
    expect(s.cards[0].payload).toEqual({ intent: 'kb_qa', confidence: 0.9 })
    expect(s.pendingCard?.detail).toBe('正在判断问题类型…')
  })

  it('grade 非 pass 判定为 warn', async () => {
    const s = await run([ev({ type: 'grade', step: 4, score: 0.4, verdict: 'partial', reason: '偏题' })])
    expect(s.cards[0].status).toBe('warn')
  })

  it('grade pass 判定为 done', async () => {
    const s = await run([ev({ type: 'grade', step: 4, score: 0.9, verdict: 'pass', reason: 'ok' })])
    expect(s.cards[0].status).toBe('done')
  })

  it('correct 事件提升回流轮次并标为 warn', async () => {
    const s = await run([ev({ type: 'correct', step: 5, action: 'rewrite_retry', round: 1 })])
    expect(s.cards[0].status).toBe('warn')
    expect(s.cards[0].round).toBe(0)
  })

  it('reflect fail 递增轮次并标为 warn', async () => {
    const s = await run([
      ev({ type: 'correct', step: 5, action: 'rewrite_retry', round: 1 }),
      ev({ type: 'reflect', step: 7, result: 'fail', round: 1 }),
    ])
    // correct 之后会挂一张「正在执行纠正策略…」的等待卡，reflect 到来时结算它
    expect(s.cards).toHaveLength(3)
    expect(s.cards[1].type).toBe('generate')
    expect(s.cards[1].status).toBe('done')
    expect(s.cards[2].type).toBe('reflect')
    expect(s.cards[2].status).toBe('warn')
    // correct(round=1) → activeRound=1；reflect fail → activeRound=2（侧栏缩进一层）
    expect(s.cards[2].round).toBe(2)
  })

  it('reflect pass 为 done', async () => {
    const s = await run([ev({ type: 'reflect', step: 7, result: 'pass', round: 0 })])
    expect(s.cards[0].status).toBe('done')
  })

  it('retrieve degraded 标为 warn', async () => {
    const s = await run([ev({ type: 'retrieve', step: 3, hit_count: 0, degraded: true })])
    expect(s.cards[0].status).toBe('warn')
  })

  it('retrieve 正常为 done', async () => {
    const s = await run([ev({ type: 'retrieve', step: 3, hit_count: 3 })])
    expect(s.cards[0].status).toBe('done')
  })

  it('error 事件写入 streamError 并把 pending 结算为 warn', async () => {
    const s = await run([
      ev({ type: 'router', step: 1, intent: 'kb_qa', confidence: 1 }),
      ev({ type: 'error', step: 0, code: 502, message: '上游不可用' }),
    ])
    expect(s.streamError).toBe('502：上游不可用')
    expect(s.pendingCard).toBeNull()
    // 等待卡被以 warn 状态结算进卡片列表
    expect(s.cards[s.cards.length - 1].status).toBe('warn')
    expect(s.activeStage).toBe(0)
  })

  it('generate 累积流式文本并更新 pending 文案', async () => {
    const s = await run([
      ev({ type: 'router', step: 1, intent: 'kb_qa', confidence: 1 }),
      ev({ type: 'generate', step: 6, delta: '你好' }),
      ev({ type: 'generate', step: 6, delta: '世界' }),
    ])
    expect(s.streamingText).toBe('你好世界')
    expect(s.pendingCard?.detail).toBe('正在流式生成答案（4 字）…')
    expect(s.activeStage).toBe(6)
  })

  it('done 事件结算生成卡耗时、字数与轮次统计', async () => {
    const s = await run([
      ev({ type: 'correct', step: 5, action: 'rewrite_retry', round: 1 }),
      ev({ type: 'generate', step: 6, delta: '答案是AB' }),
      ev({ type: 'done', step: 0, message_id: 1, elapsed_ms: 1234, token_usage: { prompt: 10, completion: 20 } }),
    ])
    const gen = s.cards.find((c) => c.type === 'generate')
    expect(gen?.payload).toEqual({ chars: 5 })
    expect(gen?.elapsedMs).toBeGreaterThanOrEqual(0)
    expect(s.doneStats).toEqual({ elapsed_ms: 1234, prompt: 10, completion: 20, rounds: 1 })
    expect(s.activeStage).toBe(0)
    expect(s.pendingCard).toBeNull()
  })

  it('done 的轮次统计同时计入 correct 与 reflect fail', async () => {
    const s = await run([
      ev({ type: 'correct', step: 5, action: 'rewrite_retry', round: 1 }),
      ev({ type: 'reflect', step: 7, result: 'fail', round: 1 }),
      ev({ type: 'correct', step: 5, action: 'rewrite_retry', round: 2 }),
      ev({ type: 'done', step: 0, message_id: 1, elapsed_ms: 1, token_usage: { prompt: 1, completion: 1 } }),
    ])
    expect(s.doneStats?.rounds).toBe(3)
  })

  it('citation 事件把引用写入助手消息', async () => {
    // mockImplementation 而非 mockResolvedValue：避免返回同一数组引用被本地 push 污染
    mockGetMessages.mockImplementation(async () => [
      message(1, 'user', '问题'),
      message(2, 'assistant', '答案', { citations: [{ doc_name: 'a.md', section_path: 'p', chunk_no: 1 }] }),
    ])
    const s = await run([ev({ type: 'citation', step: 7, citations: [{ doc_name: 'a.md', section_path: 'p', chunk_no: 1 }] })])
    const last = s.messages[s.messages.length - 1]
    expect(last.role).toBe('assistant')
    expect(last.citations).toEqual([{ doc_name: 'a.md', section_path: 'p', chunk_no: 1 }])
  })

  it('空引用的 citation 不写入助手消息的 citations', async () => {
    mockGetMessages.mockResolvedValue([message(1, 'user', '问题')])
    const s = await run([ev({ type: 'citation', step: 7, citations: [] })])
    const last = s.messages[s.messages.length - 1]
    expect(last.citations).toBeUndefined()
  })

  it('错误时用「链路异常中断」落一条助手消息', async () => {
    const s = await run([ev({ type: 'error', step: 0, code: 500, message: '炸了' })])
    const last = s.messages[s.messages.length - 1]
    expect(last.role).toBe('assistant')
    expect(last.content).toContain('链路异常中断')
    expect(last.content).toContain('500：炸了')
  })
})

describe('chat store · 管线环节推进（activeStage）', () => {
  async function stageOf(event: SseEvent): Promise<number> {
    const s = useChatStore()
    mockAsk.mockImplementation(async (_id: number, _q: string, onEvent: (e: SseEvent) => void) => {
      onEvent(event)
    })
    await s.send('问题')
    return s.activeStage
  }

  it('router: chitchat 直达生成、data_query 跳过改写、其余进入规划', async () => {
    expect(await stageOf(ev({ type: 'router', step: 1, intent: 'chitchat', confidence: 1 }))).toBe(6)
    expect(await stageOf(ev({ type: 'router', step: 1, intent: 'data_query', confidence: 1 }))).toBe(3)
    expect(await stageOf(ev({ type: 'router', step: 1, intent: 'kb_qa', confidence: 1 }))).toBe(2)
  })

  it('rewrite 推进到检索', async () => {
    expect(await stageOf(ev({ type: 'rewrite', step: 2, rewritten_query: 'q', sub_queries: [], hyde_used: false }))).toBe(3)
  })

  it('grade: pass 到生成、partial 回到检索、fail 到纠正', async () => {
    expect(await stageOf(ev({ type: 'grade', step: 4, score: 1, verdict: 'pass', reason: '' }))).toBe(6)
    expect(await stageOf(ev({ type: 'grade', step: 4, score: 0.5, verdict: 'partial', reason: '' }))).toBe(3)
    expect(await stageOf(ev({ type: 'grade', step: 4, score: 0, verdict: 'fail', reason: '' }))).toBe(5)
  })

  it('correct: rewrite_retry 回到检索、give_up 到生成', async () => {
    expect(await stageOf(ev({ type: 'correct', step: 5, action: 'rewrite_retry', round: 1 }))).toBe(3)
    expect(await stageOf(ev({ type: 'correct', step: 5, action: 'give_up', round: 1 }))).toBe(6)
  })

  it('reflect: pass 到溯源、fail 回到检索', async () => {
    expect(await stageOf(ev({ type: 'reflect', step: 7, result: 'pass', round: 0 }))).toBe(3 + 4)
    expect(await stageOf(ev({ type: 'reflect', step: 7, result: 'fail', round: 0 }))).toBe(3)
  })

  it('citation 回到空闲态', async () => {
    expect(await stageOf(ev({ type: 'citation', step: 7, citations: [] }))).toBe(0)
  })
})

describe('chat store · 发送与中断', () => {
  it('无会话时自动创建会话再提问', async () => {
    mockCreateSession.mockResolvedValue(session(42))
    const s = useChatStore()
    await s.send('你好')
    expect(mockCreateSession).toHaveBeenCalledTimes(1)
    expect(s.currentSessionId).toBe(42)
    expect(mockAsk).toHaveBeenCalledTimes(1)
  })

  it('自动创建会话失败时写 streamError 且不发问', async () => {
    mockCreateSession.mockRejectedValue(new Error('502'))
    const s = useChatStore()
    await s.send('你好')
    expect(s.streamError).toBe('会话创建失败：502')
    expect(mockAsk).not.toHaveBeenCalled()
    expect(s.messages).toEqual([])
  })

  it('发送时把用户消息（含图片）推入消息列表', async () => {
    const s = useChatStore()
    await s.selectSession(1)
    await s.send('看图', ['data:image/png;base64,AA=='])
    const first = s.messages[0]
    expect(first.role).toBe('user')
    expect(first.content).toBe('看图')
    expect(first.images).toEqual(['data:image/png;base64,AA=='])
  })

  it('无图片时用户消息不带 images 字段', async () => {
    const s = useChatStore()
    await s.selectSession(1)
    await s.send('纯文本')
    expect(s.messages[0].images).toBeUndefined()
  })

  it('流式进行中拒绝重复发送', async () => {
    const s = useChatStore()
    s.streaming = true
    await s.send('问题')
    expect(mockAsk).not.toHaveBeenCalled()
  })

  it('流结束后用后端落库消息覆盖本地消息', async () => {
    mockGetMessages.mockResolvedValueOnce([]).mockResolvedValueOnce([message(10, 'assistant', '落库答案')])
    const s = useChatStore()
    await s.selectSession(1)
    await s.send('问题')
    expect(s.messages).toEqual([message(10, 'assistant', '落库答案')])
  })

  it('回填消息失败时保留本地状态', async () => {
    mockGetMessages.mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('500'))
    const s = useChatStore()
    await s.selectSession(1)
    await s.send('问题')
    expect(s.messages.length).toBeGreaterThan(0)
    expect(s.messages[0].role).toBe('user')
  })

  it('AbortError 被吸收：不上抛且不覆盖本地消息', async () => {
    mockGetMessages.mockResolvedValue([])
    const s = useChatStore()
    await s.selectSession(1)
    const err = new Error('aborted')
    err.name = 'AbortError'
    mockAsk.mockRejectedValue(err)
    await expect(s.send('问题')).resolves.toBeUndefined()
    expect(s.messages).toHaveLength(1)
    expect(s.messages[0].role).toBe('user')
  })

  it('非 Abort 错误照常上抛', async () => {
    const s = useChatStore()
    await s.selectSession(1)
    mockAsk.mockRejectedValue(new Error('网络断了'))
    await expect(s.send('问题')).rejects.toThrow('网络断了')
  })

  it('stopStream 触发 abort', async () => {
    let captured: AbortSignal | undefined
    mockAsk.mockImplementation(async (_id: number, _q: string, _on: unknown, signal?: AbortSignal) => {
      captured = signal
      await new Promise(() => undefined) // 挂起，保持流在进行中
    })
    const s = useChatStore()
    await s.selectSession(1)
    void s.send('问题')
    await new Promise((r) => setTimeout(r, 0))
    expect(captured).toBeInstanceOf(AbortSignal)
    expect(captured?.aborted).toBe(false)
    s.stopStream()
    expect(captured?.aborted).toBe(true)
  })
})

describe('chat store · 历史决策链回看', () => {
  it('把落库 steps 还原为决策卡（轮次 + warn 判定）', async () => {
    mockGetLog.mockResolvedValue({
      id: 8,
      session_id: 1,
      message_id: 2,
      question: '旧问题',
      final_answer: '旧答案',
      total_rounds: 2,
      elapsed_ms: 500,
      created_at: '2026-01-01T00:00:00Z',
      steps: [
        { step: 1, type: 'router', detail: '路由', payload: { intent: 'kb_qa' }, elapsed_ms: 10 },
        { step: 4, type: 'grade', detail: '评估', payload: { verdict: 'partial' }, elapsed_ms: 20 },
        { step: 5, type: 'correct', detail: '纠正', payload: { round: 1 }, elapsed_ms: 30 },
        { step: 7, type: 'reflect', detail: '反思', payload: { result: 'fail' }, elapsed_ms: 40 },
      ],
    })
    const s = useChatStore()
    await s.viewDecisionLog(8)
    const log = s.viewingLog
    expect(log?.id).toBe(8)
    expect(log?.question).toBe('旧问题')
    expect(log?.elapsedMs).toBe(500)
    expect(log?.totalRounds).toBe(2)
    expect(log?.cards).toHaveLength(4)
    expect(log?.cards[0].status).toBe('done')
    expect(log?.cards[1].status).toBe('warn')
    expect(log?.cards[2].status).toBe('warn')
    expect(log?.cards[3].status).toBe('warn')
    // correct(round=1) → round=1；reflect fail → round=2
    expect(log?.cards[2].round).toBe(1)
    expect(log?.cards[3].round).toBe(2)
    expect(log?.cards[0].elapsedMs).toBe(10)
    expect(s.viewingLoading).toBe(false)
  })

  it('回看中的 grade pass 为 done', async () => {
    mockGetLog.mockResolvedValue({
      id: 9,
      session_id: 1,
      message_id: 2,
      question: 'q',
      final_answer: 'a',
      total_rounds: 0,
      elapsed_ms: 1,
      created_at: '2026-01-01T00:00:00Z',
      steps: [{ step: 4, type: 'grade', detail: '评估', payload: { verdict: 'pass' }, elapsed_ms: 5 }],
    })
    const s = useChatStore()
    await s.viewDecisionLog(9)
    expect(s.viewingLog?.cards[0].status).toBe('done')
  })

  it('流式中拒绝回看', async () => {
    const s = useChatStore()
    s.streaming = true
    await s.viewDecisionLog(1)
    expect(mockGetLog).not.toHaveBeenCalled()
    expect(s.viewingLog).toBeNull()
  })

  it('加载失败时保持空回看态并复位 loading', async () => {
    mockGetLog.mockRejectedValue(new Error('404'))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const s = useChatStore()
    await s.viewDecisionLog(1)
    expect(s.viewingLog).toBeNull()
    expect(s.viewingLoading).toBe(false)
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('exitViewing 退出回看态', async () => {
    const s = useChatStore()
    await s.viewDecisionLog(1)
    s.exitViewing()
    expect(s.viewingLog).toBeNull()
  })
})

describe('chat store · 重新生成', () => {
  it('没有当前会话时不动作', async () => {
    const s = useChatStore()
    await s.regenerate()
    expect(mockPurge).not.toHaveBeenCalled()
  })

  it('缺少用户或助手消息时不动作', async () => {
    const s = useChatStore()
    await s.selectSession(1)
    await s.regenerate()
    expect(mockPurge).not.toHaveBeenCalled()
  })

  it('删除旧助手消息、清理后端并以 skipUserPersist 重走流', async () => {
    mockGetMessages.mockResolvedValue([
      message(1, 'user', '原问题'),
      message(2, 'assistant', '旧答案'),
    ])
    const s = useChatStore()
    await s.selectSession(1)
    await s.regenerate()
    expect(mockPurge).toHaveBeenCalledWith(1)
    expect(mockAsk).toHaveBeenCalledTimes(1)
    const args = mockAsk.mock.calls[0]
    expect(args[1]).toBe('原问题')
    expect(args[4]).toBe(true)
    // 旧助手消息已从本地移除，且没有重复落一条用户消息
    expect(s.messages.filter((m) => m.role === 'user')).toHaveLength(1)
  })

  it('流式中拒绝重新生成', async () => {
    const s = useChatStore()
    s.streaming = true
    await s.regenerate()
    expect(mockPurge).not.toHaveBeenCalled()
  })
})


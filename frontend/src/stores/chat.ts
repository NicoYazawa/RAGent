import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineStore } from 'pinia'
import type { ChatMessage, ChatSession, Citation, DecisionStep, RetrieveEvent, SseEvent, SseEventType } from '@/api/types'
import * as chatApi from '@/api/chat'
import { getDecisionLog } from '@/api/admin'

/* ============================================================
 * 问答 Store — 会话管理 + SSE 事件 → 决策卡片状态机
 * 卡片四态：pending（转圈）/ done（完成）/ warn（告警）/ 回流缩进
 * ============================================================ */

export interface DecisionCard {
  uid: number
  /** 决策点序号（0 = 汇总/异常） */
  step: number
  type: SseEventType
  status: 'pending' | 'done' | 'warn'
  detail: string
  payload: Record<string, unknown>
  ts: number
  /** 回流轮次（0 起，>0 时侧栏缩进一层） */
  round: number
  /** 本环节耗时 ms（pending 未结算为 0；等待型过渡卡为 0） */
  elapsedMs: number
}

/** 历史决策链回看态（agent_decision_log → 卡片） */
export interface ViewingLog {
  id: number
  question: string
  cards: DecisionCard[]
  elapsedMs: number
  totalRounds: number
}

let uid = 1

/** 事件完成后预测下一步的 pending 文案（走 i18n，chat.hint.*） */

export const useChatStore = defineStore('chat', () => {
  const { t } = useI18n()
  /** 下一环节 pending 提示：按 SSE 事件类型取本地化文案 */
  function hintOf(type: SseEventType): string {
    return t(`chat.hint.${type}`) || ''
  }
  /* ---------- 会话 ---------- */
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<number | null>(null)
  const sessionsLoading = ref(false)

  /* ---------- 消息 ---------- */
  const messages = ref<ChatMessage[]>([])
  const messagesLoading = ref(false)

  /* ---------- 决策侧栏 ---------- */
  const cards = ref<DecisionCard[]>([])
  const pendingCard = ref<DecisionCard | null>(null)
  const streaming = ref(false)
  const streamingText = ref('')
  const streamError = ref<string | null>(null)
  const doneStats = ref<{ elapsed_ms: number; prompt: number; completion: number; rounds: number } | null>(null)
  const activeRound = ref(0)
  /** 当前进行中的管线环节（1~7，0=空闲；供流程图模式点亮） */
  const activeStage = ref(0)
  /** 历史决策链回看（非 null 时侧栏展示该日志而非实时流） */
  const viewingLog = ref<ViewingLog | null>(null)
  const viewingLoading = ref(false)

  let abortController: AbortController | null = null

  /* 单步计时：上一事件 ts（事件卡耗时 = 本事件 ts - lastTs） */
  let lastTs = 0
  /* 生成卡（流式答案）首 token 时刻与卡片 uid */
  let generateStartTs: number | null = null
  let generateCardUid: number | null = null

  const currentSession = computed(() => sessions.value.find((s) => s.id === currentSessionId.value) ?? null)

  /* ---------- 会话操作 ---------- */

  async function loadSessions(): Promise<void> {
    sessionsLoading.value = true
    try {
      sessions.value = await chatApi.listSessions()
    } finally {
      sessionsLoading.value = false
    }
  }

  async function selectSession(id: number): Promise<void> {
    if (streaming.value) stopStream()
    currentSessionId.value = id
    messagesLoading.value = true
    resetDecision()
    viewingLog.value = null
    try {
      messages.value = await chatApi.getMessages(id)
    } finally {
      messagesLoading.value = false
    }
  }

  async function newSession(): Promise<void> {
    const s = await chatApi.createSession()
    sessions.value.unshift(s)
    await selectSession(s.id)
  }

  async function removeSession(id: number): Promise<void> {
    await chatApi.deleteSession(id)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentSessionId.value === id) {
      currentSessionId.value = null
      messages.value = []
      resetDecision()
      if (sessions.value.length > 0) await selectSession(sessions.value[0].id)
    }
  }

  /* ---------- 决策卡片状态机 ---------- */

  function resetDecision(): void {
    cards.value = []
    pendingCard.value = null
    streamingText.value = ''
    streamError.value = null
    doneStats.value = null
    activeRound.value = 0
    activeStage.value = 0
    lastTs = Date.now()
    generateStartTs = null
    generateCardUid = null
  }

  function settlePending(status: 'done' | 'warn' = 'done'): void {
    if (pendingCard.value) {
      pendingCard.value.status = status
      cards.value.push(pendingCard.value)
      pendingCard.value = null
    }
  }

  /** 结算生成卡耗时（首个 generate 事件 → 结算事件），需在 settlePending 前调用 */
  function settleGenerate(settleTs: number): void {
    if (pendingCard.value && generateCardUid !== null && pendingCard.value.uid === generateCardUid) {
      pendingCard.value.elapsedMs = Math.max(0, settleTs - (generateStartTs ?? settleTs))
      // 回填本次生成的字数（供流程图模式/决策链展示，与日志 steps 的 payload.chars 同构）
      pendingCard.value.payload = { chars: streamingText.value.length }
      generateCardUid = null
      generateStartTs = null
    }
  }

  function pushPending(detail: string): void {
    pendingCard.value = { uid: uid++, step: 0, type: 'generate', status: 'pending', detail, payload: {}, ts: Date.now(), round: activeRound.value, elapsedMs: 0 }
  }

  function warnOf(event: SseEvent): boolean {
    if (event.type === 'grade') return event.verdict !== 'pass'
    if (event.type === 'correct') return true
    if (event.type === 'reflect') return event.result === 'fail'
    if (event.type === 'error') return true
    if (event.type === 'retrieve') return (event as RetrieveEvent).degraded === true
    return false
  }

  /** 事件完成后推进管线环节（供流程图模式点亮下一节点） */
  function nextStage(event: SseEvent): number {
    switch (event.type) {
      case 'router':
        // 闲聊直接进入生成；数据查询跳过改写直达检索
        return event.intent === 'chitchat' ? 6 : event.intent === 'data_query' ? 3 : 2
      case 'rewrite':
        return 3
      case 'grade':
        return event.verdict === 'pass' ? 6 : event.verdict === 'partial' ? 3 : 5
      case 'correct':
        return event.action === 'give_up' ? 6 : 3
      case 'reflect':
        return event.result === 'pass' ? 7 : 3
      case 'citation':
        return 0
      default:
        return activeStage.value
    }
  }

  function handleEvent(event: SseEvent): void {
    if (event.type === 'citation' && event.answer !== undefined) streamingText.value = event.answer
    switch (event.type) {
      case 'router':
      case 'rewrite':
      case 'retrieve':
      case 'grade':
      case 'correct':
      case 'reflect':
      case 'citation': {
        // 生成中的 pending 归档为「答案生成完成」
        if (pendingCard.value && event.type === 'reflect') {
          settleGenerate(event.ts)
          settlePending('done')
        } else {
          settlePending()
        }
        const { type, step, detail, ts, ...payload } = event
        if (type === 'correct') activeRound.value = Math.max(activeRound.value, (event as { round: number }).round)
        if (type === 'reflect' && (event as { result: string }).result === 'fail') activeRound.value += 1
        cards.value.push({
          uid: uid++,
          step,
          type,
          status: warnOf(event) ? 'warn' : 'done',
          detail,
          payload: payload as Record<string, unknown>,
          ts,
          round: type === 'correct' || type === 'reflect' ? Math.max(0, activeRound.value - (type === 'correct' ? 1 : 0)) : activeRound.value,
          elapsedMs: Math.max(0, ts - lastTs),
        })
        lastTs = ts
        const hint = hintOf(type)
        if (hint) pushPending(hint)
        activeStage.value = nextStage(event)
        break
      }
      case 'generate': {
        if (event.replace) {
          streamingText.value = ''
          generateStartTs = null
          generateCardUid = null
        }
        if (generateStartTs === null) generateStartTs = event.ts
        streamingText.value += event.delta
        if (!pendingCard.value) {
          pushPending(t('chat.streaming'))
        } else if (pendingCard.value.status === 'pending') {
          pendingCard.value.detail = t('chat.streamingN', { n: streamingText.value.length })
        }
        if (generateCardUid === null && pendingCard.value) generateCardUid = pendingCard.value.uid
        activeStage.value = 6
        break
      }
      case 'done': {
        settleGenerate(event.ts)
        settlePending()
        doneStats.value = {
          elapsed_ms: event.elapsed_ms,
          prompt: event.token_usage.prompt,
          completion: event.token_usage.completion,
          rounds: cards.value.filter((c) => c.type === 'correct' || (c.type === 'reflect' && (c.payload as { result?: string }).result === 'fail')).length,
        }
        activeStage.value = 0
        break
      }
      case 'error': {
        settleGenerate(event.ts)
        settlePending('warn')
        streamError.value = `${event.code}：${event.message}`
        activeStage.value = 0
        break
      }
    }
  }

  /* ---------- 历史决策链回看 ---------- */

  /** DecisionStep[]（日志落库）→ 决策卡（含回流轮次推算，与实时流同构） */
  function stepsToCards(steps: DecisionStep[]): DecisionCard[] {
    const out: DecisionCard[] = []
    let round = 0
    for (const step of steps) {
      if (step.type === 'correct') round = Math.max(round, (step.payload.round as number) ?? round)
      if (step.type === 'reflect' && step.payload.result === 'fail') round += 1
      const warn =
        (step.type === 'grade' && step.payload.verdict !== 'pass') ||
        step.type === 'correct' ||
        (step.type === 'reflect' && step.payload.result === 'fail') ||
        step.type === 'error'
      out.push({
        uid: uid++,
        step: step.step,
        type: step.type,
        status: warn ? 'warn' : 'done',
        detail: step.detail,
        payload: step.payload,
        ts: 0,
        round: step.type === 'correct' || step.type === 'reflect' ? Math.max(0, round) : round,
        elapsedMs: step.elapsed_ms,
      })
    }
    return out
  }

  async function viewDecisionLog(logId: number): Promise<void> {
    if (streaming.value || viewingLoading.value) return
    viewingLoading.value = true
    try {
      const log = await getDecisionLog(logId)
      viewingLog.value = {
        id: log.id,
        question: log.question,
        cards: stepsToCards(log.steps),
        elapsedMs: log.elapsed_ms,
        totalRounds: log.total_rounds,
      }
    } catch (e) {
      console.warn('[chat] 决策日志加载失败', e)
    } finally {
      viewingLoading.value = false
    }
  }

  function exitViewing(): void {
    viewingLog.value = null
  }

  /* ---------- 重新生成 ---------- */

  /** 重答最后一问：清理旧答案（本地 + 后端落库）后重走 SSE 流（图片以站内 URL 重传复用） */
  async function regenerate(): Promise<void> {
    if (!currentSessionId.value || streaming.value) return
    const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
    const lastUser = [...messages.value].reverse().find((m) => m.role === 'user')
    if (!lastAssistant || !lastUser) return
    // 本地移除旧答案，并同步清理后端落库的消息与决策日志
    const idx = messages.value.map((m) => m.id).lastIndexOf(lastAssistant.id)
    if (idx !== -1) messages.value.splice(idx, 1)
    await chatApi.purgeLastAssistant(currentSessionId.value)
    exitViewing()
    resetDecision()
    await runStream(lastUser.content, true, lastUser.images)
  }

  /* ---------- 问答主流程 ---------- */

  async function send(question: string, images?: string[]): Promise<void> {
    if (streaming.value) return
    // 无选中会话（如全新环境首次提问）时自动创建，避免发送被静默拦截
    if (!currentSessionId.value) {
      try {
        await newSession()
      } catch (e) {
        console.warn('[chat] 自动创建会话失败', e)
        streamError.value = t('chat.store.sessionCreateFailed') + (e as Error).message
        return
      }
    }
    exitViewing()
    resetDecision()
    streaming.value = true
    messages.value.push({
      id: -Date.now(),
      session_id: currentSessionId.value!,
      role: 'user',
      content: question,
      images: images?.length ? images : undefined,
      created_at: new Date().toISOString(),
    })
    await runStream(question, false, images)
  }

  /** SSE 流主体（send / regenerate 共用）；skipUserPersist=true 时不重复落用户消息 */
  async function runStream(question: string, skipUserPersist: boolean, images?: string[]): Promise<void> {
    streaming.value = true
    let finalText = ''
    let finalCitations: Citation[] | undefined
    const onEvent = (event: SseEvent): void => {
      handleEvent(event)
      if (event.type === 'generate' || event.type === 'citation') finalText = streamingText.value
      if (event.type === 'generate' && event.replace) finalCitations = undefined
      if (event.type === 'citation') finalCitations = event.citations.length ? event.citations : undefined
    }

    abortController = new AbortController()
    let aborted = false
    try {
      await chatApi.ask(currentSessionId.value!, question, onEvent, abortController.signal, skipUserPersist, images)
    } catch (err) {
      if ((err as DOMException)?.name === 'AbortError') aborted = true
      else throw err
    } finally {
      streaming.value = false
      abortController = null
      if (finalText || streamError.value) {
        messages.value.push({
          id: -Date.now() - 1,
          session_id: currentSessionId.value!,
          role: 'assistant',
          content: finalText || `**${t('chat.sidebar.chainBroken')}**\n\n${streamError.value ?? t('chat.store.unknownError')}`,
          citations: finalCitations,
          created_at: new Date().toISOString(),
        })
      }
      await loadSessions()
      const cur = sessions.value.find((s) => s.id === currentSessionId.value)
      if (cur) cur.id = cur.id // touch reactive
      // 流结束后拉取落库消息，回填真实 message_id / citations / decision_log_id
      // （中断场景后端未落库 assistant，保留本地部分答案展示）
      if (!aborted && currentSessionId.value) {
        try {
          messages.value = await chatApi.getMessages(currentSessionId.value)
        } catch {
          /* 保留本地状态 */
        }
      }
    }
  }

  function stopStream(): void {
    abortController?.abort()
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    sessionsLoading,
    messages,
    messagesLoading,
    cards,
    pendingCard,
    streaming,
    streamingText,
    streamError,
    doneStats,
    activeStage,
    viewingLog,
    viewingLoading,
    loadSessions,
    selectSession,
    newSession,
    removeSession,
    send,
    regenerate,
    stopStream,
    resetDecision,
    viewDecisionLog,
    exitViewing,
  }
})

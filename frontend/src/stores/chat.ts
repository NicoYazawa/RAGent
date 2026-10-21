import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineStore } from 'pinia'
import type { ChatMessage, ChatSession, Citation, DecisionStep, RetrieveEvent, SseEvent, SseEventType } from '@/api/types'
import * as chatApi from '@/api/chat'
import { getDecisionLog } from '@/api/admin'

/* ============================================================
 * Chat store — session management plus the SSE event to decision-card state machine
 * Four card states: pending (spinner) / done (settled) / warn (alert) / backflow indent
 * ============================================================ */

export interface DecisionCard {
  uid: number
  /** Decision point ordinal (0 = summary/error) */
  step: number
  type: SseEventType
  status: 'pending' | 'done' | 'warn'
  detail: string
  payload: Record<string, unknown>
  ts: number
  /** Backflow round (starts at 0; above 0 the sidebar indents one level) */
  round: number
  /** Stage duration in ms (0 while pending is unsettled; 0 for waiting transition cards) */
  elapsedMs: number
}

/** History replay state (agent_decision_log to cards) */
export interface ViewingLog {
  id: number
  question: string
  cards: DecisionCard[]
  elapsedMs: number
  totalRounds: number
}

let uid = 1

/** Predicts the next pending copy after an event (via i18n, chat.hint.*) */

export const useChatStore = defineStore('chat', () => {
  const { t } = useI18n()
  /** Next-stage pending hint: localized copy chosen by SSE event type */
  function hintOf(type: SseEventType): string {
    return t(`chat.hint.${type}`) || ''
  }
  /* ---------- Sessions ---------- */
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<number | null>(null)
  const sessionsLoading = ref(false)

  /* ---------- Messages ---------- */
  const messages = ref<ChatMessage[]>([])
  const messagesLoading = ref(false)

  /* ---------- Decision sidebar ---------- */
  const cards = ref<DecisionCard[]>([])
  const pendingCard = ref<DecisionCard | null>(null)
  const streaming = ref(false)
  const streamingText = ref('')
  const streamError = ref<string | null>(null)
  const doneStats = ref<{ elapsed_ms: number; prompt: number; completion: number; rounds: number } | null>(null)
  const activeRound = ref(0)
  /** The pipeline stage in progress (1-7, 0=idle; lights nodes in flowchart mode) */
  const activeStage = ref(0)
  /** History replay (when non-null the sidebar shows that log instead of the live stream) */
  const viewingLog = ref<ViewingLog | null>(null)
  const viewingLoading = ref(false)

  let abortController: AbortController | null = null

  /* Per-step timing: the previous event ts (card duration = this ts - lastTs) */
  let lastTs = 0
  /* First-token time and card uid of the generation card (streamed answer) */
  let generateStartTs: number | null = null
  let generateCardUid: number | null = null

  const currentSession = computed(() => sessions.value.find((s) => s.id === currentSessionId.value) ?? null)

  /* ---------- Session operations ---------- */

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

  /* ---------- Decision card state machine ---------- */

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

  /** Settle the generation card timing (first generate event to the settle event); call before settlePending */
  function settleGenerate(settleTs: number): void {
    if (pendingCard.value && generateCardUid !== null && pendingCard.value.uid === generateCardUid) {
      pendingCard.value.elapsedMs = Math.max(0, settleTs - (generateStartTs ?? settleTs))
      // fill in the generated char count (for flowchart/decision-chain display, matching payload.chars in the log steps)
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

  /** Advance the pipeline stage after an event (lights the next node in flowchart mode) */
  function nextStage(event: SseEvent): number {
    switch (event.type) {
      case 'router':
        // chitchat goes straight to generation; data queries skip rewriting and go to retrieval
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
        // the in-flight generation pending is archived as "answer generation complete"
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

  /* ---------- History replay ---------- */

  /** DecisionStep[] (as persisted) to decision cards (backflow rounds derived, same shape as the live stream) */
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

  /* ---------- Regeneration ---------- */

  /** Re-ask the last question: clear the old answer (locally and in the backend) then replay the SSE stream (images re-sent as in-app URLs) */
  async function regenerate(): Promise<void> {
    if (!currentSessionId.value || streaming.value) return
    const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
    const lastUser = [...messages.value].reverse().find((m) => m.role === 'user')
    if (!lastAssistant || !lastUser) return
    // remove the old answer locally and clear the persisted message and decision log in the backend
    const idx = messages.value.map((m) => m.id).lastIndexOf(lastAssistant.id)
    if (idx !== -1) messages.value.splice(idx, 1)
    await chatApi.purgeLastAssistant(currentSessionId.value)
    exitViewing()
    resetDecision()
    await runStream(lastUser.content, true, lastUser.images)
  }

  /* ---------- Main Q&A flow ---------- */

  async function send(question: string, images?: string[]): Promise<void> {
    if (streaming.value) return
    // create a session automatically when none is selected (e.g. the first question in a fresh setup) so sending is not silently blocked
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

  /** The SSE stream body (shared by send and regenerate); skipUserPersist=true avoids storing the user message twice */
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
      // after the stream, fetch the persisted messages to fill in the real message_id / citations / decision_log_id
      // (on interruption the backend stored no assistant message, so the partial local answer stays visible)
      if (!aborted && currentSessionId.value) {
        try {
          messages.value = await chatApi.getMessages(currentSessionId.value)
        } catch {
          /* keep the local state */
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

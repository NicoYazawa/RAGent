import type { ChatMessage, ChatSession, SseEvent } from './types'
import { SseParser } from './sseParser'
import { apiJson, jsonInit } from './http'
import { useLocaleStore } from '@/stores/locale'

/* ============================================================
 * Chat API
 * ============================================================ */

/** POST /api/chat/sessions */
export async function createSession(): Promise<ChatSession> {
  return apiJson<ChatSession>('/api/chat/sessions', { method: 'POST' })
}

/** GET /api/chat/sessions */
export async function listSessions(): Promise<ChatSession[]> {
  return apiJson<ChatSession[]>('/api/chat/sessions')
}

/** GET /api/chat/sessions/{session_id}/messages */
export async function getMessages(sessionId: number): Promise<ChatMessage[]> {
  return apiJson<ChatMessage[]>(`/api/chat/sessions/${sessionId}/messages`)
}

/** DELETE /api/chat/sessions/{session_id} */
export async function deleteSession(sessionId: number): Promise<void> {
  await apiJson(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' })
}

/** DELETE /api/chat/sessions/{session_id}/last-assistant — clears the old answer and decision log before regenerating */
export async function purgeLastAssistant(sessionId: number): Promise<void> {
  await apiJson(`/api/chat/sessions/${sessionId}/last-assistant`, { method: 'DELETE' })
}

/**
 * POST /api/chat/sessions/{session_id}/ask — SSE Q&A stream (the core endpoint)
 * fetch + ReadableStream consumed through SseParser callbacks;
 * images holds multimodal references (data URLs for fresh uploads / in-app URLs reused on regeneration);
 * persistence (user/assistant messages plus the decision log) is the backend's job (events and log share one source)
 */
export async function ask(
  sessionId: number,
  question: string,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
  skipUserPersist = false,
  images?: string[],
): Promise<void> {
  const locale = useLocaleStore().locale
  const base = jsonInit('POST', { question, skip_user_persist: skipUserPersist, images: images ?? [] })
  const resp = await fetch(`/api/chat/sessions/${sessionId}/ask`, {
    ...base,
    headers: { ...(base.headers as Record<string, string>), 'Accept-Language': locale },
    signal,
  })
  if (!resp.ok || !resp.body) {
    let msg = `HTTP ${resp.status}`
    try {
      const j = (await resp.json()) as { detail?: string; message?: string }
      msg = j?.detail || j?.message || msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  const parser = new SseParser()
  const decoder = new TextDecoder()
  const reader = resp.body.getReader()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const event of parser.feed(decoder.decode(value, { stream: true }))) {
        onEvent(event)
      }
    }
  } catch (err) {
    // a user interruption: absorb AbortError and rethrow anything else
    if ((err as DOMException)?.name === 'AbortError') return
    throw err
  }
  for (const event of parser.feed(decoder.decode())) {
    onEvent(event)
  }
}

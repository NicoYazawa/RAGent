import type { ChatMessage, ChatSession, SseEvent } from './types'
import { SseParser } from './sseParser'
import { apiJson, jsonInit } from './http'
import { useLocaleStore } from '@/stores/locale'

/* ============================================================
 * 问答端 API
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

/** DELETE /api/chat/sessions/{session_id}/last-assistant — 重新生成前清理旧答案与决策日志 */
export async function purgeLastAssistant(sessionId: number): Promise<void> {
  await apiJson(`/api/chat/sessions/${sessionId}/last-assistant`, { method: 'DELETE' })
}

/**
 * POST /api/chat/sessions/{session_id}/ask — SSE 问答流（核心接口）
 * fetch + ReadableStream，经 SseParser 解析回调；
 * images 为多模态图片引用（data URL 新上传 / 站内 URL 重答复用）；
 * 落库（用户/assistant 消息 + 决策日志）由后端完成（事件与日志同源）
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
    // 用户主动中断：吸收 AbortError，其余上抛
    if ((err as DOMException)?.name === 'AbortError') return
    throw err
  }
  for (const event of parser.feed(decoder.decode())) {
    onEvent(event)
  }
}

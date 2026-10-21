import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Chat API — SSE streaming Q&A is the core flow of this project.
 * Key contracts:
 *   - a non-2xx or bodyless response throws the backend detail (not a bare status code)
 *   - events are delivered one by one in arrival order
 *   - AbortError (user interruption) is absorbed and not rethrown
 *   - an event is only delivered when terminated by a blank line (\n\n); backend sse() always ends with \n\n
 */
vi.mock('../http', async () => {
  const actual = await vi.importActual<typeof import('../http')>('../http')
  return { ...actual, apiJson: vi.fn(), jsonInit: actual.jsonInit }
})

import { ask, createSession, deleteSession, getMessages, listSessions, purgeLastAssistant } from '../chat'
import { apiJson } from '../http'

const mockApiJson = apiJson as unknown as ReturnType<typeof vi.fn>

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn())
})


describe('chat api (非流式)', () => {
  it('createSession 走 POST /api/chat/sessions', async () => {
    mockApiJson.mockResolvedValue({ id: 1, title: '新会话' })
    expect(await createSession()).toEqual({ id: 1, title: '新会话' })
    expect(mockApiJson).toHaveBeenCalledWith('/api/chat/sessions', { method: 'POST' })
  })

  it('listSessions 走 GET', async () => {
    mockApiJson.mockResolvedValue([])
    await listSessions()
    expect(mockApiJson).toHaveBeenCalledWith('/api/chat/sessions')
  })

  it('getMessages 带会话 id', async () => {
    mockApiJson.mockResolvedValue([])
    await getMessages(7)
    expect(mockApiJson).toHaveBeenCalledWith('/api/chat/sessions/7/messages')
  })

  it('deleteSession 走 DELETE', async () => {
    mockApiJson.mockResolvedValue(undefined)
    await deleteSession(7)
    expect(mockApiJson).toHaveBeenCalledWith('/api/chat/sessions/7', { method: 'DELETE' })
  })

  it('purgeLastAssistant 走 DELETE last-assistant', async () => {
    mockApiJson.mockResolvedValue(undefined)
    await purgeLastAssistant(7)
    expect(mockApiJson).toHaveBeenCalledWith('/api/chat/sessions/7/last-assistant', { method: 'DELETE' })
  })
})

describe('ask (SSE 流式问答)', () => {
  it('逐个回调解析出的事件', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      body: streamOf([
        'event: retrieve\ndata: {"step":3,"hit_count":2}\n\n',
        'event: done\ndata: {"step":0}\n\n',
      ]),
    })
    const seen: any[] = []
    await ask(1, '问题', (e) => seen.push(e))
    expect(seen.map((e) => e.type)).toEqual(['retrieve', 'done'])
    expect(seen[0].hit_count).toBe(2)
  })

  it('请求体带 question / skip_user_persist / images', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, body: streamOf([]) })
    await ask(1, '问题', () => {}, undefined, true, ['data:image/png;base64,AA=='])
    const [, init] = (fetch as any).mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({
      question: '问题',
      skip_user_persist: true,
      images: ['data:image/png;base64,AA=='],
    })
  })

  it('不带图片时 images 为空数组', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, body: streamOf([]) })
    await ask(1, '问题', () => {})
    const [, init] = (fetch as any).mock.calls[0]
    expect(JSON.parse(init.body).images).toEqual([])
  })

  it('非 2xx 时抛后端 detail', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: false,
      status: 404,
      body: null,
      json: async () => ({ detail: '会话不存在' }),
    })
    await expect(ask(1, 'q', () => {})).rejects.toThrow('会话不存在')
  })

  it('响应无 body 时抛错', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, body: null })
    await expect(ask(1, 'q', () => {})).rejects.toThrow('HTTP 200')
  })

  it('错误体非 JSON 时回退到状态码', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: false,
      status: 500,
      body: null,
      json: async () => {
        throw new Error('bad')
      },
    })
    await expect(ask(1, 'q', () => {})).rejects.toThrow('HTTP 500')
  })

  it('用户中断（AbortError）被吸收，不上抛', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            const err = new Error('aborted')
            err.name = 'AbortError'
            throw err
          },
        }),
      },
    })
    await expect(ask(1, 'q', () => {})).resolves.toBeUndefined()
  })

  it('非 Abort 的读取错误照常上抛', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            throw new Error('网络断了')
          },
        }),
      },
    })
    await expect(ask(1, 'q', () => {})).rejects.toThrow('网络断了')
  })

  it('以空行结束的事件正常送达', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      body: streamOf(['event: done\ndata: {"step":0}\n\n']),
    })
    const seen: any[] = []
    await ask(1, 'q', (e) => seen.push(e))
    expect(seen.map((e) => e.type)).toEqual(['done'])
  })

  it('未以空行结束的尾事件按 SSE 规范丢弃', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      body: streamOf(['event: done\ndata: {"step":0}\n']),
    })
    const seen: any[] = []
    await ask(1, 'q', (e) => seen.push(e))
    expect(seen).toEqual([])
  })
})

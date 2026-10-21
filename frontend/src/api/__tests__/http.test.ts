import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiJson, jsonInit } from '../http'

/**
 * HTTP base layer — the single exit point for every backend call.
 * Key contract: a non-2xx response throws the backend detail/message (not a bare HTTP status),
 * and Accept-Language is always attached (the backend uses it to pick the copy).
 */
describe('apiJson', () => {
  beforeEach(() => {
    // apiJson reads the locale store, so pinia must be active first
    setActivePinia(createPinia())
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('成功时返回解析后的 JSON', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: 1, name: '制度库' }],
    })
    const r = await apiJson<{ id: number; name: string }[]>('/api/admin/kb')
    expect(r).toEqual([{ id: 1, name: '制度库' }])
    expect(fetch).toHaveBeenCalledWith('/api/admin/kb', expect.anything())
  })

  it('自动附加 Accept-Language 头', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    await apiJson('/api/x')
    const [, init] = (fetch as any).mock.calls[0]
    expect(init.headers['Accept-Language']).toBeTruthy()
  })

  it('保留调用方自带的请求头', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    await apiJson('/api/x', { headers: { 'X-Custom': 'v' } })
    const [, init] = (fetch as any).mock.calls[0]
    expect(init.headers['X-Custom']).toBe('v')
    expect(init.headers['Accept-Language']).toBeTruthy()
  })

  it('非 2xx 时抛出后端 detail', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: '仅允许 SELECT 查询' }),
    })
    await expect(apiJson('/api/x')).rejects.toThrow('仅允许 SELECT 查询')
  })

  it('后端只给 message 时抛 message', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ message: '内部错误' }),
    })
    await expect(apiJson('/api/x')).rejects.toThrow('内部错误')
  })

  it('错误体不是 JSON 时回退到 HTTP 状态码', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => {
        throw new Error('not json')
      },
    })
    await expect(apiJson('/api/x')).rejects.toThrow('HTTP 503')
  })

  it('错误体既无 detail 也无 message 时回退到状态码', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({}),
    })
    await expect(apiJson('/api/x')).rejects.toThrow('HTTP 404')
  })
})


describe('jsonInit', () => {
  it('构造 JSON 请求初始化对象', () => {
    const init = jsonInit('POST', { name: '库' })
    expect(init.method).toBe('POST')
    expect((init.headers as any)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({ name: '库' })
  })
})

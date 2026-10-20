import { useLocaleStore } from '@/stores/locale'

/* ============================================================
 * HTTP 基础层 — fetch 封装（后端 FastAPI :8000，经 vite 代理）
 * ============================================================ */

/** JSON 请求封装：非 2xx 抛出后端 message（FastAPI HTTPException detail）；自动附加 Accept-Language */
export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const locale = useLocaleStore().locale
  const r = await fetch(path, {
    ...init,
    headers: { ...(init?.headers as Record<string, string> | undefined), 'Accept-Language': locale },
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const j = (await r.json()) as { detail?: string; message?: string }
      msg = j?.detail || j?.message || msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return (await r.json()) as T
}

export function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

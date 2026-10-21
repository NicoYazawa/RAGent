import { useLocaleStore } from '@/stores/locale'

/* ============================================================
 * HTTP base layer — fetch wrapper (backend FastAPI on :8000, reached through the vite proxy)
 * ============================================================ */

/** JSON request wrapper: a non-2xx response throws the backend message (FastAPI HTTPException detail); Accept-Language is attached automatically */
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

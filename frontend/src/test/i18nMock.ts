import zhCN from '@/i18n/locales/zh-CN'

/**
 * Test translator: queries the real zh-CN bundle directly,
 * so assertions hit real copy instead of a fake translator that returns the key.
 */

type Messages = Record<string, unknown>

function lookup(messages: Messages, key: string): unknown {
  let cur: unknown = messages
  for (const seg of key.split('.')) {
    if (cur === null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[seg]
  }
  return cur
}

/** Resolve an 'a.b.c' path and interpolate {param}; a missing key falls back to the key itself (same as vue-i18n) */
export function translate(key: string, params?: Record<string, unknown>): string {
  const raw = lookup(zhCN as Messages, key)
  if (typeof raw !== 'string') return key
  if (!params) return raw
  return raw.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m))
}

/** Factory for vi.mock('vue-i18n'): keeps the real exports and replaces only useI18n */
export async function createI18nMock(importOriginal: () => Promise<unknown>): Promise<Record<string, unknown>> {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    useI18n: () => ({ t: translate, locale: 'zh-CN' }),
  }
}

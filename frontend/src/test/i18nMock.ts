import zhCN from '@/i18n/locales/zh-CN'

/**
 * 测试用翻译器：直接查真实的 zh-CN 语言包，
 * 保证断言命中的是真实文案（而不是把 key 当翻译的假翻译）。
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

/** 解析 'a.b.c' 路径并做 {param} 插值；缺失时回退为 key 本身（与 vue-i18n 行为一致） */
export function translate(key: string, params?: Record<string, unknown>): string {
  const raw = lookup(zhCN as Messages, key)
  if (typeof raw !== 'string') return key
  if (!params) return raw
  return raw.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m))
}

/** 供 vi.mock('vue-i18n') 使用的工厂：保留真实导出，仅替换 useI18n */
export async function createI18nMock(importOriginal: () => Promise<unknown>): Promise<Record<string, unknown>> {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    useI18n: () => ({ t: translate, locale: 'zh-CN' }),
  }
}

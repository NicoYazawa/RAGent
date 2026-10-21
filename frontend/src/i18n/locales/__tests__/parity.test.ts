import { describe, expect, it } from 'vitest'
import zhCN from '../zh-CN'
import enUS from '../en-US'

/** Recursively flatten into a list of leaf keys shaped like "a.b.c". */
function leafKeys(obj: unknown, prefix = ''): string[] {
  if (typeof obj !== 'object' || obj === null) return [prefix]
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    leafKeys(v, prefix ? `${prefix}.${k}` : k),
  )
}

/** Recursively collect every leaf string value. */
function leafValues(obj: unknown): string[] {
  if (typeof obj === 'string') return [obj]
  if (typeof obj !== 'object' || obj === null) return []
  return Object.values(obj as Record<string, unknown>).flatMap(leafValues)
}

describe('i18n locale parity', () => {
  it('zh-CN / en-US key 树完全一致', () => {
    expect(leafKeys(enUS).sort()).toEqual(leafKeys(zhCN).sort())
  })

  it('两种语言都不存在空字符串文案', () => {
    expect(leafValues(zhCN).filter((v) => v.trim() === '')).toEqual([])
    expect(leafValues(enUS).filter((v) => v.trim() === '')).toEqual([])
  })

  it('key 树无重复（展开后长度一致）', () => {
    const zh = leafKeys(zhCN)
    expect(new Set(zh).size).toBe(zh.length)
  })
})

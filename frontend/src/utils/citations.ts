import type { Citation } from '@/api/types'

/** 新引用显式携带编号；历史数组按正文中编号首次出现的顺序存储。 */
export function citationNumber(citation: Citation, index: number, answer: string): number {
  if (citation.ref_id !== undefined) return citation.ref_id
  const numbers = [...new Set([...answer.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])).filter((n) => n > 0))]
  return numbers[index] ?? index + 1
}

import type { Citation } from '@/api/types'

/** New citations carry their number explicitly; legacy arrays are ordered by first appearance in the text. */
export function citationNumber(citation: Citation, index: number, answer: string): number {
  if (citation.ref_id !== undefined) return citation.ref_id
  const numbers = [...new Set([...answer.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])).filter((n) => n > 0))]
  return numbers[index] ?? index + 1
}

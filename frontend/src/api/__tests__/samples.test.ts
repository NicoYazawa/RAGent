import { describe, expect, it } from 'vitest'
import { SAMPLE_QUESTIONS } from '@/api/samples'

/**
 * Sample questions (static data) — data integrity contract:
 *   unique ids, non-empty labels and questions, all three document domains covered
 */

describe('SAMPLE_QUESTIONS', () => {
  it('提供 6 条示例问题', () => {
    expect(SAMPLE_QUESTIONS).toHaveLength(6)
  })

  it('id 唯一', () => {
    const ids = SAMPLE_QUESTIONS.map((q) => q.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('每条都有非空标签与问题文本', () => {
    for (const q of SAMPLE_QUESTIONS) {
      expect(q.label.trim(), `示例 ${q.id} 缺少标签`).not.toBe('')
      expect(q.question.trim(), `示例 ${q.id} 缺少问题`).not.toBe('')
    }
  })

  it('覆盖考勤/休假/报销/组织/检索/数据恢复六类场景', () => {
    const ids = SAMPLE_QUESTIONS.map((q) => q.id)
    expect(ids).toEqual(
      expect.arrayContaining(['attendance', 'annual-leave', 'travel', 'org', 'rag', 'db-recovery']),
    )
  })
})

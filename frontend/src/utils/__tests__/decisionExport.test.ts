import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Decision-chain export — turns the Q&A decision chain into Markdown / JSON for tutorials and triage archives.
 * Key contracts:
 *   - pipes inside Markdown tables must be escaped (otherwise the table breaks)
 *   - durations under 1s render in ms, otherwise as seconds with one decimal
 *   - missing token usage renders as a placeholder instead of undefined
 */
const MESSAGES: Record<string, string> = {
  'chat.pipeline.stage1': '意图判定',
  'chat.pipeline.stage2': '查询改写',
  'chat.pipeline.stage3': '知识检索',
  'export.stepType.generate': '生成',
  'export.stepType.decision': '决策',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    // a registered key returns its translation; an unregistered one returns the key itself (same as vue-i18n)
    t: (key: string, params?: Record<string, unknown>) =>
      key in MESSAGES ? MESSAGES[key] : params ? `${key}:${JSON.stringify(params)}` : key,
  }),
}))

import { buildDecisionJson, copyText, downloadDecisionJson, fmtMs, stepName, toDecisionMarkdown } from '../decisionExport'
import type { DecisionCard } from '@/stores/chat'

const card = (over: Record<string, unknown> = {}): DecisionCard =>
  ({
    uid: 1,
    ts: 0,
    step: 1,
    type: 'router',
    status: 'done',
    detail: '命中知识问答',
    round: 0,
    elapsedMs: 120,
    payload: { intent: 'kb_qa' },
    ...over,
  }) as DecisionCard

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('fmtMs', () => {
  it('小于 1 秒显示毫秒', () => {
    expect(fmtMs(0)).toBe('0ms')
    expect(fmtMs(999)).toBe('999ms')
  })

  it('大于等于 1 秒显示一位小数秒', () => {
    expect(fmtMs(1000)).toBe('1.0s')
    expect(fmtMs(1234)).toBe('1.2s')
  })
})

describe('stepName', () => {
  it('按 step 优先取阶段名', () => {
    expect(stepName(card({ step: 3 }))).toBe('知识检索')
  })

  it('step 为 0 时回退到类型标签', () => {
    expect(stepName(card({ step: 0, type: 'generate' }))).toBe('生成')
  })

  it('未知类型回退到通用标签', () => {
    expect(stepName(card({ step: 0, type: 'unknown-type' }))).toBe('决策')
  })

  it('阶段名缺失时回退到类型标签', () => {
    // step 9 has no translation -> t() returns the key -> the type label fallback applies
    expect(stepName(card({ step: 9 }))).toBe('意图判定')
  })
})

describe('toDecisionMarkdown', () => {
  it('包含标题、问题与表头', () => {
    const md = toDecisionMarkdown('迟到怎么认定', [card()], null)
    expect(md).toContain('# export.title')
    expect(md).toContain('export.question')
    expect(md).toContain('|---|------|------|------|------|')
  })

  it('渲染阶段名而不是原始 key', () => {
    const md = toDecisionMarkdown('q', [card({ step: 3 })], null)
    expect(md).toContain('知识检索')
  })

  it('转义表格里的竖线', () => {
    const md = toDecisionMarkdown('q', [card({ detail: 'a|b' })], null)
    expect(md).toContain('a\\|b')
  })

  it('空 detail 渲染为占位符', () => {
    const md = toDecisionMarkdown('q', [card({ detail: '' })], null)
    expect(md).toMatch(/\|\s-\s\|/)
  })

  it('warn 状态使用告警文案', () => {
    const md = toDecisionMarkdown('q', [card({ status: 'warn' })], null)
    expect(md).toContain('export.statusWarn')
  })

  it('round > 0 时标注轮次', () => {
    const md = toDecisionMarkdown('q', [card({ round: 2 })], null)
    expect(md).toContain('（R2）')
  })

  it('无 stats 时不输出汇总行', () => {
    expect(toDecisionMarkdown('q', [card()], null)).not.toContain('export.summary')
  })

  it('有 token 用量时输出汇总', () => {
    const md = toDecisionMarkdown('q', [card()], { elapsedMs: 1200, rounds: 2, prompt: 10, completion: 20 })
    expect(md).toContain('export.summary')
    expect(md).toContain('30')
  })

  it('缺 token 用量时用占位符而非 undefined', () => {
    const md = toDecisionMarkdown('q', [card()], { elapsedMs: 10, rounds: 1 })
    expect(md).not.toContain('undefined')
    expect(md).toContain('—')
  })
})

describe('buildDecisionJson', () => {
  it('输出与 agent_decision_log 对齐的结构', () => {
    const j = buildDecisionJson('问题', [card()], { elapsedMs: 100, rounds: 1, prompt: 1, completion: 2 })
    expect(j.question).toBe('问题')
    expect(j.steps[0]).toMatchObject({ step: 1, type: 'router', elapsed_ms: 120 })
    expect(j.summary).toEqual({
      elapsed_ms: 100,
      total_rounds: 1,
      token_usage: { prompt: 1, completion: 2 },
    })
    expect(typeof j.exported_at).toBe('string')
  })

  it('无 stats 时 summary 为 null', () => {
    expect(buildDecisionJson('q', [], null).summary).toBeNull()
  })

  it('缺 token 用量时 token_usage 为 null', () => {
    const j = buildDecisionJson('q', [], { elapsedMs: 1, rounds: 1 })
    expect(j.summary?.token_usage).toBeNull()
  })
})

describe('downloadDecisionJson', () => {
  it('触发浏览器下载并回收 object URL', () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    downloadDecisionJson('q', [card()], null)

    expect(createObjectURL).toHaveBeenCalled()
    expect(click).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
    vi.unstubAllGlobals()
  })
})

describe('copyText', () => {
  it('clipboard API 可用时直接复制', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    expect(await copyText('文本')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('文本')
    vi.unstubAllGlobals()
  })

  it('clipboard 不可用时降级到 execCommand', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    const execCommand = vi.fn().mockReturnValue(true)
    ;(document as any).execCommand = execCommand

    expect(await copyText('文本')).toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
    // the temporary textarea used for the fallback must be removed
    expect(document.querySelectorAll('textarea').length).toBe(0)
    vi.unstubAllGlobals()
  })

  it('降级路径复制失败时返回 false', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    ;(document as any).execCommand = vi.fn().mockReturnValue(false)
    expect(await copyText('文本')).toBe(false)
    vi.unstubAllGlobals()
  })
})

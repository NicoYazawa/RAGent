import { useI18n } from 'vue-i18n'
import type { DecisionCard } from '@/stores/chat'

/* ============================================================
 * Decision-chain export — Markdown (copy/download) and JSON (download)
 * Timeline cards serve both tutorials and triage archives
 * ============================================================ */

export interface DecisionExportStats {
  elapsedMs: number
  rounds: number
  prompt?: number
  completion?: number
}

/** Event type to i18n key (aligned with chat.pipeline.stageN; generate/reflect/done/error have their own labels) */
const TYPE_KEY: Record<string, string> = {
  router: 'chat.pipeline.stage1',
  rewrite: 'chat.pipeline.stage2',
  retrieve: 'chat.pipeline.stage3',
  grade: 'chat.pipeline.stage4',
  correct: 'chat.pipeline.stage5',
  generate: 'export.stepType.generate',
  reflect: 'export.stepType.reflect',
  citation: 'chat.pipeline.stage7',
  done: 'export.stepType.done',
  error: 'export.stepType.error',
}

export function stepName(card: DecisionCard): string {
  const { t } = useI18n({ useScope: 'global' })
  const typeLabel = t(TYPE_KEY[card.type] ?? 'export.stepType.decision')
  if (card.step > 0) {
    const key = `chat.pipeline.stage${card.step}`
    const stage = t(key)
    return stage === key ? typeLabel : stage
  }
  return typeLabel
}

/** Duration formatting: under 1s shows ms, otherwise seconds with one decimal */
export function fmtMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** Decision chain to Markdown */
export function toDecisionMarkdown(question: string, cards: DecisionCard[], stats: DecisionExportStats | null): string {
  const { t } = useI18n({ useScope: 'global' })
  const lines: string[] = []
  lines.push(`# ${t('export.title')}`, '')
  lines.push(t('export.question', { q: question }), '')
  lines.push(t('export.note'), '')
  lines.push(t('export.tableHeader'), '|---|------|------|------|------|')
  for (const c of cards) {
    const no = c.step > 0 ? c.step : '-'
    const status = c.status === 'warn' ? t('export.statusWarn') : t('export.statusDone')
    const detail = c.detail.replace(/\|/g, '\\|') || '-'
    lines.push(`| ${no} | ${stepName(c)}${c.round > 0 ? `（R${c.round}）` : ''} | ${status} | ${fmtMs(c.elapsedMs)} | ${detail} |`)
  }
  lines.push('')
  if (stats) {
    const tokens = stats.prompt != null && stats.completion != null ? `${stats.prompt + stats.completion} (prompt ${stats.prompt} / completion ${stats.completion})` : '—'
    lines.push(t('export.summary', { elapsed: fmtMs(stats.elapsedMs), tokens, rounds: stats.rounds }))
  }
  lines.push('')
  return lines.join('\n')
}

/** Decision chain to a serializable JSON structure (aligned with agent_decision_log fields) */
export function buildDecisionJson(question: string, cards: DecisionCard[], stats: DecisionExportStats | null) {
  return {
    question,
    exported_at: new Date().toISOString(),
    steps: cards.map((c) => ({
      step: c.step,
      type: c.type,
      detail: c.detail,
      status: c.status,
      round: c.round,
      elapsed_ms: c.elapsedMs,
      payload: c.payload,
    })),
    summary: stats
      ? {
          elapsed_ms: stats.elapsedMs,
          total_rounds: stats.rounds,
          token_usage: stats.prompt != null && stats.completion != null ? { prompt: stats.prompt, completion: stats.completion } : null,
        }
      : null,
  }
}

/** Trigger a browser download of the JSON file */
export function downloadDecisionJson(question: string, cards: DecisionCard[], stats: DecisionExportStats | null): void {
  const blob = new Blob([JSON.stringify(buildDecisionJson(question, cards, stats), null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')
  a.href = url
  a.download = `decision-chain-${stamp}.json`
  a.click()
  URL.revokeObjectURL(url)
}

/** Copy text (clipboard API with an execCommand fallback) */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  }
}

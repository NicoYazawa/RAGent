<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DecisionCard } from '@/stores/chat'
import { fmtMs } from '@/utils/decisionExport'

/**
 * Decision-chain timing bar — share of time per stage (waiting transition cards are skipped),
 * segment width = elapsedMs / total; hovering shows the stage name and duration
 */
const props = defineProps<{ cards: DecisionCard[] }>()

interface Segment {
  key: string
  label: string
  ms: number
  ratio: number
  color: string
  warn: boolean
}

const STEP_COLOR: Record<string, string> = {
  router: 'var(--color-src-keyword)',
  rewrite: 'var(--color-src-vector)',
  retrieve: 'var(--color-src-db)',
  grade: 'var(--color-warn)',
  correct: 'var(--color-warn)',
  generate: 'var(--color-accent)',
  reflect: 'var(--color-ok)',
  citation: 'var(--color-accent-dim)',
  error: 'var(--color-danger)',
}

const { t } = useI18n()

const segments = computed<Segment[]>(() => {
  const agg = new Map<string, { ms: number; warn: boolean }>()
  for (const c of props.cards) {
    if (c.elapsedMs <= 0) continue
    const cur = agg.get(c.type)
    agg.set(c.type, { ms: (cur?.ms ?? 0) + c.elapsedMs, warn: (cur?.warn ?? false) || c.status === 'warn' })
  }
  const list = [...agg.entries()].map(([key, v]) => ({ key, ...v }))
  const total = list.reduce((s, x) => s + x.ms, 0) || 1
  // stable sort by pipeline stage order; segments under 4% merge visually but keep their tooltip
  const ORDER = ['router', 'rewrite', 'retrieve', 'grade', 'correct', 'generate', 'reflect', 'citation', 'error']
  return list
    .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key))
    .map(({ key, ms, warn }) => ({
      key,
      label: t(`chat.timing.stage.${key}`) || key,
      ms,
      ratio: ms / total,
      color: warn ? 'var(--color-warn)' : (STEP_COLOR[key] ?? 'var(--color-accent-dim)'),
      warn,
    }))
})

const totalMs = computed(() => segments.value.reduce((s, x) => s + x.ms, 0))
</script>

<template>
  <div v-if="segments.length" class="anim-fade-up">
    <div class="flex items-center justify-between font-mono text-[11px] text-ink-mute">
      <span>{{ t('chat.timing.dist') }}</span>
      <span class="text-accent">{{ fmtMs(totalMs) }}</span>
    </div>
    <div class="mt-1.5 flex h-2 w-full gap-px overflow-hidden rounded-full border border-edge bg-raise">
      <div
        v-for="seg in segments"
        :key="seg.key"
        class="h-full transition-all duration-500"
        :style="{ width: `${Math.max(seg.ratio * 100, 1.2)}%`, backgroundColor: seg.color, opacity: seg.warn ? 0.95 : 0.75 }"
        :title="t('chat.timing.segTitle', { label: seg.label, ms: fmtMs(seg.ms), pct: (seg.ratio * 100).toFixed(0) }) + (seg.warn ? ' · slow' : '')"
      />
    </div>
    <!-- Legend: only the top 5 segments to avoid clutter -->
    <div class="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-1">
      <span v-for="seg in [...segments].sort((a, b) => b.ms - a.ms).slice(0, 5)" :key="seg.key" class="flex items-center gap-1 font-mono text-[11px] text-ink-mute">
        <span class="h-1.5 w-1.5 rounded-sm" :style="{ backgroundColor: seg.color }" />
        {{ seg.label }} {{ fmtMs(seg.ms) }}
      </span>
    </div>
  </div>
</template>

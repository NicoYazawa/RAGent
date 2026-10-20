<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import type { DecisionCard } from '@/stores/chat'
import { fmtMs } from '@/utils/decisionExport'

/** 决策步骤卡片 — 四态（pending 转圈 / done / warn）+ 回流轮次缩进 + 单步耗时 */
const props = defineProps<{ card: DecisionCard }>()

const { t } = useI18n()
const stageKey = (s: number) => `chat.pipeline.stage${s}`

const TYPE_ICON: Record<string, string> = {
  router: 'route',
  rewrite: 'refresh',
  retrieve: 'search',
  grade: 'check',
  correct: 'retry',
  reflect: 'brain',
  citation: 'link',
  generate: 'sparkles',
  done: 'check',
  error: 'alert',
}

const label = computed(() => (props.card.step === 0 ? t('chat.step.flow') : t(stageKey(props.card.step)) || t('chat.step.decision')))
const icon = computed(() => TYPE_ICON[props.card.type] ?? 'info')
const isPending = computed(() => props.card.status === 'pending')
const isWarn = computed(() => props.card.status === 'warn')
/** ts 为真实毫秒时间戳时才展示时钟（回放/日志卡片 ts=0 只看耗时） */
const hasClock = computed(() => props.card.ts > 1e12)
const showElapsed = computed(() => !isPending.value && props.card.elapsedMs > 0)

/** 检索来源 → 本地化 */
const sourceLabel = computed(() => {
  const s = props.card.payload.source as string | undefined
  return s ? t(`chat.source.${s}`) : null
})
</script>

<template>
  <div
    class="anim-slide-right group relative rounded-lg border px-3 py-2.5 transition-all duration-200"
    :class="[
      isWarn ? 'border-warn/40 bg-warn/5' : isPending ? 'border-edge bg-panel/60' : 'border-edge bg-card/80',
      card.round > 0 ? 'ml-5' : '',
    ]"
  >
    <!-- 回流轮次标签 -->
    <span
      v-if="card.round > 0"
      class="absolute -left-1.5 top-1/2 h-[calc(100%-0.75rem)] w-1 -translate-y-1/2 rounded-full bg-warn/50"
      :title="t('chat.step.round', { n: card.round })"
    />
    <div class="flex items-start gap-2.5">
      <!-- 状态图标 -->
      <div class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center">
        <span
          v-if="isPending"
          class="h-4 w-4 animate-spin rounded-full border-[1.5px] border-accent/70 border-t-transparent"
          :aria-label="t('chat.step.working')"
        />
        <Icon
          v-else
          :name="isWarn ? 'alert' : icon"
          :size="14"
          class="transition-colors"
          :class="isWarn ? 'text-warn' : card.type === 'router' ? 'text-accent' : 'text-ok'"
        />
      </div>

      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="font-mono text-[11px] tracking-wider" :class="isWarn ? 'text-warn/80' : 'text-ink-mute'">
            [{{ card.step === 0 ? '×' : card.step }}] {{ label }}
          </span>
          <span v-if="card.round > 0" class="rounded-sm bg-warn/15 px-1 font-mono text-[11px] text-warn"> R{{ card.round }} </span>
          <span class="flex-1" />
          <span v-if="showElapsed" class="flex items-center gap-0.5 font-mono text-[11px] text-accent/80" :title="t('chat.step.elapsed', { ms: card.elapsedMs })">
            <Icon name="clock" :size="10" />
            {{ fmtMs(card.elapsedMs) }}
          </span>
          <span v-if="!isPending && hasClock" class="font-mono text-[11px] text-ink-mute">{{ new Date(card.ts).toLocaleTimeString(undefined, { hour12: false }) }}</span>
        </div>

        <p class="mt-1 text-[13px] leading-relaxed" :class="isPending ? 'text-ink-dim' : isWarn ? 'text-warn/90' : 'text-ink/90'">
          {{ card.detail }}
        </p>

        <!-- 关键指标 -->
        <div v-if="!isPending && card.type !== 'error'" class="mt-1.5 flex flex-wrap items-center gap-1.5">
          <template v-if="card.type === 'router'">
            <span class="rounded border border-edge-bright bg-raise px-1.5 py-0.5 font-mono text-[11px] text-accent">{{ card.payload.intent }}</span>
            <span class="font-mono text-[11px] text-ink-mute">{{ t('chat.metric.confidence') }} {{ (((card.payload.confidence as number) ?? 0) * 100).toFixed(0) }}%</span>
          </template>
          <template v-else-if="card.type === 'retrieve' && sourceLabel">
            <span class="rounded border border-edge-bright bg-raise px-1.5 py-0.5 font-mono text-[11px] text-ink-dim">{{ sourceLabel }}{{ t('chat.source.suffix') }}</span>
            <span class="font-mono text-[11px] text-accent">{{ t('chat.metric.hits', { n: (card.payload.hit_count as number) ?? 0 }) }}</span>
          </template>
          <template v-else-if="card.type === 'grade'">
            <span class="rounded px-1.5 py-0.5 font-mono text-[11px]" :class="isWarn ? 'bg-warn/15 text-warn' : 'bg-ok/15 text-ok'">
              {{ ((card.payload.score as number) ?? 0).toFixed(1) }} {{ t('chat.metric.score') }}
            </span>
          </template>
          <template v-else-if="card.type === 'correct'">
            <span class="rounded bg-warn/15 px-1.5 py-0.5 font-mono text-[11px] text-warn">{{ card.payload.action }}</span>
          </template>
          <template v-else-if="card.type === 'reflect'">
            <span class="rounded px-1.5 py-0.5 font-mono text-[11px]" :class="isWarn ? 'bg-warn/15 text-warn' : 'bg-ok/15 text-ok'">
              {{ card.payload.result }}
            </span>
          </template>
          <template v-else-if="card.type === 'citation'">
            <span class="font-mono text-[11px] text-accent">{{ (card.payload.citations as unknown[] | undefined)?.length ?? 0 }} {{ t('chat.metric.citations') }}</span>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

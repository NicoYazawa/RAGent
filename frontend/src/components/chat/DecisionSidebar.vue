<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DecisionStepCard from './DecisionStepCard.vue'
import DecisionPipeline from './DecisionPipeline.vue'
import StepTimingBar from './StepTimingBar.vue'
import Icon from '@/components/ui/Icon.vue'
import ScoreRing from './ScoreRing.vue'
import { useChatStore } from '@/stores/chat'
import type { DecisionCard } from '@/stores/chat'
import { copyText, downloadDecisionJson, fmtMs, toDecisionMarkdown, type DecisionExportStats } from '@/utils/decisionExport'

/** 决策过程侧栏 — 时间线 / 管线流程图双模式 + 历史回放 + 耗时分布与导出（可折叠由父级控制） */
const { t } = useI18n()
const store = useChatStore()
const listRef = ref<HTMLDivElement>()

const mode = ref<'timeline' | 'pipeline'>('timeline')
const copied = ref(false)

/** 回看态优先：卡片流 / 统计均切换为历史日志 */
const viewing = computed(() => store.viewingLog)
const activeCards = computed<DecisionCard[]>(() => viewing.value?.cards ?? store.cards)
const exportable = computed(() => activeCards.value.length > 0)

/** 导出用问题文本：回看取日志问题，实时取会话最后一问 */
const exportQuestion = computed(() => viewing.value?.question ?? [...store.messages].reverse().find((m) => m.role === 'user')?.content ?? '')

const exportStats = computed<DecisionExportStats | null>(() => {
  if (viewing.value) return { elapsedMs: viewing.value.elapsedMs, rounds: viewing.value.totalRounds }
  if (store.doneStats) return { elapsedMs: store.doneStats.elapsed_ms, rounds: store.doneStats.rounds, prompt: store.doneStats.prompt, completion: store.doneStats.completion }
  return null
})

async function copyMarkdown(): Promise<void> {
  const ok = await copyText(toDecisionMarkdown(exportQuestion.value, activeCards.value, exportStats.value))
  if (ok) {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  }
}

function exportJson(): void {
  downloadDecisionJson(exportQuestion.value, activeCards.value, exportStats.value)
}

watch(
  () => store.cards.length + (store.pendingCard ? 1 : 0),
  async () => {
    if (mode.value !== 'timeline' || viewing.value) return
    await nextTick()
    listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: 'smooth' })
  },
)

const gradeCard = computed(() => [...activeCards.value].reverse().find((c) => c.type === 'grade'))
</script>

<template>
  <div class="flex h-full w-[328px] shrink-0 flex-col border-l border-edge bg-panel">
    <!-- 头部 -->
    <div class="border-b border-edge px-4 pt-3">
      <div class="flex items-center gap-2">
        <h2 class="text-[13px] font-medium text-ink">{{ t('chat.sidebar.title') }}</h2>
        <span
          class="ml-auto flex items-center gap-1.5 text-[11px]"
          :class="viewing ? 'text-ok' : store.streaming ? 'text-accent' : 'text-ink-mute'"
        >
          <span class="h-1.5 w-1.5 rounded-full" :class="viewing ? 'bg-ok' : store.streaming ? 'bg-accent' : 'bg-ink-mute'" />
          {{ viewing ? 'Replay' : store.streaming ? 'Live' : 'Idle' }}
        </span>
      </div>

      <!-- 模式切换 + 导出 -->
      <div class="mt-2.5 flex items-center gap-1 pb-2.5">
        <div class="flex items-center gap-3">
          <button
            v-for="m in ['timeline', 'pipeline'] as const"
            :key="m"
            type="button"
            class="relative pb-1.5 text-[12px] transition-colors duration-150"
            :class="mode === m ? 'text-ink' : 'text-ink-mute hover:text-ink-dim'"
            @click="mode = m"
          >
            {{ m === 'timeline' ? t('chat.sidebar.timeline') : t('chat.sidebar.flowMode') }}
            <span v-if="mode === m" class="absolute inset-x-0 bottom-0 h-px bg-accent" />
          </button>
        </div>
        <div class="flex-1" />
        <button
          type="button"
          class="flex h-6.5 w-6.5 items-center justify-center rounded-md transition-colors disabled:opacity-30"
          :class="copied ? 'text-ok' : 'text-ink-mute hover:bg-raise hover:text-ink'"
          :disabled="!exportable"
          :title="copied ? t('chat.sidebar.copied') : t('chat.sidebar.copy')"
          @click="copyMarkdown"
        >
          <Icon :name="copied ? 'check' : 'copy'" :size="13" />
        </button>
        <button
          type="button"
          class="flex h-6.5 w-6.5 items-center justify-center rounded-md text-ink-mute transition-colors hover:bg-raise hover:text-ink disabled:opacity-30"
          :disabled="!exportable"
          :title="t('chat.sidebar.exportJson')"
          @click="exportJson"
        >
          <Icon name="download" :size="13" />
        </button>
      </div>
    </div>

    <!-- 历史回放横幅 -->
    <div v-if="viewing" class="flex items-center gap-2 border-b border-edge bg-card px-4 py-2">
      <Icon name="play" :size="12" class="shrink-0 text-ok" />
      <div class="min-w-0 flex-1">
        <div class="font-mono text-[11px] text-ok">{{ t('chat.sidebar.replay', { id: viewing.id, steps: viewing.cards.length }) }}</div>
        <div class="truncate text-[11px] text-ink-dim">{{ viewing.question }}</div>
      </div>
      <button
        type="button"
        class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-mute transition-colors hover:bg-raise hover:text-danger"
        :title="t('chat.sidebar.exitReplay')"
        @click="store.exitViewing()"
      >
        <Icon name="x" :size="13" />
      </button>
    </div>

    <!-- 卡片流 / 流程图 -->
    <div v-show="mode === 'timeline'" ref="listRef" class="flex-1 space-y-2 overflow-y-auto px-3 py-3">
      <div v-if="activeCards.length === 0 && !store.pendingCard" class="flex flex-col items-center gap-3 px-4 pt-10 text-center">
        <Icon name="route" :size="22" class="text-ink-mute" />
        <p class="text-xs leading-relaxed text-ink-mute">
          {{ t('chat.sidebar.emptyLive') }}<br />
          <span class="font-mono">router → rewrite → retrieve → grade → generate → reflect → citation</span>
        </p>
      </div>

      <template v-else>
        <DecisionStepCard v-for="card in activeCards" :key="card.uid" :card="card" />
        <DecisionStepCard v-if="store.pendingCard && !viewing" :card="store.pendingCard" />
      </template>

      <!-- 异常 -->
      <div v-if="store.streamError && !viewing" class="anim-fade-up rounded-lg border border-danger/40 bg-danger/5 px-3 py-2.5">
        <div class="flex items-center gap-2 text-[13px] font-medium text-danger">
          <Icon name="alert" :size="14" />
          {{ t('chat.sidebar.chainBroken') }}
        </div>
        <p class="mt-1 font-mono text-[11px] leading-relaxed text-danger/80">{{ store.streamError }}</p>
      </div>
    </div>

    <div v-show="mode === 'pipeline'" class="flex-1 overflow-y-auto px-3 py-4">
      <DecisionPipeline
        :cards="activeCards"
        :streaming="store.streaming && !viewing"
        :active-stage="viewing ? 0 : store.activeStage"
        :pending="viewing ? null : store.pendingCard"
      />
    </div>

    <!-- 底部统计 -->
    <div class="space-y-2.5 border-t border-edge px-4 py-3">
      <StepTimingBar v-if="!store.streaming || viewing" :cards="activeCards" />

      <template v-if="viewing">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <Icon name="clock" :size="13" class="text-ok" />
            <span class="text-[11px] text-ink-dim">{{ t('chat.sidebar.historyLabel') }}</span>
          </div>
          <div class="flex items-center gap-3 font-mono text-[11px]">
            <span class="text-ink-mute">{{ t('chat.sidebar.elapsed') }}</span><span class="text-ink">{{ fmtMs(viewing.elapsedMs) }}</span>
            <span class="text-ink-mute">{{ t('chat.sidebar.rounds') }}</span><span class="text-ink">{{ viewing.totalRounds }}</span>
          </div>
        </div>
      </template>
      <template v-else-if="store.doneStats">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <Icon name="check" :size="13" class="text-ok" />
            <span class="text-[11px] text-ink-dim">{{ t('chat.sidebar.doneLabel') }}</span>
          </div>
          <div class="flex items-center gap-3 font-mono text-[11px]">
            <span class="text-ink-mute">{{ t('chat.sidebar.elapsed') }}</span><span class="text-ink">{{ (store.doneStats.elapsed_ms / 1000).toFixed(1) }}s</span>
            <span class="text-ink-mute">tokens</span><span class="text-ink">{{ store.doneStats.prompt + store.doneStats.completion }}</span>
            <span class="text-ink-mute">{{ t('chat.sidebar.rounds') }}</span><span class="text-ink">{{ store.doneStats.rounds }}</span>
          </div>
        </div>
      </template>
      <template v-else-if="!store.streaming">
        <div class="flex items-center gap-2">
          <ScoreRing v-if="gradeCard" :score="(gradeCard.payload.score as number)" :size="40" />
          <div class="font-mono text-[11px] leading-relaxed text-ink-mute">
            {{ t('chat.sidebar.waitPrompt') }}<br />
            {{ t('chat.sidebar.replayHint') }}
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

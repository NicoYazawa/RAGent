<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DecisionStepCard from '@/components/chat/DecisionStepCard.vue'
import Icon from '@/components/ui/Icon.vue'
import type { DecisionCard } from '@/stores/chat'
import type { DecisionStep } from '@/api/types'

const { t } = useI18n()

/**
 * Decision-chain player — steps share the shape of the SSE events and replay the stream offline
 * Controls: previous / play-pause / next / reset / speed (1x 2x 4x)
 */
const props = defineProps<{ steps: DecisionStep[] }>()

const SPEEDS = [1, 2, 4] as const
const speedIdx = ref(0)
const playing = ref(false)
const cursor = ref(0) // number of steps shown (0 = not started)
let timer: ReturnType<typeof setInterval> | null = null

const intervalMs = computed(() => 950 / SPEEDS[speedIdx.value])

function play(): void {
  if (cursor.value >= props.steps.length) cursor.value = 0
  playing.value = true
  timer = setInterval(() => {
    if (cursor.value >= props.steps.length) {
      pause()
      return
    }
    cursor.value++
  }, intervalMs.value)
}

function pause(): void {
  playing.value = false
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function reset(): void {
  pause()
  cursor.value = 0
}

function stepBy(delta: number): void {
  pause()
  cursor.value = Math.max(0, Math.min(props.steps.length, cursor.value + delta))
}

function cycleSpeed(): void {
  speedIdx.value = (speedIdx.value + 1) % SPEEDS.length
  if (playing.value) {
    pause()
    play()
  }
}

watch(
  () => props.steps,
  () => reset(),
)

onBeforeUnmount(pause)

/** DecisionStep to DecisionCard (backflow rounds derived; elapsed_ms is the per-step duration) */
const cards = computed<DecisionCard[]>(() => {
  const out: DecisionCard[] = []
  let round = 0
  for (const step of props.steps) {
    if (step.type === 'correct') round = Math.max(round, (step.payload.round as number) ?? round)
    if (step.type === 'reflect' && step.payload.result === 'fail') round += 1
    const warn =
      (step.type === 'grade' && step.payload.verdict !== 'pass') ||
      step.type === 'correct' ||
      (step.type === 'reflect' && step.payload.result === 'fail')
    out.push({
      uid: out.length + 1,
      step: step.step,
      type: step.type,
      status: warn ? 'warn' : 'done',
      detail: step.detail,
      payload: step.payload,
      ts: 0,
      round: step.type === 'correct' || step.type === 'reflect' ? Math.max(0, round) : round === 0 ? 0 : round,
      elapsedMs: step.elapsed_ms,
    })
  }
  return out
})

const progress = computed(() => (props.steps.length ? Math.round((cursor.value / props.steps.length) * 100) : 0))
</script>

<template>
  <div class="space-y-3">
    <!-- Control bar -->
    <div class="sticky top-0 z-10 rounded-lg border border-edge bg-panel/95 p-3">
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-md border border-edge text-ink-dim transition-colors hover:text-ink disabled:opacity-30"
          :disabled="cursor <= 0"
          :aria-label="t('logs.prevStep')"
          @click="stepBy(-1)"
        >
          <Icon name="chev-left" :size="14" />
        </button>
        <button
          type="button"
          class="flex h-9 w-9 items-center justify-center rounded-lg border transition-all duration-150 active:scale-95"
          :class="playing ? 'border-danger/50 bg-danger/15 text-danger' : 'border-edge-bright bg-raise text-accent hover:bg-raise'"
          :aria-label="playing ? t('logs.pause') : t('logs.play')"
          @click="playing ? pause() : play()"
        >
          <Icon :name="playing ? 'pause' : 'play'" :size="14" />
        </button>
        <button
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-md border border-edge text-ink-dim transition-colors hover:text-ink disabled:opacity-30"
          :disabled="cursor >= steps.length"
          :aria-label="t('logs.nextStep')"
          @click="stepBy(1)"
        >
          <Icon name="chev-right" :size="14" />
        </button>
        <button
          type="button"
          class="flex h-8 items-center gap-1 rounded-md border border-edge px-2 font-mono text-[11px] text-ink-dim transition-colors hover:text-ink"
          :title="t('logs.resetReplay')"
          @click="reset"
        >
          <Icon name="refresh" :size="12" /> {{ t('logs.reset') }}
        </button>

        <div class="flex-1" />

        <button
          type="button"
          class="rounded-md border border-edge-bright bg-raise px-2 py-1 font-mono text-[11px] text-accent transition-all duration-150 hover:bg-raise"
          :title="t('logs.speed')"
          @click="cycleSpeed"
        >
          {{ SPEEDS[speedIdx] }}x
        </button>
        <span class="font-mono text-[11px] text-ink-mute">{{ t('logs.steps', { n: `${cursor}/${steps.length}` }) }}</span>
      </div>

      <!-- Progress bar -->
      <div class="mt-2.5 h-1 overflow-hidden rounded-full bg-raise">
        <div
          class="h-full rounded-full bg-accent transition-all duration-300"
          :style="{ width: `${progress}%` }"
        />
      </div>
    </div>

    <!-- Step cards -->
    <div class="space-y-2">
      <div v-if="cursor === 0" class="rounded-lg border border-dashed border-edge px-4 py-6 text-center font-mono text-[11px] text-ink-mute">
        {{ t('logs.replayHint') }}
      </div>
      <TransitionGroup name="replay">
        <DecisionStepCard v-for="(card, i) in cards.slice(0, cursor)" :key="card.uid" :card="card" :data-index="i" />
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.replay-enter-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.replay-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
</style>

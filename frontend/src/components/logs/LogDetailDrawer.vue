<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import BaseTag from '@/components/ui/BaseTag.vue'
import Icon from '@/components/ui/Icon.vue'
import StepPlayer from './StepPlayer.vue'
import MarkdownText from '@/components/chat/MarkdownText.vue'
import type { DecisionLog } from '@/api/types'
import { useDecisionLogStore } from '@/stores/decisionLog'

/** 日志详情抽屉：基本信息 + 最终答案 + 决策链回放 */
const props = defineProps<{ open: boolean; logId: number | null }>()
const emit = defineEmits<{ close: [] }>()

const store = useDecisionLogStore()
const detail = ref<DecisionLog | null>(null)
const loading = ref(false)
const tab = ref<'replay' | 'answer'>('replay')
const { t } = useI18n()

watch(
  () => [props.open, props.logId] as const,
  async ([open, id]) => {
    if (open && id != null) {
      loading.value = true
      tab.value = 'replay'
      try {
        detail.value = await store.getDetail(id)
      } finally {
        loading.value = false
      }
    } else {
      detail.value = null
    }
  },
  { immediate: true },
)

function fmt(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { hour12: false })
}
</script>

<template>
  <BaseDrawer :open="open" :title="t('logs.detailTitle', { id: logId })" width="600px" @close="emit('close')">
    <div v-if="loading" class="space-y-3 py-4">
      <div v-for="i in 5" :key="i" class="h-16 animate-pulse rounded-lg border border-edge bg-card/50" />
    </div>

    <div v-else-if="detail" class="space-y-4 pb-6">
      <!-- 基本信息 -->
      <div class="rounded-xl border border-edge bg-card/70 p-4">
        <div class="flex items-start gap-2.5">
          <Icon name="chat" :size="15" class="mt-0.5 shrink-0 text-accent" />
          <p class="text-[13.5px] font-medium leading-relaxed text-ink">{{ detail.question }}</p>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <BaseTag tone="mute"><Icon name="clock" :size="10" /> {{ fmt(detail.created_at) }}</BaseTag>
          <BaseTag tone="mute">session #{{ detail.session_id }}</BaseTag>
          <BaseTag tone="mute">msg #{{ detail.message_id }}</BaseTag>
          <BaseTag tone="accent">{{ t('logs.steps', { n: detail.steps.length }) }}</BaseTag>
          <BaseTag :tone="detail.total_rounds > 1 ? 'warn' : 'ok'">{{ t('logs.roundsRetrieve', { n: detail.total_rounds }) }}</BaseTag>
          <BaseTag tone="accent">{{ (detail.elapsed_ms / 1000).toFixed(1) }}s</BaseTag>
        </div>
      </div>

      <!-- Tab 切换 -->
      <div class="flex items-center gap-1 rounded-lg border border-edge bg-panel/60 p-1">
        <button
          type="button"
          class="flex-1 rounded-md px-3 py-1.5 text-[12.5px] transition-all duration-150"
          :class="tab === 'replay' ? 'bg-raise text-accent' : 'text-ink-mute hover:text-ink'"
          @click="tab = 'replay'"
        >
          <Icon name="play" :size="12" class="mr-1 inline" />{{ t('logs.tabReplay') }}
        </button>
        <button
          type="button"
          class="flex-1 rounded-md px-3 py-1.5 text-[12.5px] transition-all duration-150"
          :class="tab === 'answer' ? 'bg-raise text-accent' : 'text-ink-mute hover:text-ink'"
          @click="tab = 'answer'"
        >
          <Icon name="file" :size="12" class="mr-1 inline" />{{ t('logs.tabAnswer') }}
        </button>
      </div>

      <StepPlayer v-if="tab === 'replay'" :steps="detail.steps" />

      <div v-else class="rounded-xl border border-edge bg-card/70 px-4 py-3">
        <MarkdownText :text="detail.final_answer" />
      </div>
    </div>
  </BaseDrawer>
</template>

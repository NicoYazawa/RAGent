<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseEmpty from '@/components/ui/BaseEmpty.vue'
import BasePagination from '@/components/ui/BasePagination.vue'
import BaseTag from '@/components/ui/BaseTag.vue'
import LogDetailDrawer from '@/components/logs/LogDetailDrawer.vue'
import { useDecisionLogStore } from '@/stores/decisionLog'

const { t } = useI18n()

/** Decision log panel: filters (session/time range), paginated timeline and single-entry replay */
const store = useDecisionLogStore()
const drawerOpen = ref(false)
const activeLogId = ref<number | null>(null)

onMounted(() => void store.query(1))

function search(): void {
  void store.query(1)
}

function openDetail(id: number): void {
  activeLogId.value = id
  drawerOpen.value = true
}

function fmt(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { hour12: false })
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Filter bar -->
    <div class="flex min-h-14 flex-wrap items-center gap-3 border-b border-edge px-4 py-2 md:px-6">
      <h1 class="text-[18px] font-semibold leading-tight text-ink">{{ t('logs.title') }}</h1>
      <span class="font-mono text-[11px] text-ink-mute">agent_decision_log</span>
      <div class="flex-1" />
      <div class="flex flex-wrap items-center gap-2">
        <div class="w-32">
          <BaseInput v-model="store.filterSessionId" :placeholder="t('logs.sessionIdPlaceholder')" mono />
        </div>
        <input
          v-model="store.filterStart"
          type="date"
          class="h-9 rounded-lg border border-edge bg-card px-2.5 font-mono text-[12px] text-ink-dim outline-none focus:border-accent/70"
          :aria-label="t('logs.startDate')"
        />
        <span class="text-[12px] text-ink-mute">{{ t('logs.to') }}</span>
        <input
          v-model="store.filterEnd"
          type="date"
          class="h-9 rounded-lg border border-edge bg-card px-2.5 font-mono text-[12px] text-ink-dim outline-none focus:border-accent/70"
          :aria-label="t('logs.endDate')"
        />
        <BaseButton size="sm" variant="ghost" :loading="store.loading" @click="search">
          <Icon name="search" :size="12" /> {{ t('logs.search') }}
        </BaseButton>
      </div>
    </div>

    <!-- Timeline list -->
    <div class="flex-1 overflow-y-auto px-6 py-5">
      <div v-if="store.loading" class="relative ml-3 space-y-4 border-l border-edge pl-6">
        <div v-for="i in 5" :key="i" class="h-[72px] animate-pulse rounded-lg border border-edge bg-card/50" />
      </div>

      <BaseEmpty v-else-if="store.logs.length === 0" icon="logs" :text="t('logs.empty')" />

      <div v-else class="relative ml-3 border-l border-edge pl-6">
        <button
          v-for="log in store.logs"
          :key="log.id"
          type="button"
          class="group relative mb-4 w-full rounded-lg border border-edge bg-card px-4 py-3.5 text-left transition-colors duration-150 hover:border-edge-bright"
          @click="openDetail(log.id)"
        >
          <!-- Timeline node -->
          <span
            class="absolute -left-[1.9rem] top-5 flex h-3 w-3 items-center justify-center rounded-full border-2 border-panel transition-colors group-hover:border-accent"
            :class="log.total_rounds > 1 ? 'bg-warn' : 'bg-accent'"
          />

          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0 flex-1">
              <p class="truncate text-[13.5px] font-medium text-ink">{{ log.question }}</p>
              <p class="mt-1 line-clamp-2 text-[13px] leading-relaxed text-ink-mute">{{ log.final_answer.replace(/[#*`>|]/g, '').slice(0, 120) }}…</p>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <BaseTag tone="mute"><Icon name="clock" :size="9" /> {{ fmt(log.created_at) }}</BaseTag>
                <BaseTag tone="mute">session #{{ log.session_id }}</BaseTag>
                <BaseTag tone="accent">{{ t('logs.steps', { n: log.steps.length }) }}</BaseTag>
                <BaseTag :tone="log.total_rounds > 1 ? 'warn' : 'ok'">{{ t('logs.rounds', { n: log.total_rounds }) }}</BaseTag>
                <BaseTag tone="accent">{{ (log.elapsed_ms / 1000).toFixed(1) }}s</BaseTag>
              </div>
            </div>
            <span class="mt-1 flex shrink-0 items-center gap-1 text-[11px] text-ink-mute transition-colors group-hover:text-ink-dim">
              {{ t('logs.replay') }}
              <Icon name="chev-right" :size="12" />
            </span>
          </div>
        </button>
      </div>

      <!-- Pagination -->
      <div v-if="!store.loading && store.total > 0" class="mt-2 flex justify-center">
        <BasePagination :page="store.page" :page-size="store.pageSize" :total="store.total" @change="(p) => store.query(p)" />
      </div>
    </div>

    <LogDetailDrawer :open="drawerOpen" :log-id="activeLogId" @close="drawerOpen = false" />
  </div>
</template>

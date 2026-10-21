<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '@/stores/chat'

/** Left column: session list (create / switch / delete) */
const { t } = useI18n()
const store = useChatStore()

function fmtDay(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const diff = Math.floor((today.setHours(0, 0, 0, 0) - new Date(iso).setHours(0, 0, 0, 0)) / 86400000)
  if (diff === 0) return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
  if (diff === 1) return t('chat.session.yesterday')
  return `${d.getMonth() + 1}/${d.getDate()}`
}
</script>

<template>
  <div class="flex h-full w-[248px] shrink-0 flex-col border-r border-edge bg-panel">
    <div class="flex h-14 shrink-0 items-center justify-between border-b border-edge px-4">
      <span class="text-[13px] font-medium text-ink">{{ t('chat.session.title') }}</span>
      <button
        type="button"
        class="flex h-7 items-center gap-1 rounded-full border border-edge-bright px-2.5 text-[12px] text-ink-dim transition-colors duration-150 hover:border-edge-bright hover:text-ink"
        @click="store.newSession()"
      >
        <Icon name="plus" :size="12" />
        {{ t('chat.session.new') }}
      </button>
    </div>

    <div class="flex-1 overflow-y-auto py-1">
      <div v-if="store.sessionsLoading" class="space-y-px px-2 py-2">
        <div v-for="i in 4" :key="i" class="h-[42px] animate-pulse rounded bg-raise" />
      </div>

      <div v-else-if="store.sessions.length === 0" class="px-4 py-10 text-center text-[12px] text-ink-mute">
        {{ t('chat.session.empty') }}
        <button
          type="button"
          class="mt-3 block w-full rounded-full border border-edge-bright px-2 py-1.5 text-[12px] text-ink-dim hover:border-edge-bright hover:text-ink"
          @click="store.newSession()"
        >
          {{ t('chat.session.createFirst') }}
        </button>
      </div>

      <button
        v-for="s in store.sessions"
        v-else
        :key="s.id"
        type="button"
        class="group relative flex w-full flex-col justify-center gap-0.5 px-4 py-2 text-left transition-colors duration-150"
        :class="store.currentSessionId === s.id ? 'bg-raise text-ink' : 'text-ink-dim hover:bg-raise/60'"
        @click="store.selectSession(s.id)"
      >
        <span v-if="store.currentSessionId === s.id" class="absolute inset-y-2 left-0 w-px bg-accent" />
        <span class="flex w-full items-center gap-2">
          <span class="min-w-0 flex-1 truncate text-[13px]">{{ s.title }}</span>
          <span
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-mute opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
            role="button"
            :aria-label="t('chat.session.deleteAria')"
            @click.stop="store.removeSession(s.id)"
          >
            <Icon name="trash" :size="12" />
          </span>
        </span>
        <span class="flex items-center justify-between font-mono text-[11px] text-ink-mute">
          <span>#{{ s.id }}</span>
          <span>{{ fmtDay(s.updated_at) }}</span>
        </span>
      </button>
    </div>

    <div class="border-t border-edge px-4 py-2.5 text-[11px] leading-relaxed text-ink-mute">
      {{ t('chat.session.footer', { n: store.sessions.length }) }}
    </div>
  </div>
</template>

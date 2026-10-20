<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'

const { t } = useI18n()

const props = withDefaults(defineProps<{ page: number; pageSize: number; total: number }>(), { pageSize: 8 })
const emit = defineEmits<{ change: [page: number] }>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const pages = computed<(number | '…')[]>(() => {
  const t = totalPages.value
  const c = props.page
  if (t <= 7) return Array.from({ length: t }, (_, i) => i + 1)
  if (c <= 4) return [1, 2, 3, 4, 5, '…', t]
  if (c >= t - 3) return [1, '…', t - 4, t - 3, t - 2, t - 1, t]
  return [1, '…', c - 1, c, c + 1, '…', t]
})

function go(p: number): void {
  if (p >= 1 && p <= totalPages.value && p !== props.page) emit('change', p)
}
</script>

<template>
  <div class="flex items-center gap-1">
    <button
      type="button"
      class="flex h-7 w-7 items-center justify-center rounded border border-edge text-ink-mute transition-colors hover:text-ink disabled:opacity-30"
      :disabled="page <= 1"
      :aria-label="t('ui.prevPage')"
      @click="go(page - 1)"
    >
      <Icon name="chev-left" :size="13" />
    </button>
    <template v-for="(p, i) in pages" :key="i">
      <span v-if="p === '…'" class="px-1 text-xs text-ink-mute">…</span>
      <button
        v-else
        type="button"
        class="h-7 min-w-7 rounded border px-2 font-mono text-xs transition-all duration-150"
        :class="p === page ? 'border-edge-bright bg-raise text-accent' : 'border-edge text-ink-dim hover:border-edge-bright hover:text-ink'"
        @click="go(p)"
      >
        {{ p }}
      </button>
    </template>
    <button
      type="button"
      class="flex h-7 w-7 items-center justify-center rounded border border-edge text-ink-mute transition-colors hover:text-ink disabled:opacity-30"
      :disabled="page >= totalPages"
      :aria-label="t('ui.nextPage')"
      @click="go(page + 1)"
    >
      <Icon name="chev-right" :size="13" />
    </button>
    <span class="ml-2 font-mono text-[11px] text-ink-mute">{{ t('ui.totalItems', { n: total }) }}</span>
  </div>
</template>

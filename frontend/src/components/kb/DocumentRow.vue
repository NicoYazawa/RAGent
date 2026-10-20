<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import StatusBadge from './StatusBadge.vue'
import type { KbDocument } from '@/api/types'

/** 文档列表 — 五态监控 / failed 悬浮错误详情 / 重试 / 删除 / 切片明细 */
defineProps<{ docs: KbDocument }>()
const emit = defineEmits<{ retry: [docId: number]; remove: [docId: number]; chunks: [doc: KbDocument] }>()
const { t } = useI18n()

function fmt(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}`
}
</script>

<template>
  <div
    class="group grid grid-cols-[minmax(0,1fr)_100px_170px_110px_72px] items-center gap-3 border-b border-edge px-4 py-3.5 transition-colors duration-100 hover:bg-raise/50 md:px-6"
  >
    <!-- 文件 -->
    <div class="flex min-w-0 items-center gap-2.5">
      <Icon name="file" :size="15" class="shrink-0 text-ink-mute" />
      <div class="min-w-0">
        <div class="truncate text-[13px] text-ink" :title="docs.error_msg ?? docs.file_name">{{ docs.file_name }}</div>
        <div v-if="docs.status === 'failed' && docs.error_msg" class="truncate font-mono text-[11px] text-danger/80" :title="docs.error_msg">
          {{ docs.error_msg }}
        </div>
      </div>
      <span class="shrink-0 rounded border border-edge px-1 font-mono text-[11px] text-ink-mute">{{ docs.file_type }}</span>
    </div>

    <!-- 切片数（ready 可点击查看切片明细） -->
    <div class="font-mono text-[11.5px]">
      <button
        v-if="docs.status === 'ready'"
        type="button"
        class="inline-flex items-center gap-0.5 text-ink-dim transition-colors duration-150 hover:text-ink hover:underline"
        :title="t('kb.doc.viewChunks')"
        @click="emit('chunks', docs)"
      >
        {{ t('kb.doc.chunksOf', { n: docs.chunk_count }) }}
        <Icon name="chev-right" :size="11" class="text-ink-mute" />
      </button>
      <span v-else-if="docs.status === 'chunking'" class="text-ink-mute">{{ t('kb.doc.chunking') }}</span>
      <span v-else class="text-ink-mute">—</span>
    </div>

    <!-- 状态 -->
    <StatusBadge :status="docs.status" />

    <!-- 时间 -->
    <div class="font-mono text-[11px] text-ink-mute">{{ fmt(docs.updated_at) }}</div>

    <!-- 操作 -->
    <div class="flex items-center justify-end gap-1 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
      <button
        v-if="docs.status === 'failed'"
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded-md border border-edge-bright text-accent transition-all duration-150 hover:bg-raise"
        :title="t('kb.doc.retryTitle')"
        @click="emit('retry', docs.id)"
      >
        <Icon name="retry" :size="13" />
      </button>
      <button
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded-md border border-edge text-ink-mute transition-all duration-150 hover:border-danger/50 hover:text-danger"
        :title="t('kb.doc.deleteTitle')"
        @click="emit('remove', docs.id)"
      >
        <Icon name="trash" :size="13" />
      </button>
    </div>
  </div>
</template>

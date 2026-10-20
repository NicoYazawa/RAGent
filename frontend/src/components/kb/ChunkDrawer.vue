<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import BaseTag from '@/components/ui/BaseTag.vue'
import BasePagination from '@/components/ui/BasePagination.vue'
import Icon from '@/components/ui/Icon.vue'
import { listDocumentChunks } from '@/api/admin'
import type { KbChunk, KbDocument } from '@/api/types'

/** 切片明细抽屉：分页浏览文档切片（chunk_no / 章节路径 / 正文 / token 数） */
const props = defineProps<{ open: boolean; doc: KbDocument | null }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const PAGE_SIZE = 8
const loading = ref(false)
const error = ref('')
const chunks = ref<KbChunk[]>([])
const total = ref(0)
const page = ref(1)
const expanded = ref<Set<number>>(new Set())

async function load(): Promise<void> {
  if (!props.doc) return
  loading.value = true
  error.value = ''
  try {
    const result = await listDocumentChunks(props.doc.kb_id, props.doc.id, page.value, PAGE_SIZE)
    chunks.value = result.items
    total.value = result.total
  } catch (e) {
    error.value = (e as Error).message
    chunks.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.doc?.id] as const,
  ([open]) => {
    if (open) {
      page.value = 1
      expanded.value = new Set()
      void load()
    }
  },
  { immediate: true },
)

function turn(p: number): void {
  page.value = p
  expanded.value = new Set()
  void load()
}

function toggle(chunkId: number): void {
  expanded.value.has(chunkId) ? expanded.value.delete(chunkId) : expanded.value.add(chunkId)
  // Set 原地变更需触发响应式更新
  expanded.value = new Set(expanded.value)
}
</script>

<template>
  <BaseDrawer :open="open" :title="t('kb.chunkDrawerTitle', { name: doc?.file_name ?? '' })" width="640px" @close="emit('close')">
    <div v-if="loading" class="space-y-3 py-4">
      <div v-for="i in 5" :key="i" class="h-24 animate-pulse rounded-lg border border-edge bg-card/50" />
    </div>

    <div v-else-if="error" class="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-[12.5px] text-danger">
      {{ error }}
    </div>

    <div v-else-if="doc" class="space-y-4 pb-6">
      <!-- 文档概要 -->
      <div class="rounded-xl border border-edge bg-card/70 p-4">
        <div class="flex items-center gap-2.5">
          <Icon name="file" :size="15" class="shrink-0 text-accent" />
          <span class="min-w-0 truncate text-[13.5px] font-medium text-ink">{{ doc.file_name }}</span>
          <span class="shrink-0 rounded border border-edge px-1 font-mono text-[11px] uppercase text-ink-mute">{{ doc.file_type }}</span>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <BaseTag tone="accent">{{ t('kb.totalChunks', { n: total }) }}</BaseTag>
          <BaseTag tone="mute">{{ t('kb.chunkSize') }}</BaseTag>
          <BaseTag tone="mute">{{ t('kb.overlap') }}</BaseTag>
          <BaseTag tone="mute">{{ t('kb.keepSection') }}</BaseTag>
        </div>
      </div>

      <!-- 切片列表 -->
      <div
        v-for="chunk in chunks"
        :key="chunk.id"
        class="group rounded-xl border border-edge bg-card/70 p-3.5 transition-colors duration-150 hover:border-edge-bright"
      >
        <div class="flex items-center gap-2">
          <span class="rounded border border-edge-bright bg-raise px-1.5 py-0.5 font-mono text-[11px] text-accent">#{{ chunk.chunk_no }}</span>
          <span class="min-w-0 flex-1 truncate text-[12px] text-ink-dim">{{ chunk.section_path }}</span>
          <span class="shrink-0 font-mono text-[11px] text-ink-mute">{{ chunk.token_count }} tok</span>
          <button
            type="button"
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-mute transition-colors hover:bg-raise hover:text-accent"
            :title="expanded.has(chunk.id) ? t('kb.collapse') : t('kb.expand')"
            @click="toggle(chunk.id)"
          >
            <Icon name="chev-down" :size="13" class="transition-transform duration-200" :class="expanded.has(chunk.id) ? 'rotate-180' : ''" />
          </button>
        </div>
        <p
          class="mt-2 cursor-pointer whitespace-pre-line text-[12.5px] leading-relaxed text-ink-dim transition-all"
          :class="expanded.has(chunk.id) ? '' : 'line-clamp-3'"
          @click="toggle(chunk.id)"
        >
          {{ chunk.content }}
        </p>
      </div>

      <!-- 分页 -->
      <div v-if="total > PAGE_SIZE" class="flex justify-center pt-1">
        <BasePagination :page="page" :page-size="PAGE_SIZE" :total="total" @change="turn" />
      </div>
    </div>
  </BaseDrawer>
</template>

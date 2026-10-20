<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DocStatus } from '@/api/types'

/** 文档入库五态徽标 + 四步进度（parsing→chunking→embedding→ready） */
const props = defineProps<{ status: DocStatus }>()
const { t } = useI18n()

const META: Record<DocStatus, { label: string; cls: string; dot: string }> = {
  parsing: { label: t('kb.status.parsing'), cls: 'border-edge-bright bg-raise text-accent', dot: 'bg-accent' },
  chunking: { label: t('kb.status.chunking'), cls: 'border-src-keyword/40 bg-src-keyword/10 text-src-keyword', dot: 'bg-src-keyword' },
  embedding: { label: t('kb.status.embedding'), cls: 'border-src-vector/40 bg-src-vector/10 text-src-vector', dot: 'bg-src-vector' },
  ready: { label: t('kb.status.ready'), cls: 'border-ok/40 bg-ok/10 text-ok', dot: 'bg-ok' },
  failed: { label: t('kb.status.failed'), cls: 'border-danger/40 bg-danger/10 text-danger', dot: 'bg-danger' },
}

const meta = computed(() => META[props.status])
const isWorking = computed(() => ['parsing', 'chunking', 'embedding'].includes(props.status))
const STAGES: DocStatus[] = ['parsing', 'chunking', 'embedding', 'ready']
const stageIdx = computed(() => (props.status === 'failed' ? 2 : STAGES.indexOf(props.status)))
/** 入库中与失败态都要展示四步进度（失败态用红色标记断点） */
const showProgress = computed(() => isWorking.value || props.status === 'failed')
</script>

<template>
  <div class="flex items-center gap-2">
    <span class="inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[11px] leading-none" :class="meta.cls">
      <span v-if="isWorking" class="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
      <span v-else class="h-1.5 w-1.5 rounded-full" :class="meta.dot" />
      {{ meta.label }}
    </span>

    <!-- 四步进度点：仅在入库进行中显示，完成态不重复装饰 -->
    <div v-if="showProgress" class="hidden items-center gap-[3px] md:flex" :title="t('kb.progressTitle', { n: stageIdx + 1 })">
      <template v-for="(s, i) in STAGES" :key="s">
        <span
          class="h-1 w-3 rounded-full transition-all duration-300"
          :class="status === 'failed' && i >= 2 ? 'bg-danger/60' : i < stageIdx ? 'bg-ok/70' : i === stageIdx ? (isWorking ? 'bg-accent' : 'bg-ok/70') : 'bg-edge'"
        />
      </template>
    </div>
  </div>
</template>

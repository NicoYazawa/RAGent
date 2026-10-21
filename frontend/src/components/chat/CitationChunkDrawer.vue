<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import BaseTag from '@/components/ui/BaseTag.vue'
import Icon from '@/components/ui/Icon.vue'
import { getChunkByCitation } from '@/api/admin'
import type { Citation, KbChunk, KbDocument } from '@/api/types'

/** Citation drawer: a knowledge-base citation locates the chunk text; an NL2SQL citation shows the data-query evidence (SQL + result rows) */
const props = defineProps<{ open: boolean; citation: Citation | null }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const loading = ref(false)
const error = ref('')
const doc = ref<KbDocument | null>(null)
const chunk = ref<KbChunk | null>(null)

/** db source (legacy compatible: old messages have no source_type but a doc_name containing NL2SQL) */
const isDb = computed(
  () => !!props.citation && (props.citation.source_type === 'db' || props.citation.doc_name.includes('NL2SQL')),
)
const dbRows = computed(() => props.citation?.rows ?? [])
/** Dynamic result columns: union of the row keys (order preserved), dropping the meaningless id column */
const dbColumns = computed(() => {
  const cols: string[] = []
  for (const r of dbRows.value) {
    for (const k of Object.keys(r)) {
      if (k !== 'id' && !cols.includes(k)) cols.push(k)
    }
  }
  return cols
})

function fmtCell(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  return typeof v === 'number' ? v.toLocaleString(undefined) : String(v)
}

watch(
  () => [props.open, props.citation] as const,
  ([open, cite], _previous, onCleanup) => {
    let active = true
    onCleanup(() => { active = false })
    if (!open || !cite) return
    loading.value = true
    error.value = ''
    doc.value = null
    chunk.value = null
    // db source: the evidence already travels in the citation (sql + rows), so no chunk lookup is needed
    if (isDb.value) {
      loading.value = false
      return
    }
    const request = cite.doc_id !== undefined || cite.chunk_uid !== undefined || cite.kb_id !== undefined
      ? getChunkByCitation(cite.doc_name, cite.chunk_no, { doc_id: cite.doc_id, kb_id: cite.kb_id, chunk_uid: cite.chunk_uid })
      : getChunkByCitation(cite.doc_name, cite.chunk_no)
    request
      .then((r) => {
        if (!active) return
        doc.value = r.doc
        chunk.value = r.chunk
      })
      .catch((e) => {
        if (!active) return
        error.value = (e as Error).message
      })
      .finally(() => {
        if (active) loading.value = false
      })
  },
  { immediate: true },
)
</script>

<template>
  <BaseDrawer :open="open" :title="isDb ? t('chat.cite.titleDb') : t('chat.cite.titleChunk')" width="560px" @close="emit('close')">
    <div v-if="loading" class="space-y-3 py-4">
      <div class="h-20 animate-pulse rounded-xl border border-edge bg-card/50" />
      <div class="h-48 animate-pulse rounded-xl border border-edge bg-card/50" />
    </div>

    <div v-else-if="error" class="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-[12.5px] leading-relaxed text-danger">
      {{ error }}
    </div>

    <!-- NL2SQL data-query evidence -->
    <div v-else-if="citation && isDb" class="space-y-4 pb-6">
      <div v-if="!citation.sql" class="rounded-xl border border-edge bg-card/70 p-4 text-[12.5px] leading-relaxed text-ink-dim">
        {{ t('chat.cite.dbLegacy') }}
      </div>
      <template v-else>
        <!-- Query context -->
        <div class="rounded-xl border border-edge bg-card/70 p-4">
          <div class="flex items-center gap-2.5">
            <Icon name="db" :size="15" class="shrink-0 text-accent" />
            <span class="min-w-0 truncate text-[13.5px] font-medium text-ink">{{ t('chat.msg.citeDb', { table: 'sales' }) }}</span>
            <span class="shrink-0 rounded border border-edge px-1 font-mono text-[11px] uppercase text-ink-mute">mysql</span>
          </div>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <BaseTag tone="accent">{{ t('chat.cite.nl2sqlTag') }}</BaseTag>
            <BaseTag tone="mute">{{ t('chat.cite.hits', { n: dbRows.length }) }}</BaseTag>
            <BaseTag tone="mute">{{ t('chat.cite.whitelist') }}</BaseTag>
          </div>
          <p class="mt-2.5 font-mono text-[11px] leading-relaxed text-ink-mute">
            {{ t('chat.cite.evidenceNote') }}
          </p>
        </div>

        <!-- Generated SQL -->
        <div class="rounded-xl border border-edge-bright bg-card/70 p-4">
          <div class="flex items-center gap-2">
            <span class="rounded border border-edge-bright bg-raise px-1.5 py-0.5 font-mono text-[11px] text-accent">SQL</span>
            <span class="text-[12px] text-ink-dim">{{ t('chat.cite.sqlLabel') }}</span>
          </div>
          <pre class="mt-3 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[12px] leading-[1.8] text-ink/90">{{ citation.sql }}</pre>
        </div>

        <!-- Query result table -->
        <div class="rounded-xl border border-edge bg-card/70 p-4">
          <div class="flex items-center gap-2">
            <span class="rounded border border-edge px-1.5 py-0.5 font-mono text-[11px] text-ink-dim">RESULT</span>
            <span class="text-[12px] text-ink-dim">{{ t('chat.cite.resultRows') }}</span>
          </div>
          <div class="mt-3 max-h-72 overflow-auto rounded-lg border border-edge">
            <table class="w-full border-collapse text-left">
              <thead>
                <tr class="sticky top-0 bg-panel">
                  <th
                    v-for="col in dbColumns"
                    :key="col"
                    class="whitespace-nowrap border-b border-edge px-3 py-2 font-mono text-[11px] uppercase tracking-wide text-ink-mute"
                  >
                    {{ col }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, ri) in dbRows" :key="ri" class="transition-colors hover:bg-raise/60">
                  <td
                    v-for="col in dbColumns"
                    :key="col"
                    class="whitespace-nowrap border-b border-edge/60 px-3 py-1.5 text-[12px] tabular-nums text-ink/90"
                  >
                    {{ fmtCell(r[col]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>

    <div v-else-if="citation && doc && chunk" class="space-y-4 pb-6">
      <!-- Citation context -->
      <div class="rounded-xl border border-edge bg-card/70 p-4">
        <div class="flex items-center gap-2.5">
          <Icon name="file" :size="15" class="shrink-0 text-accent" />
          <span class="min-w-0 truncate text-[13.5px] font-medium text-ink">{{ doc.file_name }}</span>
          <span class="shrink-0 rounded border border-edge px-1 font-mono text-[11px] uppercase text-ink-mute">{{ doc.file_type }}</span>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <BaseTag tone="accent">{{ t('chat.cite.docTag', { doc: citation.doc_name }) }}</BaseTag>
          <BaseTag tone="mute">{{ citation.section_path }}</BaseTag>
          <BaseTag tone="mute">{{ t('chat.cite.chunkTag', { no: citation.chunk_no, total: doc.chunk_count }) }}</BaseTag>
        </div>
        <p class="mt-2.5 font-mono text-[11px] leading-relaxed text-ink-mute">
          {{ t('chat.cite.esHit', { id: doc.id, no: chunk.chunk_no }) }}
        </p>
      </div>

      <!-- Chunk body -->
      <div class="rounded-xl border border-edge-bright bg-card/70 p-4">
        <div class="flex items-center gap-2">
          <span class="rounded border border-edge-bright bg-raise px-1.5 py-0.5 font-mono text-[11px] text-accent">#{{ chunk.chunk_no }}</span>
          <span class="min-w-0 flex-1 truncate text-[12px] text-ink-dim">{{ chunk.section_path }}</span>
          <span class="shrink-0 font-mono text-[11px] text-ink-mute">{{ chunk.token_count }} tok</span>
        </div>
        <p class="mt-3 whitespace-pre-line text-[13px] leading-[1.9] text-ink/90">{{ chunk.content }}</p>
      </div>
    </div>
  </BaseDrawer>
</template>

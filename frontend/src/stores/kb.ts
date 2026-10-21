import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import i18n from '@/i18n'
import type { KbDocument, KnowledgeBase } from '@/api/types'
import * as adminApi from '@/api/admin'

/**
 * Knowledge-base store:
 * data is loaded from the backend through the api layer,
 * and ingestion status refreshes through a 2.5s poll (reflecting pipeline progress live)
 */
export const useKbStore = defineStore('kb', () => {
  const selectedKbId = ref<number | null>(null)
  const loading = ref(false)
  const creating = ref(false)
  const deleting = ref(false)
  const documentsRefreshing = ref(false)

  const kbs = ref<KnowledgeBase[]>([])
  const documents = ref<KbDocument[]>([])

  const selectedKb = computed(() => kbs.value.find((k) => k.id === selectedKbId.value) ?? null)
  const processingCount = computed(() => documents.value.filter((d) => ['parsing', 'chunking', 'embedding'].includes(d.status)).length)
  const failedCount = computed(() => documents.value.filter((d) => d.status === 'failed').length)

  let kbRequest = 0
  let documentRequest = 0

  async function loadKbs(): Promise<void> {
    const request = ++kbRequest
    const result = await adminApi.listKbs()
    if (request === kbRequest) kbs.value = result
  }

  async function loadDocuments(): Promise<void> {
    const request = ++documentRequest
    const kbId = selectedKbId.value
    if (!selectedKbId.value) {
      documents.value = []
      documentsRefreshing.value = false
      return
    }
    documentsRefreshing.value = true
    try {
      const result = await adminApi.listDocuments(selectedKbId.value)
      if (request === documentRequest && kbId === selectedKbId.value) documents.value = result
    } finally {
      if (request === documentRequest) documentsRefreshing.value = false
    }
  }

  async function refresh(): Promise<void> {
    await Promise.all([loadKbs(), loadDocuments()])
  }

  // switching knowledge base fetches its documents; failures no longer surface as unhandled rejections
  watch(selectedKbId, () => void loadDocuments().catch(() => undefined))

  /* Ingestion polling (requests only while processingCount > 0 to avoid idle work) */
  let pollTimer: number | null = null
  let polling = false

  function startPolling(): void {
    if (pollTimer != null) return
    pollTimer = window.setInterval(() => {
      if (polling || processingCount.value === 0) return
      polling = true
      refresh()
        .catch(() => undefined)
        .finally(() => {
          polling = false
        })
    }, 2500)
  }

  async function init(): Promise<void> {
    loading.value = true
    try {
      await loadKbs()
      if (!selectedKbId.value && kbs.value.length > 0) selectedKbId.value = kbs.value[0].id
      else await loadDocuments()
    } finally {
      loading.value = false
    }
    startPolling()
  }

  async function createKb(name: string, description: string): Promise<void> {
    creating.value = true
    try {
      const kb = await adminApi.createKb(name, description)
      await loadKbs()
      selectedKbId.value = kb.id
    } finally {
      creating.value = false
    }
  }

  async function upload(files: File[]): Promise<{ ok: number; errors: string[] }> {
    const { t } = i18n.global
    if (!selectedKbId.value) return { ok: 0, errors: [t('kb.noSelection')] }
    let ok = 0
    const errors: string[] = []
    for (const f of files) {
      try {
        await adminApi.uploadDocument(selectedKbId.value, f)
        ok++
      } catch (e) {
        errors.push(`${f.name}：${(e as Error).message}`)
      }
    }
    await refresh()
    return { ok, errors }
  }

  async function removeKb(kbId: number): Promise<void> {
    if (deleting.value) return
    deleting.value = true
    try {
      await adminApi.deleteKb(kbId)
      ++kbRequest
      kbs.value = kbs.value.filter(k => k.id !== kbId)
      if (selectedKbId.value === kbId) {
        ++documentRequest
        documents.value = []
        selectedKbId.value = kbs.value[0]?.id ?? null
      }
    } finally {
      deleting.value = false
    }
  }

  async function removeDoc(docId: number): Promise<void> {
    if (!selectedKbId.value) return
    await adminApi.deleteDocument(selectedKbId.value, docId)
    await refresh()
  }

  async function retryDoc(docId: number): Promise<void> {
    if (!selectedKbId.value) return
    await adminApi.retryDocument(selectedKbId.value, docId)
    await refresh()
  }

  return {
    kbs,
    selectedKbId,
    selectedKb,
    documents,
    loading,
    creating,
    deleting,
    documentsRefreshing,
    processingCount,
    failedCount,
    init,
    refresh,
    createKb,
    removeKb,
    upload,
    removeDoc,
    retryDoc,
  }
})

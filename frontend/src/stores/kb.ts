import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useI18n } from 'vue-i18n'
import type { KbDocument, KnowledgeBase } from '@/api/types'
import * as adminApi from '@/api/admin'

/**
 * 知识库管理 Store：
 * 数据经 api 层从后端加载，
 * 入库中状态通过 2.5s 轮询刷新（实时反映流水线推进）
 */
export const useKbStore = defineStore('kb', () => {
  const selectedKbId = ref<number | null>(null)
  const loading = ref(false)
  const creating = ref(false)
  const documentsRefreshing = ref(false)

  const kbs = ref<KnowledgeBase[]>([])
  const documents = ref<KbDocument[]>([])

  const selectedKb = computed(() => kbs.value.find((k) => k.id === selectedKbId.value) ?? null)
  const processingCount = computed(() => documents.value.filter((d) => ['parsing', 'chunking', 'embedding'].includes(d.status)).length)
  const failedCount = computed(() => documents.value.filter((d) => d.status === 'failed').length)

  async function loadKbs(): Promise<void> {
    kbs.value = await adminApi.listKbs()
  }

  async function loadDocuments(): Promise<void> {
    if (!selectedKbId.value) {
      documents.value = []
      return
    }
    documentsRefreshing.value = true
    try {
      documents.value = await adminApi.listDocuments(selectedKbId.value)
    } finally {
      documentsRefreshing.value = false
    }
  }

  async function refresh(): Promise<void> {
    await Promise.all([loadKbs(), loadDocuments()])
  }

  // 切换知识库时自动拉取文档；失败不再冒泡成未处理的 Promise 拒绝
  watch(selectedKbId, () => void loadDocuments().catch(() => undefined))

  /* 入库中状态轮询（仅 processingCount > 0 时发起请求，避免空转） */
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
    const { t } = useI18n({ useScope: 'global' })
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
    documentsRefreshing,
    processingCount,
    failedCount,
    init,
    refresh,
    createKb,
    upload,
    removeDoc,
    retryDoc,
  }
})

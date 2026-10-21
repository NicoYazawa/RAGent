import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { DecisionLog } from '@/api/types'
import * as adminApi from '@/api/admin'

/** Decision log store — filtered paginated queries plus single-entry details */
export const useDecisionLogStore = defineStore('decisionLog', () => {
  const logs = ref<DecisionLog[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = 8
  const loading = ref(false)

  const filterSessionId = ref<string>('')
  const filterStart = ref('')
  const filterEnd = ref('')

  async function query(p = 1): Promise<void> {
    loading.value = true
    page.value = p
    try {
      const result = await adminApi.queryDecisionLogs({
        session_id: filterSessionId.value.trim() ? Number(filterSessionId.value.trim()) : undefined,
        start: filterStart.value || undefined,
        end: filterEnd.value || undefined,
        page: p,
        page_size: pageSize,
      })
      logs.value = result.items
      total.value = result.total
    } finally {
      loading.value = false
    }
  }

  async function getDetail(logId: number): Promise<DecisionLog> {
    return adminApi.getDecisionLog(logId)
  }

  return { logs, total, page, pageSize, loading, filterSessionId, filterStart, filterEnd, query, getDetail }
})

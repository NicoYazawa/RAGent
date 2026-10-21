import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { DatasourceItem } from '@/api/types'
import * as adminApi from '@/api/admin'

/** Data-source store — the three retrieval-source switches plus connection settings */
export const useDatasourceStore = defineStore('datasource', () => {
  const items = ref<DatasourceItem[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const savedAt = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    try {
      items.value = await adminApi.getDatasources()
    } finally {
      loading.value = false
    }
  }

  async function save(): Promise<void> {
    saving.value = true
    try {
      await adminApi.updateDatasources(items.value)
      savedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    } finally {
      saving.value = false
    }
  }

  return { items, loading, saving, savedAt, load, save }
})

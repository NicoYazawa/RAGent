<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseEmpty from '@/components/ui/BaseEmpty.vue'
import DocumentRow from '@/components/kb/DocumentRow.vue'
import UploadModal from '@/components/kb/UploadModal.vue'
import ChunkDrawer from '@/components/kb/ChunkDrawer.vue'
import { useKbStore } from '@/stores/kb'
import type { KbDocument, KnowledgeBase } from '@/api/types'

/** 知识库管理页：库列表 → 文档列表 → 上传/状态监控/切片明细 */
const { t } = useI18n()
const store = useKbStore()
const createOpen = ref(false)
const uploadOpen = ref(false)
const newName = ref('')
const newDesc = ref('')
const createError = ref('')
const deleteTarget = ref<Pick<KnowledgeBase, 'id' | 'name'> | null>(null)
const deleteError = ref('')

function openDelete(): void {
  if (!store.selectedKb) return
  deleteTarget.value = { id: store.selectedKb.id, name: store.selectedKb.name }
  deleteError.value = ''
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value || store.deleting) return
  try {
    await store.removeKb(deleteTarget.value.id)
    deleteTarget.value = null
    chunkDoc.value = null
  } catch (e) {
    deleteError.value = (e as Error).message
  }
}

/** 当前库的切片总量（底部汇总用，由行数据求和） */
const totalChunks = computed(() => store.documents.reduce((sum, d) => sum + d.chunk_count, 0))
const readyCount = computed(() => store.documents.filter((d) => d.status === 'ready').length)
const failedCount = computed(() => store.documents.filter((d) => d.status === 'failed').length)
const chunkDoc = ref<KbDocument | null>(null)

onMounted(() => void store.init())

async function confirmCreate(): Promise<void> {
  if (!newName.value.trim()) {
    createError.value = t('kb.nameRequired')
    return
  }
  try {
    await store.createKb(newName.value.trim(), newDesc.value.trim() || t('kb.noDesc'))
    createOpen.value = false
    newName.value = ''
    newDesc.value = ''
    createError.value = ''
  } catch (e) {
    createError.value = (e as Error).message
  }
}

async function onRemove(docId: number): Promise<void> {
  await store.removeDoc(docId)
}

async function onRetry(docId: number): Promise<void> {
  await store.retryDoc(docId)
}

function onViewChunks(doc: KbDocument): void {
  chunkDoc.value = doc
}
</script>

<template>
  <div class="flex h-full">
    <!-- 左：知识库列表 -->
    <div class="flex w-[264px] shrink-0 flex-col border-r border-edge bg-panel">
      <div class="flex h-14 items-center justify-between border-b border-edge px-4">
        <span class="text-[13px] font-medium text-ink">{{ t('kb.list.title') }}</span>
        <BaseButton size="sm" variant="ghost" @click="createOpen = true">
          <Icon name="plus" :size="12" /> {{ t('chat.session.new') }}
        </BaseButton>
      </div>
      <div class="flex-1 overflow-y-auto py-1">
        <div v-if="store.loading" class="space-y-px px-2 py-2">
          <div v-for="i in 3" :key="i" class="h-[68px] animate-pulse rounded bg-raise" />
        </div>
        <button
          v-for="kb in store.kbs"
          v-else
          :key="kb.id"
          type="button"
          class="relative w-full px-4 py-2.5 text-left transition-colors duration-150"
          :class="store.selectedKbId === kb.id ? 'bg-raise text-ink' : 'text-ink-dim hover:bg-raise/60'"
          @click="store.selectedKbId = kb.id"
        >
          <span v-if="store.selectedKbId === kb.id" class="absolute inset-y-2 left-0 w-px bg-accent" />
          <span class="block truncate text-[13px] font-medium">{{ kb.name }}</span>
          <span class="mt-0.5 block truncate text-[11px] text-ink-mute">{{ kb.description }}</span>
          <span class="mt-1 flex items-center gap-3 font-mono text-[11px] text-ink-mute">
            <span><span class="text-ink-dim">{{ kb.doc_count }}</span> {{ t('kb.list.docs') }}</span>
            <span><span class="text-ink-dim">{{ kb.chunk_count }}</span> {{ t('kb.list.chunks') }}</span>
          </span>
        </button>
      </div>
      <div class="border-t border-edge px-4 py-2.5 text-[11px] leading-relaxed text-ink-mute">
        {{ t('kb.archEs') }}<br />
        {{ t('kb.archMysql') }}
      </div>
    </div>

    <!-- 右：文档管理 -->
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- 工具栏 -->
      <div class="flex min-h-14 items-center gap-3 border-b border-edge px-4 md:px-6">
        <h1 class="truncate text-[18px] font-semibold leading-tight text-ink">
          {{ store.selectedKb?.name ?? t('kb.noSelection') }}
        </h1>
        <div class="flex items-center gap-2 font-mono text-[11px]">
          <span v-if="store.processingCount > 0" class="flex items-center gap-1 rounded border border-edge-bright bg-raise px-1.5 py-0.5 text-ink-dim">
            <span class="h-2 w-2 animate-spin rounded-full border border-current border-t-transparent" />
            {{ store.processingCount }} {{ t('kb.processing') }}
          </span>
          <span v-if="store.failedCount > 0" class="rounded border border-danger/40 bg-danger/10 px-1.5 py-0.5 text-danger">
            {{ store.failedCount }} {{ t('kb.failed') }}
          </span>
        </div>
        <div class="flex-1" />
        <BaseButton size="sm" variant="danger" :disabled="!store.selectedKbId || store.deleting" @click="openDelete">
          <Icon name="trash-2" :size="13" /> {{ t('kb.deleteBtn') }}
        </BaseButton>
        <BaseButton size="sm" variant="ghost" :disabled="!store.selectedKbId" @click="uploadOpen = true">
          <Icon name="upload" :size="13" /> {{ t('kb.uploadBtn') }}
        </BaseButton>
      </div>

      <!-- 文档表头 -->
      <div v-if="store.documents.length" class="grid grid-cols-[minmax(0,1fr)_100px_170px_110px_72px] gap-3 border-b border-edge px-4 py-2 text-[12px] text-ink-mute md:px-6">
        <span>{{ t('kb.col.doc') }}</span>
        <span>{{ t('kb.col.chunk') }}</span>
        <span>{{ t('kb.col.status') }}</span>
        <span>{{ t('kb.col.updated') }}</span>
        <span class="text-right">{{ t('kb.col.actions') }}</span>
      </div>

      <!-- 文档列表 -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="store.loading" class="space-y-2 p-4">
          <div v-for="i in 4" :key="i" class="h-12 animate-pulse rounded-lg border border-edge bg-card/50" />
        </div>
        <DocumentRow
          v-else-if="store.documents.length"
          v-for="doc in store.documents"
          :key="doc.id"
          :docs="doc"
          @retry="onRetry"
          @remove="onRemove"
          @chunks="onViewChunks"
        />
        <BaseEmpty v-else-if="store.selectedKbId" icon="file" :text="t('kb.emptyDocs')" />
        <BaseEmpty v-else icon="book" :text="t('kb.pleaseSelect')" />
      </div>

      <!-- 库概览：全部数字由行数据求和，不做估算 -->
      <div v-if="store.documents.length" class="grid grid-cols-2 gap-px border-t border-edge bg-edge md:grid-cols-4">
        <div class="bg-panel px-4 py-3">
          <div class="text-[11px] text-ink-mute">{{ t('kb.col.doc') }}</div>
          <div class="mt-1 font-mono text-[18px] leading-none text-ink">{{ store.documents.length }}</div>
        </div>
        <div class="bg-panel px-4 py-3">
          <div class="text-[11px] text-ink-mute">{{ t('kb.col.chunk') }}</div>
          <div class="mt-1 font-mono text-[18px] leading-none text-ink">{{ totalChunks }}</div>
        </div>
        <div class="bg-panel px-4 py-3">
          <div class="text-[11px] text-ink-mute">{{ t('kb.status.ready') }}</div>
          <div class="mt-1 font-mono text-[18px] leading-none text-ok">{{ readyCount }}</div>
        </div>
        <div class="bg-panel px-4 py-3">
          <div class="text-[11px] text-ink-mute">{{ t('kb.status.failed') }}</div>
          <div class="mt-1 font-mono text-[18px] leading-none" :class="failedCount ? 'text-danger' : 'text-ink-mute'">
            {{ failedCount }}
          </div>
        </div>
      </div>
    </div>

    <!-- 新建知识库弹窗 -->
    <BaseModal :open="createOpen" :title="t('kb.createTitle')" width="420px" @close="createOpen = false">
      <div class="space-y-3.5">
        <div>
          <label class="mb-1.5 block text-xs text-ink-dim">{{ t('kb.nameLabel') }}</label>
          <BaseInput v-model="newName" :placeholder="t('kb.namePlaceholder')" />
        </div>
        <div>
          <label class="mb-1.5 block text-xs text-ink-dim">{{ t('kb.descLabel') }}</label>
          <BaseInput v-model="newDesc" :placeholder="t('kb.descPlaceholder')" />
        </div>
        <p v-if="createError" class="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">{{ createError }}</p>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <BaseButton variant="ghost" size="sm" @click="createOpen = false">{{ t('common.action.cancel') }}</BaseButton>
          <BaseButton size="sm" :loading="store.creating" @click="confirmCreate">{{ t('kb.createBtn') }}</BaseButton>
        </div>
      </template>
    </BaseModal>

    <BaseModal :open="deleteTarget != null" :title="t('kb.deleteTitle')" width="440px" @close="!store.deleting && (deleteTarget = null)">
      <p class="text-sm leading-relaxed text-ink-dim">{{ t('kb.deleteWarning', { name: deleteTarget?.name ?? '' }) }}</p>
      <p v-if="deleteError" role="alert" class="mt-3 text-sm text-danger">{{ deleteError }}</p>
      <template #footer>
        <div class="flex justify-end gap-2">
          <BaseButton size="sm" variant="ghost" :disabled="store.deleting" @click="deleteTarget = null">{{ t('common.action.cancel') }}</BaseButton>
          <BaseButton size="sm" variant="danger" :loading="store.deleting" @click="confirmDelete">{{ t('kb.deleteConfirm') }}</BaseButton>
        </div>
      </template>
    </BaseModal>

    <!-- 上传弹窗 -->
    <UploadModal :open="uploadOpen" @close="uploadOpen = false" />

    <!-- 切片明细抽屉 -->
    <ChunkDrawer :open="chunkDoc != null" :doc="chunkDoc" @close="chunkDoc = null" />
  </div>
</template>

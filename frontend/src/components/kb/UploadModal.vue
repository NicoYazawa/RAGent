<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Icon from '@/components/ui/Icon.vue'
import { useKbStore } from '@/stores/kb'

/** Upload dialog — type/size validation, batch upload and result feedback */
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const store = useKbStore()
const dragOver = ref(false)
const picked = ref<File[]>([])
const uploading = ref(false)
const resultMsg = ref<{ ok: number; errors: string[] } | null>(null)
const inputRef = ref<HTMLInputElement>()

const sizeText = computed(() => (f: File) => (f.size > 1024 * 1024 ? `${(f.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB`))

function onDrop(e: DragEvent): void {
  dragOver.value = false
  const files = Array.from(e.dataTransfer?.files ?? [])
  if (files.length) picked.value = [...picked.value, ...files]
}

function onPick(e: Event): void {
  const files = Array.from((e.target as HTMLInputElement).files ?? [])
  if (files.length) picked.value = [...picked.value, ...files]
  ;(e.target as HTMLInputElement).value = ''
}

function reset(): void {
  picked.value = []
  resultMsg.value = null
}

async function confirmUpload(): Promise<void> {
  if (!picked.value.length) return
  uploading.value = true
  try {
    resultMsg.value = await store.upload(picked.value)
    picked.value = []
  } finally {
    uploading.value = false
  }
}
void props
</script>

<template>
  <BaseModal :open="open" :title="t('kb.uploadTitle')" width="520px" @close="emit('close')">
    <div class="space-y-4">
      <p class="text-xs leading-relaxed text-ink-dim">
        {{ t('kb.uploadDesc') }}
      </p>

      <!-- Drop zone -->
      <div
        class="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 transition-all duration-150"
        :class="dragOver ? 'border-accent bg-raise' : 'border-edge-bright bg-card/50 hover:border-edge-bright'"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @drop.prevent="onDrop"
        @click="inputRef?.click()"
      >
        <Icon name="upload" :size="22" class="text-ink-mute" />
        <p class="text-[13px] text-ink-dim">{{ t('kb.dropHint') }}</p>
        <p class="font-mono text-[11px] text-ink-mute">{{ t('kb.targetKb') }}{{ store.selectedKb?.name ?? t('kb.none') }}</p>
        <input ref="inputRef" type="file" multiple accept=".md,.txt,.pdf,.docx" class="hidden" @change="onPick" />
      </div>

      <!-- Pending upload list -->
      <div v-if="picked.length" class="space-y-1.5">
        <div v-for="(f, i) in picked" :key="i" class="flex items-center gap-2 rounded-lg border border-edge bg-card px-3 py-2">
          <Icon name="file" :size="14" class="shrink-0 text-ink-mute" />
          <span class="min-w-0 flex-1 truncate text-[12.5px] text-ink">{{ f.name }}</span>
          <span class="font-mono text-[11px] text-ink-mute">{{ sizeText(f) }}</span>
          <button type="button" class="text-ink-mute hover:text-danger" :aria-label="t('kb.remove')" @click="picked.splice(i, 1)">
            <Icon name="x" :size="12" />
          </button>
        </div>
      </div>

      <!-- Result feedback -->
      <div v-if="resultMsg" class="space-y-1.5">
        <div class="rounded-lg border border-ok/40 bg-ok/10 px-3 py-2 text-[12px] text-ok">
          {{ t('kb.uploadAccepted', { n: resultMsg.ok }) }}
        </div>
        <div v-for="(err, i) in resultMsg.errors" :key="i" class="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
          {{ err }}
        </div>
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <BaseButton variant="ghost" size="sm" @click="reset(); emit('close')">{{ t('common.action.close') }}</BaseButton>
        <BaseButton size="sm" :loading="uploading" :disabled="!picked.length" @click="confirmUpload">
          {{ t('kb.uploadBtn') }} {{ picked.length ? `(${picked.length})` : '' }}
        </BaseButton>
      </div>
    </template>
  </BaseModal>
</template>

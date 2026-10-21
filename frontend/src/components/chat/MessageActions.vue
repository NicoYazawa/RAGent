<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BaseTooltip from '@/components/ui/BaseTooltip.vue'
import type { ChatMessage } from '@/api/types'
import { copyText } from '@/utils/decisionExport'

/**
 * Assistant answer action bar — appears on hover:
 * copy the full text / open the decision chain / regenerate (last message only)
 */
const props = defineProps<{
  message: ChatMessage
  canRegenerate?: boolean
}>()

const emit = defineEmits<{ regenerate: []; viewDecision: [] }>()
const { t } = useI18n()

const copied = ref(false)

async function copy(): Promise<void> {
  const ok = await copyText(props.message.content)
  if (ok) {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  }
}
</script>

<template>
  <div
    class="mt-1 flex items-center gap-0.5 opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover/msg:opacity-100"
    :aria-label="t('chat.msg.actionsLabel')"
  >
    <BaseTooltip :content="copied ? t('chat.msg.copiedShort') : t('chat.msg.copyFull')">
      <button
        type="button"
        class="flex h-6.5 w-6.5 items-center justify-center rounded-md text-ink-mute transition-colors hover:bg-raise hover:text-ink focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/60"
        @click="copy"
      >
        <Icon :name="copied ? 'check' : 'copy'" :size="13" :class="copied ? 'text-ok' : ''" />
      </button>
    </BaseTooltip>

    <button
      v-if="message.decision_log_id != null"
      type="button"
      class="flex h-6.5 items-center gap-1 rounded-md px-1.5 text-ink-mute transition-colors hover:bg-raise hover:text-ink"
      :title="t('chat.msg.viewDecision')"
      @click="emit('viewDecision')"
    >
      <Icon name="route" :size="13" />
      <span class="text-[11px]">{{ t('chat.msg.decisionChain') }}</span>
    </button>

    <button
      v-if="canRegenerate"
      type="button"
      class="flex h-6.5 items-center gap-1 rounded-md px-1.5 text-ink-mute transition-colors hover:bg-raise hover:text-ink"
      :title="t('chat.msg.regenTitle')"
      @click="emit('regenerate')"
    >
      <Icon name="refresh" :size="13" />
      <span class="text-[11px]">{{ t('chat.msg.regenerate') }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'

defineProps<{ icon?: string; text?: string }>()

const { t } = useI18n()
</script>

<template>
  <div class="anim-fade-up flex flex-col items-center justify-center gap-3 py-14 text-ink-mute">
    <div class="flex h-12 w-12 items-center justify-center rounded-xl border border-edge bg-card text-accent/60">
      <Icon :name="icon ?? 'info'" :size="22" />
    </div>
    <p class="text-sm">{{ text ?? t('ui.empty') }}</p>
    <slot />
  </div>
</template>

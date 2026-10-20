<script setup lang="ts">
/** 标签 — tone: accent/warn/danger/ok/mute */
withDefaults(defineProps<{ tone?: 'accent' | 'warn' | 'danger' | 'ok' | 'mute' }>(), { tone: 'accent' })
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[11px] leading-none"
    :class="[
      tone === 'accent' && 'border-edge-bright bg-raise text-ink-dim',
      tone === 'warn' && 'border-warn/40 bg-warn/10 text-warn',
      tone === 'danger' && 'border-danger/40 bg-danger/10 text-danger',
      tone === 'ok' && 'border-ok/40 bg-ok/10 text-ok',
      tone === 'mute' && 'border-edge bg-card text-ink-mute',
    ]"
  >
    <slot />
  </span>
</template>

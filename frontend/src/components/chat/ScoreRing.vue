<script setup lang="ts">
import { computed } from 'vue'

/** 检索质量评分环（0-10）：≥7 青、5~7 琥珀、<5 红 */
const props = defineProps<{ score: number; size?: number }>()

const R = 20
const CIRC = 2 * Math.PI * R * 0.75 // 270° 弧

const ratio = computed(() => Math.max(0, Math.min(1, props.score / 10)))
// 颜色跟随主题变量（暗色亮青 / 亮色深青），保证浅底可读
const color = computed(() =>
  props.score >= 7 ? 'var(--color-accent)' : props.score >= 5 ? 'var(--color-warn)' : 'var(--color-danger)',
)
const dash = computed(() => `${CIRC * ratio.value} ${CIRC}`)
</script>

<template>
  <div class="relative inline-flex items-center justify-center" :style="{ width: size ?? 52, height: size ?? 52 }">
    <svg :width="size ?? 52" :height="size ?? 52" viewBox="0 0 48 48" class="rotate-[135deg]">
      <circle cx="24" cy="24" :r="R" fill="none" stroke="var(--color-edge)" stroke-width="4" stroke-linecap="round" :stroke-dasharray="`${CIRC} ${CIRC}`" />
      <circle cx="24" cy="24" :r="R" fill="none" :stroke="color" stroke-width="4" stroke-linecap="round" :stroke-dasharray="dash" class="transition-all duration-700" />
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center leading-none">
      <span class="font-mono text-[13px] font-bold transition-colors" :style="{ color }">{{ score.toFixed(1) }}</span>
    </div>
  </div>
</template>

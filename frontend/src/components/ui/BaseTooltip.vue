<script setup lang="ts">
import { TooltipProvider, TooltipRoot, TooltipTrigger, TooltipPortal, TooltipContent, TooltipArrow } from 'reka-ui'

/**
 * 统一悬浮提示 — 无障碍完整（hover 意图、键盘 focus、Esc 关闭）
 * 视觉层仍用 token 类名，不引入库自带样式
 */
withDefaults(
  defineProps<{
    content: string
    side?: 'top' | 'right' | 'bottom' | 'left'
    delay?: number
    disabled?: boolean
    align?: 'start' | 'center' | 'end'
  }>(),
  { side: 'top', delay: 260, disabled: false, align: 'center' },
)
</script>

<template>
  <TooltipProvider :delay-duration="delay">
    <TooltipRoot :disabled="disabled">
      <TooltipTrigger as-child>
        <slot />
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent
          :side="side"
          :align="align"
          :side-offset="7"
          :collision-padding="8"
          class="tooltip-pop z-[60] select-none rounded-md border border-edge-bright bg-panel/95 px-2.5 py-1.5 text-[11.5px] leading-none text-ink-dim shadow-[0_6px_20px_rgba(6,11,24,0.55)]"
        >
          {{ content }}
          <TooltipArrow class="fill-panel" :width="9" :height="5" />
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>

<style scoped>
.tooltip-pop {
  transform-origin: var(--reka-tooltip-content-transform-origin, center);
  animation: tooltipIn 0.14s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes tooltipIn {
  from {
    opacity: 0;
    transform: scale(0.96);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>

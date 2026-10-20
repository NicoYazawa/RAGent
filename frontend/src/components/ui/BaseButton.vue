<script setup lang="ts">
/**
 * 统一按钮 — primary(反白实心)/ghost(描边)/danger(负向)/soft(底色)
 * 圆角统一为胶囊，颜色预算只留给状态，primary 用反白而不是彩色填充
 */
withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger' | 'soft'
    size?: 'sm' | 'md'
    disabled?: boolean
    loading?: boolean
    block?: boolean
    title?: string
  }>(),
  { variant: 'primary', size: 'md', disabled: false, loading: false, block: false },
)
</script>

<template>
  <button
    type="button"
    :title="title"
    :disabled="disabled || loading"
    class="inline-flex items-center justify-center gap-1.5 rounded-full font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40"
    :class="[
      size === 'sm' ? 'h-7 px-3 text-[12px]' : 'h-[34px] px-4 text-[13px]',
      block ? 'w-full' : '',
      variant === 'primary' && 'bg-ink text-deep hover:bg-ink/90',
      variant === 'ghost' && 'border border-edge-bright text-ink-dim hover:border-ink/40 hover:text-ink',
      variant === 'danger' && 'border border-danger/50 text-danger hover:bg-danger/10',
      variant === 'soft' && 'bg-raise text-ink-dim hover:text-ink',
    ]"
  >
    <span v-if="loading" class="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
    <slot />
  </button>
</template>

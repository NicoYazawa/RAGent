<script setup lang="ts">
/** Toggle — the on state glows teal */
const props = withDefaults(defineProps<{ modelValue: boolean; disabled?: boolean }>(), { disabled: false })
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

function toggle(): void {
  if (!props.disabled) emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    class="relative h-5.5 w-10 shrink-0 rounded-full border transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40"
    :class="modelValue ? 'border-edge-bright bg-raise' : 'border-edge-bright bg-raise'"
    @click="toggle"
  >
    <span
      class="absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full transition-all duration-200"
      :class="modelValue ? 'left-[calc(100%-1.125rem)] bg-accent' : 'left-0.5 bg-ink-mute'"
    />
  </button>
</template>

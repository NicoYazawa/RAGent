<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    type?: string
    disabled?: boolean
    mono?: boolean
  }>(),
  { placeholder: '', type: 'text', disabled: false, mono: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
}
void props
</script>

<template>
  <input
    :type="type"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    class="h-9 w-full rounded-lg border border-edge-bright bg-card px-3 text-[13px] text-ink outline-none transition-colors duration-150 placeholder:text-ink-mute focus:border-accent/70 disabled:cursor-not-allowed disabled:opacity-40"
    :class="mono && 'font-mono text-[12px]'"
    @input="onInput"
  />
</template>

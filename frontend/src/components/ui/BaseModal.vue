<script setup lang="ts">
import { onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AnimatePresence, motion } from 'motion-v'
import { FocusScope } from 'reka-ui'
import Icon from './Icon.vue'

const { t } = useI18n()

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    width?: string
    closeOnOverlay?: boolean
  }>(),
  { width: '480px', closeOnOverlay: true },
)
const emit = defineEmits<{ close: [] }>()

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
  },
)

// avoid leaving body scroll locked when the component unmounts while open
onUnmounted(() => {
  document.body.style.overflow = ''
})

function onOverlay(): void {
  if (props.closeOnOverlay) emit('close')
}

/** On open, focus the first input rather than the close button in the header */
function onMountAutoFocus(e: Event): void {
  const container = e.target as HTMLElement | null
  const preferred = container?.querySelector<HTMLElement>('[data-autofocus], input:not([type="hidden"]), textarea, select')
  if (!preferred) return
  e.preventDefault()
  preferred.focus()
}
</script>

<template>
  <Teleport to="body">
    <AnimatePresence>
      <motion.div
        v-if="open"
        key="modal"
        class="fixed inset-0 z-50 flex items-center justify-center p-6"
        :initial="{ opacity: 0 }"
        :animate="{ opacity: 1 }"
        :exit="{ opacity: 0 }"
        :transition="{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }"
        @keydown.esc="emit('close')"
      >
        <div class="absolute inset-0 bg-deep/80" @click="onOverlay" />
        <!-- FocusScope: focus trap plus focus returning to the trigger on close -->
        <FocusScope as-child :trapped="open" @mount-auto-focus="onMountAutoFocus">
          <motion.div
            class="scanline relative flex max-h-[85vh] w-full flex-col overflow-hidden rounded-xl border border-edge-bright bg-panel shadow-[var(--shadow-overlay)]"
            :style="{ maxWidth: width }"
            :initial="{ opacity: 0, scale: 0.96, y: 10 }"
            :animate="{ opacity: 1, scale: 1, y: 0 }"
            :exit="{ opacity: 0, scale: 0.97, y: 6 }"
            :transition="{ type: 'spring', stiffness: 360, damping: 30, mass: 0.9 }"
            role="dialog"
            aria-modal="true"
            :aria-label="title"
          >
            <div class="flex items-center justify-between border-b border-edge px-5 py-3.5">
              <h3 class="text-sm font-semibold tracking-wide text-ink">{{ title }}</h3>
              <button
                type="button"
                class="flex h-7 w-7 items-center justify-center rounded-md text-ink-mute transition-colors hover:bg-raise hover:text-ink focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/60"
                :aria-label="t('ui.close')"
                @click="emit('close')"
              >
                <Icon name="x" :size="15" />
              </button>
            </div>
            <div class="flex-1 overflow-y-auto px-5 py-4">
              <slot />
            </div>
            <div v-if="$slots.footer" class="border-t border-edge px-5 py-3.5">
              <slot name="footer" />
            </div>
          </motion.div>
        </FocusScope>
      </motion.div>
    </AnimatePresence>
  </Teleport>
</template>

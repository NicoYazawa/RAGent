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
  }>(),
  { width: '560px' },
)
const emit = defineEmits<{ close: [] }>()

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
  },
)

onUnmounted(() => {
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <AnimatePresence>
      <motion.div
        v-if="open"
        key="drawer"
        class="fixed inset-0 z-50"
        :initial="{ opacity: 0 }"
        :animate="{ opacity: 1 }"
        :exit="{ opacity: 0 }"
        :transition="{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }"
        @keydown.esc="emit('close')"
      >
        <div class="absolute inset-0 bg-deep/80" @click="emit('close')" />
        <FocusScope as-child :trapped="open">
          <motion.aside
            class="absolute right-0 top-0 flex h-full flex-col border-l border-edge-bright bg-panel shadow-[var(--shadow-overlay)]"
            :style="{ width }"
            :initial="{ x: '100%' }"
            :animate="{ x: 0 }"
            :exit="{ x: '102%' }"
            :transition="{ type: 'spring', stiffness: 320, damping: 32, mass: 0.9 }"
            role="dialog"
            aria-modal="true"
            :aria-label="title"
          >
            <div class="scanline flex items-center justify-between border-b border-edge px-5 py-3.5">
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
          </motion.aside>
        </FocusScope>
      </motion.div>
    </AnimatePresence>
  </Teleport>
</template>

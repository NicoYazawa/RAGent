<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'

const { t } = useI18n()

/** Full-screen image lightbox: ESC / overlay / close in the top-right; multiple images page left and right with an index */
const props = defineProps<{
  open: boolean
  images: string[]
}>()

const index = defineModel<number>('index', { default: 0 })

const emit = defineEmits<{ close: [] }>()

function prev(): void {
  if (index.value > 0) index.value -= 1
}

function next(): void {
  if (index.value < props.images.length - 1) index.value += 1
}

function onKey(e: KeyboardEvent): void {
  if (!props.open) return
  if (e.key === 'Escape') emit('close')
  else if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
  },
)

/* Preload the neighbouring images on open and switch (smoother paging) */
watch(
  () => [props.open, index.value] as const,
  ([open, i]) => {
    if (!open) return
    for (const j of [i - 1, i + 1]) {
      if (props.images[j]) new Image().src = props.images[j]
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="viewer">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-deep/85" @click="emit('close')">
        <!-- Close -->
        <button
          type="button"
          class="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-lg border border-edge bg-card text-ink-mute transition-all duration-150 hover:border-edge-bright hover:text-accent active:scale-95"
          :aria-label="t('ui.closePreview')"
          @click.stop="emit('close')"
        >
          <Icon name="x" :size="16" />
        </button>

        <!-- Previous -->
        <button
          v-if="images.length > 1 && index > 0"
          type="button"
          class="absolute left-4 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-edge bg-card/90 text-ink-dim transition-all duration-150 hover:border-edge-bright hover:text-accent active:scale-95"
          :aria-label="t('ui.prevImage')"
          @click.stop="prev"
        >
          <Icon name="chev-left" :size="18" />
        </button>

        <!-- Full image (fades when switching; clicking the image does not close it, so details stay visible) -->
        <Transition name="viewer-img" mode="out-in">
          <img
            :key="index"
            :src="images[index]"
            :alt="t('ui.previewAlt', { n: index + 1 })"
            class="max-h-[82vh] max-w-[88vw] cursor-zoom-in rounded-xl border border-edge bg-panel object-contain shadow-[var(--shadow-overlay)]"
            @click.stop
          />
        </Transition>

        <!-- Next -->
        <button
          v-if="images.length > 1 && index < images.length - 1"
          type="button"
          class="absolute right-4 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-edge bg-card/90 text-ink-dim transition-all duration-150 hover:border-edge-bright hover:text-accent active:scale-95"
          :aria-label="t('ui.nextImage')"
          @click.stop="next"
        >
          <Icon name="chev-right" :size="18" />
        </button>

        <!-- Index indicator -->
        <span v-if="images.length > 1" class="absolute bottom-5 font-mono text-[11px] tracking-wider text-ink-mute">
          {{ index + 1 }} / {{ images.length }}
        </span>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.viewer-enter-active,
.viewer-leave-active {
  transition: opacity 0.18s ease-out;
}
.viewer-enter-from,
.viewer-leave-to {
  opacity: 0;
}
.viewer-img-enter-active,
.viewer-img-leave-active {
  transition: opacity 0.12s ease;
}
.viewer-img-enter-from,
.viewer-img-leave-to {
  opacity: 0;
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/ui/Icon.vue'
import BaseTooltip from '@/components/ui/BaseTooltip.vue'
import ImageViewer from '@/components/ui/ImageViewer.vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from 'vue-i18n'
import { SAMPLE_QUESTIONS } from '@/api/samples'

/** Bottom input: Enter sends / Shift+Enter inserts a newline / interruptible while streaming, plus the sample strip and multimodal images (pick/paste/drop) */
const store = useChatStore()
const { t } = useI18n()
const draft = ref('')
const images = ref<string[]>([])
const textareaRef = ref<HTMLTextAreaElement>()
const fileRef = ref<HTMLInputElement>()
const dragging = ref(false)
const imageWarn = ref('')

const MAX_IMAGES = 4
const MAX_SIDE = 1280 // target long edge when compressing large images
const MAX_FILE_BYTES = 10 * 1024 * 1024

function autosize(): void {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 132)}px`
}

/* ---------- Image attachments: pick / paste / drop / compress ---------- */

function warn(msg: string): void {
  imageWarn.value = msg
  setTimeout(() => (imageWarn.value = ''), 2600)
}

function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

/** Small images and gifs are read as-is (animation kept); large ones are scaled on a canvas and re-encoded as JPEG to bound the size */
async function toDataUrl(file: File): Promise<string> {
  if (file.size <= 600 * 1024 || file.type === 'image/gif') return readAsDataURL(file)
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error(t('chat.input.imageParseFailed')))
      el.src = url
    })
    const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(img.width * scale)
    canvas.height = Math.round(img.height * scale)
    canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.85)
  } finally {
    URL.revokeObjectURL(url)
  }
}

async function addImages(files: FileList | File[] | null): Promise<void> {
  if (!files || store.streaming) return
  const room = MAX_IMAGES - images.value.length
  if (room <= 0) {
    warn(t('chat.input.tooMany', { max: MAX_IMAGES }))
    return
  }
  const list = Array.from(files).filter((f) => f.type.startsWith('image/'))
  if (!list.length) return
  for (const f of list.slice(0, room)) {
    if (f.size > MAX_FILE_BYTES) {
      warn(t('chat.input.imageTooLarge'))
      continue
    }
    images.value.push(await toDataUrl(f))
  }
  if (list.length > room) warn(t('chat.input.tooManyIgnored', { max: MAX_IMAGES, n: list.length - room }))
}

function pickImages(): void {
  fileRef.value?.click()
}

function onFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  void addImages(input.files)
  input.value = ''
}

function onPaste(e: ClipboardEvent): void {
  if (e.clipboardData?.files?.length) void addImages(e.clipboardData.files)
}

function onDrop(e: DragEvent): void {
  dragging.value = false
  if (e.dataTransfer?.files?.length) {
    e.preventDefault()
    void addImages(e.dataTransfer.files)
  }
}

function removeImage(i: number): void {
  images.value.splice(i, 1)
  if (previewIndex.value >= images.value.length) previewIndex.value = Math.max(0, images.value.length - 1)
}

/* Click a thumbnail to preview (in-page lightbox) */
const previewOpen = ref(false)
const previewIndex = ref(0)

function openPreview(i: number): void {
  previewIndex.value = i
  previewOpen.value = true
}

/* ---------- Sending ---------- */

const canSend = computed(() => !!(draft.value.trim() || images.value.length))

function send(): void {
  if (!canSend.value || store.streaming) return
  const q = draft.value.trim() || (images.value.length > 1 ? t('chat.input.defaultMulti', { n: images.value.length }) : t('chat.input.defaultSingle'))
  const imgs = images.value.length ? [...images.value] : undefined
  draft.value = ''
  images.value = []
  autosize()
  void store.send(q, imgs)
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

function useSample(q: string): void {
  draft.value = q
  autosize()
  textareaRef.value?.focus()
}
</script>

<template>
  <div class="border-t border-edge bg-panel px-4 py-3 md:px-6">
    <!-- Sample question strip -->
    <div class="mb-2 hidden items-center gap-1.5 overflow-x-auto pb-0.5 sm:flex">
      <span class="shrink-0 text-[11px] text-ink-mute">{{ t('chat.input.sampleLabel') }}</span>
      <button
        v-for="s in SAMPLE_QUESTIONS"
        :key="s.id"
        type="button"
        class="shrink-0 rounded-full border border-edge px-2.5 py-1 text-[11px] text-ink-dim transition-colors duration-150 hover:border-edge-bright hover:text-ink"
        @click="useSample(s.question)"
      >
        {{ t(`chat.samples.${s.id}`) }}
      </button>
    </div>

    <div class="flex items-end gap-3">
      <div
        class="flex-1 rounded-lg border bg-card transition-colors duration-150 focus-within:border-accent/70"
        :class="dragging ? 'border-accent' : 'border-edge'"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
      >
        <!-- Image preview strip -->
        <div v-if="images.length" class="flex items-start gap-2 px-3 pt-2.5">
          <div v-for="(img, i) in images" :key="i" class="group/img relative">
            <img
              :src="img"
              :alt="t('chat.input.attachment', { n: i + 1 })"
              class="h-14 w-14 cursor-zoom-in rounded-lg border border-edge bg-panel object-cover transition-all duration-150 hover:border-edge-bright"
              @click="openPreview(i)"
            />
            <button
              type="button"
              class="absolute -right-1.5 -top-1.5 flex h-4.5 w-4.5 items-center justify-center rounded-full border border-edge bg-panel text-ink-mute transition-all duration-150 hover:border-danger/60 hover:text-danger"
              :aria-label="t('chat.input.removeImage', { n: i + 1 })"
              @click="removeImage(i)"
            >
              <Icon name="x" :size="9" />
            </button>
          </div>
          <span class="mt-auto pb-0.5 font-mono text-[11px] text-ink-mute">{{ images.length }}/{{ MAX_IMAGES }}</span>
        </div>

        <textarea
          id="chat-textarea"
          ref="textareaRef"
          v-model="draft"
          rows="1"
          :disabled="store.streaming"
          :placeholder="t('chat.input.placeholder')"
          class="max-h-[132px] w-full resize-none bg-transparent px-4 py-2.5 text-[13.5px] leading-relaxed text-ink outline-none placeholder:text-ink-mute"
          :class="images.length ? 'pt-2' : ''"
          @input="autosize"
          @keydown="onKeydown"
          @paste="onPaste"
        />
      </div>

      <!-- Attach-image button -->
      <BaseTooltip :content="t('chat.input.attachTitle')">
        <button
          type="button"
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border text-ink-mute transition-colors duration-150 hover:text-ink-dim active:scale-95"
          :class="images.length ? 'border-accent/70 text-ink' : 'border-edge-bright'"
          :aria-label="t('chat.input.attachAria')"
          @click="pickImages"
        >
          <Icon name="image" :size="16" />
        </button>
      </BaseTooltip>

      <button
        v-if="!store.streaming"
        type="button"
        :disabled="!canSend"
        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors duration-150 active:scale-95 disabled:opacity-30"
        :class="canSend ? 'bg-ink text-deep hover:bg-ink/90' : 'border border-edge text-ink-mute'"
        :aria-label="t('chat.input.sendAria')"
        @click="send"
      >
        <Icon name="send" :size="16" />
      </button>
      <button
        v-else
        type="button"
        class="flex h-10 items-center gap-1.5 rounded-full border border-danger/50 bg-danger/10 px-4 text-[12px] text-danger transition-colors duration-150 hover:bg-danger/20 active:scale-95"
        @click="store.stopStream()"
      >
        <Icon name="stop" :size="12" />
        {{ t('chat.input.stop') }}
      </button>
    </div>

    <!-- Image count/size warning line (disappears automatically) -->
    <div v-if="imageWarn" class="mt-1.5 flex items-center gap-1.5 text-[11px] text-danger">
      <Icon name="alert" :size="11" />
      {{ imageWarn }}
    </div>

    <!-- Hidden file input -->
    <input ref="fileRef" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple class="hidden" @change="onFileChange" />

    <!-- Thumbnail preview dialog -->
    <ImageViewer :open="previewOpen" :images="images" v-model:index="previewIndex" @close="previewOpen = false" />
  </div>
</template>

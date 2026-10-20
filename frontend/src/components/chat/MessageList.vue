<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import MarkdownText from './MarkdownText.vue'
import MessageActions from './MessageActions.vue'
import CitationChunkDrawer from './CitationChunkDrawer.vue'
import Icon from '@/components/ui/Icon.vue'
import ImageViewer from '@/components/ui/ImageViewer.vue'
import { useChatStore } from '@/stores/chat'
import { useI18n } from 'vue-i18n'
import { SAMPLE_QUESTIONS } from '@/api/samples'
import type { Citation } from '@/api/types'
import { citationNumber } from '@/utils/citations'

/** 中栏：对话气泡流 + 流式渲染 + 引用溯源联动 + 答案操作条 */
const { t } = useI18n()
const store = useChatStore()
const listRef = ref<HTMLDivElement>()
const highlightCite = ref<number | null>(null)
let highlightTimer: ReturnType<typeof setTimeout> | null = null

/** 最后一条助手消息（重新生成按钮仅它可见） */
const lastAssistantIdx = computed(() => {
  for (let i = store.messages.length - 1; i >= 0; i--) {
    if (store.messages[i].role === 'assistant') return i
  }
  return -1
})

watch(
  () => store.messages.length + store.streamingText.length,
  async () => {
    await nextTick()
    listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: 'smooth' })
  },
)

function onCiteClick(msgIndex: number, n: number): void {
  highlightCite.value = msgIndex * 100 + n
  if (highlightTimer) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => (highlightCite.value = null), 1800)
  nextTick(() => {
    document.getElementById(`cite-card-${msgIndex}-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

/* 引用切片抽屉（知识库引用 → 定位切片原文；NL2SQL 引用 → 数据查询证据视图） */
const drawerOpen = ref(false)
const drawerCite = ref<Citation | null>(null)

function openCitation(c: Citation, msgIndex: number, n: number): void {
  onCiteClick(msgIndex, n)
  drawerCite.value = c
  drawerOpen.value = true
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
}

/* 图片预览弹窗（页内 Lightbox，多图可切换） */
const viewerOpen = ref(false)
const viewerImages = ref<string[]>([])
const viewerIndex = ref(0)

function openViewer(images: string[], i: number): void {
  viewerImages.value = images
  viewerIndex.value = i
  viewerOpen.value = true
}

/* 附图加载失败（如历史消息的图片文件已不存在）时显示占位，避免破图图标 */
const imgErr = ref<Record<string, boolean>>({})
function imgErrKey(msgId: number | string, ii: number): string {
  return `${msgId}:${ii}`
}
function isImgErr(msgId: number | string, ii: number): boolean {
  return !!imgErr.value[imgErrKey(msgId, ii)]
}
function onImgErr(msgId: number | string, ii: number): void {
  imgErr.value[imgErrKey(msgId, ii)] = true
}

function fillSample(q: string): void {
  const el = document.getElementById('chat-textarea') as HTMLTextAreaElement | null
  if (el) {
    el.value = q
    el.dispatchEvent(new Event('input'))
    el.focus()
  }
}
</script>

<template>
  <div ref="listRef" class="flex-1 overflow-y-auto px-4 py-6 md:px-8">
    <!-- 空状态：首次进入要问的第一个问题 -->
    <div v-if="store.messages.length === 0 && !store.streaming" class="mx-auto flex h-full max-w-[720px] flex-col justify-center gap-7">
      <div class="flex items-center gap-3">
        <img src="/logo.png" alt="RAGent" class="h-10 w-10 shrink-0 rounded-lg object-cover" />
        <div>
          <h2 class="text-[24px] font-semibold leading-tight text-ink">RAGent</h2>
          <p class="mt-1 text-[13px] text-ink-mute">{{ t('chat.msg.welcome') }}</p>
        </div>
      </div>
      <div class="grid gap-px overflow-hidden rounded-lg border border-edge bg-edge sm:grid-cols-2">
        <button
          v-for="s in SAMPLE_QUESTIONS"
          :key="s.id"
          type="button"
          class="group flex items-start gap-3 bg-card px-4 py-3.5 text-left transition-colors duration-150 hover:bg-raise"
          @click="fillSample(s.question)"
        >
          <Icon name="zap" :size="14" class="mt-0.5 shrink-0 text-ink-mute transition-colors group-hover:text-accent" />
          <div class="min-w-0">
            <div class="text-[13px] leading-snug text-ink">{{ s.question }}</div>
            <div class="mt-1 text-[11px] text-ink-mute">{{ t(`chat.samples.${s.id}`) }}</div>
          </div>
        </button>
      </div>
    </div>

    <!-- 消息流 -->
    <div v-else class="mx-auto max-w-[720px] space-y-6">
      <template v-for="(msg, i) in store.messages" :key="msg.id">
        <!-- 用户气泡（多模态：附图缩略图 + 文本） -->
        <div v-if="msg.role === 'user'" class="flex justify-end">
          <div class="max-w-[82%] rounded-lg bg-raise px-4 py-2.5 text-[13.5px] leading-relaxed text-ink">
            <div v-if="msg.images?.length" class="mb-2 flex flex-wrap justify-end gap-1.5">
              <template v-for="(img, ii) in msg.images" :key="ii">
                <img
                  v-if="!isImgErr(msg.id, ii)"
                  :src="img"
                  :alt="t('chat.input.attachment', { n: ii + 1 })"
                  class="h-24 w-24 cursor-zoom-in rounded border border-edge bg-panel object-cover transition-colors duration-150 hover:border-edge-bright"
                  loading="lazy"
                  @error="onImgErr(msg.id, ii)"
                  @click="openViewer(msg.images ?? [], ii)"
                />
                <div
                  v-else
                  class="flex h-24 w-24 cursor-default flex-col items-center justify-center gap-1 rounded border border-edge bg-panel px-1 text-center text-[11px] text-ink-mute"
                >
                  <Icon name="image" :size="16" />
                  <span>{{ t('chat.msg.imageLost') }}</span>
                </div>
              </template>
            </div>
            {{ msg.content }}
          </div>
        </div>

        <!-- 助手气泡 -->
        <div v-else class="group/msg flex gap-3">
          <img src="/logo.png" alt="RAGent" class="mt-0.5 h-6 w-6 shrink-0 rounded object-cover" />
          <div class="min-w-0 flex-1">
            <div class="rounded-lg border border-edge bg-card px-4 py-3 text-[13.5px] leading-relaxed">
              <MarkdownText :text="msg.content" :citations="msg.citations" @cite-click="(n) => onCiteClick(i, n)" />
            </div>
            <!-- 引用卡片列表 -->
            <div v-if="msg.citations?.length" class="mt-2 flex flex-wrap gap-1.5">
              <button
                v-for="(c, ci) in msg.citations"
                :id="`cite-card-${i}-${citationNumber(c, ci, msg.content)}`"
                :key="ci"
                type="button"
                class="group flex items-center gap-2 rounded border px-2.5 py-1.5 text-left transition-colors duration-150"
                :class="
                  highlightCite === i * 100 + citationNumber(c, ci, msg.content)
                    ? 'border-accent/70 bg-raise'
                    : 'border-edge bg-panel hover:border-edge-bright'
                "
                @click="openCitation(c, i, citationNumber(c, ci, msg.content))"
              >
                <span class="font-mono text-[11px] text-ink-mute">{{ citationNumber(c, ci, msg.content) }}</span>
                <template v-if="c.source_type === 'db' || c.doc_name.includes('NL2SQL')">
                  <Icon name="db" :size="12" class="shrink-0 text-ink-mute" />
                  <span class="text-[12px] text-ink-dim group-hover:text-ink">{{ t('chat.msg.citeDb', { table: 'sales' }) }}</span>
                  <span class="font-mono text-[11px] text-ink-mute">{{ t('chat.msg.sqlLive') }}</span>
                </template>
                <template v-else>
                  <span class="text-[12px] text-ink-dim group-hover:text-ink">{{ t('chat.msg.fromDoc', { doc: c.doc_name, path: c.section_path }) }}</span>
                  <span class="font-mono text-[11px] text-ink-mute">#{{ c.chunk_no }}</span>
                </template>
              </button>
            </div>
            <div class="mt-1.5 flex items-center gap-2">
              <span class="font-mono text-[11px] text-ink-mute">{{ fmtTime(msg.created_at) }}</span>
            </div>
            <!-- 操作条：复制 / 决策链 / 重新生成（末条）/ 反馈 -->
            <MessageActions
              :message="msg"
              :can-regenerate="i === lastAssistantIdx && !store.streaming"
              @regenerate="store.regenerate()"
              @view-decision="msg.decision_log_id != null && store.viewDecisionLog(msg.decision_log_id)"
            />
          </div>
        </div>
      </template>

      <!-- 流式助手气泡 -->
      <div v-if="store.streaming" class="flex gap-3">
        <img src="/logo.png" alt="RAGent" class="mt-0.5 h-6 w-6 shrink-0 rounded object-cover" />
        <div class="min-w-0 flex-1">
          <div class="rounded-lg border border-edge bg-card px-4 py-3 text-[13.5px] leading-relaxed">
            <template v-if="store.streamingText">
              <div class="typing-caret">
                <MarkdownText :text="store.streamingText" />
              </div>
            </template>
            <template v-else>
              <div class="flex items-center gap-2 py-1 text-[13px] text-ink-dim">
                <span class="thinking-dot h-1.5 w-1.5 rounded-full bg-ink-mute" style="animation-delay: 0s" />
                <span class="thinking-dot h-1.5 w-1.5 rounded-full bg-ink-mute" style="animation-delay: 0.15s" />
                <span class="thinking-dot h-1.5 w-1.5 rounded-full bg-ink-mute" style="animation-delay: 0.3s" />
                <span class="ml-1 text-[12px] text-ink-mute">{{ t('chat.msg.thinking') }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 引用切片抽屉 -->
    <CitationChunkDrawer :open="drawerOpen" :citation="drawerCite" @close="drawerOpen = false" />

    <!-- 图片预览弹窗 -->
    <ImageViewer :open="viewerOpen" :images="viewerImages" v-model:index="viewerIndex" @close="viewerOpen = false" />
  </div>
</template>

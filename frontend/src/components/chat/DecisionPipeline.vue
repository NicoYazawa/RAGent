<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import type { DecisionCard } from '@/stores/chat'
import { fmtMs } from '@/utils/decisionExport'

/**
 * 管线流程图模式 — 6 决策点垂直管线，SSE 实时点亮当前环节；
 * 回流（CRAG/Self-RAG）与闲聊直答旁路以虚线回边可视化
 */
const props = defineProps<{
  cards: DecisionCard[]
  /** 正在流式（实时模式） */
  streaming: boolean
  /** 当前进行中的管线环节（1~7，0=空闲） */
  activeStage: number
  /** 当前 pending 过渡卡（active 节点内展示动态文案） */
  pending: DecisionCard | null
}>()

const { t } = useI18n()
const stageKey = (s: number) => `chat.pipeline.stage${s}`

interface StageDef {
  step: number
  icon: string
  types: string[]
}

const STAGES: StageDef[] = [
  { step: 1, icon: 'route', types: ['router'] },
  { step: 2, icon: 'refresh', types: ['rewrite'] },
  { step: 3, icon: 'search', types: ['retrieve'] },
  { step: 4, icon: 'check', types: ['grade'] },
  { step: 5, icon: 'retry', types: ['correct'] },
  { step: 6, icon: 'sparkles', types: ['generate', 'reflect'] },
  { step: 7, icon: 'link', types: ['citation'] },
]

/* 行几何：固定行高 56px + 间隙 10px，回边按中心定位（纯 CSS 无测量） */
const ROW_H = 56
const ROW_GAP = 10
const centerOf = (rowIdx: number) => rowIdx * (ROW_H + ROW_GAP) + ROW_H / 2

interface NodeState {
  def: StageDef
  state: 'inactive' | 'active' | 'done' | 'warn'
  elapsedMs: number
  detail: string
  metric: string | null
  /** 未触发环节的旁路原因（流程结束后展示，替代生硬的「待触发」） */
  skip: string | null
}

/* 路由意图（判断旁路原因用，需先于 nodes 定义） */
const routerCard = computed(() => props.cards.find((c) => c.type === 'router'))
const intent = computed(() => (routerCard.value?.payload as { intent?: string } | undefined)?.intent ?? null)
const isChitchat = computed(() => intent.value === 'chitchat')

/** 已结束（实时完成或历史回放）但该环节无卡片 → 按意图/评分给出跳过原因 */
const finished = computed(() => !props.streaming && props.cards.length > 0)

function skipReason(def: StageDef): string | null {
  if (!finished.value) return null
  switch (def.step) {
    case 2:
      if (intent.value === 'chitchat') return t('chat.pipeline.skip.chitchatRewrite')
      if (intent.value === 'data_query') return t('chat.pipeline.skip.dataQueryRetrieve')
      if (intent.value === 'summarize') return t('chat.pipeline.skip.summarize')
      return null
    case 3:
      return intent.value === 'chitchat' ? t('chat.pipeline.skip.chitchatRetrieve') : null
    case 4:
      return intent.value === 'chitchat' ? t('chat.pipeline.skip.chitchatGrade') : null
    case 5:
      if (intent.value === 'chitchat') return t('chat.pipeline.skip.chitchatCorrect')
      if (intent.value === 'data_query') return t('chat.pipeline.skip.dataBypassCorrect')
      return t('chat.pipeline.skip.scorePassCorrect')
    case 7:
      return intent.value === 'chitchat' ? t('chat.pipeline.skip.chitchatCitation') : null
    default:
      return null
  }
}

const nodes = computed<NodeState[]>(() =>
  STAGES.map((def) => {
    const own = props.cards.filter((c) => def.types.includes(c.type))
    const elapsedMs = own.reduce((s, c) => s + c.elapsedMs, 0)
    const last = own[own.length - 1]
    const warn = own.some((c) => c.status === 'warn')
    const active = props.streaming && props.activeStage === def.step
    const state: NodeState['state'] = active ? 'active' : own.length === 0 ? 'inactive' : warn ? 'warn' : 'done'

    // 动态文案：active 时优先 pending 提示，否则取该环节最后一张卡
    const detail = active && props.pending && props.activeStage === def.step ? props.pending.detail : (last?.detail ?? '')
    const p = (last?.payload ?? {}) as Record<string, unknown>
    let metric: string | null = null
    if (def.step === 1 && p.intent) metric = `${p.intent} · ${(((p.confidence as number) ?? 0) * 100).toFixed(0)}%`
    else if (def.step === 3 && own.length) {
      // 精排卡（source=rerank）不是独立检索路，不计入「N 路命中」，避免重复计数
      const laneCards = own.filter((c) => (c.payload.source as string) !== 'rerank')
      if (laneCards.length) {
        const hits = laneCards.reduce((s, c) => s + ((c.payload.hit_count as number) ?? 0), 0)
        metric = t('chat.pipeline.laneHits', { lanes: laneCards.length, hits })
      }
    } else if (def.step === 4 && p.score != null) metric = `${(p.score as number).toFixed(1)} ${t('chat.metric.score')}`
    else if (def.step === 5 && p.action) metric = String(p.action)
    else if (def.step === 6 && own.length) {
      const gen = own.find((c) => c.type === 'generate')
      const refl = [...own].reverse().find((c) => c.type === 'reflect')
      metric = [gen ? `${(gen.payload.chars as number) ?? 0}${t('chat.metric.chars')}` : null, refl ? `${t('chat.metric.selfCheck')} ${String(refl.payload.result)}` : null].filter(Boolean).join(' · ') || null
    } else if (def.step === 7 && Array.isArray(p.citations)) metric = `${(p.citations as unknown[]).length} ${t('chat.metric.citations')}`
    return { def, state, elapsedMs, detail, metric, skip: own.length === 0 ? skipReason(def) : null }
  }),
)

/* 回边与旁路（按行中心定位的绝对定位虚线；routerCard/intent/isChitchat 见上） */
const EDGE_ROW = { retrieve: 2, crag: 4, generate: 5 } as const

const edges = computed(() => {
  const list: { key: string; label: string; from: number; to: number; side: 'left' | 'farleft' }[] = []
  if (props.cards.some((c) => c.type === 'correct')) {
    list.push({ key: 'crag', label: t('chat.pipeline.edge.crag'), from: EDGE_ROW.crag, to: EDGE_ROW.retrieve, side: 'left' })
  }
  if (props.cards.some((c) => c.type === 'reflect' && (c.payload as { result?: string }).result === 'fail')) {
    list.push({ key: 'reflect', label: t('chat.pipeline.edge.reflect'), from: EDGE_ROW.generate, to: EDGE_ROW.retrieve, side: 'farleft' })
  }
  return list
})

const bypass = computed(() => {
  if (!isChitchat.value) return null
  return { from: 0, to: 5 } // ① → ⑥ 闲聊直答旁路
})

function edgeStyle(from: number, to: number): Record<string, string> {
  const top = centerOf(to)
  return { top: `${top}px`, height: `${centerOf(from) - top}px` }
}
</script>

<template>
  <div class="anim-fade-up relative py-1" :style="{ paddingLeft: '44px' }">
    <!-- 回流回边（左 gutter 两层虚线，⑤/⑥ → ③） -->
    <div
      v-for="e in edges"
      :key="e.key"
      class="absolute rounded-l-xl border border-dashed"
      :class="e.side === 'left' ? 'border-warn/60' : 'border-edge-bright'"
      :style="{ left: e.side === 'left' ? '22px' : '2px', width: '16px', ...edgeStyle(e.from, e.to) }"
    >
      <span
        class="absolute left-1.5 top-1/2 -translate-y-1/2 -rotate-90 whitespace-nowrap font-mono text-[8.5px] tracking-wider"
        :class="e.side === 'left' ? 'text-warn/80' : 'text-accent/80'"
      >
        {{ e.label }}
      </span>
    </div>

    <!-- 闲聊直答旁路（① → ⑥ 最外层） -->
    <div
      v-if="bypass"
      class="absolute rounded-r-xl border border-dashed border-ok/60"
      :style="{ right: '4px', width: '16px', ...edgeStyle(bypass.from, bypass.to) }"
    >
      <span class="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 -rotate-90 whitespace-nowrap font-mono text-[8.5px] tracking-wider text-ok">
        {{ t('chat.pipeline.bypass.chitchat') }}
      </span>
    </div>

    <!-- 节点列：行高 56 + 间隙 10（连接线），与 centerOf 几何一致 -->
    <div class="flex flex-col">
      <div v-for="(n, i) in nodes" :key="n.def.step" class="contents">
        <div
          class="flex items-center gap-2.5 rounded-xl border px-3 transition-all duration-300"
          :class="[
            n.state === 'active'
              ? 'glow-edge border-edge-bright bg-raise'
              : n.state === 'warn'
                ? 'border-warn/40 bg-warn/5'
                : n.state === 'done'
                  ? 'border-edge bg-card/80'
                  : 'border-edge/60 border-dashed bg-transparent',
          ]"
          :style="{ height: `${ROW_H}px` }"
        >
          <!-- 序号+图标 -->
          <span
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-bold transition-colors"
            :class="
              n.state === 'active'
                ? 'border border-edge-bright bg-raise text-accent'
                : n.state === 'warn'
                  ? 'border border-warn/40 bg-warn/15 text-warn'
                  : n.state === 'done'
                    ? 'border border-ok/40 bg-ok/10 text-ok'
                    : 'border border-edge text-ink-mute'
            "
          >
            {{ n.def.step }}
          </span>
          <Icon
            :name="n.state === 'active' ? 'zap' : n.def.icon"
            :size="14"
            class="shrink-0 transition-colors"
            :class="n.state === 'active' ? 'animate-pulse text-accent' : n.state === 'warn' ? 'text-warn' : n.state === 'done' ? 'text-ok' : 'text-ink-mute'"
          />

          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="text-[12px] font-medium" :class="n.state === 'inactive' ? 'text-ink-mute' : n.state === 'warn' ? 'text-warn/90' : 'text-ink/90'">
                {{ t(stageKey(n.def.step)) }}
              </span>
              <span v-if="n.metric" class="truncate font-mono text-[11px] text-accent/80">{{ n.metric }}</span>
            </div>
            <p class="mt-0.5 truncate text-[11px] leading-tight" :class="n.state === 'inactive' ? 'text-ink-mute/60' : 'text-ink-dim'">
              {{ n.detail || n.skip || '' }}
            </p>
          </div>

          <span v-if="n.elapsedMs > 0" class="shrink-0 font-mono text-[11px] text-accent/80">{{ fmtMs(n.elapsedMs) }}</span>
        </div>

        <!-- 节点间连接线 -->
        <div v-if="i < nodes.length - 1" class="flex justify-start" :style="{ height: `${ROW_GAP}px`, marginLeft: '26px' }">
          <div
            class="w-px transition-colors duration-300"
            :class="nodes[i].state !== 'inactive' && nodes[i + 1].state !== 'inactive' ? 'bg-raise0' : 'bg-edge'"
            :style="{ height: '100%' }"
          />
        </div>
      </div>
    </div>
  </div>
</template>

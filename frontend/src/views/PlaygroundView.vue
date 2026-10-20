<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import ScoreRing from '@/components/chat/ScoreRing.vue'
import { sourceMeta, fuseAndGrade, getDatasources, testRetrieveLane } from '@/api/admin'
import type { FusedItem, RetrievalGrade, RetrievalLane, RetrievalSource } from '@/api/types'

/**
 * 检索测试 Playground — 直观验证 Q3/Q4 链路：
 * 三路并行召回（按数据源开关裁剪）→ 应用层 RRF 融合（k=60）→ Grader 评分
 */
const { t } = useI18n()
const ALL_SOURCES: RetrievalSource[] = ['vector', 'keyword', 'database']
const SAMPLE_ITEMS = [
  { key: 'mixed', q: 'ES 的向量检索和 BM25 关键词检索怎么配合？' },
  { key: 'ops', q: '磁盘使用率超过多少会触发告警？' },
  { key: 'biz', q: '上季度智能音箱卖得怎么样？' },
]
const samples = computed(() => SAMPLE_ITEMS.map((s) => ({ label: t(`playground.samples.${s.key}`), q: s.q })))

const enabled = ref<RetrievalSource[]>([])
const loadingConfig = ref(true)

const query = ref('')
const topK = ref(5)
const running = ref(false)

interface LaneState {
  status: 'idle' | 'loading' | 'done' | 'error'
  lane: RetrievalLane | null
  error: string
}
const lanes = ref<Record<string, LaneState>>({})
const fused = ref<FusedItem[] | null>(null)
const grade = ref<RetrievalGrade | null>(null)
const fusing = ref(false)

onMounted(async () => {
  const items = await getDatasources()
  enabled.value = items.filter((i) => i.enabled).map((i) => i.source_type)
  reset()
  loadingConfig.value = false
})

function reset(): void {
  lanes.value = Object.fromEntries(ALL_SOURCES.map((s) => [s, { status: 'idle', lane: null, error: '' }]))
  fused.value = null
  grade.value = null
}

async function run(): Promise<void> {
  const q = query.value.trim()
  if (!q || running.value) return
  running.value = true
  reset()
  for (const s of enabled.value) lanes.value[s].status = 'loading'

  // 三路并行召回，各路独立完成即点亮（模拟 asyncio.gather）
  const done = Promise.all(
    enabled.value.map(async (s) => {
      try {
        const lane = await testRetrieveLane(q, s, topK.value)
        lanes.value[s] = { status: 'done', lane, error: '' }
      } catch (e) {
        lanes.value[s] = { status: 'error', lane: null, error: (e as Error).message }
      }
    }),
  )
  await done

  // 全部召回完成后融合 + 评分（真实模式传 query 供 Grader 评估）
  fusing.value = true
  try {
    const ready = enabled.value.map((s) => lanes.value[s].lane).filter((l): l is RetrievalLane => l != null)
    const result = await fuseAndGrade(ready, q)
    fused.value = result.fused
    grade.value = result.grade
  } finally {
    fusing.value = false
    running.value = false
  }
}

const disabledSources = () => ALL_SOURCES.filter((s) => !enabled.value.includes(s))
const hasResult = () => fused.value != null || grade.value != null

/** 示例 chip：填充并立即执行 */
function useSample(q: string): void {
  query.value = q
  void run()
}

const VERDICT_CLS: Record<RetrievalGrade['verdict'], string> = {
  pass: 'border-ok/50 bg-ok/10 text-ok',
  partial: 'border-warn/50 bg-warn/10 text-warn',
  fail: 'border-danger/50 bg-danger/10 text-danger',
}
function verdictLabel(v: RetrievalGrade['verdict']): string {
  return t(`playground.verdict.${v}`)
}
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <!-- 页头 -->
      <div class="mb-6">
        <h1 class="text-[24px] font-semibold leading-tight text-ink">
          {{ t('playground.title') }}
        </h1>
        <p class="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-ink-mute">
          {{ t('playground.intro') }}
        </p>
      </div>

      <!-- 工具栏 -->
      <div class="rounded-lg border border-edge bg-card p-4">
        <div class="flex flex-wrap items-center gap-3">
          <div class="flex min-w-[240px] flex-1 items-center gap-2 rounded-lg border border-edge bg-panel px-3 transition-colors duration-150 focus-within:border-accent/70">
            <Icon name="search" :size="15" class="shrink-0 text-ink-mute" />
            <input
              v-model="query"
              type="text"
              :placeholder="t('playground.queryPlaceholder')"
              class="h-10 w-full bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-mute"
              @keydown.enter="run"
            />
          </div>

          <div class="flex items-center gap-3">
            <button
              v-for="k in [3, 5, 8]"
              :key="k"
              type="button"
              class="relative pb-1 font-mono text-[12px] transition-colors"
              :class="topK === k ? 'text-ink' : 'text-ink-mute hover:text-ink-dim'"
              :title="t('playground.topKTitle', { k })"
              @click="topK = k"
            >
              k={{ k }}
              <span v-if="topK === k" class="absolute inset-x-0 -bottom-0.5 h-px bg-accent" />
            </button>
          </div>

          <button
            type="button"
            class="flex h-10 items-center gap-2 rounded-lg border px-4 text-[13px] font-medium transition-all duration-150 active:scale-95 disabled:opacity-40"
            :class="query.trim() && !running ? 'border-edge-bright bg-raise text-accent hover:bg-raise' : 'border-edge text-ink-mute'"
            :disabled="!query.trim() || running"
            @click="run"
          >
            <Icon :name="running ? 'refresh' : 'zap'" :size="14" :class="running ? 'animate-spin' : ''" />
            {{ running ? t('playground.running') : t('playground.run') }}
          </button>
        </div>

        <!-- 示例 chips -->
        <div class="mt-3 flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 font-mono text-[11px] tracking-wider text-ink-mute">{{ t('playground.sampleLabel') }}</span>
          <button
            v-for="s in samples"
            :key="s.q"
            type="button"
            class="rounded-full border border-edge bg-card px-2.5 py-1 text-[11px] text-ink-dim transition-all duration-150 hover:border-edge-bright hover:text-accent"
            @click="useSample(s.q)"
          >
            {{ s.label }}
          </button>
          <span v-if="disabledSources().length" class="ml-auto font-mono text-[11px] text-ink-mute">
            {{ t('playground.disabled') }}{{ disabledSources().map((s) => sourceMeta(s).label).join(' / ') }}{{ t('playground.seeDatasource') }}
          </span>
        </div>
      </div>

      <!-- 空态：当前召回配置 + 检索链路（数据来自真实开关状态） -->
      <div
        v-if="!loadingConfig && !running && !hasResult() && lanes.vector?.status === 'idle'"
        class="mt-6 grid gap-4 lg:grid-cols-2"
      >
        <div class="overflow-hidden rounded-lg border border-edge bg-card">
          <div class="border-b border-edge px-4 py-2.5">
            <h2 class="text-[13px] font-medium text-ink">{{ t('playground.recall') }}</h2>
            <p class="mt-0.5 text-[11px] text-ink-mute">{{ t('playground.recallSub', { n: topK }) }}</p>
          </div>
          <div class="divide-y divide-edge">
            <div v-for="s in ALL_SOURCES" :key="s" class="flex items-start gap-3 px-4 py-3">
              <Icon :name="sourceMeta(s).icon" :size="15" class="mt-0.5 shrink-0 text-ink-mute" />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-[13px] text-ink">{{ sourceMeta(s).label }}</span>
                  <span class="ml-auto text-[11px]" :class="enabled.includes(s) ? 'text-ok' : 'text-ink-mute'">
                    {{ enabled.includes(s) ? 'Enabled' : 'Disabled' }}
                  </span>
                </div>
                <p class="mt-1 text-[12px] leading-relaxed text-ink-mute">{{ sourceMeta(s).desc }}</p>
              </div>
            </div>
          </div>
        </div>

        <div class="overflow-hidden rounded-lg border border-edge bg-card">
          <div class="border-b border-edge px-4 py-2.5">
            <h2 class="text-[13px] font-medium text-ink">{{ t('playground.chain') }}</h2>
          </div>
          <ol class="px-4 py-3">
            <li class="flex gap-3 pb-3.5">
              <span class="font-mono text-[11px] leading-5 text-ink-mute">1</span>
              <div>
                <div class="text-[13px] text-ink">{{ t('playground.recall') }}</div>
                <div class="mt-0.5 text-[11px] text-ink-mute">{{ t('playground.recallSub', { n: topK }) }}</div>
              </div>
            </li>
            <li class="flex gap-3 pb-3.5">
              <span class="font-mono text-[11px] leading-5 text-ink-mute">2</span>
              <div>
                <div class="text-[13px] text-ink">{{ t('playground.rrf') }}</div>
                <div class="mt-0.5 text-[11px] text-ink-mute">{{ t('playground.rrfNote') }}</div>
              </div>
            </li>
            <li class="flex gap-3 pb-3.5">
              <span class="font-mono text-[11px] leading-5 text-ink-mute">3</span>
              <div>
                <div class="text-[13px] text-ink">{{ t('playground.chainGrader') }}</div>
                <div class="mt-0.5 text-[11px] text-ink-mute">{{ t('playground.chainGraderNote') }}</div>
              </div>
            </li>
            <li class="flex gap-3">
              <span class="font-mono text-[11px] leading-5 text-ink-mute">4</span>
              <div>
                <div class="text-[13px] text-ink">{{ t('playground.chainCitation') }}</div>
                <div class="mt-0.5 text-[11px] text-ink-mute">{{ t('playground.chainCitationNote') }}</div>
              </div>
            </li>
          </ol>
        </div>
      </div>

      <template v-if="lanes.vector?.status !== 'idle'">
        <!-- ① 三路召回 -->
        <h3 class="mb-3 mt-6 flex items-center gap-2 text-[13.5px] font-semibold text-ink">
          <span class="font-mono text-[11px] text-ink-mute">①</span>
          {{ t('playground.recall') }}
          <span class="font-mono text-[11px] font-normal text-ink-mute">{{ t('playground.recallSub', { n: topK }) }}</span>
        </h3>
        <div class="grid gap-3 md:grid-cols-2">
          <div
            v-for="s in enabled"
            :key="s"
            class="rounded-xl border p-3.5 transition-colors duration-200"
            :class="lanes[s].status === 'loading' ? 'border-edge-bright bg-card/60' : 'border-edge bg-card/80'"
          >
            <div class="flex items-center gap-2">
              <Icon :name="sourceMeta(s).icon" :size="14" :class="sourceMeta(s).color" />
              <span class="text-[12.5px] font-medium text-ink">{{ sourceMeta(s).label }}</span>
              <span class="flex-1" />
              <span v-if="lanes[s].status === 'loading'" class="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-accent/70 border-t-transparent" />
              <span v-else-if="lanes[s].status === 'done'" class="font-mono text-[11px] text-ok">
                {{ lanes[s].lane?.hits.length ?? 0 }} {{ t('playground.hitsUnit') }} · {{ lanes[s].lane?.latency_ms }}ms
              </span>
              <span v-else-if="lanes[s].status === 'error'" class="font-mono text-[11px] text-danger">{{ t('playground.laneFailed') }}</span>
            </div>

            <div v-if="lanes[s].status === 'loading'" class="mt-3 space-y-2">
              <div v-for="i in 3" :key="i" class="h-10 animate-pulse rounded-lg border border-edge bg-panel/50" />
            </div>
            <div v-else-if="lanes[s].status === 'error'" class="mt-2 text-[11.5px] text-danger">{{ lanes[s].error }}</div>
            <div v-else-if="lanes[s].lane" class="mt-2.5 space-y-1.5">
              <div v-for="(hit, hi) in lanes[s].lane!.hits" :key="hi" class="rounded-lg border border-edge/70 bg-panel/60 px-2.5 py-2">
                <div class="flex items-center gap-2">
                  <span class="min-w-0 flex-1 truncate text-[11.5px] text-ink/90">{{ hit.title }}</span>
                  <span class="shrink-0 rounded bg-raise px-1 font-mono text-[11px] text-ink-dim">{{ hit.score }}</span>
                </div>
                <p class="mt-1 line-clamp-2 text-[11px] leading-relaxed text-ink-mute">{{ hit.snippet }}</p>
              </div>
              <p v-if="!lanes[s].lane!.hits.length" class="py-2 text-center font-mono text-[11px] text-ink-mute">0 {{ t('playground.hitsUnit') }}</p>
            </div>
          </div>
        </div>

        <!-- ② RRF 融合 -->
        <h3 class="mb-3 mt-6 flex items-center gap-2 text-[13.5px] font-semibold text-ink">
          <span class="font-mono text-[11px] text-accent">②</span>
          {{ t('playground.rrf') }}
          <span class="font-mono text-[11px] font-normal text-ink-mute">{{ t('playground.rrfNote') }}</span>
          <span v-if="fusing" class="h-3 w-3 animate-spin rounded-full border-[1.5px] border-accent/70 border-t-transparent" />
        </h3>
        <div class="overflow-hidden rounded-xl border border-edge bg-card/80">
          <div v-if="fusing" class="space-y-2 p-4">
            <div v-for="i in 4" :key="i" class="h-9 animate-pulse rounded-lg border border-edge bg-panel/50" />
          </div>
          <template v-else-if="fused?.length">
            <div class="grid grid-cols-[2.2rem_1fr_4.5rem_7.5rem] items-center gap-2 border-b border-edge bg-panel/60 px-4 py-2 font-mono text-[11px] tracking-wider text-ink-mute">
              <span>RANK</span><span>{{ t('playground.colFragment') }}</span><span class="text-right">RRF</span><span class="text-right">{{ t('playground.colSource') }}</span>
            </div>
            <div
              v-for="(item, i) in fused"
              :key="item.key"
              class="grid grid-cols-[2.2rem_1fr_4.5rem_7.5rem] items-center gap-2 border-b border-edge/50 px-4 py-2.5 transition-colors last:border-b-0 hover:bg-panel/40"
            >
              <span class="font-mono text-[11px]" :class="i === 0 ? 'text-accent' : 'text-ink-mute'">#{{ i + 1 }}</span>
              <div class="min-w-0">
                <div class="truncate text-[12px] text-ink/90">{{ item.hit.title }}</div>
                <div class="truncate font-mono text-[11px] text-ink-mute">
                  {{ item.hit.meta.doc_name ? `${item.hit.meta.doc_name} #${item.hit.meta.chunk_no}` : t('playground.bizRow') }}
                </div>
              </div>
              <span class="text-right font-mono text-[11px] text-accent">{{ item.rrf.toFixed(4) }}</span>
              <div class="flex flex-wrap justify-end gap-1">
                <span
                  v-for="ln in item.from_lanes"
                  :key="ln"
                  class="rounded border border-edge px-1 font-mono text-[11px]"
                  :class="sourceMeta(ln).color"
                >
                  {{ sourceMeta(ln).short }}
                </span>
              </div>
            </div>
          </template>
          <div v-else class="px-4 py-6 text-center font-mono text-[11px] text-ink-mute">{{ t('playground.fuseEmpty') }}</div>
        </div>

        <!-- ③ Grader 评分 -->
        <h3 class="mb-3 mt-6 flex items-center gap-2 text-[13.5px] font-semibold text-ink">
          <span class="font-mono text-[11px] text-accent">③</span>
          {{ t('playground.grader') }}
        </h3>
        <div v-if="grade" class="anim-fade-up rounded-xl border border-edge bg-card/80 p-4">
          <div class="flex items-center gap-4">
            <ScoreRing :score="grade.score" :size="64" />
            <div class="min-w-0 flex-1">
              <span class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px]" :class="VERDICT_CLS[grade.verdict]">
                <Icon name="zap" :size="11" />
                {{ verdictLabel(grade.verdict) }}
              </span>
              <p class="mt-2 text-[12.5px] leading-relaxed text-ink-dim">{{ grade.reason }}</p>
            </div>
          </div>
          <div class="mt-3 flex flex-wrap gap-2 border-t border-edge pt-3 font-mono text-[11px] text-ink-mute">
            <span class="text-ok">{{ t('playground.reasonPass') }}</span>
            <span class="text-warn">{{ t('playground.reasonPartial') }}</span>
            <span class="text-danger">{{ t('playground.reasonFail') }}</span>
          </div>
        </div>
        <div v-else-if="!fusing" class="rounded-xl border border-dashed border-edge px-4 py-6 text-center font-mono text-[11px] text-ink-mute">{{ t('playground.waitFuse') }}</div>
      </template>
    </div>
  </div>
</template>

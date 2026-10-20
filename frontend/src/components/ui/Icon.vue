<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import {
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  Globe,
  Image,
  Info,
  KeyRound,
  Layers,
  List,
  MessageSquare,
  Moon,
  Network,
  PanelRight,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Route,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  Square,
  StepForward,
  Sun,
  Trash2,
  TriangleAlert,
  Upload,
  X,
  Zap,
} from 'lucide-vue-next'

/**
 * 统一线性图标组件（stroke 风格，24x24 viewBox）
 * 底层使用 lucide-vue-next：纯 SVG、无内置配色，颜色由 currentColor 继承 token，
 * 与 theme.css 的青色光效体系零冲突。新增图标在此登记即可。
 */
const props = withDefaults(
  defineProps<{
    name: string
    size?: number
  }>(),
  { size: 16 },
)

const icons: Record<string, Component> = {
  alert: TriangleAlert,
  book: BookOpen,
  brain: Brain,
  chat: MessageSquare,
  check: Check,
  'chev-down': ChevronDown,
  'chev-left': ChevronLeft,
  'chev-right': ChevronRight,
  clock: Clock,
  copy: Copy,
  db: Database,
  database2: Database,
  download: Download,
  file: FileText,
  globe: Globe,
  image: Image,
  info: Info,
  key: KeyRound,
  layers: Layers,
  link: ExternalLink,
  logs: List,
  moon: Moon,
  node: Network,
  'panel-right': PanelRight,
  pause: Pause,
  play: Play,
  plus: Plus,
  refresh: RefreshCw,
  retry: RotateCcw,
  route: Route,
  search: Search,
  send: Send,
  slider: SlidersHorizontal,
  sparkles: Sparkles,
  step: StepForward,
  stop: Square,
  sun: Sun,
  trash: Trash2,
  upload: Upload,
  x: X,
  zap: Zap,
}

const resolved = computed(() => icons[props.name] ?? Info)
</script>

<template>
  <component :is="resolved" :size="size" :stroke-width="2" aria-hidden="true" class="shrink-0" />
</template>

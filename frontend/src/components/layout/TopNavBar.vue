<script setup lang="ts">
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import Icon from '@/components/ui/Icon.vue'
import BaseTooltip from '@/components/ui/BaseTooltip.vue'
import { useThemeStore } from '@/stores/theme'
import { useLocaleStore } from '@/stores/locale'
import { useI18n } from 'vue-i18n'

const route = useRoute()
const theme = useThemeStore()
const localeStore = useLocaleStore()
const { locale } = storeToRefs(localeStore)
const { t } = useI18n()

const navItems = [
  { key: 'nav.chat', to: '/chat', icon: 'chat' },
  { key: 'nav.kb', to: '/admin/kb', icon: 'book' },
  { key: 'nav.datasource', to: '/admin/datasources', icon: 'slider' },
  { key: 'nav.playground', to: '/admin/playground', icon: 'layers' },
  { key: 'nav.logs', to: '/admin/logs', icon: 'logs' },
]

function isActive(to: string): boolean {
  return route.path === to || (to === '/chat' && route.path === '/')
}
</script>

<template>
  <header class="scanline flex h-14 items-center border-b border-edge bg-panel/90">
    <!-- 品牌区 -->
    <div class="flex items-center gap-3 pl-5 pr-8">
      <img
        src="/logo.png"
        alt="RAGent"
        class="h-8 w-8 shrink-0 rounded-lg object-cover"
      />
      <div class="flex flex-col leading-none">
        <span class="text-[15px] font-bold tracking-wide text-ink">
          <span class="glow-text">RAG</span>ent
        </span>
        <span class="mt-1 font-mono text-[11px] tracking-[0.18em] text-ink-mute">AI KNOWLEDGE QA SYSTEM</span>
      </div>
    </div>

    <!-- 导航菜单 -->
    <nav class="flex h-full items-stretch gap-1" :aria-label="t('layout.mainNav')">
      <router-link
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="group relative flex items-center gap-2 px-5 text-sm transition-colors duration-150"
        :class="isActive(item.to) ? 'text-accent' : 'text-ink-dim hover:text-ink'"
      >
        <Icon :name="item.icon" :size="15" />
        <span>{{ t(item.key) }}</span>
        <!-- 激活指示条 -->
        <span
          class="absolute bottom-0 left-1/2 h-[2px] -translate-x-1/2 rounded-full transition-all duration-200"
          :class="isActive(item.to) ? 'w-8 bg-accent' : 'w-0 bg-transparent group-hover:w-6 group-hover:bg-edge-bright'"
        />
      </router-link>
    </nav>

    <div class="flex-1" />

    <!-- 右侧状态区 -->
    <div class="flex items-center gap-3 pr-5">
      <!-- 语言切换（中 / EN） -->
      <div class="flex items-center gap-1 rounded-md border border-edge bg-card px-1 py-0.5">
        <button
          v-for="l in (['zh-CN', 'en-US'] as const)"
          :key="l"
          type="button"
          class="rounded px-2 py-1 text-xs font-medium transition-colors duration-150"
          :class="locale === l ? 'bg-raise text-accent' : 'text-ink-mute hover:text-ink'"
          @click="localeStore.setLocale(l)"
        >
          {{ l === 'zh-CN' ? '中' : 'EN' }}
        </button>
      </div>
      <!-- 亮色/暗色模式切换 -->
      <BaseTooltip :content="theme.mode === 'dark' ? t('layout.theme.toLight') : t('layout.theme.toDark')">
        <button
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-md border border-edge bg-card text-ink-dim transition-all duration-150 hover:border-edge-bright hover:text-accent active:scale-95 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/60"
          :aria-label="theme.mode === 'dark' ? t('layout.theme.toLight') : t('layout.theme.toDark')"
          @click="theme.toggle()"
        >
          <Icon :name="theme.mode === 'dark' ? 'sun' : 'moon'" :size="15" />
        </button>
      </BaseTooltip>
    </div>
  </header>
</template>

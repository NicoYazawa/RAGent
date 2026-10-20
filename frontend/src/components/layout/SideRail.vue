<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BaseTooltip from '@/components/ui/BaseTooltip.vue'
import { useThemeStore } from '@/stores/theme'
import { useLocaleStore } from '@/stores/locale'

/**
 * 应用外壳 — 桌面为 52px 图标轨（顶部品牌、中部五个目的地、底部主题与语言），
 * 手机折叠为底部标签栏。选择态统一为一条 1px accent 线。
 */
const route = useRoute()
const theme = useThemeStore()
const localeStore = useLocaleStore()
const { locale } = storeToRefs(localeStore)
const { t } = useI18n()

const items = [
  { key: 'nav.chat', to: '/chat', icon: 'chat', short: 'chat.short' },
  { key: 'nav.kb', to: '/admin/kb', icon: 'book', short: 'kb.short' },
  { key: 'nav.datasource', to: '/admin/datasources', icon: 'slider', short: 'datasource.short' },
  { key: 'nav.playground', to: '/admin/playground', icon: 'layers', short: 'playground.short' },
  { key: 'nav.logs', to: '/admin/logs', icon: 'logs', short: 'logs.short' },
]

const isActive = (to: string): boolean => route.path === to || (to === '/chat' && route.path === '/')

const themeLabel = computed(() => (theme.mode === 'dark' ? t('layout.theme.toLight') : t('layout.theme.toDark')))
</script>

<template>
  <!-- 桌面：图标轨 -->
  <aside class="hidden h-full w-[52px] shrink-0 flex-col items-center border-r border-edge bg-panel py-3 md:flex">
    <router-link to="/chat" class="mb-4 flex h-9 w-9 items-center justify-center" aria-label="RAGent">
      <img src="/logo.png" alt="RAGent" class="h-7 w-7 rounded object-cover" />
    </router-link>

    <nav class="flex w-full flex-1 flex-col items-center gap-0.5" :aria-label="t('layout.mainNav')">
      <BaseTooltip v-for="item in items" :key="item.to" :content="t(item.key)" side="right">
        <router-link
          :to="item.to"
          class="relative flex h-9 w-9 items-center justify-center rounded-md transition-colors duration-150"
          :class="isActive(item.to) ? 'text-ink' : 'text-ink-mute hover:text-ink-dim'"
        >
          <Icon :name="item.icon" :size="17" />
          <span v-if="isActive(item.to)" class="absolute -left-[8px] top-1/2 h-4 w-px -translate-y-1/2 bg-accent" />
        </router-link>
      </BaseTooltip>
    </nav>

    <div class="flex flex-col items-center gap-1 pt-2">
      <BaseTooltip :content="themeLabel" side="right">
        <button
          type="button"
          class="flex h-9 w-9 items-center justify-center rounded-md text-ink-mute transition-colors duration-150 hover:text-ink-dim"
          :aria-label="themeLabel"
          @click="theme.toggle()"
        >
          <Icon :name="theme.mode === 'dark' ? 'sun' : 'moon'" :size="16" />
        </button>
      </BaseTooltip>
      <BaseTooltip :content="t('layout.switchLocale')" side="right">
        <button
          type="button"
          class="flex h-8 w-9 items-center justify-center rounded-md text-[11px] font-medium text-ink-mute transition-colors duration-150 hover:text-ink-dim"
          :aria-label="t('layout.switchLocale')"
          @click="localeStore.setLocale(locale === 'zh-CN' ? 'en-US' : 'zh-CN')"
        >
          {{ locale === 'zh-CN' ? '中' : 'EN' }}
        </button>
      </BaseTooltip>
    </div>
  </aside>

  <!-- 手机：底部标签栏 -->
  <nav
    class="fixed inset-x-0 bottom-0 z-40 flex h-14 items-stretch border-t border-edge bg-panel md:hidden"
    :aria-label="t('layout.mainNav')"
  >
    <router-link
      v-for="item in items"
      :key="item.to"
      :to="item.to"
      class="relative flex flex-1 flex-col items-center justify-center gap-0.5"
      :class="isActive(item.to) ? 'text-ink' : 'text-ink-mute'"
    >
      <Icon :name="item.icon" :size="17" />
      <span class="text-[11px] leading-none">{{ t(item.key) }}</span>
      <span v-if="isActive(item.to)" class="absolute inset-x-3 top-0 h-px bg-accent" />
    </router-link>
  </nav>
</template>

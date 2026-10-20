import { defineStore } from 'pinia'
import { ref } from 'vue'
import i18n, { DEFAULT_LOCALE, SUPPORTED_LOCALES, type Locale } from '@/i18n'

const STORAGE_KEY = 'ragent-locale'

function normalize(v: string | null): Locale {
  if (v && (SUPPORTED_LOCALES as readonly string[]).includes(v)) return v as Locale
  // 浏览器语言前缀匹配（zh-* → zh-CN，en-* → en-US）
  if (v) {
    const lower = v.toLowerCase()
    if (lower.startsWith('zh')) return 'zh-CN'
    if (lower.startsWith('en')) return 'en-US'
  }
  return DEFAULT_LOCALE
}

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<Locale>(DEFAULT_LOCALE)

  function apply(v: Locale) {
    locale.value = v
    i18n.global.locale.value = v
    document.documentElement.lang = v === 'zh-CN' ? 'zh-CN' : 'en'
  }

  function initLocale() {
    const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
    const nav = typeof navigator !== 'undefined' ? navigator.language : null
    apply(normalize(stored ?? nav))
  }

  function setLocale(v: Locale) {
    apply(v)
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, v)
  }

  return { locale, initLocale, setLocale }
})

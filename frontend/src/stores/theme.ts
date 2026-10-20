import { ref } from 'vue'
import { defineStore } from 'pinia'

/** 主题 Store — dark（默认）/ light 双模式，localStorage 持久化 */
export type ThemeMode = 'dark' | 'light'
const STORAGE_KEY = 'ragent-theme'

function readInitial(): ThemeMode {
  // index.html 防闪脚本可能已设置 class；否则读 localStorage
  if (typeof document !== 'undefined' && document.documentElement.classList.contains('light')) return 'light'
  try {
    return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readInitial())

  function apply(m: ThemeMode): void {
    document.documentElement.classList.toggle('light', m === 'light')
    try {
      localStorage.setItem(STORAGE_KEY, m)
    } catch {
      /* 隐私模式下忽略 */
    }
  }

  apply(mode.value)

  function toggle(): void {
    mode.value = mode.value === 'dark' ? 'light' : 'dark'
    apply(mode.value)
  }

  return { mode, toggle }
})

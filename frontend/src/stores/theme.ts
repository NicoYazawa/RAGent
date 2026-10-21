import { ref } from 'vue'
import { defineStore } from 'pinia'

/** Theme store — dark (default) and light modes persisted in localStorage */
export type ThemeMode = 'dark' | 'light'
const STORAGE_KEY = 'ragent-theme'

function readInitial(): ThemeMode {
  // the anti-flash script in index.html may have set the class; otherwise read localStorage
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
      /* ignored in private mode */
    }
  }

  apply(mode.value)

  function toggle(): void {
    mode.value = mode.value === 'dark' ? 'light' : 'dark'
    apply(mode.value)
  }

  return { mode, toggle }
})

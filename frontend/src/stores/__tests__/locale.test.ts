import { beforeEach, describe, expect, it } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useLocaleStore } from '../locale'

describe('locale store', () => {
  beforeEach(() => {
    localStorage.clear()
    // @ts-expect-error - redefine navigator.language
    delete navigator.language
    setActivePinia(createPinia())
  })

  it('无存储时按浏览器语言初始化', () => {
    Object.defineProperty(navigator, 'language', { value: 'en-US', configurable: true })
    const s = useLocaleStore()
    s.initLocale()
    expect(s.locale).toBe('en-US')
  })

  it('localStorage 优先于浏览器语言', () => {
    localStorage.setItem('ragent-locale', 'zh-CN')
    Object.defineProperty(navigator, 'language', { value: 'en-US', configurable: true })
    const s = useLocaleStore()
    s.initLocale()
    expect(s.locale).toBe('zh-CN')
  })

  it('setLocale 持久化并切换', () => {
    const s = useLocaleStore()
    s.setLocale('en-US')
    expect(s.locale).toBe('en-US')
    expect(localStorage.getItem('ragent-locale')).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')
  })

  it('不支持的浏览器语言回落 zh-CN', () => {
    Object.defineProperty(navigator, 'language', { value: 'fr-FR', configurable: true })
    const s = useLocaleStore()
    s.initLocale()
    expect(s.locale).toBe('zh-CN')
  })
})

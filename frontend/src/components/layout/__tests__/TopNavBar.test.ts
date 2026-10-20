import { describe, expect, it, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import TopNavBar from '../TopNavBar.vue'
import { useLocaleStore } from '@/stores/locale'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', component: { template: '<div/>' } }],
})

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN, 'en-US': enUS },
})

function mountNav() {
  return mount(TopNavBar, {
    global: { plugins: [i18n, router, createPinia()] },
  })
}

describe('TopNavBar 语言切换器', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('渲染 中 / EN 两个切换按钮', () => {
    const wrapper = mountNav()
    const btns = wrapper.findAll('button').filter((b) => ['中', 'EN'].includes(b.text()))
    expect(btns.length).toBe(2)
  })

  it('点击 EN 后 locale 切换并持久化到 localStorage', async () => {
    const wrapper = mountNav()
    const enBtn = wrapper.findAll('button').filter((b) => b.text() === 'EN')[0]
    await enBtn.trigger('click')
    expect(useLocaleStore().locale).toBe('en-US')
    expect(localStorage.getItem('ragent-locale')).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')
  })

  it('点击 中 后 locale 回落中文', async () => {
    const wrapper = mountNav()
    const zhBtn = wrapper.findAll('button').filter((b) => b.text() === '中')[0]
    await zhBtn.trigger('click')
    expect(useLocaleStore().locale).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('导航标签随语言切换渲染英文', async () => {
    const wrapper = mountNav()
    i18n.global.locale.value = 'en-US'
    await wrapper.vm.$nextTick()
    const texts = wrapper.findAll('nav a span').map((s) => s.text())
    expect(texts).toContain('Smart Q&A')
    expect(texts).toContain('Knowledge Base')
    expect(texts).toContain('Decision Logs')
  })
})

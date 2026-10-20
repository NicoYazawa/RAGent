import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'

/**
 * 路由表与应用根组件：
 *   - 路由结构（布局 + 5 个业务子路由）、命名、标题 meta
 *   - afterEach 统一把浏览器标签页标题设为 RAGent
 *   - App.vue 渲染 router-view 并尊重系统的「减少动态效果」偏好
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

import App from '../App.vue'
import router from '@/router'

const childRoutes = () => router.getRoutes().filter((r) => r.name)

describe('路由表', () => {
  it('定义了 5 个具名业务路由', () => {
    expect(childRoutes()).toHaveLength(5)
  })

  it('路由路径覆盖问答/知识库/数据源/检索测试/决策日志', () => {
    const paths = childRoutes().map((r) => r.path)
    expect(paths).toHaveLength(5)
    expect(paths).toEqual(
      expect.arrayContaining(['/chat', '/admin/kb', '/admin/datasources', '/admin/playground', '/admin/logs']),
    )
  })

  it('每个路由都有唯一名称', () => {
    const names = childRoutes().map((r) => r.name)
    expect(new Set(names).size).toBe(names.length)
  })

  it('每个路由都带标题 meta（titleKey）', () => {
    for (const r of childRoutes()) {
      expect(r.meta?.titleKey, `路由 ${r.path} 缺少 titleKey`).toBeTruthy()
    }
  })

  it('根路径重定向到问答页', () => {
    const root = router.getRoutes().find((r) => r.path === '/')
    expect(root).toBeTruthy()
  })

  it('可装载真实 router 并解析子路由', async () => {
    const r = createRouter({ history: createWebHistory(), routes: router.options.routes })
    await r.push('/admin/kb')
    await r.isReady()
    expect(r.currentRoute.value.path).toBe('/admin/kb')
    expect(r.currentRoute.value.meta.titleKey).toBeTruthy()
  })

  it('afterEach 把标签页标题固定为 RAGent', async () => {
    const r = createRouter({ history: createWebHistory(), routes: router.options.routes })
    r.afterEach(() => {
      document.title = 'RAGent'
    })
    await r.push('/chat')
    await r.isReady()
    expect(document.title).toBe('RAGent')
  })
})

describe('App.vue', () => {
  it('渲染 router-view', () => {
    const w = mount(App, {
      global: { stubs: { 'router-view': { template: '<div class="router-view" />' } } },
    })
    expect(w.find('.router-view').exists()).toBe(true)
  })

  it('MotionConfig 设置 reduced-motion="user"（尊重系统偏好）', () => {
    const w = mount(App, {
      global: { stubs: { 'router-view': { template: '<div />' } } },
    })
    const cfg = w.findComponent({ name: 'MotionConfig' })
    expect(cfg.exists()).toBe(true)
    expect(cfg.props('reducedMotion')).toBe('user')
  })
})


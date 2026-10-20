import { describe, expect, it, vi } from 'vitest'

/**
 * 应用引导（main.ts）—— 挂载顺序契约：
 *   createApp → use(Pinia) → use(i18n) → initLocale() → use(Router) → mount('#app')
 */

const boot = vi.hoisted(() => {
  const order: string[] = []
  const app = {
    use: vi.fn((_plugin: unknown) => {
      order.push('use')
      return app
    }),
    mount: vi.fn((_el: unknown) => {
      order.push('mount')
      return app
    }),
  }
  return {
    order,
    app,
    createApp: vi.fn(() => {
      order.push('createApp')
      return app
    }),
    initLocale: vi.fn(() => {
      order.push('initLocale')
    }),
  }
})

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return { ...actual, createApp: boot.createApp }
})

vi.mock('@/stores/locale', () => ({
  useLocaleStore: () => ({ initLocale: boot.initLocale }),
}))

describe('main.ts 应用引导', () => {
  it('按 Pinia → i18n → 语言初始化 → Router → 挂载 的顺序启动', async () => {
    document.body.innerHTML = '<div id="app"></div>'
    await import('@/main')
    expect(boot.createApp).toHaveBeenCalled()
    expect(boot.order).toEqual(['createApp', 'use', 'use', 'initLocale', 'use', 'mount'])
    expect(boot.app.mount).toHaveBeenCalledWith('#app')
  })
})

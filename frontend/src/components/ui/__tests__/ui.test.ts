import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

/**
 * UI 基础组件 —— 交互契约（不是快照对比）：
 *   - BaseButton：variant/size/loading/disabled 决定样式与可点性
 *   - BaseInput / BaseToggle：v-model 事件契约
 *   - BasePagination：页码窗口与 change 事件，越界/同页不触发
 *   - BaseModal / BaseDrawer：遮罩/ESC/关闭按钮、body 滚动锁、焦点
 *   - ImageViewer：键盘与按钮翻页、越界保护
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

import BaseButton from '../BaseButton.vue'
import BaseDrawer from '../BaseDrawer.vue'
import BaseEmpty from '../BaseEmpty.vue'
import BaseInput from '../BaseInput.vue'
import BaseModal from '../BaseModal.vue'
import BasePagination from '../BasePagination.vue'
import BaseTag from '../BaseTag.vue'
import BaseToggle from '../BaseToggle.vue'
import ImageViewer from '../ImageViewer.vue'

/** Teleport 的内容渲染到 body，测试里挂到 body 上便于断言 */
const mountOpts = { global: { stubs: { teleport: true } } }

/** 需要真实 DOM（焦点 / window 键盘事件）的组件挂到 document.body */
const attachOpts = { global: { stubs: { teleport: true } }, attachTo: document.body }

const mounted: { unmount: () => void }[] = []

function mountAttached<T>(...args: Parameters<typeof mount<T>>): ReturnType<typeof mount<T>> {
  const w = mount<T>(...args)
  mounted.push(w)
  return w
}

beforeEach(() => {
  document.body.style.overflow = ''
})

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  document.body.innerHTML = ''
})

describe('BaseButton', () => {
  it('默认 primary + md 样式', () => {
    const w = mount(BaseButton, { slots: { default: '确定' } })
    expect(w.classes()).toContain('bg-ink')
    expect(w.classes()).toContain('h-[34px]')
    expect(w.text()).toBe('确定')
  })

  it('ghost 变体使用描边样式', () => {
    const w = mount(BaseButton, { props: { variant: 'ghost' } })
    expect(w.classes()).toContain('border')
    expect(w.classes()).not.toContain('bg-ink')
  })

  it('danger 变体使用危险色', () => {
    const w = mount(BaseButton, { props: { variant: 'danger' } })
    expect(w.classes()).toContain('text-danger')
  })

  it('soft 变体使用底色', () => {
    const w = mount(BaseButton, { props: { variant: 'soft' } })
    expect(w.classes()).toContain('bg-raise')
  })

  it('sm 尺寸使用小号高度', () => {
    const w = mount(BaseButton, { props: { size: 'sm' } })
    expect(w.classes()).toContain('h-7')
  })

  it('block 时占满宽度', () => {
    const w = mount(BaseButton, { props: { block: true } })
    expect(w.classes()).toContain('w-full')
  })

  it('loading 时展示转圈并禁用按钮', () => {
    const w = mount(BaseButton, { props: { loading: true } })
    expect(w.attributes('disabled')).toBeDefined()
    expect(w.find('span.animate-spin').exists()).toBe(true)
  })

  it('disabled 时按钮不可点', () => {
    const w = mount(BaseButton, { props: { disabled: true } })
    expect(w.attributes('disabled')).toBeDefined()
  })

  it('透传 title 属性', () => {
    const w = mount(BaseButton, { props: { title: '提示' } })
    expect(w.attributes('title')).toBe('提示')
  })
})

describe('BaseEmpty', () => {
  it('默认展示语言包里的空态文案', () => {
    const w = mount(BaseEmpty)
    expect(w.text()).toContain('暂无数据')
  })

  it('自定义文案覆盖默认', () => {
    const w = mount(BaseEmpty, { props: { text: '还没有内容' } })
    expect(w.text()).toContain('还没有内容')
  })

  it('渲染插槽内容', () => {
    const w = mount(BaseEmpty, { slots: { default: '<button>去添加</button>' } })
    expect(w.find('button').text()).toBe('去添加')
  })
})

describe('BaseInput', () => {
  it('输入时抛出 update:modelValue', async () => {
    const w = mount(BaseInput, { props: { modelValue: '' } })
    await w.find('input').setValue('你好')
    expect(w.emitted('update:modelValue')).toEqual([['你好']])
  })

  it('透传 type / placeholder / disabled', () => {
    const w = mount(BaseInput, { props: { modelValue: 'x', type: 'password', placeholder: '密码', disabled: true } })
    const input = w.find('input')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('placeholder')).toBe('密码')
    expect(input.attributes('disabled')).toBeDefined()
  })

  it('mono 时使用等宽字体', () => {
    const w = mount(BaseInput, { props: { modelValue: '', mono: true } })
    expect(w.find('input').classes()).toContain('font-mono')
  })
})

describe('BaseTag', () => {
  it('默认 accent 色调', () => {
    const w = mount(BaseTag, { slots: { default: '标签' } })
    expect(w.classes()).toContain('bg-raise')
    expect(w.text()).toBe('标签')
  })

  it('warn / danger / ok / mute 各自映射样式', () => {
    expect(mount(BaseTag, { props: { tone: 'warn' } }).classes()).toContain('text-warn')
    expect(mount(BaseTag, { props: { tone: 'danger' } }).classes()).toContain('text-danger')
    expect(mount(BaseTag, { props: { tone: 'ok' } }).classes()).toContain('text-ok')
    expect(mount(BaseTag, { props: { tone: 'mute' } }).classes()).toContain('text-ink-mute')
  })
})

describe('BaseToggle', () => {
  it('aria-checked 反映当前值', () => {
    expect(mount(BaseToggle, { props: { modelValue: true } }).attributes('aria-checked')).toBe('true')
    expect(mount(BaseToggle, { props: { modelValue: false } }).attributes('aria-checked')).toBe('false')
  })

  it('点击抛出取反后的值', async () => {
    const w = mount(BaseToggle, { props: { modelValue: false } })
    await w.trigger('click')
    expect(w.emitted('update:modelValue')).toEqual([[true]])
  })

  it('disabled 时点击不抛事件', async () => {
    const w = mount(BaseToggle, { props: { modelValue: false, disabled: true } })
    await w.trigger('click')
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })
})

describe('BasePagination', () => {
  it('总页数不足 7 时平铺所有页码', () => {
    const w = mount(BasePagination, { props: { page: 1, total: 30, pageSize: 10 } })
    const labels = w.findAll('button').map((b) => b.text()).filter((x) => x !== '')
    expect(labels).toEqual(['1', '2', '3'])
  })

  it('页数多时当前页靠前显示省略号', () => {
    const w = mount(BasePagination, { props: { page: 2, total: 200, pageSize: 10 } })
    expect(w.text()).toContain('…')
  })

  it('页数多时当前页靠后显示省略号', () => {
    const w = mount(BasePagination, { props: { page: 18, total: 200, pageSize: 10 } })
    expect(w.text()).toContain('…')
  })

  it('页数多且居中时显示当前页前后各一页', () => {
    const w = mount(BasePagination, { props: { page: 10, total: 200, pageSize: 10 } })
    const labels = w.findAll('button').map((b) => b.text())
    expect(labels).toContain('9')
    expect(labels).toContain('10')
    expect(labels).toContain('11')
  })

  it('首页时上一页按钮禁用', () => {
    const w = mount(BasePagination, { props: { page: 1, total: 200, pageSize: 10 } })
    expect(w.findAll('button')[0].attributes('disabled')).toBeDefined()
  })

  it('末页时下一页按钮禁用', () => {
    const w = mount(BasePagination, { props: { page: 20, total: 200, pageSize: 10 } })
    const buttons = w.findAll('button')
    expect(buttons[buttons.length - 1].attributes('disabled')).toBeDefined()
  })

  it('点击页码抛出 change', async () => {
    const w = mount(BasePagination, { props: { page: 1, total: 200, pageSize: 10 } })
    const target = w.findAll('button').find((b) => b.text() === '2')!
    await target.trigger('click')
    expect(w.emitted('change')).toEqual([[2]])
  })

  it('点击当前页不触发 change', async () => {
    const w = mount(BasePagination, { props: { page: 3, total: 30, pageSize: 10 } })
    const target = w.findAll('button').find((b) => b.text() === '3')!
    await target.trigger('click')
    expect(w.emitted('change')).toBeUndefined()
  })

  it('点击上一页/下一页抛出 change', async () => {
    const w = mount(BasePagination, { props: { page: 3, total: 200, pageSize: 10 } })
    const buttons = w.findAll('button')
    await buttons[0].trigger('click')
    await buttons[buttons.length - 1].trigger('click')
    expect(w.emitted('change')).toEqual([[2], [4]])
  })

  it('展示条目总数', () => {
    const w = mount(BasePagination, { props: { page: 1, total: 42, pageSize: 10 } })
    expect(w.text()).toContain('42')
  })
})

describe('BaseModal', () => {
  it('open 时渲染对话框与标题', () => {
    const w = mount(BaseModal, { props: { open: true, title: '上传文档' }, ...mountOpts })
    expect(w.find('[role="dialog"]').exists()).toBe(true)
    expect(w.text()).toContain('上传文档')
  })

  it('open=false 时不渲染内容', () => {
    const w = mount(BaseModal, { props: { open: false, title: 'x' }, ...mountOpts })
    expect(w.find('[role="dialog"]').exists()).toBe(false)
  })

  it('关闭按钮抛出 close', async () => {
    const w = mount(BaseModal, { props: { open: true, title: 'x' }, ...mountOpts })
    await w.find('button[aria-label="关闭"]').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })

  it('点击遮罩抛出 close', async () => {
    const w = mount(BaseModal, { props: { open: true, title: 'x' }, ...mountOpts })
    await w.find('.absolute.inset-0.bg-deep\\/80').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })

  it('closeOnOverlay=false 时点击遮罩不关闭', async () => {
    const w = mount(BaseModal, { props: { open: true, title: 'x', closeOnOverlay: false }, ...mountOpts })
    await w.find('.absolute.inset-0.bg-deep\\/80').trigger('click')
    expect(w.emitted('close')).toBeUndefined()
  })

  it('ESC 抛出 close', async () => {
    const w = mount(BaseModal, { props: { open: true, title: 'x' }, ...mountOpts })
    await w.find('div.fixed').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('close')).toBeTruthy()
  })

  it('打开时锁定 body 滚动，关闭时恢复', async () => {
    const w = mount(BaseModal, { props: { open: false, title: 'x' }, ...mountOpts })
    await w.setProps({ open: true })
    expect(document.body.style.overflow).toBe('hidden')
    await w.setProps({ open: false })
    expect(document.body.style.overflow).toBe('')
  })

  it('卸载时恢复 body 滚动', async () => {
    const w = mount(BaseModal, { props: { open: false, title: 'x' }, ...mountOpts })
    await w.setProps({ open: true })
    expect(document.body.style.overflow).toBe('hidden')
    w.unmount()
    expect(document.body.style.overflow).toBe('')
  })

  it('渲染 footer 插槽', () => {
    const w = mount(BaseModal, {
      props: { open: true, title: 'x' },
      slots: { footer: '<button class="ok">好</button>' },
      ...mountOpts,
    })
    expect(w.find('button.ok').exists()).toBe(true)
  })

  it('无 footer 插槽时不渲染 footer 容器', () => {
    const w = mount(BaseModal, { props: { open: true, title: 'x' }, ...mountOpts })
    expect(w.text()).not.toContain('footer')
  })

  it('打开时自动聚焦首个输入控件', async () => {
    const w = mountAttached(BaseModal, {
      props: { open: true, title: 'x' },
      slots: { default: '<input class="first" /><textarea class="second" />' },
      ...attachOpts,
    })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    const focused = document.activeElement as HTMLElement | null
    expect(focused?.className).toContain('first')
  })
})

describe('BaseDrawer', () => {
  it('open 时渲染抽屉与标题', () => {
    const w = mount(BaseDrawer, { props: { open: true, title: '引用溯源' }, ...mountOpts })
    expect(w.find('[role="dialog"]').exists()).toBe(true)
    expect(w.text()).toContain('引用溯源')
  })

  it('open=false 时不渲染抽屉', () => {
    const w = mount(BaseDrawer, { props: { open: false, title: 'x' }, ...mountOpts })
    expect(w.find('[role="dialog"]').exists()).toBe(false)
  })

  it('关闭按钮抛出 close', async () => {
    const w = mount(BaseDrawer, { props: { open: true, title: 'x' }, ...mountOpts })
    await w.find('button[aria-label="关闭"]').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })

  it('点击遮罩抛出 close', async () => {
    const w = mount(BaseDrawer, { props: { open: true, title: 'x' }, ...mountOpts })
    await w.find('.absolute.inset-0.bg-deep\\/80').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })

  it('ESC 抛出 close', async () => {
    const w = mount(BaseDrawer, { props: { open: true, title: 'x' }, ...mountOpts })
    await w.find('div.fixed').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('close')).toBeTruthy()
  })

  it('打开时锁定 body 滚动', async () => {
    const w = mount(BaseDrawer, { props: { open: false, title: 'x' }, ...mountOpts })
    await w.setProps({ open: true })
    expect(document.body.style.overflow).toBe('hidden')
    await w.setProps({ open: false })
    expect(document.body.style.overflow).toBe('')
  })

  it('卸载时恢复 body 滚动', () => {
    const w = mount(BaseDrawer, { props: { open: true, title: 'x' }, ...mountOpts })
    w.unmount()
    expect(document.body.style.overflow).toBe('')
  })
})

describe('ImageViewer', () => {
  const images = ['a.png', 'b.png', 'c.png']

  it('open 时渲染大图与序号', () => {
    const w = mount(ImageViewer, { props: { open: true, images }, ...mountOpts })
    expect(w.find('img').attributes('src')).toBe('a.png')
    expect(w.text()).toContain('1 / 3')
  })

  it('open=false 时不渲染', () => {
    const w = mount(ImageViewer, { props: { open: false, images }, ...mountOpts })
    expect(w.find('img').exists()).toBe(false)
  })

  it('单图时不显示翻页按钮与序号', () => {
    const w = mount(ImageViewer, { props: { open: true, images: ['a.png'] }, ...mountOpts })
    expect(w.find('button[aria-label="上一张"]').exists()).toBe(false)
    expect(w.text()).not.toContain('/ 1')
  })

  it('第一张不显示「上一张」按钮', () => {
    const w = mount(ImageViewer, { props: { open: true, images }, ...mountOpts })
    expect(w.find('button[aria-label="上一张"]').exists()).toBe(false)
    expect(w.find('button[aria-label="下一张"]').exists()).toBe(true)
  })

  it('点击「下一张」切换 index', async () => {
    const w = mount(ImageViewer, { props: { open: true, images, index: 0 }, ...mountOpts })
    await w.find('button[aria-label="下一张"]').trigger('click')
    expect(w.emitted('update:index')).toEqual([[1]])
  })

  it('点击「上一张」切换 index', async () => {
    const w = mount(ImageViewer, { props: { open: true, images, index: 2 }, ...mountOpts })
    await w.find('button[aria-label="上一张"]').trigger('click')
    expect(w.emitted('update:index')).toEqual([[1]])
  })

  it('ESC 抛出 close', async () => {
    const w = mountAttached(ImageViewer, { props: { open: true, images }, ...attachOpts })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await w.vm.$nextTick()
    expect(w.emitted('close')).toBeTruthy()
  })

  it('方向键翻页', async () => {
    const w = mountAttached(ImageViewer, { props: { open: true, images, index: 1 }, ...attachOpts })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await w.vm.$nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await w.vm.$nextTick()
    expect(w.emitted('update:index')).toEqual([[2], [1]])
  })

  it('关闭时忽略键盘事件', async () => {
    const w = mountAttached(ImageViewer, { props: { open: false, images, index: 1 }, ...attachOpts })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await w.vm.$nextTick()
    expect(w.emitted('update:index')).toBeUndefined()
    expect(w.emitted('close')).toBeUndefined()
  })

  it('点击遮罩抛出 close', async () => {
    const w = mount(ImageViewer, { props: { open: true, images }, ...mountOpts })
    await w.find('.fixed.inset-0.z-50').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })

  it('打开时锁定 body 滚动', async () => {
    const w = mount(ImageViewer, { props: { open: false, images }, ...mountOpts })
    await w.setProps({ open: true })
    expect(document.body.style.overflow).toBe('hidden')
    await w.setProps({ open: false })
    expect(document.body.style.overflow).toBe('')
  })
})


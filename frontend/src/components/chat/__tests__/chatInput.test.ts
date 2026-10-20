import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 聊天输入区 —— 关键契约：
 *   - Enter 发送 / Shift+Enter 换行 / 输入法组合中不误发
 *   - 流式期间显示「停止生成」，输入框禁用
 *   - 图片附件：选择/粘贴/拖拽、非图片过滤、超量与超大告警、移除、点击预览
 *   - 只有图片没有文字时用默认问句兜底
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('@/api/chat', () => ({
  listSessions: vi.fn(),
  getMessages: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  purgeLastAssistant: vi.fn(),
  ask: vi.fn(),
}))

import ChatInput from '../ChatInput.vue'
import ImageViewer from '@/components/ui/ImageViewer.vue'
import { useChatStore } from '@/stores/chat'

const imgFile = (name = 'a.png', size = 1024) => new File([new Uint8Array(size)], name, { type: 'image/png' })

/** 通过隐藏 file input 附加图片，并等待 FileReader 异步读取完成 */
async function attach(w: ReturnType<typeof mount>, files: File[], expected: number): Promise<void> {
  const input = w.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: files })
  await input.trigger('change')
  await vi.waitFor(() => {
    expect(w.findAll('img[src^="data:"]')).toHaveLength(expected)
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('ChatInput', () => {
  it('空输入时发送按钮禁用', () => {
    const w = mount(ChatInput)
    expect(w.find('button[aria-label="发送"]').attributes('disabled')).toBeDefined()
  })

  it('输入文本后发送按钮可用', async () => {
    const w = mount(ChatInput)
    await w.find('textarea').setValue('你好')
    expect(w.find('button[aria-label="发送"]').attributes('disabled')).toBeUndefined()
  })

  it('Enter 发送并清空输入框', async () => {
    const store = useChatStore()
    const send = vi.spyOn(store, 'send').mockResolvedValue(undefined)
    const w = mount(ChatInput)
    await w.find('textarea').setValue('年假几天')
    await w.find('textarea').trigger('keydown', { key: 'Enter' })
    expect(send).toHaveBeenCalledWith('年假几天', undefined)
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('Shift+Enter 不发送', async () => {
    const store = useChatStore()
    const send = vi.spyOn(store, 'send').mockResolvedValue(undefined)
    const w = mount(ChatInput)
    await w.find('textarea').setValue('换行')
    await w.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(send).not.toHaveBeenCalled()
  })

  it('输入法组合中的 Enter 不发送', async () => {
    const store = useChatStore()
    const send = vi.spyOn(store, 'send').mockResolvedValue(undefined)
    const w = mount(ChatInput)
    await w.find('textarea').setValue('拼音')
    await w.find('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    expect(send).not.toHaveBeenCalled()
  })

  it('流式期间显示停止按钮并禁用输入框', async () => {
    const store = useChatStore()
    store.streaming = true
    const w = mount(ChatInput)
    expect(w.text()).toContain('停止生成')
    expect(w.find('textarea').attributes('disabled')).toBeDefined()
    expect(w.find('button[aria-label="发送"]').exists()).toBe(false)
  })

  it('流式期间点击停止按钮中断流', async () => {
    const store = useChatStore()
    store.streaming = true
    const stop = vi.spyOn(store, 'stopStream')
    const w = mount(ChatInput)
    await w.findAll('button').find((b) => b.text().includes('停止生成'))!.trigger('click')
    expect(stop).toHaveBeenCalled()
  })

  it('点击示例问题填入草稿', async () => {
    const w = mount(ChatInput)
    const sample = w.findAll('button').find((b) => b.text().includes('考勤制度'))!
    await sample.trigger('click')
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toContain('迟到')
  })

  it('选择图片文件后展示缩略图', async () => {
    const w = mount(ChatInput)
    await attach(w, [imgFile()], 1)
    expect(w.findAll('img[src^="data:image/png"]')).toHaveLength(1)
  })

  it('非图片文件被忽略', async () => {
    const w = mount(ChatInput)
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.txt', { type: 'text/plain' })] })
    await input.trigger('change')
    await new Promise((r) => setTimeout(r, 0))
    expect(w.findAll('img[src^="data:"]')).toHaveLength(0)
  })

  it('粘贴图片也能加入附件', async () => {
    const w = mount(ChatInput)
    await w.find('textarea').trigger('paste', { clipboardData: { files: [imgFile('p.png')] } })
    await vi.waitFor(() => {
      expect(w.findAll('img[src^="data:image/png"]')).toHaveLength(1)
    })
  })

  it('拖拽图片也能加入附件', async () => {
    const w = mount(ChatInput)
    // drop 监听挂在输入框的外层容器上
    const zone = w.find('textarea').element.parentElement as HTMLElement
    const ev = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(ev, 'dataTransfer', { value: { files: [imgFile('d.png')] } })
    zone.dispatchEvent(ev)
    await vi.waitFor(() => {
      expect(w.findAll('img[src^="data:image/png"]')).toHaveLength(1)
    })
  })

  it('超出数量上限时提示并只保留上限数量', async () => {
    const w = mount(ChatInput)
    await attach(w, [1, 2, 3, 4, 5].map((i) => imgFile(`f${i}.png`)), 4)
    await vi.waitFor(() => {
      expect(w.text()).toContain('最多附带 4 张图片')
    })
  })

  it('超大文件被拒绝并提示', async () => {
    const w = mount(ChatInput)
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [imgFile('big.png', 10 * 1024 * 1024 + 1)] })
    await input.trigger('change')
    await vi.waitFor(() => {
      expect(w.text()).toContain('单张图片不能超过 10MB')
    })
    expect(w.findAll('img[src^="data:image/png"]')).toHaveLength(0)
  })

  it('移除图片后缩略图数量减少', async () => {
    const w = mount(ChatInput)
    await attach(w, [imgFile()], 1)
    await w.find('button[aria-label="移除图片1"]').trigger('click')
    expect(w.findAll('img[src^="data:image/png"]')).toHaveLength(0)
  })

  it('点击缩略图打开预览', async () => {
    const w = mount(ChatInput, { global: { stubs: { teleport: true } } })
    await attach(w, [imgFile()], 1)
    await w.find('img[src^="data:image/png"]').trigger('click')
    expect(w.findComponent(ImageViewer).props('open')).toBe(true)
  })

  it('只有图片没有文字时用默认问句发送', async () => {
    const store = useChatStore()
    const send = vi.spyOn(store, 'send').mockResolvedValue(undefined)
    const w = mount(ChatInput)
    await attach(w, [imgFile()], 1)
    await w.find('button[aria-label="发送"]').trigger('click')
    expect(send).toHaveBeenCalledWith('请分析这张图片', expect.any(Array))
  })

  it('多张图片无文字时用复数默认问句', async () => {
    const store = useChatStore()
    const send = vi.spyOn(store, 'send').mockResolvedValue(undefined)
    const w = mount(ChatInput)
    await attach(w, [imgFile('a.png'), imgFile('b.png')], 2)
    await w.find('button[aria-label="发送"]').trigger('click')
    expect(send).toHaveBeenCalledWith('请分析这 2 张图片', expect.any(Array))
  })

  it('流式期间不发送', async () => {
    const store = useChatStore()
    store.streaming = true
    const send = vi.spyOn(store, 'send').mockResolvedValue(undefined)
    const w = mount(ChatInput)
    await w.find('textarea').setValue('x')
    await w.find('textarea').trigger('keydown', { key: 'Enter' })
    expect(send).not.toHaveBeenCalled()
  })
})


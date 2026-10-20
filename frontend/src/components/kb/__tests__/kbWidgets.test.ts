import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { KbDocument } from '@/api/types'

/**
 * 知识库侧抽屉与上传弹窗：
 *   - ChunkDrawer：打开即拉切片、分页、展开/收起正文、错误态
 *   - UploadModal：拖拽/选择文件、待上传列表与移除、上传结果反馈
 */

vi.mock('vue-i18n', async (importOriginal) => {
  const { createI18nMock } = await import('@/test/i18nMock')
  return createI18nMock(importOriginal)
})

vi.mock('@/api/admin', () => ({
  listDocumentChunks: vi.fn(),
  uploadDocument: vi.fn(),
  listKbs: vi.fn(),
  listDocuments: vi.fn(),
  createKb: vi.fn(),
  deleteDocument: vi.fn(),
  retryDocument: vi.fn(),
  getDatasources: vi.fn(),
  updateDatasources: vi.fn(),
}))

import ChunkDrawer from '../ChunkDrawer.vue'
import UploadModal from '../UploadModal.vue'
import { listDocumentChunks, uploadDocument, listKbs, listDocuments } from '@/api/admin'
import { useKbStore } from '@/stores/kb'

const mockListChunks = listDocumentChunks as unknown as ReturnType<typeof vi.fn>
const mockUpload = uploadDocument as unknown as ReturnType<typeof vi.fn>
const mockListKbs = listKbs as unknown as ReturnType<typeof vi.fn>
const mockListDocs = listDocuments as unknown as ReturnType<typeof vi.fn>

const doc: KbDocument = {
  id: 7,
  kb_id: 1,
  file_name: '考勤制度.md',
  file_type: 'md',
  status: 'ready',
  chunk_count: 12,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const chunk = (no: number, id = no) => ({
  id,
  doc_id: 7,
  chunk_no: no,
  section_path: `第${no}节`,
  content: `切片 ${no} 的正文内容`,
  token_count: 10 * no,
})

const mountOpts = { global: { stubs: { teleport: true } } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockListChunks.mockResolvedValue({ items: [chunk(1), chunk(2)], total: 2, page: 1, page_size: 8 })
  mockUpload.mockResolvedValue({ id: 1, kb_id: 1, file_name: 'a.md', file_type: 'md', status: 'parsing', chunk_count: 0, created_at: '', updated_at: '' })
  mockListKbs.mockResolvedValue([])
  mockListDocs.mockResolvedValue([])
})

describe('ChunkDrawer', () => {
  it('打开时按 kb/doc 拉取切片', async () => {
    mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    expect(mockListChunks).toHaveBeenCalledWith(1, 7, 1, 8)
  })

  it('加载完成后展示切片列表', async () => {
    const w = mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('切片 1 的正文内容')
    expect(w.text()).toContain('第1节')
    expect(w.text()).toContain('10 tok')
  })

  it('未打开时不拉取数据', () => {
    mount(ChunkDrawer, { props: { open: false, doc }, ...mountOpts })
    expect(mockListChunks).not.toHaveBeenCalled()
  })

  it('加载中展示骨架', () => {
    mockListChunks.mockReturnValue(new Promise(() => undefined))
    const w = mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    expect(w.findAll('.animate-pulse')).toHaveLength(5)
  })

  it('查询失败展示错误信息', async () => {
    mockListChunks.mockRejectedValue(new Error('文档已删除'))
    const w = mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.text()).toContain('文档已删除')
  })

  it('点击展开按钮切换正文展开状态', async () => {
    const w = mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    const btn = w.find('button[title="展开全文"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(w.find('button[title="收起"]').exists()).toBe(true)
  })

  it('总切片数超过一页时展示分页', async () => {
    mockListChunks.mockResolvedValue({ items: [chunk(1)], total: 40, page: 1, page_size: 8 })
    const w = mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.findComponent({ name: 'BasePagination' }).exists()).toBe(true)
  })

  it('切换页码后按新页码重新拉取', async () => {
    mockListChunks.mockResolvedValue({ items: [chunk(1)], total: 40, page: 1, page_size: 8 })
    const w = mount(ChunkDrawer, { props: { open: true, doc }, ...mountOpts })
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    const page2 = w.findAll('button').find((b) => b.text() === '2')!
    await page2.trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    expect(mockListChunks).toHaveBeenLastCalledWith(1, 7, 2, 8)
  })
})

describe('UploadModal', () => {
  it('展示目标知识库名', () => {
    const store = useKbStore()
    store.kbs = [{ id: 1, name: '制度库', description: '', doc_count: 0, chunk_count: 0, created_at: '', updated_at: '' }]
    store.selectedKbId = 1
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    expect(w.text()).toContain('制度库')
  })

  it('未选择知识库时展示「未选择」', () => {
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    expect(w.text()).toContain('未选择')
  })

  it('选择文件后进入待上传列表', async () => {
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.md', { type: 'text/markdown' })] })
    await input.trigger('change')
    await w.vm.$nextTick()
    expect(w.text()).toContain('a.md')
  })

  it('拖拽文件也进入待上传列表', async () => {
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const zone = w.find('input[type="file"]').element.parentElement as HTMLElement
    const ev = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(ev, 'dataTransfer', { value: { files: [new File(['x'], 'b.md', { type: 'text/markdown' })] } })
    zone.dispatchEvent(ev)
    await w.vm.$nextTick()
    expect(w.text()).toContain('b.md')
  })

  it('可以移除待上传文件', async () => {
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.md', { type: 'text/markdown' })] })
    await input.trigger('change')
    await w.vm.$nextTick()
    await w.find('button[aria-label="移除"]').trigger('click')
    expect(w.text()).not.toContain('a.md')
  })

  it('未选文件时上传按钮禁用', () => {
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const uploadBtn = w.findAll('button').find((b) => b.text().includes('上传'))!
    expect(uploadBtn.attributes('disabled')).toBeDefined()
  })

  it('上传成功后展示受理结果', async () => {
    const store = useKbStore()
    store.selectedKbId = 1
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.md', { type: 'text/markdown' })] })
    await input.trigger('change')
    await w.vm.$nextTick()
    const uploadBtn = w.findAll('button').find((b) => b.text().includes('上传'))!
    await uploadBtn.trigger('click')
    await vi.waitFor(() => {
      expect(w.text()).toContain('已受理 1 个文件')
    })
    expect(mockUpload).toHaveBeenCalledWith(1, expect.any(File))
  })

  it('上传失败时展示错误条目', async () => {
    mockUpload.mockRejectedValue(new Error('文件格式不支持'))
    const store = useKbStore()
    store.selectedKbId = 1
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.md', { type: 'text/markdown' })] })
    await input.trigger('change')
    await w.vm.$nextTick()
    const uploadBtn = w.findAll('button').find((b) => b.text().includes('上传'))!
    await uploadBtn.trigger('click')
    await vi.waitFor(() => {
      expect(w.text()).toContain('文件格式不支持')
    })
  })

  it('关闭按钮清空待上传列表并关闭', async () => {
    const w = mount(UploadModal, { props: { open: true }, ...mountOpts })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.md', { type: 'text/markdown' })] })
    await input.trigger('change')
    await w.vm.$nextTick()
    await w.findAll('button').find((b) => b.text() === '关闭')!.trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })
})


import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import i18n from '@/i18n'
import UploadModal from '../UploadModal.vue'
import { useKbStore } from '@/stores/kb'
import * as adminApi from '@/api/admin'

// Keep vue-i18n real: mocking useI18n hides calls outside component setup.
vi.mock('@/api/admin', () => ({
  listKbs: vi.fn(),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  i18n.global.locale.value = 'zh-CN'
  vi.mocked(adminApi.listKbs).mockResolvedValue([])
  vi.mocked(adminApi.listDocuments).mockResolvedValue([])
  vi.mocked(adminApi.uploadDocument).mockResolvedValue({
    id: 1, kb_id: 7, file_name: 'manual.md', file_type: 'md',
    status: 'parsing', chunk_count: 0, created_at: '', updated_at: '',
  })
})

afterEach(() => {
  i18n.global.locale.value = 'zh-CN'
})

describe('document upload with real internationalization', () => {
  it('sends the selected file and displays acceptance after clicking Upload', async () => {
    const pinia = createPinia()
    const errors: unknown[] = []
    const wrapper = mount(UploadModal, {
      props: { open: true },
      global: { plugins: [pinia, i18n], stubs: { teleport: true }, config: { errorHandler: (error) => errors.push(error) } },
    })
    useKbStore(pinia).selectedKbId = 7
    const file = new File(['# Manual'], 'manual.md', { type: 'text/markdown' })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    const uploadButton = wrapper.findAll('button').find((button) => button.text().includes('上传文档'))!
    expect(uploadButton.attributes('disabled')).toBeUndefined()
    await uploadButton.trigger('click')
    await flushPromises()
    expect(errors).toEqual([])
    expect(adminApi.uploadDocument).toHaveBeenCalledWith(7, file)
    expect(wrapper.text()).toContain('已受理 1 个文件')
    wrapper.unmount()
  })

  it('returns a localized missing-knowledge-base error outside component setup', async () => {
    const store = useKbStore(createPinia())
    i18n.global.locale.value = 'en-US'
    await expect(store.upload([new File(['text'], 'manual.md')])).resolves.toEqual({
      ok: 0, errors: [i18n.global.t('kb.noSelection')],
    })
    expect(adminApi.uploadDocument).not.toHaveBeenCalled()
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDatasourceStore } from '../datasource'
import { useDecisionLogStore } from '../decisionLog'
import { useThemeStore } from '../theme'

vi.mock('@/api/admin', () => ({
  getDatasources: vi.fn(),
  updateDatasources: vi.fn(),
  queryDecisionLogs: vi.fn(),
  getDecisionLog: vi.fn(),
}))

import * as adminApi from '@/api/admin'

const mockAdmin = adminApi as unknown as Record<string, ReturnType<typeof vi.fn>>

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.documentElement.classList.remove('light')
  vi.clearAllMocks()
})

describe('datasource store', () => {
  it('load 拉取数据源并复位 loading', async () => {
    mockAdmin.getDatasources.mockResolvedValue([{ source_type: 'vector', enabled: true }])
    const s = useDatasourceStore()
    await s.load()
    expect(s.items).toHaveLength(1)
    expect(s.loading).toBe(false)
  })

  it('load 失败时 loading 仍被复位（不卡死）', async () => {
    mockAdmin.getDatasources.mockRejectedValue(new Error('boom'))
    const s = useDatasourceStore()
    await expect(s.load()).rejects.toThrow('boom')
    expect(s.loading).toBe(false)
  })

  it('save 提交当前 items 并记录保存时间', async () => {
    mockAdmin.updateDatasources.mockResolvedValue({ updated: 2 })
    const s = useDatasourceStore()
    s.items = [{ source_type: 'vector', enabled: false }] as any
    await s.save()
    expect(mockAdmin.updateDatasources).toHaveBeenCalledWith(s.items)
    expect(s.savedAt).toBeTruthy()
    expect(s.saving).toBe(false)
  })

  it('save 失败时 saving 被复位', async () => {
    mockAdmin.updateDatasources.mockRejectedValue(new Error('bad'))
    const s = useDatasourceStore()
    await expect(s.save()).rejects.toThrow('bad')
    expect(s.saving).toBe(false)
    expect(s.savedAt).toBeNull()
  })
})

describe('decisionLog store', () => {
  it('query 填充日志与总数并记录页码', async () => {
    mockAdmin.queryDecisionLogs.mockResolvedValue({ items: [{ id: 1 }], total: 42, page: 2, page_size: 8 })
    const s = useDecisionLogStore()
    await s.query(2)
    expect(s.logs).toHaveLength(1)
    expect(s.total).toBe(42)
    expect(s.page).toBe(2)
    expect(s.loading).toBe(false)
  })

  it('空白会话 ID 不下发过滤参数', async () => {
    mockAdmin.queryDecisionLogs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 })
    const s = useDecisionLogStore()
    s.filterSessionId = '   '
    await s.query()
    const arg = mockAdmin.queryDecisionLogs.mock.calls[0][0]
    expect(arg.session_id).toBeUndefined()
  })

  it('非空会话 ID 转成数字下发', async () => {
    mockAdmin.queryDecisionLogs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 })
    const s = useDecisionLogStore()
    s.filterSessionId = ' 42 '
    await s.query()
    const arg = mockAdmin.queryDecisionLogs.mock.calls[0][0]
    expect(arg.session_id).toBe(42)
  })

  it('时间区间为空时不下发', async () => {
    mockAdmin.queryDecisionLogs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 })
    const s = useDecisionLogStore()
    await s.query()
    const arg = mockAdmin.queryDecisionLogs.mock.calls[0][0]
    expect(arg.start).toBeUndefined()
    expect(arg.end).toBeUndefined()
  })

  it('query 失败时 loading 被复位', async () => {
    mockAdmin.queryDecisionLogs.mockRejectedValue(new Error('boom'))
    const s = useDecisionLogStore()
    await expect(s.query()).rejects.toThrow('boom')
    expect(s.loading).toBe(false)
  })

  it('getDetail 透传后端详情', async () => {
    mockAdmin.getDecisionLog.mockResolvedValue({ id: 7 })
    const s = useDecisionLogStore()
    expect(await s.getDetail(7)).toEqual({ id: 7 })
    expect(mockAdmin.getDecisionLog).toHaveBeenCalledWith(7)
  })
})

describe('theme store', () => {
  it('默认 dark 并写入 localStorage', () => {
    const s = useThemeStore()
    expect(s.mode).toBe('dark')
    expect(localStorage.getItem('ragent-theme')).toBe('dark')
  })

  it('localStorage 里的 light 会被恢复', () => {
    localStorage.setItem('ragent-theme', 'light')
    const s = useThemeStore()
    expect(s.mode).toBe('light')
  })

  it('html 上已有 light class 时优先于存储', () => {
    localStorage.setItem('ragent-theme', 'dark')
    document.documentElement.classList.add('light')
    const s = useThemeStore()
    expect(s.mode).toBe('light')
  })

  it('toggle 在 dark/light 之间切换并同步 class', () => {
    const s = useThemeStore()
    s.toggle()
    expect(s.mode).toBe('light')
    expect(document.documentElement.classList.contains('light')).toBe(true)
    s.toggle()
    expect(s.mode).toBe('dark')
    expect(document.documentElement.classList.contains('light')).toBe(false)
  })
})

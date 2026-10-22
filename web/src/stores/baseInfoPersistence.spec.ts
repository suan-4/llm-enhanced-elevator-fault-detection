import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportStore } from './report'
import * as api from '@/api/reports'

vi.mock('@/api/reports', () => ({
  getReport: vi.fn(), saveReport: vi.fn(), generateReport: vi.fn(),
  createReport: vi.fn(), listReports: vi.fn(),
}))
vi.mock('@/api/report', () => ({ fetchJteItems: vi.fn(async () => ({ items: [] })) }))

describe('base information durable state', () => {
  let storage: Map<string, string>
  let savedForm: Record<string, string>

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    storage = new Map()
    savedForm = {}
    vi.stubGlobal('window', { setTimeout, clearTimeout, localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) },
      removeItem: (key: string) => { storage.delete(key) },
    } })
    vi.mocked(api.createReport).mockResolvedValue({ report: { id: '123', version: 1, status: 'draft' } } as never)
    vi.mocked(api.listReports).mockResolvedValue({ items: [], total: 0 } as never)
    vi.mocked(api.saveReport).mockImplementation(async (_id, value) => {
      savedForm = { ...value.form }
      return { version: 2, status: 'draft', saved_at: '2026-10-22T12:00:00' } as never
    })
  })

  it('persists copied base information before new assessment creation completes', async () => {
    const store = useReportStore()
    store.form.clientName = '已保存的委托单位'
    store.saveBaseInfoProfile('常用抬头')
    await store.createNew()
    expect(savedForm.clientName).toBe('已保存的委托单位')
    expect(store.version).toBe(2)
  })

  it('persists copied base information on first entry with no existing draft', async () => {
    const store = useReportStore()
    store.form.clientName = '首次带入的委托单位'
    store.saveBaseInfoProfile('常用抬头')
    await store.ensureDraft()
    expect(savedForm.clientName).toBe('首次带入的委托单位')
  })

  it('retries a failed initial save without creating another draft or losing copied input', async () => {
    const store = useReportStore()
    store.form.clientName = '等待重试的委托单位'
    store.saveBaseInfoProfile('重试方案')
    vi.mocked(api.saveReport).mockRejectedValueOnce(new Error('temporary save failure'))
    await expect(store.ensureDraft()).rejects.toThrow('temporary save failure')
    expect(store.ready).toBe(false)
    await store.ensureDraft()
    expect(store.ready).toBe(true)
    expect(store.draftError).toBe('')
    expect(savedForm.clientName).toBe('等待重试的委托单位')
    expect(api.createReport).toHaveBeenCalledTimes(1)
  })

  it('does not report a saved profile or change the list when storage is full', () => {
    const store = useReportStore()
    store.ensureBaseInfoLoaded()
    window.localStorage.setItem = () => { throw new Error('quota exceeded') }
    expect(store.saveBaseInfoProfile('无法保存')).toBeNull()
    expect(store.baseInfoProfiles).toEqual([])
  })

  it('restores the stored profile list when updating last-used selection fails', () => {
    const store = useReportStore()
    const first = store.saveBaseInfoProfile('第一套')
    const before = new Map(storage)
    window.localStorage.setItem = (key, value) => {
      if (key.endsWith('.last')) throw new Error('storage denied')
      storage.set(key, value)
    }
    expect(store.saveBaseInfoProfile('第二套')).toBeNull()
    expect(store.baseInfoProfiles.map(p => p.id)).toEqual([first?.id])
    expect(storage).toEqual(before)
  })
})

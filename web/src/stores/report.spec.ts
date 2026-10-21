import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportStore } from './report'
import * as api from '@/api/reports'

vi.mock('@/api/reports', () => ({ getReport: vi.fn(), saveReport: vi.fn(), generateReport: vi.fn(), createReport: vi.fn() }))
vi.mock('@/api/report', () => ({ fetchJteItems: vi.fn(async () => ({ items: [] })) }))

const report = (status: string, resultCurrent = true) => ({
  id: '123', status, version: 1, form: { clientName: '原委托单位' }, items: [],
  report_no: status === 'draft' ? null : 'OLD-001', score: null, grade: null,
  narrative: '历史结果', risks: {}, generated_at: '2026-10-16T12:00:00',
  provenance: { result_current: resultCurrent, assessment_issues: ['综合计分待确认'] },
})

describe('saved report preview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.stubGlobal('window', { clearTimeout, setTimeout })
  })

  it('viewing a historical report does not save or regenerate it', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('generated') } as never)
    const store = useReportStore()
    await store.openReport('123')
    await store.ensurePreview()
    expect(store.generated?.narrative).toBe('历史结果')
    expect(store.generated?.llm_used).toBeNull()
    expect(store.generated?.loaded_from_history).toBe(true)
    expect(api.saveReport).not.toHaveBeenCalled()
    expect(api.generateReport).not.toHaveBeenCalled()
  })

  it('keeps new generation model status and controlled reason codes', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft', false) } as never)
    vi.mocked(api.saveReport).mockResolvedValue({ saved_at: 'now', version: 1, status: 'draft' } as never)
    vi.mocked(api.generateReport).mockResolvedValue({ report: {
      ...report('generated'), provenance: { llm_used: false, llm_status: 'degraded', llm_error_code: 'context_budget_exceeded' },
    } } as never)
    const store = useReportStore()
    await store.openReport('123')
    await store.generate()
    expect(store.generated?.loaded_from_history).toBe(false)
    expect(store.generated?.llm_status).toBe('degraded')
    expect(store.generated?.llm_error_code).toBe('context_budget_exceeded')
  })

  it('restores an unchanged pending preview, but not a stale result', async () => {
    const store = useReportStore()
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft') } as never)
    await store.openReport('123')
    expect(store.generated?.assessment_issues).toEqual(['综合计分待确认'])
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft', false) } as never)
    await store.openReport('123')
    expect(store.generated).toBeNull()
  })

  it('does not mix newer input with an older generation response', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft', false) } as never)
    vi.mocked(api.saveReport).mockResolvedValue({ saved_at: 'now', version: 1, status: 'draft' } as never)
    let finish!: (value: never) => void
    vi.mocked(api.generateReport).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const store = useReportStore()
    await store.openReport('123')
    const pending = store.generate()
    await vi.waitFor(() => expect(api.generateReport).toHaveBeenCalled())
    store.form.clientName = '请求期间修改的新输入'
    finish({ report: report('draft') } as never)
    await expect(pending).rejects.toThrow('输入已修改')
    expect(store.generated).toBeNull()
    expect(store.form.clientName).toBe('请求期间修改的新输入')
  })

  it('keeps the current input when saving before switching fails, including a retry', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft', false) } as never)
    vi.mocked(api.saveReport).mockRejectedValue(new Error('保存失败'))
    const store = useReportStore()
    await store.openReport('123')
    store.form.clientName = '尚未保存'
    store.scheduleSave(60_000)
    await expect(store.openReport('456')).rejects.toThrow('保存失败')
    await expect(store.openReport('456')).rejects.toThrow('保存失败')
    expect(store.reportId).toBe('123')
    expect(store.form.clientName).toBe('尚未保存')
    expect(api.getReport).toHaveBeenCalledTimes(1)
  })

  it('waits for an in-flight autosave before creating a new assessment', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft', false) } as never)
    vi.mocked(api.createReport).mockResolvedValue({ report: { ...report('draft', false), id: '456' } } as never)
    let finish!: (value: never) => void
    vi.mocked(api.saveReport).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const store = useReportStore()
    await store.openReport('123')
    const saving = store.save()
    const creating = store.createNew()
    await Promise.resolve()
    await Promise.resolve()
    expect(api.createReport).not.toHaveBeenCalled()
    finish({ saved_at: 'now', version: 2, status: 'draft' } as never)
    await saving
    await creating
    expect(store.reportId).toBe('456')
    expect(store.version).toBe(1)
  })

  it('serializes overlapping saves and sends the latest version with a stable input snapshot', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('draft', false) } as never)
    let finish!: (value: never) => void
    vi.mocked(api.saveReport)
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ saved_at: 'later', version: 3, status: 'draft' } as never)
    const store = useReportStore()
    await store.openReport('123')
    store.form.clientName = '第一次输入'
    const first = store.save()
    await vi.waitFor(() => expect(api.saveReport).toHaveBeenCalledTimes(1))
    store.form.clientName = '第二次输入'
    const second = store.save()
    await Promise.resolve()
    expect(api.saveReport).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.saveReport).mock.calls[0][1].form.clientName).toBe('第一次输入')
    finish({ saved_at: 'now', version: 2, status: 'draft' } as never)
    await Promise.all([first, second])
    expect(vi.mocked(api.saveReport).mock.calls[1][1]).toMatchObject({
      version: 2, form: { clientName: '第二次输入' },
    })
    expect(store.version).toBe(3)
  })
})

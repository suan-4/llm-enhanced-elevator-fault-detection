import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportStore } from './report'
import * as api from '@/api/reports'

vi.mock('@/api/reports', () => ({ getReport: vi.fn(), saveReport: vi.fn(), generateReport: vi.fn() }))
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
})

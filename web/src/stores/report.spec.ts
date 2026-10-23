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
    vi.mocked(api.saveReport)
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValue({ saved_at: 'new', version: 2, status: 'draft' } as never)
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
    expect(store.version).toBe(2)
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

describe('旧草稿抬头兼容', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.stubGlobal('window', { clearTimeout, setTimeout })
  })

  it('floorsStopsDoors 字符串拆成层/站/门三个数字', async () => {
    vi.mocked(api.getReport).mockResolvedValue({
      report: {
        ...report('draft', false),
        form: { clientName: '原委托单位', floorsStopsDoors: '10 层　12 站　12 门' },
      },
    } as never)
    const store = useReportStore()
    await store.openReport('123')
    expect(store.form.floors).toBe('10')
    expect(store.form.stops).toBe('12')
    expect(store.form.doors).toBe('12')
    expect('floorsStopsDoors' in store.form).toBe(false)
  })

  it('旧草稿缺失站数时不会把门数移到站数', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: {
      ...report('draft', false), form: { floorsStopsDoors: '10 层　/ 站　12 门' },
    } } as never)
    const store = useReportStore()
    await store.openReport('123')
    expect([store.form.floors, store.form.stops, store.form.doors]).toEqual(['10', '', '12'])
  })

  it('只提交有效分支，草稿仍保留停用输入及旧报告漏填状态', () => {
    const store = useReportStore()
    store.items = [{ no: '1.1', name: '项目', sub: '', req: [], opts: [] }]
    store.hydrate({form: {}, items: [], version: 1, status: 'draft'})
    expect(store.stateOf('1.1').result).toBe('')
    Object.assign(store.stateOf('1.1'), {
      result: '符合', reasons: ['先前风险'], other: true, otherText: '先前描述',
    })
    const saved = store.serializeItems()[0]
    expect(saved.reasons).toEqual([])
    expect(saved.other_text).toBe('')
    store.hydrate({ form: {}, items: [saved], version: 2, status: 'draft' })
    expect(store.stateOf('1.1')).toMatchObject({
      result: '符合', reasons: ['先前风险'], other: true, otherText: '先前描述',
    })
  })

  it('额定载重/额定速度从旧字符串提取数字，单位不进入值', async () => {
    vi.mocked(api.getReport).mockResolvedValue({
      report: {
        ...report('draft', false),
        form: { clientName: '原委托单位', ratedLoad: '1000 kg', ratedSpeed: '/ m/s' },
      },
    } as never)
    const store = useReportStore()
    await store.openReport('123')
    expect(store.form.ratedLoad).toBe('1000')
    expect(store.form.ratedSpeed).toBe('')
  })
})

describe('报告查看页往返（暂存录入现场）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.stubGlobal('window', { clearTimeout, setTimeout })
  })

  it('查看归档报告后返回，恢复原草稿与预览状态', async () => {
    vi.mocked(api.getReport)
      .mockResolvedValueOnce({ report: report('draft') } as never)
      .mockResolvedValueOnce({ report: { ...report('filed'), id: '999', report_no: 'OLD-999' } } as never)
    const store = useReportStore()
    await store.openReport('123')
    store.form.clientName = '正在填写的草稿'
    store.stashSession()
    await store.openReport('999')
    expect(store.reportId).toBe('999')
    expect(store.status).toBe('filed')
    expect(store.restoreStashedSession()).toBe(true)
    expect(store.reportId).toBe('123')
    expect(store.status).toBe('draft')
    expect(store.form.clientName).toBe('正在填写的草稿')
    expect(store.generated?.narrative).toBe('历史结果')
    expect(api.saveReport).not.toHaveBeenCalled()
  })

  it('直接打开查看页（没有现场）时清空当前报告，回评估页重新准备', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ report: report('filed') } as never)
    const store = useReportStore()
    store.stashSession()
    await store.openReport('123')
    expect(store.restoreStashedSession()).toBe(false)
    store.clearSession()
    expect(store.reportId).toBe('')
    expect(store.status).toBe('draft')
    expect(store.generated).toBeNull()
    expect(store.form.clientName).toBe('')
  })
})

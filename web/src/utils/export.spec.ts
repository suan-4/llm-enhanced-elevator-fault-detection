import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useExport } from './export'
import { useReportStore } from '@/stores/report'
import * as api from '@/api/report'
import * as flow from '@/api/reports'
import { ApiError } from './http'

vi.mock('@/api/report', () => ({ exportReport: vi.fn(), fetchJteItems: vi.fn(async () => ({ items: [] })) }))
vi.mock('@/api/reports', () => ({ getReport: vi.fn(), saveReport: vi.fn() }))
vi.mock('./performance', () => ({
  beginInteraction: () => ({ measure: async (_: string, fn: () => unknown) => fn(), finish: vi.fn() }),
  afterPaint: async () => undefined,
}))
vi.mock('./toast', () => ({ useToast: () => ({ show: vi.fn() }) }))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.stubGlobal('window', { clearTimeout, setTimeout })
})

it('exports a server snapshot, archives only that report and can export again', async () => {
  vi.mocked(flow.getReport).mockResolvedValue({ report: {
    id: '123', status: 'generated', version: 2, form: {}, items: [],
    report_no: 'TEST-001', risks: {}, generated_at: 'now',
    provenance: { result_current: true, result_digest: 'a'.repeat(64) },
  } } as never)
  vi.mocked(api.exportReport).mockResolvedValue({
    success: true, report_id: '123', status: 'filed', filename: 'test.docx',
    path: '/exports/test.docx', size: 100, fmt: 'docx',
  } as never)
  const store = useReportStore()
  await store.openReport('123')
  const exp = useExport()
  await exp.run('docx')
  expect(api.exportReport).toHaveBeenCalledWith(expect.objectContaining({
    fmt: 'docx', report_id: '123', version: 2, result_digest: 'a'.repeat(64),
  }))
  expect(vi.mocked(api.exportReport).mock.calls[0][0]).not.toHaveProperty('body_html')
  expect(store.status).toBe('filed')
  await store.save()
  expect(flow.saveReport).not.toHaveBeenCalled()
  await exp.run('pdf')
  expect(api.exportReport).toHaveBeenCalledTimes(2)
})

it('does not call export without a current generated snapshot', async () => {
  const exp = useExport()
  await exp.run('pdf')
  expect(api.exportReport).not.toHaveBeenCalled()
})

it('reconciles a lost success response before allowing edits or new work', async () => {
  const report = {
    id: '123', status: 'generated', version: 2, form: {}, items: [],
    report_no: 'TEST-001', risks: {}, generated_at: 'now',
    provenance: { result_current: true, result_digest: 'a'.repeat(64) },
  }
  vi.mocked(flow.getReport)
    .mockResolvedValueOnce({ report } as never)
    .mockResolvedValueOnce({ report: { ...report, status: 'filed', files: [{
      fmt: 'docx', version: 2, result_digest: 'a'.repeat(64),
      filename: 'saved.docx', path: '/exports/saved.docx', size: 123,
    }] } } as never)
  vi.mocked(api.exportReport).mockRejectedValue(new Error('网络超时'))
  const store = useReportStore()
  await store.openReport('123')
  const exp = useExport()
  await exp.run('docx')
  expect(store.status).toBe('filed')
  expect(exp.result.value?.filename).toBe('saved.docx')
  await store.save()
  expect(flow.saveReport).not.toHaveBeenCalled()
})

it('keeps an interrupted in-flight export read-only even when reopened before commit', async () => {
  vi.mocked(flow.getReport).mockResolvedValue({ report: {
    id: '123', status: 'generated', version: 2, form: {}, items: [],
    report_no: 'TEST-001', risks: {}, generated_at: 'now',
    provenance: { result_current: true, result_digest: 'a'.repeat(64) },
  } } as never)
  vi.mocked(api.exportReport).mockRejectedValue(new ApiError(0, '连接中断'))
  const store = useReportStore()
  await store.openReport('123')
  await useExport().run('docx')
  expect(store.exportUncertain).toBe(true)
  await store.openReport('123')
  expect(store.exportUncertain).toBe(true)
  await store.save()
  expect(flow.saveReport).not.toHaveBeenCalled()
})

it('remembers a failed export for its report after the user switches reports', async () => {
  vi.mocked(flow.getReport).mockImplementation(async id => ({ report: {
    id, status: 'generated', version: 2, form: {}, items: [],
    report_no: 'TEST-'+id, risks: {}, generated_at: 'now',
    provenance: { result_current: true, result_digest: 'a'.repeat(64) },
  } } as never))
  let reject!: (error: Error) => void
  vi.mocked(api.exportReport).mockImplementation(() => new Promise((_, fail) => { reject = fail }))
  const store = useReportStore()
  await store.openReport('123')
  const pending = useExport().run('docx')
  await vi.waitFor(() => expect(api.exportReport).toHaveBeenCalled())
  await store.openReport('456')
  reject(new ApiError(0, '连接中断'))
  await pending
  expect(store.reportId).toBe('456')
  expect(store.exportUncertain).toBe(false)
  await store.openReport('123')
  expect(store.exportUncertain).toBe(true)
})

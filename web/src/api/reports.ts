/* 报告作业接口。id 一律当字符串（雪花 ID 超出 JS 安全整数）。 */
import { request } from '@/utils/http'
import type { Grade, RiskCategory } from '@/domain/riskScore'
import type { SelectedRisk } from '@/domain/riskAssign'

export interface ItemAnswer {
  no: string
  /** fit / unfit / na / 空=未填 */
  result: string
  reasons: string[]
  other_text: string
}

export interface RiskValue {
  severity: number | null
  probability: string | null
  /** 与服务端口径一致：Ⅰ类 / Ⅱ类 / Ⅲ类 */
  category: RiskCategory
  source: string
  selected_risks?: SelectedRisk[]
  issue?: string
}

export interface Counters {
  total: number
  done: number
  unfit: number
  missing: number
}

export interface ReportSummary {
  id: string
  report_no: string | null
  status: 'draft' | 'generated' | 'filed' | 'void'
  version: number
  created_by: string
  created_at: string
  updated_at: string
  generated_at: string | null
  exported_at: string | null
  voided_at: string | null
  void_reason: string
  client_name: string
  user_name: string
  device_category: string
  product_no: string
  location: string
  assessed_on: string
  form: Record<string, string>
  items: ItemAnswer[]
  counters: Counters
  risks: Record<string, RiskValue>
  score: number | null
  grade: Grade | null
  narrative: string
  provenance: Record<string, unknown>
}

export function createReport(
  form?: Record<string, string>,
): Promise<{ success: boolean; report: ReportSummary }> {
  return request('/reports', { method: 'POST', body: form ? { form } : {} })
}

export function getReport(
  id: string,
): Promise<{ success: boolean; report: ReportSummary }> {
  return request(`/reports/${id}`)
}

export interface DraftResponse {
  success: boolean
  id: string
  status: ReportSummary['status']
  version: number
  form: Record<string, string>
  items: ItemAnswer[]
  counters: Counters
}

export function getDraft(id: string): Promise<DraftResponse> {
  return request(`/reports/${id}/draft`)
}

export function saveReport(
  id: string,
  body: { form: Record<string, string>; items: ItemAnswer[]; version?: number },
): Promise<{ success: boolean; counters: Counters; saved_at: string; version: number; status: ReportSummary['status'] }> {
  return request(`/reports/${id}`, { method: 'PUT', body })
}

export function generateReport(
  id: string,
  useLlm = false,
): Promise<{ success: boolean; report: ReportSummary }> {
  return request(`/reports/${id}/generate`, { method: 'POST', body: { use_llm: useLlm }, timeout: 180_000 })
}

export function listReports(
  params: {
    status?: string
    q?: string
    mine?: boolean
    page?: number
    size?: number
  } = {},
): Promise<{ success: boolean; total: number; page: number; size: number; items: ReportSummary[] }> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.q) query.set('q', params.q)
  if (params.mine) query.set('mine', 'true')
  query.set('page', String(params.page ?? 1))
  query.set('size', String(params.size ?? 20))
  return request(`/reports?${query.toString()}`)
}

export function voidReport(
  id: string,
  reason: string,
): Promise<{ success: boolean; report: ReportSummary }> {
  return request(`/reports/${id}/void`, {
    method: 'POST',
    body: { reason, confirm: true },
  })
}

export function cloneReport(
  id: string,
): Promise<{ success: boolean; report: ReportSummary }> {
  return request(`/reports/${id}/clone`, { method: 'POST', body: {} })
}

export function deleteReport(id: string): Promise<{ success: boolean }> {
  return request(`/reports/${id}?confirm=true`, { method: 'DELETE' })
}

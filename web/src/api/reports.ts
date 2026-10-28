/* 报告作业接口。id 一律当字符串（雪花 ID 超出 JS 安全整数）。 */
import { getToken, request } from '@/utils/http'
import type { Grade, RiskCategory } from '@/domain/riskScore'
import type { SelectedRisk } from '@/domain/riskAssign'

export interface ItemAnswer {
  no: string
  /** fit / unfit / na / 空=未填 */
  result: string
  reasons: string[]
  other_text: string
  editing?: { reasons: string[]; other: boolean; other_text: string; legacy_combined?: boolean }
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
  files?: { fmt: string; filename: string; path: string; size: number;
    version: number; result_digest: string; sha256: string }[]
  /** 本次生成响应的计时，不作为报告业务内容保存 */
  performance?: Record<string, unknown>
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

export interface KgSelection {
  item_no: string
  path_id: string | null
  decision: 'selected' | 'no_candidate'
  rank?: number | null
  query?: string
}

export function generateReport(
  id: string,
  useLlm = false,
  kgSelections: KgSelection[] = [],
): Promise<{ success: boolean; report: ReportSummary }> {
  return request(`/reports/${id}/generate`, {
    method: 'POST',
    body: { use_llm: useLlm, kg_selections: kgSelections },
    timeout: 180_000,
  })
}

/** 流式生成：只接收最终正文文本片段，report 事件返回完整报告。 */
export async function generateReportStream(
  id: string,
  useLlm: boolean,
  kgSelections: KgSelection[],
  onText: (text: string) => void,
): Promise<{ success: boolean; report: ReportSummary }> {
  const base = import.meta.env.VITE_API_BASE || '/api'
  const token = getToken()
  const res = await fetch(`${base}/reports/${id}/generate/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ use_llm: useLlm, kg_selections: kgSelections }),
  })
  if (!res.ok || !res.body) {
    throw new Error(`生成请求失败（HTTP ${res.status}）`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let report: ReportSummary | null = null
  let streamError = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const line = block.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      const payload = line.slice(6).trim()
      if (!payload || payload === '[DONE]') continue
      let event: { type?: string; text?: string; report?: ReportSummary; message?: string }
      try {
        event = JSON.parse(payload)
      } catch {
        continue
      }
      if (event.type === 'text' && event.text) onText(event.text)
      else if (event.type === 'report' && event.report) report = event.report
      else if (event.type === 'error') streamError = event.message || '生成失败'
    }
  }
  if (streamError) throw new Error(streamError)
  if (!report) throw new Error('生成结束但没有收到报告')
  return { success: true, report }
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

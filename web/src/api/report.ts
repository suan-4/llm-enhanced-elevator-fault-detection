import { request } from '@/utils/http'
import type { ExportResponse, JteItemsResponse } from '@/types/api'

/** 拉取 JTE 模板条目目录（66 条，顺序与模板一致） */
export function fetchJteItems(): Promise<JteItemsResponse> {
  return request<JteItemsResponse>('/report/jte-items')
}

export interface ExportPayload {
  fmt: 'pdf' | 'docx'
  title: string
  subtitle?: string
  /** [[标签, 值], ...]；正文已自带抬头表时不要传 */
  meta?: string[][]
  body_html: string
  footer?: string
  filename?: string
}

/** 导出 PDF / Word；LibreOffice 转换耗时数秒，超时放宽 */
export function exportReport(payload: ExportPayload): Promise<ExportResponse> {
  return request<ExportResponse>('/report/export', {
    method: 'POST',
    body: payload,
    timeout: 180_000,
  })
}

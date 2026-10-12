import { request } from '@/utils/http'

/** 在板端用系统默认程序打开导出产物（仅允许打开导出目录内的文件） */
export function openExport(target: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>('/report/open', {
    method: 'POST',
    body: { target },
    timeout: 20_000,
  })
}

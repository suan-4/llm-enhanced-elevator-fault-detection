import { request } from '@/utils/http'

/** 一体机状态。仅本机调用有效，非本机一律返回 kiosk_running=false。 */
export interface KioskStatus {
  success: boolean
  kiosk_running: boolean
  exit_enabled: boolean
  local: boolean
  /** 探针（pgrep）是否可用；不可用时前端保守显示退出入口 */
  probe_ok: boolean
}

export function kioskStatus(): Promise<KioskStatus> {
  return request<KioskStatus>('/kiosk/status', { timeout: 8000 })
}

/** 关闭 kiosk 界面返回桌面。登录页也要能调用——否则进不去系统时没有出口。 */
export function exitKiosk(): Promise<{ success: boolean; kiosk_running: boolean }> {
  return request<{ success: boolean; kiosk_running: boolean }>('/kiosk/exit', {
    method: 'POST',
    timeout: 15000,
  })
}

export interface ImeState {
  success: boolean
  state: number
  label: string
  available: boolean
}

/** 输入法中英切换状态。板端为 fcitx5，经接口驱动。 */
export function imeStatus(): Promise<ImeState> {
  return request<ImeState>('/ime/status', { timeout: 8000 })
}

export function toggleIme(): Promise<ImeState> {
  return request<ImeState>('/ime/toggle', { method: 'POST', timeout: 8000 })
}

/** 在板端用系统默认程序打开导出产物或所在目录 */
export function openExport(target: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>('/report/open', {
    method: 'POST',
    body: { target },
    timeout: 20000,
  })
}

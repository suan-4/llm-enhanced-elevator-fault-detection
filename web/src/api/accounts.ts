/* 账号管理接口（单角色：登录即可）。
   注意 id 一律当字符串处理 —— 雪花 ID 超出 JS 安全整数，转数字会失真。 */
import { request } from '@/utils/http'

export interface Account {
  id: string
  username: string
  display_name: string
  employee_no: string
  role: string
  is_active: boolean
  must_change_password: boolean
  created_at: string
  last_login_at: string | null
}

export interface AccountListResponse {
  success: boolean
  total: number
  page: number
  size: number
  items: Account[]
}

export function listAccounts(params: {
  status?: string
  q?: string
  page?: number
  size?: number
} = {}): Promise<AccountListResponse> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.q) query.set('q', params.q)
  query.set('page', String(params.page ?? 1))
  query.set('size', String(params.size ?? 50))
  return request<AccountListResponse>(`/accounts?${query.toString()}`)
}

export function createAccount(body: {
  display_name: string
  username: string
  password: string
  employee_no?: string
  require_change?: boolean
}): Promise<{ success: boolean; account: Account }> {
  return request<{ success: boolean; account: Account }>('/accounts', {
    method: 'POST',
    body,
  })
}

export function updateAccount(
  accountId: string,
  body: {
    display_name?: string
    employee_no?: string
    is_active?: boolean
    confirm?: boolean
  },
): Promise<{ success: boolean; account: Account }> {
  return request<{ success: boolean; account: Account }>(`/accounts/${accountId}`, {
    method: 'PATCH',
    body,
  })
}

export function deleteAccount(accountId: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(`/accounts/${accountId}?confirm=true`, {
    method: 'DELETE',
  })
}

export function resetPassword(
  accountId: string,
  newPassword: string,
  requireChange = false,
): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>(
    `/accounts/${accountId}/reset-password`,
    { method: 'POST', body: { new_password: newPassword, require_change: requireChange, confirm: true } },
  )
}

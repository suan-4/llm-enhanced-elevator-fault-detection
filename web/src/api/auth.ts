import { request } from '@/utils/http'
import type { LoginResponse, MeResponse } from '@/types/api'

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: { username, password },
  })
}

export function logout(): Promise<{ success: boolean }> {
  return request<{ success: boolean }>('/auth/logout', { method: 'POST' })
}

export function me(): Promise<MeResponse> {
  return request<MeResponse>('/auth/me')
}

/* ── 初始化向导与口令找回（v1 账号体系）────────────────── */

export interface SetupStatus {
  initialized: boolean
  /** 板端是否配了恢复口令文件（决定登录页要不要显示「忘记口令」） */
  recovery_available: boolean
  version: string
}

export function setupStatus(): Promise<SetupStatus & { success: boolean }> {
  return request<SetupStatus & { success: boolean }>('/setup/status')
}

export function setupInit(body: {
  display_name: string
  username: string
  password: string
}): Promise<LoginResponse> {
  return request<LoginResponse>('/setup/init', { method: 'POST', body })
}

export function forgotPassword(body: {
  recovery_key: string
  username: string
  new_password: string
}): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>('/auth/forgot-password', {
    method: 'POST',
    body,
  })
}

export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>('/auth/change-password', {
    method: 'POST',
    body: { old_password: oldPassword, new_password: newPassword },
  })
}

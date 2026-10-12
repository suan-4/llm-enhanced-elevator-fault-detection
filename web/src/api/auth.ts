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

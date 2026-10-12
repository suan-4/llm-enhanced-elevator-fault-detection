/* 请求封装：统一鉴权头、错误归一、超时。
   不使用 axios —— 板端离线，少一个依赖就少一份风险。 */

const API_BASE = import.meta.env.VITE_API_BASE || '/api'
const TOKEN_KEY = 'elevator_token'
const DEFAULT_TIMEOUT = 60_000

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = `请求失败（HTTP ${res.status}）`
  try {
    const data = (await res.json()) as { detail?: unknown }
    if (typeof data.detail === 'string') {
      detail = data.detail
    }
  } catch {
    // 响应不是 JSON，保留默认提示
  }
  return new ApiError(res.status, detail)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  timeout?: number
  /** 生成报告等长耗时接口使用 */
  signal?: AbortSignal
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, timeout = DEFAULT_TIMEOUT, signal } = options
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeout)

  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  const headers: Record<string, string> = { ...authHeaders() }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    window.clearTimeout(timer)
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, '请求超时，请检查网络或稍后重试')
    }
    throw new ApiError(0, '无法连接服务器，请确认后端服务已启动')
  }
  window.clearTimeout(timer)

  if (!res.ok) {
    throw await parseError(res)
  }

  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

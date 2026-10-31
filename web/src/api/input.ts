export type InputAction = { key: string } | { candidate: string } | { page: 'next' }
export interface InputStatus { keyboard: boolean; pinyin: boolean; voice: boolean; offline: boolean }
export interface PinyinResult { candidates: string[]; committed: string; has_next: boolean }

export async function inputRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api/input' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Elevator-Input': '1' },
    body: body === undefined ? undefined : JSON.stringify(body), signal,
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '输入服务暂不可用')
  return result as T
}

/* 无视觉效果的计时事件。只记录阶段/状态/时长，绝不包含表单和鉴权。 */
export interface Interaction {
  measure<T>(name: string, work: () => Promise<T>): Promise<T>
  finish(status: 'ok' | 'error'): void
}

export function beginInteraction(name: string): Interaction {
  const clock = globalThis.performance?.now?.bind(globalThis.performance)
  const started = clock?.()
  const stages: { name: string; duration_ms: number; status: 'ok' | 'error' }[] = []
  let finished = false
  return {
    async measure<T>(stage: string, work: () => Promise<T>): Promise<T> {
      const beginning = clock?.()
      let status: 'ok' | 'error' = 'ok'
      try {
        return await work()
      } catch (error) {
        status = 'error'
        throw error
      } finally {
        if (beginning !== undefined && clock) {
          stages.push({ name: stage, duration_ms: clock() - beginning, status })
        }
      }
    },
    finish(status) {
      if (finished) return
      finished = true
      if (started === undefined || !clock || typeof window === 'undefined' || typeof window?.dispatchEvent !== 'function') return
      try {
        window.dispatchEvent(new CustomEvent('elevator:performance', {
          detail: { schema_version: 1, name, status, total_ms: clock() - started, stages },
        }))
      } catch { /* 观测能力缺失不能让已完成的报告变成失败。 */ }
    },
  }
}

export async function afterPaint(): Promise<void> {
  if (typeof requestAnimationFrame !== 'function') return
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
}

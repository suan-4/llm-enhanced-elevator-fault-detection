import { afterEach, describe, expect, it, vi } from 'vitest'
import { afterPaint, beginInteraction } from './performance'

afterEach(() => vi.unstubAllGlobals())

describe('nonvisual interaction measurement', () => {
  it('measures stages and emits once without copying user data', async () => {
    let now = 0
    vi.stubGlobal('performance', { now: () => now })
    const dispatchEvent = vi.fn()
    vi.stubGlobal('window', { dispatchEvent })
    const trace = beginInteraction('report_generate')
    const result = await trace.measure('save', async () => { now = 25; return 'private form' })
    now = 100
    trace.finish('ok')
    trace.finish('error')
    expect(result).toBe('private form')
    expect(dispatchEvent).toHaveBeenCalledTimes(1)
    const value = dispatchEvent.mock.calls[0]![0].detail
    expect(value.total_ms).toBe(100)
    expect(value.stages).toEqual([{ name: 'save', duration_ms: 25, status: 'ok' }])
    expect(JSON.stringify(value)).not.toContain('private form')
  })

  it('does not swallow failures', async () => {
    vi.stubGlobal('performance', { now: () => 1 })
    vi.stubGlobal('window', { dispatchEvent: vi.fn() })
    const trace = beginInteraction('report_generate')
    const error = new Error('business error')
    await expect(trace.measure('save', async () => { throw error })).rejects.toBe(error)
    trace.finish('error')
    expect(window.dispatchEvent).toHaveBeenCalledOnce()
  })

  it('missing browser APIs never block the operation', async () => {
    vi.stubGlobal('performance', undefined)
    vi.stubGlobal('window', undefined)
    const trace = beginInteraction('report_generate')
    expect(await trace.measure('save', async () => 42)).toBe(42)
    expect(() => trace.finish('ok')).not.toThrow()
    await afterPaint()
  })

  it('an absent event target or a broken observer cannot fail a completed report', () => {
    vi.stubGlobal('performance', { now: () => 10 })
    vi.stubGlobal('window', undefined)
    expect(() => beginInteraction('report_generate').finish('ok')).not.toThrow()
    vi.stubGlobal('window', { dispatchEvent: () => { throw new Error('observer unavailable') } })
    expect(() => beginInteraction('report_generate').finish('ok')).not.toThrow()
  })

  it('waits for two painting opportunities rather than declaring the DOM update painted', async () => {
    const queue: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => queue.push(callback))
    let finished = false
    const pending = afterPaint().then(() => { finished = true })
    expect(finished).toBe(false)
    queue.shift()!(0)
    await Promise.resolve()
    expect(finished).toBe(false)
    queue.shift()!(16)
    await pending
    expect(finished).toBe(true)
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAdaptivePolling } from '../src/composables/useAdaptivePolling.js'

describe('adaptive polling', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('uses 2s while running and 10s while idle', async () => {
    vi.useFakeTimers()
    const poll = vi.fn()
      .mockResolvedValueOnce({ state: 'running' })
      .mockResolvedValueOnce({ state: 'idle' })
      .mockResolvedValue({ state: 'idle' })
    const polling = useAdaptivePolling(poll, { runningDelay: 2000, idleDelay: 10000 })

    polling.start()
    await vi.advanceTimersByTimeAsync(0)
    expect(poll).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1999)
    expect(poll).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(poll).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(9999)
    expect(poll).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(poll).toHaveBeenCalledTimes(3)
    polling.stop()
  })
})

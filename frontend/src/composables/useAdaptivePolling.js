import { onBeforeUnmount, unref, watch } from 'vue'

export function taskIsRunning(task) {
  const state = String(task?.state || '').toLowerCase()
  return Boolean(task?.active) || ['starting', 'running', 'stopping', 'queued'].includes(state)
}

export function useAdaptivePolling(fn, options = {}) {
  const {
    active = true,
    runningDelay = 2000,
    idleDelay = 10000,
    getRunning = taskIsRunning,
    immediate = true,
  } = options
  let timer = null
  let stopped = true
  let inFlight = false
  let lastRunning = false

  function clearTimer() {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  function canPoll() {
    return !stopped && Boolean(unref(active)) && !globalThis.document?.hidden
  }

  function schedule(delay = lastRunning ? runningDelay : idleDelay) {
    clearTimer()
    if (!canPoll()) return
    timer = setTimeout(tick, delay)
  }

  async function tick() {
    clearTimer()
    if (!canPoll() || inFlight) return
    inFlight = true
    try {
      const result = await fn()
      lastRunning = Boolean(getRunning(result))
    } finally {
      inFlight = false
      schedule()
    }
  }

  function start() {
    if (!stopped) return
    stopped = false
    globalThis.document?.addEventListener?.('visibilitychange', handleVisibility)
    if (immediate) tick()
    else schedule()
  }

  function stop() {
    stopped = true
    clearTimer()
    globalThis.document?.removeEventListener?.('visibilitychange', handleVisibility)
  }

  function handleVisibility() {
    clearTimer()
    if (canPoll()) tick()
  }

  function setRunning(value) {
    lastRunning = Boolean(value)
    if (!inFlight && canPoll()) schedule(lastRunning ? runningDelay : idleDelay)
  }

  if (active && typeof active === 'object') {
    watch(active, (enabled) => {
      clearTimer()
      if (enabled && !stopped) tick()
    })
  }

  onBeforeUnmount(stop)
  return { start, stop, refresh: tick, setRunning, isRunning: () => lastRunning }
}

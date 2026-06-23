import { onBeforeUnmount } from 'vue'

export function usePolling(fn, interval = 2000, options = {}) {
  const { maxDelay = 30000, pauseWhenHidden = false } = options
  let timer = null
  let active = false
  let errorCount = 0
  let paused = false

  function getDelay() {
    if (errorCount === 0) return interval
    return Math.min(interval * Math.pow(2, errorCount), maxDelay)
  }

  async function tick() {
    if (!active || paused) return
    try {
      await fn()
    } catch (_) {}
    if (active) {
      timer = setTimeout(tick, getDelay())
    }
  }

  function handleVisibility() {
    if (!pauseWhenHidden) return
    paused = document.hidden
    if (!paused && active && timer === null) {
      tick()
    }
  }

  function start() {
    if (active) return
    active = true
    if (pauseWhenHidden) {
      document.addEventListener('visibilitychange', handleVisibility)
      paused = document.hidden
    }
    if (!paused) tick()
  }

  function stop() {
    active = false
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    if (pauseWhenHidden) {
      document.removeEventListener('visibilitychange', handleVisibility)
      paused = false
    }
  }

  function reportError() {
    errorCount++
  }

  function reportSuccess() {
    errorCount = 0
  }

  onBeforeUnmount(stop)

  return { start, stop, reportError, reportSuccess }
}

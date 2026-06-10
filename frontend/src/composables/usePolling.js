import { onBeforeUnmount } from 'vue'

export function usePolling(fn, interval = 2000) {
  let timer = null

  function start() {
    stop()
    fn()
    timer = setInterval(fn, interval)
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  onBeforeUnmount(stop)

  return { start, stop }
}

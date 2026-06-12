import { onBeforeUnmount } from 'vue'

// 自适应轮询：用递归 setTimeout 取代 setInterval。
// 关键差别——只有当上一次请求（含网络往返）真正结束后，才安排下一次。
// 网络不好时，setInterval 会无视上一次是否完成而持续 fire，请求堆积、
// 进一步堵死浏览器并发连接；递归 setTimeout 天然串行，不会堆积。
export function usePolling(fn, interval = 2000) {
  let timer = null
  let active = false

  async function tick() {
    if (!active) return
    try {
      await fn()
    } catch (_) {
      // fn 内部一般已自行 catch，这里兜底，避免一次失败终止整个轮询
    }
    if (active) {
      timer = setTimeout(tick, interval)
    }
  }

  function start() {
    if (active) return
    active = true
    tick()
  }

  function stop() {
    active = false
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  onBeforeUnmount(stop)

  return { start, stop }
}

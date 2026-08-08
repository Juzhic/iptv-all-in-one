import { onBeforeUnmount, onMounted, ref } from 'vue'

export function parseHashRoute(hash, validRoutes, fallback = 'overview', aliases = {}) {
  const raw = String(hash || '').replace(/^#\/?/, '').split('?')[0]
  let route = fallback
  try {
    route = decodeURIComponent(raw || fallback)
  } catch (_) {
    route = fallback
  }
  route = aliases[route] || route
  return validRoutes.includes(route) ? route : fallback
}

export function routeHash(route) {
  return `#/${encodeURIComponent(route)}`
}

export function useHashRoute({ routes, fallback = 'overview', aliases = {}, beforeChange } = {}) {
  const validRoutes = Array.isArray(routes) ? routes : []
  const current = ref(parseHashRoute(globalThis.location?.hash, validRoutes, fallback, aliases))
  let restoring = false

  async function canChange(next, previous) {
    if (!beforeChange || next === previous) return true
    return (await beforeChange(next, previous)) !== false
  }

  async function navigate(next, { replace = false } = {}) {
    const target = validRoutes.includes(next) ? next : fallback
    if (!await canChange(target, current.value)) return false
    current.value = target
    const hash = routeHash(target)
    if (globalThis.location?.hash !== hash) {
      if (replace && globalThis.history?.replaceState) {
        globalThis.history.replaceState(null, '', hash)
      } else {
        globalThis.location.hash = hash
      }
    }
    return true
  }

  async function syncFromHash() {
    if (restoring) return
    const next = parseHashRoute(globalThis.location?.hash, validRoutes, fallback, aliases)
    if (!await canChange(next, current.value)) {
      restoring = true
      globalThis.history?.replaceState?.(null, '', routeHash(current.value))
      restoring = false
      return
    }
    current.value = next
  }

  onMounted(() => {
    globalThis.addEventListener?.('hashchange', syncFromHash)
    if (globalThis.location?.hash !== routeHash(current.value)) {
      globalThis.history?.replaceState?.(null, '', routeHash(current.value))
    }
  })

  onBeforeUnmount(() => {
    globalThis.removeEventListener?.('hashchange', syncFromHash)
  })

  return { current, navigate, syncFromHash }
}

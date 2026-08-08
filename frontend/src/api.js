// ─── 统一 API 请求封装 ───

// 默认请求超时（毫秒）。网络不好时，避免 fetch 无限挂起、
// 耗尽浏览器对单一域名的并发连接数（约 6 个），导致页面"卡死"。
export const DEFAULT_TIMEOUT = 20000

// 错误消息映射
const ERROR_MESSAGES = {
  400: '请求参数错误',
  401: '认证失败，请检查用户名和密码',
  403: '没有权限执行此操作',
  404: '请求的资源不存在',
  409: '操作冲突，请稍后重试',
  429: '请求过于频繁，请稍后重试',
  500: '服务器内部错误',
  502: '服务不可用',
  503: '服务暂时不可用',
  504: '请求超时',
}

// 解包后端统一响应格式 {ok, data, ...} → data
function unwrap(json) {
  if (json && typeof json === 'object' && 'ok' in json) {
    if (!json.ok) {
      const error = new Error(json.error || json.message || '请求失败')
      error.data = json.data ?? json
      error.payload = json
      throw error
    }
    const data = json.data ?? json
    // 保留顶层 message 字段，供调用方展示后端提示
    if (json.message && data && typeof data === 'object' && !('message' in data)) {
      data.message = json.message
    }
    return data
  }
  return json
}

// 给 fetch 套上超时控制：到时自动 abort，释放连接。
function fetchWithTimeout(url, opts = {}) {
  const { timeout = DEFAULT_TIMEOUT, signal, ...rest } = opts
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)
  // 兼容调用方自带的 signal
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }
  return fetch(url, { credentials: 'same-origin', signal: controller.signal, ...rest })
    .catch(err => {
      if (err.name === 'AbortError' && timedOut) {
        throw new Error('请求超时，请检查网络连接')
      }
      throw err
    })
    .finally(() => clearTimeout(timer))
}

async function parseJSONResponse(response) {
  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch (_) {
      payload = { message: text }
    }
  }

  if (!response.ok) {
    const backendMessage = payload?.error || payload?.message
    const error = new Error(backendMessage || ERROR_MESSAGES[response.status] || `请求失败 (HTTP ${response.status})`)
    error.status = response.status
    error.response = response
    error.data = payload?.data ?? payload
    error.payload = payload
    throw error
  }

  return unwrap(payload)
}

export function fetchJSON(url, opts = {}) {
  return fetchWithTimeout(url, opts).then(parseJSONResponse)
}

function mutationJSON(method, url, data = {}, opts = {}) {
  return fetchJSON(url, {
    ...opts,
    method,
    headers: {
      ...(opts.headers || {}),
      'Content-Type': 'application/json',
      'X-IPTV-Request': '1',
    },
    body: JSON.stringify(data ?? {}),
  })
}

export function postJSON(url, data = {}, opts = {}) {
  return mutationJSON('POST', url, data, opts)
}

export function putJSON(url, data = {}, opts = {}) {
  return mutationJSON('PUT', url, data, opts)
}

export function patchJSON(url, data = {}, opts = {}) {
  return mutationJSON('PATCH', url, data, opts)
}

export function deleteJSON(url, data = {}, opts = {}) {
  return mutationJSON('DELETE', url, data, opts)
}

export async function fetchText(url, opts = {}) {
  const response = await fetchWithTimeout(url, opts)
  if (!response.ok) await parseJSONResponse(response)
  return response.text()
}

function withQuery(path, params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  }
  const encoded = query.toString()
  return encoded ? `${path}?${encoded}` : path
}

function responseTask(payload) {
  const task = payload?.task ?? payload?.data?.task
  if (task && typeof task === 'object') return { ...payload, ...task, task }
  if (payload?.data && typeof payload.data === 'object') return { ...payload, ...payload.data }
  return payload
}

// ─── 初始数据 ───
export function apiGetInitial(opts = {}) {
  return fetchJSON('/api/initial', opts)
}
export function apiGetDashboard(trendLimit = 10, opts = {}) {
  return fetchJSON(withQuery('/api/dashboard', { trend_limit: trendLimit }), opts)
}
export function apiGetTasks(opts = {}) {
  return fetchJSON('/api/tasks', opts)
}

// ─── 配置 ───
export function apiGetConfig(opts = {}) {
  return fetchJSON('/api/config', opts)
}
export function apiGetConfigSecurityStatus(opts = {}) {
  return fetchJSON('/api/config/security-status', opts)
}
export function apiSaveConfig(data, opts = {}) {
  return postJSON('/api/config', data, opts)
}
export function apiExportConfig(opts = {}) {
  return fetchJSON('/api/config/export', opts)
}
export function apiImportConfig(data, opts = {}) {
  return postJSON('/api/config/import', data, opts)
}

// ─── 数据文件 ───
export function apiGetText(key, opts = {}) {
  return fetchJSON(`/api/text/${encodeURIComponent(key)}`, opts)
}
export function apiSaveText(key, content, opts = {}) {
  return postJSON(`/api/text/${encodeURIComponent(key)}`, { content }, opts)
}
export function apiResetDemo(opts = {}) {
  return postJSON('/api/reset-demo', {}, opts)
}
export function apiDiscover(data = {}, opts = {}) {
  return postJSON('/api/discover', data, opts)
}
export function apiDiscoverMerge(data, opts = {}) {
  return postJSON('/api/discover/merge', data, opts)
}

// ─── 测试历史 ───
export function apiGetRuns(start, end, params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/runs', { ...params, start, end }), opts)
}
export function apiGetRun(runId, opts = {}) {
  return fetchJSON(`/api/run/${encodeURIComponent(runId)}`, opts)
}
export function apiGetRunChannels(runId, page, size, filters = {}, opts = {}) {
  return fetchJSON(withQuery(`/api/run/${encodeURIComponent(runId)}/channels`, {
    ...filters,
    page,
    size,
  }), opts)
}
export function apiDeleteRun(runId, opts = {}) {
  return deleteJSON(`/api/run/${encodeURIComponent(runId)}`, {}, opts)
}
export function apiGetRunLogs(runId, opts = {}) {
  return fetchJSON(`/api/run/${encodeURIComponent(runId)}/logs`, opts)
}
export function apiCompareRuns(runA, runB, opts = {}) {
  return fetchJSON(withQuery('/api/compare', { run_a: runA, run_b: runB }), opts)
}
export function apiGetSources(params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/sources', params), opts)
}

// ─── 测试控制 ───
export function apiTriggerTest(opts = {}) {
  return postJSON('/api/trigger', {}, opts).then(responseTask)
}
export function apiStopTest(opts = {}) {
  return postJSON('/api/stop', {}, opts).then(responseTask)
}
export function apiGetProgress(after = 0, taskId = '', opts = {}) {
  return fetchJSON(withQuery('/api/progress', { after, task_id: taskId }), opts)
}

// ─── 结果 ───
export function apiDownloadUrl(fmt) {
  return `/api/download/${fmt}`
}
export function apiPreviewResult(fmt, opts = {}) {
  return fetchText(`/api/download/${encodeURIComponent(fmt)}`, opts)
}

// ─── 扫描 ───
export function apiScanTrigger(provinces, opts = {}) {
  return postJSON('/api/scan/trigger', { provinces }, opts).then(responseTask)
}
export function apiScanTriggerIncremental(data = {}, opts = {}) {
  return postJSON('/api/scan/trigger-incremental', data, opts).then(responseTask)
}
export function apiScanStop(opts = {}) {
  return postJSON('/api/scan/stop', {}, opts).then(responseTask)
}
export function apiScanForceClear(opts = {}) {
  return postJSON('/api/scan/force-clear', {}, opts).then(responseTask)
}
export function apiScanStatus(taskId = '', opts = {}) {
  return fetchJSON(withQuery('/api/scan/status', { task_id: taskId }), opts)
}
export function apiScanLatest(opts = {}) {
  return fetchJSON('/api/scan/latest', opts)
}
export function apiScanResults(params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/results', params), opts)
}
export function apiScanHistory(opts = {}) {
  return fetchJSON('/api/scan/history', opts)
}
export function apiScanStats(params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/stats', params), opts)
}
export function apiScanYieldStats(params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/yield-stats', params), opts)
}
export function apiScanConfig(opts = {}) {
  return fetchJSON('/api/scan/config', opts)
}
export function apiSaveScanConfig(data, opts = {}) {
  return postJSON('/api/scan/config', data, opts)
}

export function apiScanKeys(opts = {}) {
  return fetchJSON('/api/scan/keys', opts)
}
export function apiScanKeysCredits(opts = {}) {
  return fetchJSON('/api/scan/keys/credits', { timeout: 60000, ...opts })
}
export function apiScanKeyAdd(platform, key, email, opts = {}) {
  const body = { platform, key }
  if (email) body.email = email
  return postJSON('/api/scan/keys', body, opts)
}
export function apiScanKeyUpdate(platform, keyId, newKey, email, opts = {}) {
  const body = {
    platform,
    key_id: keyId,
    new_key: newKey,
  }
  if (email) body.email = email
  return putJSON('/api/scan/keys', body, opts)
}
export function apiScanKeyDelete(platform, keyId, opts = {}) {
  return deleteJSON('/api/scan/keys', { platform, key_id: keyId }, opts)
}

// ─── 持久化扫描结果 ───
export function apiPersistentGrouped(params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/persistent/grouped', params), opts)
}
export function apiPersistentDetails(sourceIp, page, size, filters = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/persistent/details', {
    ...filters,
    source_ip: sourceIp,
    page,
    size,
  }), opts)
}
export function apiPersistentStats(opts = {}) {
  return fetchJSON('/api/scan/persistent/stats', opts)
}
export function apiPersistentManualCheck(opts = {}) {
  return postJSON('/api/scan/persistent/manual-check', {}, opts).then(responseTask)
}
export function apiDetectionLogs(limit = 200, opts = {}) {
  return fetchJSON(withQuery('/api/scan/detection/logs', { limit }), opts)
}
export function apiDetectionStatus(taskId = '', opts = {}) {
  return fetchJSON(withQuery('/api/scan/detection/status', { task_id: taskId }), opts)
}
export function apiDetectionRuns(start, end, limit = 100, params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/detection/runs', { ...params, start, end, limit }), opts)
}
export function apiDetectionRunResults(cycleId, page, size, filters = {}, opts = {}) {
  return fetchJSON(withQuery('/api/scan/detection/run/' + encodeURIComponent(cycleId) + '/results', {
    ...filters,
    page,
    size,
  }), opts)
}
export function apiPersistentRecheck(url, opts = {}) {
  return postJSON('/api/scan/persistent/recheck', { url }, opts).then(responseTask)
}
export function apiPersistentPriority(url, priority, opts = {}) {
  return postJSON('/api/scan/persistent/priority', { url, priority }, opts)
}

export async function fetchAllPaged(fetchPage, options = {}) {
  const { pageSize = 200, maxPages = 500, signal } = options
  const items = []
  let page = 1
  let total = Number.POSITIVE_INFINITY

  while (page <= maxPages && items.length < total) {
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError')
    const payload = await fetchPage(page, pageSize, { signal })
    const pageItems = Array.isArray(payload)
      ? payload
      : (payload?.items || payload?.results || [])
    items.push(...pageItems)
    total = Number(payload?.total)
    if (!Number.isFinite(total)) total = pageItems.length < pageSize ? items.length : Number.POSITIVE_INFINITY
    if (!pageItems.length || pageItems.length < pageSize) break
    page += 1
  }

  return items
}

export function apiPersistentAllDetails(sourceIp, filters = {}, opts = {}) {
  return fetchAllPaged(
    (page, size, requestOpts) => apiPersistentDetails(sourceIp, page, size, filters, requestOpts),
    opts,
  )
}

export function apiScanAllResults(params = {}, opts = {}) {
  return fetchAllPaged(
    (page, size, requestOpts) => apiScanResults({ ...params, page, size }, requestOpts),
    opts,
  )
}

// ─── SSE 连接（带自动重连） ───

let runtimeCapabilityPromise = null
let runtimeCapabilityExpiry = 0
const RUNTIME_CAPABILITY_TTL = 60_000 // 1 分钟缓存

function getSseOverride() {
  try {
    const override = window.localStorage?.getItem('iptv_enable_sse')
    if (override === '1') return true
    if (override === '0') return false
  } catch (_) {}
  const envValue = String(import.meta.env?.VITE_ENABLE_SSE || '').toLowerCase()
  if (envValue === '1' || envValue === 'true') return true
  if (envValue === '0' || envValue === 'false') return false
  return null
}

export function apiRuntimeCapabilities() {
  const now = Date.now()
  if (!runtimeCapabilityPromise || now > runtimeCapabilityExpiry) {
    runtimeCapabilityExpiry = now + RUNTIME_CAPABILITY_TTL
    runtimeCapabilityPromise = fetchJSON('/api/runtime', { timeout: 5000 }).catch(() => null)
  }
  return runtimeCapabilityPromise
}

export async function shouldUseSse() {
  const override = getSseOverride()
  if (override !== null) return override
  const runtime = await apiRuntimeCapabilities()
  return runtime?.sse?.enabled === true
}

/**
 * 创建带自动重连的 SSE 连接。
 * 断线后自动重试（指数退避），重试耗尽才通知 onerror。
 * @param {string} url - SSE 端点
 * @param {object} handlers - 事件处理器（status, log, progress 等，含 onerror）
 * @param {object} opts - 选项
 * @param {number} opts.maxRetries - 最大重试次数（默认 5）
 * @param {number} opts.baseDelay - 首次重连延迟 ms（默认 2000）
 * @returns {{ close: function }}
 */
export function createSseConnection(url, handlers = {}, opts = {}) {
  const maxRetries = opts.maxRetries ?? 5
  const baseDelay = opts.baseDelay ?? 2000

  let es = null
  let retryCount = 0
  let retryTimer = null
  let closed = false

  function connect() {
    if (closed) return
    es = new EventSource(url)

    // 注册命名事件（跳过特殊键）
    for (const [name, fn] of Object.entries(handlers)) {
      if (name === 'onerror' || name === 'onFailed' || name === 'onReconnecting') continue
      if (typeof fn === 'function') es.addEventListener(name, fn)
    }

    es.onerror = () => {
      if (closed) return
      es.close()
      es = null

      if (retryCount >= maxRetries) {
        // 重试耗尽，通知上层切换轮询
        if (handlers.onerror) handlers.onerror()
        return
      }
      retryCount++
      const delay = Math.min(baseDelay * Math.pow(2, retryCount - 1), 30000)
      if (handlers.onReconnecting) handlers.onReconnecting(retryCount, delay)
      retryTimer = setTimeout(connect, delay)
    }
  }

  connect()

  return {
    close() {
      closed = true
      if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
      if (es) { es.close(); es = null }
    },
  }
}

export function connectTestSse(handlers = {}) {
  return createSseConnection('/api/test/stream', handlers)
}

export function connectDetectionSse(handlers = {}) {
  return createSseConnection('/api/detection/stream', handlers)
}

export function connectScanSse(handlers = {}) {
  return createSseConnection('/api/scan/stream', handlers)
}

// ─── IP扫描 ───
export function apiIpScanTrigger(data, opts = {}) {
  return postJSON('/api/ip-scan/trigger', data, opts).then(responseTask)
}
export function apiIpScanStop(opts = {}) {
  return postJSON('/api/ip-scan/stop', {}, opts).then(responseTask)
}
export function apiIpScanForceClear(opts = {}) {
  return postJSON('/api/ip-scan/force-clear', {}, opts).then(responseTask)
}
export function apiIpScanStatus(taskId = '', opts = {}) {
  return fetchJSON(withQuery('/api/ip-scan/status', { task_id: taskId }), opts)
}
export function apiIpScanLogs(after = 0, limit = 500, taskId = '', opts = {}) {
  return fetchJSON(withQuery('/api/ip-scan/logs', { after, limit, task_id: taskId }), opts)
}
export function apiIpScanResults(params = {}, opts = {}) {
  return fetchJSON(withQuery('/api/ip-scan/results', params), opts)
}
export function apiIpScanLatest(opts = {}) {
  return fetchJSON('/api/ip-scan/latest', opts)
}
export function apiIpScanHistory(limit = 20, opts = {}) {
  return fetchJSON(withQuery('/api/ip-scan/history', { limit }), opts)
}
export function apiIpScanStats(scanId, opts = {}) {
  return fetchJSON(withQuery('/api/ip-scan/stats', { scan_id: scanId }), opts)
}
export function apiIpScanExportUrl(scanId) {
  return '/api/ip-scan/export?scan_id=' + encodeURIComponent(scanId)
}

export function connectIpScanSse(handlers = {}) {
  return createSseConnection('/api/ip-scan/stream', handlers)
}

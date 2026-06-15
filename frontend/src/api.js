// ─── 统一 API 请求封装 ───

// 默认请求超时（毫秒）。网络不好时，避免 fetch 无限挂起、
// 耗尽浏览器对单一域名的并发连接数（约 6 个），导致页面“卡死”。
const DEFAULT_TIMEOUT = 20000

function checkStatus(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r
}

// 给 fetch 套上超时控制：到时自动 abort，释放连接。
function fetchWithTimeout(url, opts = {}) {
  const { timeout = DEFAULT_TIMEOUT, signal, ...rest } = opts
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  // 兼容调用方自带的 signal
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }
  return fetch(url, { credentials: 'same-origin', signal: controller.signal, ...rest })
    .finally(() => clearTimeout(timer))
}

export function fetchJSON(url, opts = {}) {
  return fetchWithTimeout(url, opts).then(checkStatus).then(r => r.json())
}

export function postJSON(url, data) {
  return fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function putJSON(url, data) {
  return fetchJSON(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteJSON(url, data) {
  const opts = { method: 'DELETE' }
  if (data !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(data)
  }
  return fetchWithTimeout(url, opts).then(checkStatus).then(r => r.json())
}

export function fetchText(url) {
  return fetchWithTimeout(url).then(checkStatus).then(r => r.text())
}

// ─── 初始数据 ───
export function apiGetInitial() {
  return fetchJSON('/api/initial')
}

// ─── 配置 ───
export function apiGetConfig() {
  return fetchJSON('/api/config')
}
export function apiSaveConfig(data) {
  return postJSON('/api/config', data)
}

// ─── 数据文件 ───
export function apiGetText(key) {
  return fetchJSON(`/api/text/${key}`)
}
export function apiSaveText(key, content) {
  return postJSON(`/api/text/${key}`, { content })
}
export function apiResetDemo() {
  return postJSON('/api/reset-demo')
}

// ─── 测试历史 ───
export function apiGetRuns(start, end) {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  const qs = params.toString()
  return fetchJSON('/api/runs' + (qs ? '?' + qs : ''))
}
export function apiGetRun(runId) {
  return fetchJSON(`/api/run/${runId}`)
}
export function apiGetRunChannels(runId, page, size) {
  const params = new URLSearchParams()
  if (page != null) params.set('page', page)
  if (size != null) params.set('size', size)
  const qs = params.toString()
  return fetchJSON(`/api/run/${runId}/channels` + (qs ? '?' + qs : ''))
}
export function apiDeleteRun(runId) {
  return deleteJSON(`/api/run/${runId}`)
}
export function apiGetRunLogs(runId) {
  return fetchJSON(`/api/run/${runId}/logs`)
}

// ─── 测试控制 ───
export function apiTriggerTest() {
  return postJSON('/api/trigger')
}
export function apiStopTest() {
  return postJSON('/api/stop')
}
export function apiGetProgress(after = 0) {
  return fetchJSON(`/api/progress?after=${after}`)
}

// ─── 结果 ───
export function apiDownloadUrl(fmt) {
  return `/api/download/${fmt}`
}
export function apiPreviewResult(fmt) {
  return fetchText(`/api/download/${fmt}`)
}

// ─── 扫描 ───
export function apiScanTrigger(provinces) {
  return postJSON('/api/scan/trigger', { provinces })
}
export function apiScanStop() {
  return postJSON('/api/scan/stop')
}
export function apiScanForceClear() {
  return postJSON('/api/scan/force-clear')
}
export function apiScanStatus() {
  return fetchJSON('/api/scan/status')
}
export function apiScanLatest() {
  return fetchJSON('/api/scan/latest')
}
export function apiScanResults(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return fetchJSON('/api/scan/results' + (qs ? '?' + qs : ''))
}
export function apiScanHistory() {
  return fetchJSON('/api/scan/history')
}
export function apiScanStats(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return fetchJSON('/api/scan/stats' + (qs ? '?' + qs : ''))
}
export function apiScanConfig() {
  return fetchJSON('/api/scan/config')
}
export function apiSaveScanConfig(data) {
  return postJSON('/api/scan/config', data)
}
export function apiScanKeys() {
  return fetchJSON('/api/scan/keys')
}
export function apiScanKeyAdd(platform, key) {
  return postJSON('/api/scan/keys', { platform, key })
}
export function apiScanKeyUpdate(platform, oldKey, newKey) {
  return putJSON('/api/scan/keys', { platform, old_key: oldKey, new_key: newKey })
}
export function apiScanKeyDelete(platform, key) {
  return deleteJSON('/api/scan/keys', { platform, key })
}

// ─── 持久化扫描结果 ───
export function apiPersistentGrouped() {
  return fetchJSON('/api/scan/persistent/grouped')
}
export function apiPersistentDetails(sourceIp, page, size) {
  const params = new URLSearchParams({ source_ip: sourceIp })
  if (page != null) params.set('page', page)
  if (size != null) params.set('size', size)
  return fetchJSON('/api/scan/persistent/details?' + params.toString())
}
export function apiPersistentStats() {
  return fetchJSON('/api/scan/persistent/stats')
}
export function apiPersistentManualCheck() {
  return postJSON('/api/scan/persistent/manual-check')
}
export function apiDetectionLogs(limit = 200) {
  return fetchJSON('/api/scan/detection/logs?limit=' + limit)
}
export function apiDetectionRuns(start, end, limit = 100) {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  params.set('limit', limit)
  return fetchJSON('/api/scan/detection/runs?' + params.toString())
}
export function apiDetectionRunResults(cycleId, page, size) {
  const params = new URLSearchParams()
  if (page != null) params.set('page', page)
  if (size != null) params.set('size', size)
  const qs = params.toString()
  return fetchJSON('/api/scan/detection/run/' + encodeURIComponent(cycleId) + '/results' + (qs ? '?' + qs : ''))
}


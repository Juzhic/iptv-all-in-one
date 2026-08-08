const TASK_TYPES = ['test', 'scan', 'ip_scan', 'detection']

export function normalizeTask(task, fallbackType = '') {
  if (!task || typeof task !== 'object') return null
  const taskType = task.task_type || task.type || fallbackType
  const state = task.state || (task.running ? 'running' : 'idle')
  return {
    ...task,
    task_id: task.task_id || task.id || '',
    task_type: taskType,
    state,
    active: task.active ?? ['starting', 'queued', 'running', 'stopping'].includes(String(state).toLowerCase()),
    progress: task.progress && typeof task.progress === 'object'
      ? task.progress
      : (Number.isFinite(Number(task.progress)) ? Number(task.progress) : 0),
    error: task.error || '',
  }
}

export function normalizeTasks(payload) {
  const source = payload?.data ?? payload ?? {}
  const result = Object.fromEntries(TASK_TYPES.map(type => [type, null]))
  for (const type of TASK_TYPES) result[type] = normalizeTask(source[type], type)
  if (Array.isArray(source.items)) {
    for (const item of source.items) {
      const normalized = normalizeTask(item)
      if (normalized && Object.hasOwn(result, normalized.task_type)) result[normalized.task_type] = normalized
    }
  }
  return result
}

export function taskStorageKey(type) {
  return `iptv-task-id:${type}`
}

export function readTaskId(type) {
  try { return globalThis.sessionStorage?.getItem(taskStorageKey(type)) || '' } catch (_) { return '' }
}

export function rememberTask(task, fallbackType = '') {
  const normalized = normalizeTask(task, fallbackType)
  if (!normalized?.task_id || !normalized.task_type) return normalized
  try { globalThis.sessionStorage?.setItem(taskStorageKey(normalized.task_type), normalized.task_id) } catch (_) {}
  return normalized
}

export function clearTaskId(type) {
  try { globalThis.sessionStorage?.removeItem(taskStorageKey(type)) } catch (_) {}
}

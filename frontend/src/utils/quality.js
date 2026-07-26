export function qualityTheme(status) {
  if (status === 'good') return 'success'
  if (status === 'poor') return 'warning'
  if (status === 'unreachable') return 'danger'
  return 'default'
}

export function qualityLabel(status) {
  if (status === 'good') return '好'
  if (status === 'poor') return '差'
  if (status === 'unreachable') return '不可达'
  return '待检测'
}

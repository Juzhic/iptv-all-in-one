export const qualityThemeMap = {
  excellent: 'success',
  good: 'primary',
  fair: 'warning',
  poor: 'danger',
}

export const qualityLabelMap = {
  excellent: '优秀',
  good: '良好',
  fair: '一般',
  poor: '较差',
}

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

export function formatDateTime(date) {
  return new Date(date).toLocaleString('zh-CN')
}

export function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().split('T')[0]
}

export function formatDateShort(s) {
  if (!s) return '-'
  return s.substring(0, 19)
}

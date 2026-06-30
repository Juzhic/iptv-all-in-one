export function normalizeSortInfo(sort) {
  const item = Array.isArray(sort) ? sort[0] : sort
  if (!item || typeof item !== 'object') return {}
  if (!item.sortBy || typeof item.descending !== 'boolean') return {}
  return { sortBy: item.sortBy, descending: item.descending }
}

function comparable(value) {
  if (value == null || value === '') return { empty: true, value: '' }
  const number = Number(value)
  if (Number.isFinite(number) && String(value).trim() !== '') {
    return { empty: false, numeric: true, value: number }
  }
  return { empty: false, numeric: false, value: String(value) }
}

export function compareSortValues(a, b, descending = false) {
  const va = comparable(a)
  const vb = comparable(b)
  if (va.empty && vb.empty) return 0
  if (va.empty) return 1
  if (vb.empty) return -1

  let result
  if (va.numeric && vb.numeric) {
    result = va.value - vb.value
  } else {
    result = String(va.value).localeCompare(String(vb.value))
  }
  return descending ? -result : result
}

export function sortRows(rows, sortInfo) {
  const { sortBy, descending } = normalizeSortInfo(sortInfo)
  const data = [...(rows || [])]
  if (!sortBy) return data
  return data.sort((a, b) => compareSortValues(a?.[sortBy], b?.[sortBy], descending))
}

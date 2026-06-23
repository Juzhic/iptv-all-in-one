export const platformLabelMap = {
  quake: 'Quake 360',
  hunter: 'Hunter 鹰图',
  daydaymap: 'DayDayMap',
  fofa: 'Fofa',
}

export const platformThemeMap = {
  quake: 'primary',
  hunter: 'success',
  daydaymap: 'warning',
  fofa: 'danger',
}

export function platformLabel(platform) {
  if (!platform) return '未知平台'
  const lower = platform.toLowerCase()
  for (const [key, label] of Object.entries(platformLabelMap)) {
    if (lower.includes(key)) return label
  }
  return platform
}

export function platformTheme(platform) {
  if (!platform) return 'default'
  const lower = platform.toLowerCase()
  for (const [key, theme] of Object.entries(platformThemeMap)) {
    if (lower.includes(key)) return theme
  }
  return 'default'
}

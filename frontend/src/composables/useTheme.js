import { ref, watch } from 'vue'

const THEME_KEY = 'iptv-theme'

const theme = ref('light')
let initialized = false

function readSavedTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch (_) {}
  return null
}

function getPreferredTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function init() {
  if (!initialized) {
    theme.value = readSavedTheme() || getPreferredTheme()
    initialized = true
  }
  apply()
}

function apply() {
  if (typeof document === 'undefined') return

  const isDark = theme.value === 'dark'
  const root = document.documentElement

  // TDesign 主题变量依赖 :root.dark / theme-mode='dark'
  root.classList.toggle('dark', isDark)
  root.setAttribute('theme-mode', theme.value)
  root.style.colorScheme = theme.value

  if (document.body) {
    document.body.classList.toggle('t-dark', isDark)
  }

  try { localStorage.setItem(THEME_KEY, theme.value) } catch (_) {}
}

function setTheme(value) {
  theme.value = value === 'dark' ? 'dark' : 'light'
}

function toggle() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

watch(theme, apply)

export function useTheme() {
  return { theme, setTheme, toggle, init }
}

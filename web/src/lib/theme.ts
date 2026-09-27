// Day and night. Night is the brooder lamp in the dark; day is morning light on straw.

export type Theme = 'day' | 'night'

function stored(): Theme | null {
  try {
    const v = localStorage.getItem('coop-theme')
    return v === 'day' || v === 'night' ? v : null
  } catch {
    return null
  }
}

export function currentTheme(): Theme {
  return stored() ?? (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'day' : 'night')
}

export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'day' ? '#fbf6ec' : '#0c0a08')
}

export function setTheme(t: Theme) {
  try {
    localStorage.setItem('coop-theme', t)
  } catch {}
  applyTheme(t)
}

import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import type { Accent } from '@/stores/themeStore'

/**
 * The design tokens from index.css resolved to plain #rrggbb, for the
 * canvas/WebGL effect libraries (thinking-orbs, bot-avatars, …) that cannot
 * read CSS variables or oklch(). Published by ThemeProvider after it writes
 * data-theme / data-accent, so it always matches the in-app theme.
 */
export interface FxPalette {
  theme: 'light' | 'dark'
  accent: Accent
  acc: string
  ink: string
  ink3: string
  warn: string
  ok: string
  surface: string
}

export const useFxPalette = create<FxPalette>(() => ({
  theme: 'light',
  accent: 'cobalt',
  acc: '#2c4fbd',
  ink: '#1b1a17',
  ink3: '#7d7b77',
  warn: '#d0891c',
  ok: '#2f8a52',
  surface: '#fbfaf7',
}))

let probe: CanvasRenderingContext2D | null | undefined

/** Resolve a CSS custom property to the opaque colour it paints over --bg. */
function resolveCssColor(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = styles.getPropertyValue(name).trim()
  if (!value) return fallback
  if (probe === undefined) {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    probe = canvas.getContext('2d', { willReadFrequently: true })
  }
  if (!probe) return fallback
  // Composite over the page background so translucent tokens (--ink3) come
  // out as the colour the reader actually sees.
  probe.fillStyle = styles.getPropertyValue('--bg').trim() || '#fff'
  probe.fillRect(0, 0, 1, 1)
  probe.fillStyle = value
  probe.fillRect(0, 0, 1, 1)
  const [r, g, b] = probe.getImageData(0, 0, 1, 1).data
  return `#${[r, g, b].map((n) => n.toString(16).padStart(2, '0')).join('')}`
}

export function publishFxPalette(theme: FxPalette['theme'], accent: Accent) {
  const styles = getComputedStyle(document.documentElement)
  const prev = useFxPalette.getState()
  useFxPalette.setState({
    theme,
    accent,
    acc: resolveCssColor(styles, '--acc', prev.acc),
    ink: resolveCssColor(styles, '--ink', prev.ink),
    ink3: resolveCssColor(styles, '--ink3', prev.ink3),
    warn: resolveCssColor(styles, '--warn', prev.warn),
    ok: resolveCssColor(styles, '--ok', prev.ok),
    surface: resolveCssColor(styles, '--surface', prev.surface),
  })
}

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

function subscribeReducedMotion(onChange: () => void) {
  const query = window.matchMedia(REDUCED_MOTION)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

export function useReducedMotion() {
  return useSyncExternalStore(subscribeReducedMotion, () => window.matchMedia(REDUCED_MOTION).matches, () => false)
}

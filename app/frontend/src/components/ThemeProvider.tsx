import { useLayoutEffect } from 'react'
import { publishFxPalette } from '@/lib/fxPalette'
import { useThemeStore } from '@/stores/themeStore'

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)
  const accent = useThemeStore((s) => s.accentOverride ?? s.accent)

  useLayoutEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.dataset.accent = accent
    // Effects drawn on canvas/WebGL need the tokens as real colours.
    publishFxPalette(theme, accent)
  }, [theme, accent])

  return <>{children}</>
}

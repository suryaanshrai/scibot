import { useEffect } from 'react'
import { useThemeStore } from '@/stores/themeStore'

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)
  const accent = useThemeStore((s) => s.accentOverride ?? s.accent)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.dataset.accent = accent
  }, [theme, accent])

  return <>{children}</>
}

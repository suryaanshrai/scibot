import { useEffect } from 'react'
import { useThemeStore } from '@/stores/themeStore'

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
  }, [theme])

  return <>{children}</>
}

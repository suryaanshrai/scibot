import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark'
export type Accent = 'cobalt' | 'teal' | 'vermilion'

interface ThemeState {
  theme: Theme
  accent: Accent
  /** Temporary accent for a page (e.g. the landing page); not persisted. */
  accentOverride: Accent | null
  setTheme: (t: Theme) => void
  setAccent: (a: Accent) => void
  setAccentOverride: (a: Accent | null) => void
  toggle: () => void
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      accent: 'cobalt',
      accentOverride: null,
      setTheme: (theme) => set({ theme }),
      setAccent: (accent) => set({ accent }),
      setAccentOverride: (accentOverride) => set({ accentOverride }),
      toggle: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
    }),
    {
      name: 'scibot-theme',
      partialize: ({ theme, accent }) => ({ theme, accent }),
    }
  )
)

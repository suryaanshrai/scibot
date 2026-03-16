import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { ConfigOptions, UserConfig } from '@/types/config'
import { EMPTY_CONFIG, EMPTY_CONFIG_OPTIONS } from '@/types/config'

interface AuthState {
  username: string | null
  authHeader: string | null
  globalConfig: UserConfig
  configOptions: ConfigOptions
  isAuthenticated: boolean

  login: (username: string, authHeader: string, config: UserConfig, options: ConfigOptions) => void
  logout: () => void
  setConfigOptions: (options: ConfigOptions) => void
  updateGlobalConfig: (config: UserConfig) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      username: null,
      authHeader: null,
      globalConfig: EMPTY_CONFIG,
      configOptions: EMPTY_CONFIG_OPTIONS,
      isAuthenticated: false,

      login: (username, authHeader, config, options) =>
        set({ username, authHeader, globalConfig: config, configOptions: options, isAuthenticated: true }),

      logout: () =>
        set({
          username: null,
          authHeader: null,
          isAuthenticated: false,
          globalConfig: EMPTY_CONFIG,
          configOptions: EMPTY_CONFIG_OPTIONS,
        }),

      setConfigOptions: (configOptions) => set({ configOptions }),

      updateGlobalConfig: (globalConfig) => set({ globalConfig }),
    }),
    {
      name: 'scibot-auth',
      storage: createJSONStorage(() => sessionStorage),
    }
  )
)

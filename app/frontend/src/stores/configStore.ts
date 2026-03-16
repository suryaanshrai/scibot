import { create } from 'zustand'
import type { UserConfig } from '@/types/config'

interface ConfigState {
  chatConfigs: Record<string, Partial<UserConfig>>
  pendingChatConfig: Partial<UserConfig>

  getChatConfig: (chatId: string) => Partial<UserConfig>
  setChatConfig: (chatId: string, config: Partial<UserConfig>) => void
  updateChatConfig: (chatId: string, updates: Partial<UserConfig>) => void
  resetChatConfig: (chatId: string) => void
  setPendingChatConfig: (config: Partial<UserConfig>) => void
  resetPendingChatConfig: () => void
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  chatConfigs: {},
  pendingChatConfig: {},

  getChatConfig: (chatId) => get().chatConfigs[chatId] ?? {},

  setChatConfig: (chatId, config) =>
    set((s) => ({ chatConfigs: { ...s.chatConfigs, [chatId]: config } })),

  updateChatConfig: (chatId, updates) =>
    set((s) => ({
      chatConfigs: { ...s.chatConfigs, [chatId]: { ...s.chatConfigs[chatId], ...updates } },
    })),

  resetChatConfig: (chatId) =>
    set((s) => {
      const next = { ...s.chatConfigs }
      delete next[chatId]
      return { chatConfigs: next }
    }),

  setPendingChatConfig: (config) => set({ pendingChatConfig: config }),

  resetPendingChatConfig: () => set({ pendingChatConfig: {} }),
}))

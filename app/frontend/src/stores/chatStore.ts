import { create } from 'zustand'
import type { ChatMeta, Message } from '@/types/chat'
import type { SourceEntry } from '@/types/sources'

interface ChatState {
  chats: ChatMeta[]
  messages: Record<string, Message[]>
  currentChatId: string | null
  chatsLoaded: boolean
  pendingSources: SourceEntry[]             // sources queued before a chat starts

  setCurrentChat: (chatId: string | null) => void
  setChatsLoaded: (loaded: boolean) => void
  setChats: (chats: ChatMeta[]) => void
  upsertChat: (chat: ChatMeta) => void
  replaceMessages: (chatId: string, messages: Message[]) => void
  createChat: (chat: ChatMeta) => void
  deleteChat: (chatId: string) => void
  updateChatTitle: (chatId: string, title: string) => void
  clearMessages: (chatId: string) => void

  addMessage: (msg: Message) => void
  appendToken: (chatId: string, msgId: string, token: string) => void
  finalizeMessage: (chatId: string, msgId: string, content: string) => void
  setMessageSources: (chatId: string, msgId: string, sources: Message['sources']) => void
  addToolCall: (chatId: string, msgId: string, tool: string) => void
  resolveToolCalls: (chatId: string, msgId: string) => void

  setPendingSources: (sources: SourceEntry[]) => void
  clearPendingSources: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  chats: [],
  messages: {},
  currentChatId: null,
  chatsLoaded: false,
  pendingSources: [],

  setCurrentChat: (chatId) => set({ currentChatId: chatId }),
  setChatsLoaded: (chatsLoaded) => set({ chatsLoaded }),
  setChats: (chats) => set({ chats, chatsLoaded: true }),
  upsertChat: (chat) =>
    set((s) => {
      const existing = s.chats.find((c) => c.chatId === chat.chatId)
      const chats = existing
        ? s.chats.map((c) => (c.chatId === chat.chatId ? { ...c, ...chat } : c))
        : [chat, ...s.chats]
      return { chats }
    }),
  replaceMessages: (chatId, messages) =>
    set((s) => ({ messages: { ...s.messages, [chatId]: messages } })),

  createChat: (chat) =>
    set((s) => ({
      chats: [chat, ...s.chats.filter((c) => c.chatId !== chat.chatId)],
      messages: { ...s.messages, [chat.chatId]: s.messages[chat.chatId] ?? [] },
      currentChatId: chat.chatId,
    })),

  deleteChat: (chatId) =>
    set((s) => {
      const chats = s.chats.filter((c) => c.chatId !== chatId)
      const messages = { ...s.messages }
      delete messages[chatId]
      return { chats, messages, currentChatId: s.currentChatId === chatId ? null : s.currentChatId }
    }),

  updateChatTitle: (chatId, title) =>
    set((s) => ({
      chats: s.chats.map((c) => (c.chatId === chatId ? { ...c, title, updatedAt: new Date().toISOString() } : c)),
    })),

  clearMessages: (chatId) =>
    set((s) => ({ messages: { ...s.messages, [chatId]: [] } })),

  addMessage: (msg) =>
    set((s) => {
      const existing = s.messages[msg.chatId] ?? []
      const chats = s.chats.map((c) =>
        c.chatId === msg.chatId ? { ...c, updatedAt: new Date().toISOString() } : c
      )
      return { messages: { ...s.messages, [msg.chatId]: [...existing, msg] }, chats }
    }),

  appendToken: (chatId, msgId, token) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [chatId]: (s.messages[chatId] ?? []).map((m) =>
          m.id === msgId ? { ...m, content: m.content + token, streaming: true } : m
        ),
      },
    })),

  finalizeMessage: (chatId, msgId, content) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [chatId]: (s.messages[chatId] ?? []).map((m) =>
          m.id === msgId ? { ...m, content, streaming: false } : m
        ),
      },
    })),

  setMessageSources: (chatId, msgId, sources) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [chatId]: (s.messages[chatId] ?? []).map((m) =>
          m.id === msgId ? { ...m, sources } : m
        ),
      },
    })),

  addToolCall: (chatId, msgId, tool) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [chatId]: (s.messages[chatId] ?? []).map((m) =>
          m.id === msgId
            ? { ...m, toolCalls: [...(m.toolCalls ?? []), { name: tool, status: 'running' }] }
            : m
        ),
      },
    })),

  resolveToolCalls: (chatId, msgId) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [chatId]: (s.messages[chatId] ?? []).map((m) =>
          m.id === msgId
            ? {
                ...m,
                toolCalls: (m.toolCalls ?? []).map((t) => ({ ...t, status: 'done' })),
              }
            : m
        ),
      },
    })),

  setPendingSources: (sources) => set({ pendingSources: sources }),
  clearPendingSources: () => set({ pendingSources: [] }),
}))

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Bot, Loader2, Plus, Rocket, SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SourceForm } from '@/components/sources/SourceForm'
import { MessageList } from '@/components/chat/MessageList'
import { ChatInput } from '@/components/chat/ChatInput'
import { ChatHeader } from '@/components/chat/ChatHeader'
import { CollectionSourcesRail } from '@/components/chat/CollectionSourcesRail'
import { NewChatSettingsSheet } from '@/components/chat/NewChatSettingsSheet'
import { SourcesPanel } from '@/components/chat/SourcesPanel'
import { HITLDialog } from '@/components/chat/HITLDialog'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import { useConfigStore } from '@/stores/configStore'
import { addSourcesToChat, createChat as createChatRequest, getChatHistory, getCollectionDetail, resumeChat, sendMessage } from '@/lib/api'
import { generateId } from '@/lib/utils'
import type { CollectionDetail } from '@/types/collections'
import type { SourceEntry } from '@/types/sources'
import type { HITLPayload, Message } from '@/types/chat'

export function ChatPage() {
  const { chatId } = useParams<{ chatId?: string }>()
  const navigate = useNavigate()
  const { username, authHeader, globalConfig } = useAuthStore()
  const { chatConfigs, getChatConfig, setChatConfig, pendingChatConfig, resetPendingChatConfig } = useConfigStore()

  const {
    chats, messages: allMessages, chatsLoaded, createChat, addMessage,
    appendToken, finalizeMessage, addToolCall, resolveToolCalls, replaceMessages,
    pendingSources, setPendingSources, clearPendingSources, upsertChat, setMessageSources,
  } = useChatStore()

  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [localSources, setLocalSources] = useState<SourceEntry[]>([...pendingSources])
  const [sending, setSending] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)
  const [hitlPayload, setHitlPayload] = useState<HITLPayload | null>(null)
  const [newChatSettingsOpen, setNewChatSettingsOpen] = useState(false)
  const [collectionRailOpen, setCollectionRailOpen] = useState(true)
  const [collectionDetail, setCollectionDetail] = useState<CollectionDetail | null>(null)
  const [collectionLoading, setCollectionLoading] = useState(false)
  const [collectionError, setCollectionError] = useState<string | null>(null)

  const auth = useMemo(() => {
    if (!username || !authHeader) return null
    return { username, authHeader }
  }, [authHeader, username])

  // Sync localSources from pendingSources when navigating to /chat (new chat)
  useEffect(() => {
    if (!chatId) {
      setLocalSources([...pendingSources])
    }
  }, [chatId, pendingSources])

  const messages = chatId ? (allMessages[chatId] ?? []) : []
  const isNewChat = !chatId
  const activeChat = chatId ? chats.find((c) => c.chatId === chatId) : null
  const activeCollectionName = activeChat?.collectionName?.trim() ?? ''
  const hasCachedHistory = Boolean(chatId && allMessages[chatId])
  const hasCachedConfig = Boolean(chatId && Object.prototype.hasOwnProperty.call(chatConfigs, chatId))
  const pendingLLM = pendingChatConfig.llm?.model ?? globalConfig.llm.model
  const pendingProvider = pendingChatConfig.llm?.provider ?? globalConfig.llm.provider

  useEffect(() => {
    if (!auth || !chatId) return
    if (hasCachedHistory && hasCachedConfig) return
    let cancelled = false
    void getChatHistory(auth, chatId)
      .then((history) => {
        if (cancelled) return
        upsertChat(history.chat)
        replaceMessages(chatId, history.messages)
        setChatConfig(chatId, history.chatConfig)
      })
      .catch((error) => {
        if (cancelled) return
        console.error(error)
        setPageError(error instanceof Error ? error.message : 'Failed to load chat')
        if (chatsLoaded) navigate('/chat', { replace: true })
      })
    return () => {
      cancelled = true
    }
  }, [
    auth,
    chatId,
    chatsLoaded,
    hasCachedConfig,
    hasCachedHistory,
    navigate,
    replaceMessages,
    setChatConfig,
    upsertChat,
  ])

  useEffect(() => {
    if (!chatId || !auth) {
      setCollectionDetail(null)
      setCollectionError(null)
      setCollectionLoading(false)
      return
    }

    if (!activeCollectionName) {
      setCollectionDetail(null)
      setCollectionError(null)
      setCollectionLoading(false)
      return
    }

    let cancelled = false
    setCollectionLoading(true)
    setCollectionError(null)

    void getCollectionDetail(auth, activeCollectionName)
      .then((detail) => {
        if (cancelled) return
        setCollectionDetail(detail)
      })
      .catch((error) => {
        if (cancelled) return
        console.error(error)
        setCollectionDetail(null)
        setCollectionError(error instanceof Error ? error.message : 'Failed to load attached sources')
      })
      .finally(() => {
        if (cancelled) return
        setCollectionLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [activeCollectionName, auth, chatId])

  const handleStartChat = useCallback(async () => {
    if (!auth) return
    setBusy(true)
    setPageError(null)
    try {
      const chat = await createChatRequest(auth, { sources: localSources, configOverride: pendingChatConfig })
      createChat(chat)
      if (Object.keys(pendingChatConfig).length) {
        setChatConfig(chat.chatId, pendingChatConfig)
      }
      clearPendingSources()
      resetPendingChatConfig()
      setLocalSources([])
      navigate(`/chat/${chat.chatId}`)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Failed to create chat')
    } finally {
      setBusy(false)
    }
  }, [auth, clearPendingSources, createChat, localSources, navigate, pendingChatConfig, resetPendingChatConfig, setChatConfig])

  const handleSend = useCallback((query: string) => {
    if (!chatId || !auth) return
    setSending(true)
    setPageError(null)

    const userMsgId = generateId()
    const aiMsgId = generateId()

    const userMsg: Message = {
      id: userMsgId,
      chatId,
      role: 'user',
      content: query,
      createdAt: new Date().toISOString(),
    }

    const aiMsg: Message = {
      id: aiMsgId,
      chatId,
      role: 'assistant',
      content: '',
      toolCalls: [],
      streaming: true,
      createdAt: new Date().toISOString(),
    }

    addMessage(userMsg)
    addMessage(aiMsg)

    sendMessage(auth, chatId, query, getChatConfig(chatId), {
      onToken: (token) => appendToken(chatId, aiMsgId, token),
      onToolStart: (tool) => addToolCall(chatId, aiMsgId, tool),
      onSources: (sources) => setMessageSources(chatId, aiMsgId, sources),
      onInterrupt: (payload, content, sources) => {
        finalizeMessage(chatId, aiMsgId, content)
        if (sources) setMessageSources(chatId, aiMsgId, sources)
        resolveToolCalls(chatId, aiMsgId)
        setHitlPayload(payload)
        setSending(false)
      },
      onDone: (content, sources) => {
        finalizeMessage(chatId, aiMsgId, content)
        if (sources) setMessageSources(chatId, aiMsgId, sources)
        resolveToolCalls(chatId, aiMsgId)
        setSending(false)
        clearPendingSources()
      },
      onError: (err) => {
        console.error(err)
        finalizeMessage(chatId, aiMsgId, `Error: ${err.message}`)
        resolveToolCalls(chatId, aiMsgId)
        setPageError(err.message)
        setSending(false)
      },
    })
  }, [auth, chatId, addMessage, appendToken, addToolCall, clearPendingSources, finalizeMessage, getChatConfig, resolveToolCalls, setMessageSources])

  const handleResume = useCallback((response: boolean) => {
    if (!chatId || !auth || !hitlPayload) return

    setSending(true)
    setHitlPayload(null)

    const aiMsgId = generateId()
    const aiMsg: Message = {
      id: aiMsgId,
      chatId,
      role: 'assistant',
      content: '',
      toolCalls: [],
      streaming: true,
      createdAt: new Date().toISOString(),
    }

    addMessage(aiMsg)

    resumeChat(auth, chatId, response, {
      onToken: (token) => appendToken(chatId, aiMsgId, token),
      onToolStart: (tool) => addToolCall(chatId, aiMsgId, tool),
      onSources: (sources) => setMessageSources(chatId, aiMsgId, sources),
      onInterrupt: (payload, content, sources) => {
        finalizeMessage(chatId, aiMsgId, content)
        if (sources) setMessageSources(chatId, aiMsgId, sources)
        resolveToolCalls(chatId, aiMsgId)
        setHitlPayload(payload)
        setSending(false)
      },
      onDone: (content, sources) => {
        finalizeMessage(chatId, aiMsgId, content)
        if (sources) setMessageSources(chatId, aiMsgId, sources)
        resolveToolCalls(chatId, aiMsgId)
        setSending(false)
      },
      onError: (err) => {
        console.error(err)
        finalizeMessage(chatId, aiMsgId, `Error: ${err.message}`)
        resolveToolCalls(chatId, aiMsgId)
        setPageError(err.message)
        setSending(false)
      },
    })
  }, [auth, chatId, hitlPayload, addMessage, appendToken, addToolCall, finalizeMessage, resolveToolCalls, setMessageSources])

  return (
    <div className="flex flex-col h-full">
      {/* Active chat header */}
      {chatId && <ChatHeader chatId={chatId} />}

      {/* Empty state — new chat */}
      {isNewChat && (
        <>
        <div className="flex items-center h-14 border-b px-4 gap-3 bg-background">
          <div className="flex-1 min-w-0">
            <span className="font-medium text-sm truncate">New chat</span>
          </div>

          <div className="hidden sm:flex items-center">
            <span className="inline-flex items-center rounded-md bg-secondary px-2 py-1 text-[11px] text-secondary-foreground">
              {pendingProvider}/{pendingLLM}
            </span>
          </div>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={() => setNewChatSettingsOpen(true)}
            title="Chat settings"
          >
            <SlidersHorizontal size={16} />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto flex min-h-full w-full max-w-xl items-center justify-center py-6">
            <div className="w-full space-y-6">
            <div className="text-center space-y-2">
              <Bot size={40} className="mx-auto text-primary" />
              <h2 className="text-xl font-semibold">New research chat</h2>
              <p className="text-sm text-muted-foreground">
                Optionally add sources to ground the conversation, then start chatting.
              </p>
            </div>

            <div className="rounded-xl border bg-card p-4">
              <SourceForm
                sources={localSources}
                onChange={setLocalSources}
                onSubmit={handleStartChat}
                submitLabel="Start Chat"
                submitDisabled={busy}
                submitLoading={busy}
                submitLoadingLabel="Starting chat..."
              />
            </div>

            {busy && (
              <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" />
                <span>Preparing sources and creating the chat. Large ingests can take a minute.</span>
              </div>
            )}

            {pageError && <p className="text-sm text-destructive text-center">{pageError}</p>}

            <div className="flex justify-center">
              <Button
                variant="link"
                size="sm"
                className="text-muted-foreground"
                disabled={busy}
                onClick={async () => {
                  if (!auth) return
                  setBusy(true)
                  setPageError(null)
                  try {
                    const chat = await createChatRequest(auth, { configOverride: pendingChatConfig })
                    createChat(chat)
                    if (Object.keys(pendingChatConfig).length) {
                      setChatConfig(chat.chatId, pendingChatConfig)
                    }
                    clearPendingSources()
                    resetPendingChatConfig()
                    setLocalSources([])
                    navigate(`/chat/${chat.chatId}`)
                  } catch (error) {
                    setPageError(error instanceof Error ? error.message : 'Failed to create chat')
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                <Plus size={14} className="mr-1" />
                Skip sources and start chatting
              </Button>
            </div>
            </div>
          </div>
        </div>
        <NewChatSettingsSheet open={newChatSettingsOpen} onOpenChange={setNewChatSettingsOpen} />
        </>
      )}

      {/* Active chat messages */}
      {chatId && (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="flex min-h-0 flex-1 flex-col">
            {messages.length === 0 ? (
              <div className="flex flex-1 items-center justify-center flex-col gap-3 text-muted-foreground">
                <Rocket size={32} />
                <p className="text-sm">Send a message to begin</p>
                {pageError && <p className="text-sm text-destructive">{pageError}</p>}
              </div>
            ) : (
              <MessageList messages={messages} />
            )}

            <ChatInput
              onSend={handleSend}
              onToggleSources={() => setSourcesOpen(true)}
              disabled={busy}
              sending={sending}
            />
          </div>

          <CollectionSourcesRail
            collection={collectionDetail}
            loading={collectionLoading}
            error={collectionError}
            open={collectionRailOpen}
            onToggle={() => setCollectionRailOpen((open) => !open)}
          />
        </div>
      )}

      {/* Sources panel (slide-in from right) */}
      <SourcesPanel
        open={sourcesOpen}
        onOpenChange={setSourcesOpen}
        sources={localSources}
        onSourcesChange={setLocalSources}
        onAddToChat={async () => {
          if (!auth) return
          if (!chatId || !activeChat) {
            setPendingSources(localSources)
            setSourcesOpen(false)
            return
          }

          setBusy(true)
          setPageError(null)
          try {
            const result = await addSourcesToChat(auth, activeChat, localSources, getChatConfig(chatId))
            upsertChat(result.chat)
            if (result.configOverride) {
              setChatConfig(chatId, result.configOverride)
            }
            setLocalSources([])
            clearPendingSources()
            setSourcesOpen(false)
          } catch (error) {
            setPageError(error instanceof Error ? error.message : 'Failed to add sources')
          } finally {
            setBusy(false)
          }
        }}
        busy={busy}
        mode={chatId ? 'add' : 'new'}
      />

      {/* HITL approval dialog */}
      <HITLDialog
        payload={hitlPayload}
        onApprove={() => handleResume(true)}
        onDeny={() => handleResume(false)}
      />
    </div>
  )
}

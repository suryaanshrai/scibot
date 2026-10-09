import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChatHeader } from '@/components/chat/ChatHeader'
import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList } from '@/components/chat/MessageList'
import { SourcesRail } from '@/components/chat/SourcesRail'
import type { RailTab } from '@/components/chat/SourcesRail'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import { useConfigStore } from '@/stores/configStore'
import {
  addSourcesToChat, clearChatMessages, getChatHistory, getCollectionDetail, resumeChat, sendMessage, updateChatTitle,
} from '@/lib/api'
import type { StreamHandlers } from '@/lib/api'
import { citedSources, normalizeHitl, trace } from '@/lib/answer'
import { generateId } from '@/lib/utils'
import type { CollectionDetail } from '@/types/collections'
import type { Message } from '@/types/chat'
import type { SourceEntry } from '@/types/sources'

const RAIL_BREAKPOINT = 1200
const OVERLAY_BREAKPOINT = 768

function useViewportWidth() {
  const [width, setWidth] = useState(() => window.innerWidth)
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return width
}

function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(900)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

export function ChatPage() {
  const { chatId = '' } = useParams<{ chatId: string }>()
  const navigate = useNavigate()
  const { username, authHeader, globalConfig } = useAuthStore()
  const { chatConfigs, getChatConfig, setChatConfig } = useConfigStore()
  const {
    chats, messages: allMessages, chatsLoaded, addMessage, appendToken, finalizeMessage, replaceMessages,
    upsertChat, setMessageSources, patchMessage, clearMessages, updateChatTitle: setLocalTitle,
  } = useChatStore()

  const viewport = useViewportWidth()
  const overlay = viewport < OVERLAY_BREAKPOINT
  const [railOpen, setRailOpen] = useState(() => window.innerWidth >= RAIL_BREAKPOINT)
  const [railTab, setRailTab] = useState<RailTab>('cited')
  const [addOpen, setAddOpen] = useState(false)
  const [hoverRef, setHoverRef] = useState<number | null>(null)
  const [pageError, setPageError] = useState<string | null>(null)
  const [ingesting, setIngesting] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [collectionDetail, setCollectionDetail] = useState<CollectionDetail | null>(null)
  const [collectionLoading, setCollectionLoading] = useState(false)
  const [collectionError, setCollectionError] = useState<string | null>(null)
  const [collectionVersion, setCollectionVersion] = useState(0)
  const [columnRef, columnWidth] = useElementWidth<HTMLDivElement>()
  const runRef = useRef<string | null>(null)

  // The rail follows the viewport across the 1200px breakpoint, as in the design.
  const wide = viewport >= RAIL_BREAKPOINT
  const lastWide = useRef(wide)
  useEffect(() => {
    if (lastWide.current !== wide) {
      lastWide.current = wide
      setRailOpen(wide)
    }
  }, [wide])

  const auth = useMemo(() => (username && authHeader ? { username, authHeader } : null), [authHeader, username])
  const messages = useMemo(() => allMessages[chatId] ?? [], [allMessages, chatId])
  const activeChat = chats.find((c) => c.chatId === chatId) ?? null
  const collectionName = activeChat?.collectionName?.trim() || null
  const hasCachedHistory = Boolean(allMessages[chatId])
  const hasCachedConfig = Object.prototype.hasOwnProperty.call(chatConfigs, chatId)
  const chatOverride = getChatConfig(chatId)
  const modelLabel = chatOverride.llm?.model || globalConfig.llm.model || 'default model'
  const running = messages.some((m) => m.runStatus === 'running' || m.runStatus === 'writing')
  const waiting = messages.some((m) => m.runStatus === 'waiting')

  useEffect(() => {
    setHoverRef(null)
    setPageError(null)
    setAddOpen(false)
    setRailTab('cited')
  }, [chatId])

  useEffect(() => {
    if (!auth || !chatId || (hasCachedHistory && hasCachedConfig)) return
    let cancelled = false
    void getChatHistory(auth, chatId)
      .then((history) => {
        if (cancelled) return
        upsertChat(history.chat)
        if (!hasCachedHistory) replaceMessages(chatId, history.messages)
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
  }, [auth, chatId, chatsLoaded, hasCachedConfig, hasCachedHistory, navigate, replaceMessages, setChatConfig, upsertChat])

  useEffect(() => {
    if (!auth || !collectionName) {
      setCollectionDetail(null)
      setCollectionError(null)
      setCollectionLoading(false)
      return
    }
    let cancelled = false
    setCollectionLoading(true)
    setCollectionError(null)
    void getCollectionDetail(auth, collectionName)
      .then((detail) => !cancelled && setCollectionDetail(detail))
      .catch((error) => {
        if (cancelled) return
        setCollectionDetail(null)
        setCollectionError(error instanceof Error ? error.message : 'Failed to load attached sources')
      })
      .finally(() => !cancelled && setCollectionLoading(false))
    return () => {
      cancelled = true
    }
  }, [auth, collectionName, collectionVersion])

  const latestWithSources = useMemo(
    () => [...messages].reverse().find((m) => m.role === 'assistant' && m.sources?.some((s) => !s.filtered)),
    [messages]
  )
  const cited = useMemo(() => citedSources(latestWithSources), [latestWithSources])

  const streamHandlers = useCallback(
    (msgId: string): StreamHandlers => {
      const patch = (fn: (m: Message) => Message) => patchMessage(chatId, msgId, fn)
      return {
        onToken: (token) => {
          patch(trace.token())
          appendToken(chatId, msgId, token)
        },
        onToolStart: (tool) => patch(trace.tool(tool)),
        onSourceCount: (count) => patch(trace.sources(count)),
        onSources: (sources) => setMessageSources(chatId, msgId, sources),
        onStage: (stage) => {
          if (stage === 'checker') patch(trace.checker())
        },
        onInterrupt: (payload, content, sources) => {
          finalizeMessage(chatId, msgId, content)
          if (sources) setMessageSources(chatId, msgId, sources)
          patch(trace.interrupt(normalizeHitl(payload)))
          runRef.current = msgId
        },
        onDone: (content, sources) => {
          finalizeMessage(chatId, msgId, content)
          if (sources) setMessageSources(chatId, msgId, sources)
          patch(trace.done())
          if (sources?.some((s) => !s.filtered)) setRailTab('cited')
        },
        onError: (err) => {
          console.error(err)
          patch((m) => ({ ...trace.fail()(m), content: m.content || `Error: ${err.message}` }))
          setPageError(err.message)
        },
      }
    },
    [appendToken, chatId, finalizeMessage, patchMessage, setMessageSources]
  )

  const handleSend = useCallback(
    (query: string) => {
      if (!chatId || !auth) return
      setPageError(null)
      const aiMsgId = generateId()
      const now = new Date().toISOString()
      addMessage({ id: generateId(), chatId, role: 'user', content: query, createdAt: now })
      addMessage({ id: aiMsgId, chatId, role: 'assistant', content: '', streaming: true, createdAt: now, ...trace.start() })

      if (activeChat && (activeChat.title === 'Untitled chat' || !activeChat.title.trim())) {
        const title = query.replace(/\s+/g, ' ').slice(0, 60)
        setLocalTitle(chatId, title)
        void updateChatTitle(auth, chatId, title).catch(console.error)
      }

      sendMessage(auth, chatId, query, getChatConfig(chatId), streamHandlers(aiMsgId))
    },
    [activeChat, addMessage, auth, chatId, getChatConfig, setLocalTitle, streamHandlers]
  )

  const handleResume = useCallback(
    (approved: boolean) => {
      const msgId = runRef.current
      if (!chatId || !auth || !msgId) return
      runRef.current = null
      patchMessage(chatId, msgId, trace.resume(approved))
      const handlers = streamHandlers(msgId)
      let resumedContent = ''
      resumeChat(auth, chatId, approved, {
        ...handlers,
        onToken: (token) => {
          // The resumed run streams a fresh answer into the same message.
          if (!resumedContent) finalizeMessage(chatId, msgId, '')
          resumedContent += token
          handlers.onToken(token)
        },
        onDone: (content, sources) => {
          if (approved) setCollectionVersion((v) => v + 1)
          handlers.onDone(content, sources)
        },
      })
    },
    [auth, chatId, finalizeMessage, patchMessage, streamHandlers]
  )

  const handleAddSources = useCallback(
    async (sources: SourceEntry[]) => {
      if (!auth || !activeChat) return false
      setIngesting(true)
      setAddError(null)
      try {
        const result = await addSourcesToChat(auth, activeChat, sources, getChatConfig(chatId))
        upsertChat(result.chat)
        if (result.configOverride) setChatConfig(chatId, result.configOverride)
        setCollectionVersion((v) => v + 1)
        setAddOpen(false)
        return true
      } catch (error) {
        setAddError(error instanceof Error ? error.message : 'Failed to add sources')
        return false
      } finally {
        setIngesting(false)
      }
    },
    [activeChat, auth, chatId, getChatConfig, setChatConfig, upsertChat]
  )

  const handleClear = useCallback(async () => {
    if (!auth) return
    try {
      await clearChatMessages(auth, chatId)
      clearMessages(chatId)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Failed to clear history')
    }
  }, [auth, chatId, clearMessages])

  const openCitation = useCallback((ref: number) => {
    setRailOpen(true)
    setRailTab('cited')
    setHoverRef(ref)
  }, [])

  const sourceCount = useMemo(
    () => (collectionDetail ? Object.values(collectionDetail.sources).reduce((n, list) => n + (list?.length ?? 0), 0) : 0),
    [collectionDetail]
  )
  const emptyHint = collectionName
    ? `Grounded in ${sourceCount || 'the'} attached source${sourceCount === 1 ? '' : 's'}. Answers cite excerpts and are reviewed by the Checker before you see them.`
    : 'No sources attached. The agents can still search arXiv, PubMed and whitelisted sites.'

  const tight = columnWidth < 620

  return (
    <>
      <ChatHeader
        title={activeChat?.title ?? 'Chat'}
        modelLabel={modelLabel}
        railOpen={railOpen}
        onToggleRail={() => setRailOpen((open) => !open)}
        onOpenSettings={() => navigate(`/settings?scope=chat&chat=${encodeURIComponent(chatId)}`)}
        onClear={handleClear}
      />
      <div className="flex min-h-0 flex-1">
        <div ref={columnRef} className="flex min-w-0 flex-1 flex-col">
          <MessageList
            messages={messages}
            emptyHint={emptyHint}
            hoverRef={hoverRef}
            onHoverRef={setHoverRef}
            onCite={openCitation}
            onApprove={() => handleResume(true)}
            onDeny={() => handleResume(false)}
            tight={tight}
          />
          {pageError && (
            <p className="mx-auto mb-2 w-full max-w-[812px] px-11 text-[12.5px] text-warn max-sm:px-4">{pageError}</p>
          )}
          <ChatInput
            onSend={handleSend}
            onOpenSources={() => {
              setRailOpen(true)
              setRailTab('collection')
              setAddOpen(true)
            }}
            disabled={running || waiting || !auth}
            tight={tight}
          />
        </div>
        {railOpen && (
          <SourcesRail
            tab={railTab}
            onTab={setRailTab}
            cited={cited}
            hoverRef={hoverRef}
            onHoverRef={setHoverRef}
            collectionName={collectionName}
            collection={collectionDetail}
            collectionLoading={collectionLoading}
            collectionError={collectionError}
            ingesting={ingesting}
            addError={addError}
            onAddSources={handleAddSources}
            addOpen={addOpen}
            onAddOpen={setAddOpen}
            overlay={overlay}
            onClose={() => setRailOpen(false)}
          />
        )}
      </div>
    </>
  )
}

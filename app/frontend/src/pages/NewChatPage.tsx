import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ModelPill, Spinner } from '@/components/sb/primitives'
import { SourceStager } from '@/components/sources/SourceStager'
import { createChat as createChatRequest } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useConfigStore } from '@/stores/configStore'

export function NewChatPage() {
  const navigate = useNavigate()
  const { username, authHeader, globalConfig } = useAuthStore()
  const { createChat, pendingSources, setPendingSources, clearPendingSources } = useChatStore()
  const { pendingChatConfig, resetPendingChatConfig, setChatConfig } = useConfigStore()
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const modelLabel = pendingChatConfig.llm?.model || globalConfig.llm.model || 'default model'

  const start = async (withSources: boolean) => {
    if (!username || !authHeader || starting) return
    setStarting(true)
    setError(null)
    try {
      const chat = await createChatRequest(
        { username, authHeader },
        { sources: withSources ? pendingSources : [], configOverride: pendingChatConfig }
      )
      createChat(chat)
      if (Object.keys(pendingChatConfig).length) setChatConfig(chat.chatId, pendingChatConfig)
      clearPendingSources()
      resetPendingChatConfig()
      navigate(`/chat/${chat.chatId}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create chat')
    } finally {
      setStarting(false)
    }
  }

  return (
    <>
      <header data-screen-label="New chat" className="flex h-14 flex-none items-center gap-1.5 border-b border-line pr-3 pl-7 max-sm:pl-4">
        <span className="flex-1 text-[14.5px] font-semibold">New chat</span>
        <ModelPill label={modelLabel} onClick={() => navigate('/settings')} />
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[700px] px-8 pb-[72px] max-sm:px-4" style={{ paddingTop: 'clamp(40px,11vh,120px)' }}>
          <h1 className="m-0 font-serif font-normal leading-[.98] tracking-[-0.032em]" style={{ fontSize: 'clamp(46px,5.6vw,72px)' }}>
            New research <em>chat</em>
          </h1>
          <p className="mt-[18px] mb-10 max-w-[46ch] text-[16px] leading-[1.55] text-ink2">
            Optionally add sources to ground the conversation, then start chatting.
          </p>

          <div className="rounded-2xl border border-line2 bg-surface shadow-sb">
            <SourceStager sources={pendingSources} onChange={setPendingSources} />
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3.5">
              <button
                type="button"
                onClick={() => void start(false)}
                disabled={starting}
                className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-medium text-ink2 underline decoration-line2 underline-offset-4 hover:text-ink disabled:cursor-wait"
              >
                Skip sources and start chatting
              </button>
              <button
                type="button"
                onClick={() => void start(true)}
                disabled={starting}
                className="flex h-10 cursor-pointer items-center gap-2 rounded-[10px] border-0 bg-acc px-[18px] text-[13.5px] font-semibold text-accink transition-[filter] hover:brightness-110"
                style={{ opacity: starting ? 0.7 : 1 }}
              >
                {starting && <Spinner className="text-accink" />}
                {starting ? 'Starting chat…' : 'Start chat'}
              </button>
            </div>
          </div>

          {starting && pendingSources.length > 0 && (
            <p className="mt-[18px] mb-0 text-[13px] text-ink2">Preparing sources and creating the chat. Large ingests can take a minute.</p>
          )}
          {error && <p className="mt-[18px] mb-0 text-[13px] font-medium text-warn">{error}</p>}
        </div>
      </div>
    </>
  )
}

import { useEffect, useRef } from 'react'
import { AssistantMessage } from './AssistantMessage'
import type { Message } from '@/types/chat'

interface MessageListProps {
  messages: Message[]
  emptyHint: string
  hoverRef: number | null
  onHoverRef: (ref: number | null) => void
  onCite: (ref: number) => void
  onApprove: () => void
  onDeny: () => void
  tight: boolean
}

export function MessageList({ messages, emptyHint, hoverRef, onHoverRef, onCite, onApprove, onDeny, tight }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const last = messages[messages.length - 1]

  // Follow the conversation while it grows, unless the reader has scrolled up.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 240
    if (nearBottom || last?.role === 'user') el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages.length, last?.content.length, last?.role, last?.hitl, last?.runStatus])

  const firstUserId = messages.find((m) => m.role === 'user')?.id

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[900px]" style={{ padding: tight ? '32px 20px 20px' : '52px 44px 24px' }}>
        {messages.length === 0 && (
          <div className="flex min-h-[52vh] flex-col items-start justify-end gap-2.5 pb-6">
            <p className="m-0 font-serif text-[40px] leading-[1.05] tracking-[-0.025em] text-ink">
              Send a message <em>to begin</em>
            </p>
            <p className="m-0 max-w-[52ch] text-[14px] text-ink2">{emptyHint}</p>
          </div>
        )}
        {messages.map((m) => {
          if (m.role === 'user') {
            const first = m.id === firstUserId
            return (
              <h2
                key={m.id}
                className="mt-0 mb-[22px] max-w-[32em] font-serif text-[25px] leading-tight font-medium tracking-[-0.018em] text-balance whitespace-pre-wrap"
                style={{ paddingTop: first ? 0 : 40, borderTop: first ? 0 : '1px solid var(--line)' }}
              >
                {m.content}
              </h2>
            )
          }
          return (
            <AssistantMessage
              key={m.id}
              message={m}
              hoverRef={hoverRef}
              onHoverRef={onHoverRef}
              onCite={onCite}
              onApprove={onApprove}
              onDeny={onDeny}
              tight={tight}
            />
          )
        })}
      </div>
    </div>
  )
}

import { useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowUp, CirclePlus } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ChatInputProps {
  onSend: (query: string) => void
  onOpenSources: () => void
  disabled?: boolean
  tight?: boolean
}

export function ChatInput({ onSend, onOpenSources, disabled, tight }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const ready = Boolean(value.trim()) && !disabled

  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 52), 180)}px`
  }, [value])

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex-none" style={{ padding: tight ? '0 16px 16px' : '0 44px 18px' }}>
      <div className="mx-auto max-w-[812px]">
        <div className="flex items-end gap-1.5 rounded-2xl border border-line2 bg-surface py-2 pr-2 pl-1.5 shadow-sb">
          <button
            type="button"
            onClick={onOpenSources}
            title="Add / view sources"
            aria-label="Add or view sources"
            className="flex h-9 w-9 flex-none cursor-pointer items-center justify-center rounded-[10px] border-0 bg-transparent text-ink3 transition-colors hover:bg-bg1 hover:text-acc"
          >
            <CirclePlus size={18} />
          </button>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder="Ask a research question…"
            className="max-h-[180px] min-h-[52px] flex-1 resize-none border-0 bg-transparent px-1 py-[7px] text-[15px] leading-normal text-ink outline-none focus-visible:outline-none"
          />
          <button
            type="button"
            onClick={submit}
            aria-label="Send"
            disabled={!ready}
            className={cn(
              'flex h-9 w-9 flex-none items-center justify-center rounded-full border-0 transition-colors duration-200',
              ready ? 'cursor-pointer bg-acc text-accink' : 'cursor-default bg-line text-ink3'
            )}
          >
            <ArrowUp size={17} />
          </button>
        </div>
        <p className="mt-2 mb-0 text-center text-[11px] text-ink3">Enter to send · Shift+Enter for newline</p>
      </div>
    </div>
  )
}

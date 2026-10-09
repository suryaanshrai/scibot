import { useEffect, useRef, useState } from 'react'
import { Eraser, PanelRight, SlidersHorizontal } from 'lucide-react'
import { IconButton, ModelPill } from '@/components/sb/primitives'

interface ChatHeaderProps {
  title: string
  modelLabel: string
  railOpen: boolean
  onToggleRail: () => void
  onOpenSettings: () => void
  onClear: () => void | Promise<void>
}

export function ChatHeader({ title, modelLabel, railOpen, onToggleRail, onOpenSettings, onClear }: ChatHeaderProps) {
  const [armed, setArmed] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const clear = () => {
    if (!armed) {
      setArmed(true)
      timer.current = window.setTimeout(() => setArmed(false), 3000)
      return
    }
    window.clearTimeout(timer.current)
    setArmed(false)
    void onClear()
  }

  return (
    <header
      data-screen-label="Chat"
      className="flex h-14 flex-none items-center gap-1.5 border-b border-line pr-3 pl-7 max-sm:pl-4"
    >
      <span className="min-w-0 flex-1 truncate text-[14.5px] font-semibold">{title}</span>
      <ModelPill label={modelLabel} onClick={onOpenSettings} className="mr-1.5 max-sm:hidden" />
      {armed ? (
        <button
          type="button"
          onClick={clear}
          className="h-[30px] cursor-pointer rounded-lg border-0 bg-warn px-3 text-[12.5px] font-semibold whitespace-nowrap text-[#1B1A17]"
        >
          Clear history?
        </button>
      ) : (
        <IconButton label="Clear chat history" onClick={clear}>
          <Eraser size={16} />
        </IconButton>
      )}
      <IconButton label="Chat settings" onClick={onOpenSettings}>
        <SlidersHorizontal size={16} />
      </IconButton>
      <IconButton label="Sources" onClick={onToggleRail} active={railOpen}>
        <PanelRight size={16} />
      </IconButton>
    </header>
  )
}

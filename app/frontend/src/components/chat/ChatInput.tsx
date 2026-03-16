import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Send, PlusCircle, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from '@/components/ui/tooltip'

interface ChatInputProps {
  onSend: (query: string) => void
  onToggleSources: () => void
  disabled?: boolean
  sending?: boolean
}

export function ChatInput({ onSend, onToggleSources, disabled, sending }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || sending) return
    onSend(trimmed)
    setValue('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <TooltipProvider>
      <div className="border-t bg-background px-4 py-3">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-2 items-end rounded-xl border bg-card px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-ring">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0 mb-0.5 text-muted-foreground hover:text-primary"
                  onClick={onToggleSources}
                  type="button"
                >
                  <PlusCircle size={18} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Add / view sources</TooltipContent>
            </Tooltip>

            <Textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a research question… (Shift+Enter for newline)"
              className="flex-1 border-0 bg-transparent focus-visible:ring-0 resize-none min-h-[36px] max-h-40 py-1.5 px-0 text-sm"
              rows={1}
              disabled={disabled || sending}
            />

            <Button
              type="button"
              size="icon"
              className="h-8 w-8 shrink-0 mb-0.5"
              onClick={submit}
              disabled={!value.trim() || disabled || sending}
            >
              {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground text-center mt-1">
            Enter to send · Shift+Enter for newline
          </p>
        </div>
      </div>
    </TooltipProvider>
  )
}

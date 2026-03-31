import { useState } from 'react'
import { SlidersHorizontal, Pencil, Check, X, Eraser } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import { useConfigStore } from '@/stores/configStore'
import { ChatSettingsSheet } from './ChatSettingsSheet'
import { cn } from '@/lib/utils'
import { updateChatTitle as updateChatTitleRequest, clearChatMessages } from '@/lib/api'

interface ChatHeaderProps {
  chatId: string
}

export function ChatHeader({ chatId }: ChatHeaderProps) {
  const { chats, updateChatTitle, clearMessages } = useChatStore()
  const { username, authHeader, globalConfig } = useAuthStore()
  const { getChatConfig } = useConfigStore()

  const chat = chats.find((c) => c.chatId === chatId)
  const chatOverride = getChatConfig(chatId)
  const activeLLM = chatOverride.llm?.model ?? globalConfig.llm.model
  const activeProvider = chatOverride.llm?.provider ?? globalConfig.llm.provider

  const [editing, setEditing] = useState(false)
  const [editVal, setEditVal] = useState(chat?.title ?? '')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)

  const startEdit = () => {
    setEditVal(chat?.title ?? '')
    setEditing(true)
  }

  const confirmEdit = async () => {
    if (editVal.trim() && username && authHeader) {
      await updateChatTitleRequest({ username, authHeader }, chatId, editVal.trim())
      updateChatTitle(chatId, editVal.trim())
    }
    setEditing(false)
  }

  const cancelEdit = () => setEditing(false)

  const handleClear = async () => {
    if (username && authHeader) {
      await clearChatMessages({ username, authHeader }, chatId)
      clearMessages(chatId)
    }
    setClearOpen(false)
  }

  return (
    <>
      <div className="flex items-center h-14 border-b px-4 gap-3 bg-background">
        {editing ? (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Input
              autoFocus
              value={editVal}
              onChange={(e) => setEditVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') confirmEdit()
                if (e.key === 'Escape') cancelEdit()
              }}
              className="h-8 text-sm max-w-xs"
            />
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={confirmEdit}><Check size={14} /></Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={cancelEdit}><X size={14} /></Button>
          </div>
        ) : (
          <button
            type="button"
            className={cn('flex-1 min-w-0 text-left group flex items-center gap-1.5')}
            onDoubleClick={startEdit}
            title="Double-click to rename"
          >
            <span className="font-medium text-sm truncate">{chat?.title ?? 'Chat'}</span>
            <Pencil size={12} className="opacity-0 group-hover:opacity-50 transition-opacity shrink-0" />
          </button>
        )}

        {/* Active model badge */}
        <Badge variant="secondary" className="text-[11px] shrink-0 hidden sm:flex">
          {activeProvider}/{activeLLM}
        </Badge>

        {/* Clear history */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => setClearOpen(true)}
          title="Clear chat history"
        >
          <Eraser size={16} />
        </Button>

        {/* Settings */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => setSettingsOpen(true)}
          title="Chat settings"
        >
          <SlidersHorizontal size={16} />
        </Button>
      </div>

      <AlertDialog open={clearOpen} onOpenChange={setClearOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear chat history?</AlertDialogTitle>
            <AlertDialogDescription>
              All messages in this chat will be permanently deleted and the AI will
              lose all context from this conversation. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleClear}>Clear history</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ChatSettingsSheet chatId={chatId} open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  )
}

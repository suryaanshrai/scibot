import { useEffect, useRef, useState } from 'react'
import { useLocation, useMatch, useNavigate } from 'react-router-dom'
import { LogOut, Moon, MoreHorizontal, PanelLeft, Pencil, Plus, Settings, Sun, Trash2 } from 'lucide-react'
import { IconButton, Wordmark } from '@/components/sb/primitives'
import { cn, formatRelativeTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useThemeStore } from '@/stores/themeStore'
import { deleteChat as deleteChatRequest, updateChatTitle as updateChatTitleRequest } from '@/lib/api'
import type { ChatMeta } from '@/types/chat'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

function navItemClass(active: boolean) {
  return cn(
    'flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-[9px] border-0 px-3 text-left text-[13.5px] font-medium text-ink transition-colors hover:bg-line',
    active ? 'bg-line' : 'bg-transparent'
  )
}

function ChatRow({ chat, active }: { chat: ChatMeta; active: boolean }) {
  const navigate = useNavigate()
  const { username, authHeader } = useAuthStore()
  const { deleteChat, updateChatTitle } = useChatStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(chat.title)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) {
        setMenuOpen(false)
        setConfirmDelete(false)
      }
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  const auth = username && authHeader ? { username, authHeader } : null
  const sourceCount = chat.collectionName ? ' · sources attached' : ''

  const saveTitle = async () => {
    const next = title.trim()
    setEditing(false)
    if (!next || next === chat.title || !auth) return
    updateChatTitle(chat.chatId, next)
    await updateChatTitleRequest(auth, chat.chatId, next).catch(console.error)
  }

  const remove = async () => {
    if (!auth) return
    await deleteChatRequest(auth, chat.chatId).catch(console.error)
    deleteChat(chat.chatId)
    setMenuOpen(false)
    if (active) navigate('/chat')
  }

  if (editing) {
    return (
      <div className="rounded-[9px] border border-line2 bg-surface px-2 py-1.5">
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => void saveTitle()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void saveTitle()
            if (e.key === 'Escape') {
              setTitle(chat.title)
              setEditing(false)
            }
          }}
          className="h-7 w-full border-0 bg-transparent px-1 text-[13.5px] font-medium text-ink outline-none"
        />
      </div>
    )
  }

  return (
    <div className="group relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => navigate(`/chat/${chat.chatId}`)}
        className={cn(
          'flex w-full cursor-pointer flex-col gap-0.5 rounded-[9px] border border-solid py-[9px] pr-9 pl-3 text-left font-ui text-ink',
          active ? 'border-line2 bg-surface' : 'border-transparent bg-transparent hover:bg-line'
        )}
      >
        <span className={cn('block max-w-full truncate text-[13.5px]', active ? 'font-semibold' : 'font-medium')}>{chat.title}</span>
        <span className="text-[12px] text-ink3">
          {formatRelativeTime(chat.updatedAt)}
          {sourceCount}
        </span>
      </button>
      <button
        type="button"
        aria-label="Chat options"
        onClick={() => setMenuOpen((v) => !v)}
        className={cn(
          'absolute top-2 right-1.5 flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-ink3 transition-opacity hover:bg-line hover:text-ink',
          menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'
        )}
      >
        <MoreHorizontal size={15} />
      </button>
      {menuOpen && (
        <div className="absolute top-10 right-1.5 z-20 flex w-44 flex-col gap-0.5 rounded-[10px] border border-line2 bg-surface p-1 shadow-sb">
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false)
              setTitle(chat.title)
              setEditing(true)
            }}
            className="flex h-8 cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2.5 text-left text-[13px] text-ink hover:bg-bg1"
          >
            <Pencil size={13} /> Rename
          </button>
          <button
            type="button"
            onClick={() => (confirmDelete ? void remove() : setConfirmDelete(true))}
            className={cn(
              'flex h-8 cursor-pointer items-center gap-2 rounded-md border-0 px-2.5 text-left text-[13px]',
              confirmDelete ? 'bg-warn font-semibold text-[#1B1A17]' : 'bg-transparent text-ink hover:bg-bg1'
            )}
          >
            <Trash2 size={13} /> {confirmDelete ? 'Delete chat?' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  )
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const chatId = useMatch('/chat/:chatId')?.params.chatId
  const { username, logout } = useAuthStore()
  const { chats } = useChatStore()
  const { theme, toggle: toggleTheme } = useThemeStore()

  const onSettings = location.pathname.startsWith('/settings')
  const ThemeIcon = theme === 'dark' ? Sun : Moon
  const signOut = () => {
    logout()
    navigate('/login')
  }

  if (collapsed) {
    return (
      <aside className="flex w-[60px] flex-none flex-col items-center gap-1.5 border-r border-line bg-bg1 py-3">
        <IconButton label="Expand sidebar" onClick={onToggle} className="h-9 w-9 rounded-[9px]">
          <PanelLeft size={16} />
        </IconButton>
        <button
          type="button"
          aria-label="New chat"
          title="New chat"
          onClick={() => navigate('/chat')}
          className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-[9px] border border-line2 bg-surface text-ink"
        >
          <Plus size={16} />
        </button>
        <div className="flex-1" />
        <IconButton label="Settings" onClick={() => navigate('/settings')} active={onSettings} className="h-9 w-9 rounded-[9px]">
          <Settings size={16} />
        </IconButton>
        <IconButton label="Toggle theme" onClick={toggleTheme} className="h-9 w-9 rounded-[9px]">
          <ThemeIcon size={16} />
        </IconButton>
        <IconButton label="Sign out" onClick={signOut} className="h-9 w-9 rounded-[9px] text-ink3">
          <LogOut size={15} />
        </IconButton>
      </aside>
    )
  }

  return (
    <aside className="flex w-[252px] flex-none flex-col border-r border-line bg-bg1">
      <div className="flex h-14 flex-none items-center gap-2 pr-2.5 pl-5">
        <Wordmark className="flex-1 text-[24px]" />
        <IconButton label="Collapse sidebar" onClick={onToggle}>
          <PanelLeft size={16} />
        </IconButton>
      </div>
      <div className="px-3 pt-1.5 pb-3.5">
        <button
          type="button"
          onClick={() => navigate('/chat')}
          className="flex h-[38px] w-full cursor-pointer items-center gap-2 rounded-[10px] border border-line2 bg-surface px-3 text-[13.5px] font-medium text-ink shadow-[0_1px_1px_rgb(0_0_0/.04)] transition-colors hover:border-ink3"
        >
          <Plus size={16} />
          New chat
        </button>
      </div>
      <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-2">
        {chats.length === 0 && <p className="px-3 py-2 text-[12.5px] text-ink3">No chats yet. Start one above.</p>}
        {chats.map((chat) => (
          <ChatRow key={chat.chatId} chat={chat} active={!onSettings && chat.chatId === chatId} />
        ))}
      </nav>
      <div className="flex flex-col gap-0.5 border-t border-line px-2 pt-2.5 pb-3">
        <button type="button" onClick={() => navigate('/settings')} className={navItemClass(onSettings)}>
          <Settings size={16} />
          Settings
        </button>
        <button type="button" onClick={toggleTheme} className={navItemClass(false)}>
          <ThemeIcon size={16} />
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
        <div className="mt-1 flex h-10 items-center gap-2.5 pr-1 pl-2.5">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accsoft text-[11.5px] font-semibold text-acc">
            {username?.[0]?.toUpperCase() ?? '?'}
          </span>
          <span className="flex-1 truncate text-[13.5px] font-medium">{username}</span>
          <IconButton label="Sign out" onClick={signOut} className="text-ink3">
            <LogOut size={15} />
          </IconButton>
        </div>
      </div>
    </aside>
  )
}

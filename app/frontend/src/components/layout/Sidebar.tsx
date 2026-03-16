import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  MessageSquare, Plus, Settings, LogOut, Trash2,
  ChevronLeft, ChevronRight, Bot, Sun, Moon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { cn, formatRelativeTime, truncate } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useThemeStore } from '@/stores/themeStore'
import { deleteChat as deleteChatRequest } from '@/lib/api'

export function Sidebar() {
  const navigate = useNavigate()
  const { username, authHeader, logout } = useAuthStore()
  const { chats, deleteChat } = useChatStore()
  const { theme, toggle: toggleTheme } = useThemeStore()
  const [collapsed, setCollapsed] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  const handleNewChat = () => {
    navigate('/chat')
  }

  const handleDeleteConfirm = async () => {
    if (deleteTarget) {
      if (username && authHeader) {
        await deleteChatRequest({ username, authHeader }, deleteTarget)
      }
      deleteChat(deleteTarget)
      navigate('/chat')
      setDeleteTarget(null)
    }
  }

  return (
    <>
      <aside
        className={cn(
          'flex flex-col border-r bg-sidebar text-sidebar-foreground transition-all duration-200 shrink-0',
          collapsed ? 'w-12' : 'w-[var(--sidebar-width)]'
        )}
      >
        {/* Header */}
        <div className="flex items-center h-14 px-3 border-b gap-2">
          {!collapsed && (
            <>
              <Bot className="text-primary shrink-0" size={22} />
              <span className="font-semibold text-sm tracking-tight">SciBot</span>
              <div className="flex-1" />
            </>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </Button>
        </div>

        {/* New chat button */}
        <div className={cn('px-2 py-2', collapsed && 'px-1')}>
          <Button
            variant="outline"
            className={cn('w-full gap-2 justify-start', collapsed && 'justify-center px-0')}
            size="sm"
            onClick={handleNewChat}
          >
            <Plus size={16} />
            {!collapsed && 'New chat'}
          </Button>
        </div>

        <Separator />

        {/* Chat list */}
        <ScrollArea className="flex-1 py-1">
          {!collapsed && chats.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-4 px-3">
              No chats yet. Start one!
            </p>
          )}
          {chats.map((chat) => (
            <div key={chat.chatId} className="group relative">
              <NavLink
                to={`/chat/${chat.chatId}`}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2 px-3 py-2 text-sm rounded mx-1 my-0.5 transition-colors',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'hover:bg-muted text-foreground'
                  )
                }
              >
                <MessageSquare size={14} className="shrink-0" />
                {!collapsed && (
                  <div className="flex-1 min-w-0">
                    <p className="truncate leading-tight">{truncate(chat.title, 28)}</p>
                    <p className="text-xs text-muted-foreground">{formatRelativeTime(chat.updatedAt)}</p>
                  </div>
                )}
              </NavLink>

              {/* Delete button on hover */}
              {!collapsed && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                  onClick={(e) => { e.preventDefault(); setDeleteTarget(chat.chatId) }}
                >
                  <Trash2 size={12} />
                </Button>
              )}
            </div>
          ))}
        </ScrollArea>

        <Separator />

        {/* Bottom user menu */}
        <div className={cn('p-2', collapsed && 'p-1')}>
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 px-2 py-2 rounded text-sm transition-colors w-full',
                isActive ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
                collapsed && 'justify-center'
              )
            }
          >
            <Settings size={16} />
            {!collapsed && 'Settings'}
          </NavLink>

          {/* Theme toggle */}
          <Button
            variant="ghost"
            size="sm"
            className={cn('w-full mt-1 gap-2', collapsed ? 'justify-center px-0' : 'justify-start')}
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            {!collapsed && (theme === 'dark' ? 'Light mode' : 'Dark mode')}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className={cn('w-full mt-1 gap-2', collapsed ? 'justify-center px-0' : 'justify-start')}
                size="sm"
              >
                <div className="h-6 w-6 rounded-full bg-primary/20 flex items-center justify-center text-xs font-semibold text-primary shrink-0">
                  {username?.[0]?.toUpperCase() ?? '?'}
                </div>
                {!collapsed && <span className="truncate">{username}</span>}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-48">
              <DropdownMenuItem disabled className="text-xs text-muted-foreground">
                {username}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive"
                onClick={() => { logout(); navigate('/login') }}
              >
                <LogOut size={14} className="mr-2" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* Delete confirm dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete chat?</AlertDialogTitle>
            <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm} className="bg-destructive text-white hover:bg-destructive/90">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

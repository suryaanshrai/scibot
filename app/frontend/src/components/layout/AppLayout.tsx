import { useEffect, useState } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { getChats } from '@/lib/api'

const COLLAPSE_KEY = 'scibot-sidebar-collapsed'

function readCollapsed() {
  try {
    const saved = localStorage.getItem(COLLAPSE_KEY)
    if (saved !== null) return saved === '1'
  } catch {
    // storage unavailable
  }
  return typeof window !== 'undefined' && window.innerWidth < 900
}

export function AppLayout() {
  const { isAuthenticated, username, authHeader } = useAuthStore()
  const { chatsLoaded, setChats } = useChatStore()
  const [collapsed, setCollapsed] = useState(readCollapsed)

  useEffect(() => {
    if (!isAuthenticated || !username || !authHeader || chatsLoaded) return
    void getChats({ username, authHeader }).then(setChats).catch(console.error)
  }, [authHeader, chatsLoaded, isAuthenticated, setChats, username])

  const toggle = () =>
    setCollapsed((value) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, value ? '0' : '1')
      } catch {
        // storage unavailable
      }
      return !value
    })

  if (!isAuthenticated) return <Navigate to="/login" replace />

  return (
    <div className="flex h-dvh min-h-[560px] overflow-hidden bg-bg font-ui text-[14px] text-ink">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <main className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </main>
    </div>
  )
}

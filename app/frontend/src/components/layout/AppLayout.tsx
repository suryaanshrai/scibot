import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { getChats } from '@/lib/api'

export function AppLayout() {
  const { isAuthenticated, username, authHeader } = useAuthStore()
  const { chatsLoaded, setChats } = useChatStore()

  useEffect(() => {
    if (!isAuthenticated || !username || !authHeader || chatsLoaded) return
    void getChats({ username, authHeader }).then(setChats).catch(console.error)
  }, [authHeader, chatsLoaded, isAuthenticated, setChats, username])

  if (!isAuthenticated) return <Navigate to="/login" replace />

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}

"use client"

import * as React from "react"
import { api } from "@/lib/api"
import { useAuth } from "./auth-context"

type AppContextValue = {
  pages: any[]
  posts: any[]
  imageTemplates: any[]
  dashboardData: any | null
  isInitialLoading: boolean
  refreshPages: () => Promise<void>
  refreshPosts: () => Promise<void>
  refreshImageTemplates: () => Promise<void>
  refreshDashboard: () => Promise<void>
  setDashboardData: (data: any | null) => void
}

const AppContext = React.createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading } = useAuth()

  const [pages, setPages] = React.useState<any[]>([])
  const [posts, setPosts] = React.useState<any[]>([])
  const [imageTemplates, setImageTemplates] = React.useState<any[]>([])
  const [dashboardData, setDashboardData] = React.useState<any | null>(null)
  const [isInitialLoading, setIsInitialLoading] = React.useState(true)

  const refreshPages = React.useCallback(async () => {
    try {
      const res = await api.get("/api/pages")
      setPages(res.data)
    } catch { /* handled by interceptor */ }
  }, [])

  const refreshPosts = React.useCallback(async () => {
    try {
      const res = await api.get("/posts", { params: { limit: 50 } })
      setPosts(res.data)
    } catch { /* handled by interceptor */ }
  }, [])

  const refreshImageTemplates = React.useCallback(async () => {
    try {
      const res = await api.get("/api/image-templates")
      setImageTemplates(res.data)
    } catch { /* handled by interceptor */ }
  }, [])

  const refreshDashboard = React.useCallback(async () => {
    try {
      const res = await api.get("/api/dashboard")
      setDashboardData(res.data)
    } catch { /* handled by interceptor */ }
  }, [])

  const fetchAll = React.useCallback(async () => {
    setIsInitialLoading(true)
    await Promise.allSettled([
      refreshPages(),
      refreshPosts(),
      refreshImageTemplates(),
      refreshDashboard(),
    ])
    setIsInitialLoading(false)
  }, [refreshPages, refreshPosts, refreshImageTemplates, refreshDashboard])

  React.useEffect(() => {
    if (!authLoading) {
      if (isAuthenticated) {
        fetchAll()
      } else {
        setPages([])
        setPosts([])
        setImageTemplates([])
        setDashboardData(null)
        setIsInitialLoading(false)
      }
    }
  }, [isAuthenticated, authLoading, fetchAll])

  return (
    <AppContext.Provider
      value={{
        pages,
        posts,
        imageTemplates,
        dashboardData,
        isInitialLoading,
        refreshPages,
        refreshPosts,
        refreshImageTemplates,
        refreshDashboard,
        setDashboardData,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const context = React.useContext(AppContext)
  if (!context) throw new Error("useApp must be used inside AppProvider")
  return context
}

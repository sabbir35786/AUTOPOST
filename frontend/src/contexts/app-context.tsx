"use client"

import * as React from "react"
import { api } from "@/lib/api"
import { useAuth } from "./auth-context"

type AppContextValue = {
  pages: any[]
  posts: any[]
  imageTemplates: any[]
  dashboardData: any | null
  dashboardLoading: boolean
  dashboardError: string | null
  isInitialLoading: boolean
  refreshPages: () => Promise<void>
  refreshPosts: () => Promise<void>
  refreshImageTemplates: () => Promise<void>
  refreshDashboard: () => Promise<void>
  setDashboardData: (data: any | null) => void
  clearDashboardError: () => void
}

const AppContext = React.createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading } = useAuth()

  const [pages, setPages] = React.useState<any[]>([])
  const [posts, setPosts] = React.useState<any[]>([])
  const [imageTemplates, setImageTemplates] = React.useState<any[]>([])
  const [dashboardData, setDashboardData] = React.useState<any | null>(null)
  const [dashboardLoading, setDashboardLoading] = React.useState(false)
  const [dashboardError, setDashboardError] = React.useState<string | null>(null)
  const [isInitialLoading, setIsInitialLoading] = React.useState(true)

  const refreshPages = React.useCallback(async () => {
    try {
      const res = await api.get("/api/pages")
      setPages(res.data)
    } catch {
      console.warn("[AppContext] Failed to fetch pages")
    }
  }, [])

  const refreshPosts = React.useCallback(async () => {
    try {
      const res = await api.get("/posts", { params: { limit: 50 } })
      setPosts(res.data)
    } catch {
      console.warn("[AppContext] Failed to fetch posts")
    }
  }, [])

  const refreshImageTemplates = React.useCallback(async () => {
    try {
      const res = await api.get("/api/image-templates")
      setImageTemplates(res.data)
    } catch {
      console.warn("[AppContext] Failed to fetch image templates")
    }
  }, [])

  const refreshDashboard = React.useCallback(async () => {
    setDashboardLoading(true)
    setDashboardError(null)
    try {
      const res = await api.get("/api/dashboard")
      setDashboardData(res.data)
    } catch {
      if (!dashboardData) {
        setDashboardError("Could not load dashboard data. Tap to retry.")
      }
      console.warn("[AppContext] Failed to fetch dashboard data")
    } finally {
      setDashboardLoading(false)
    }
  }, [dashboardData])

  const clearDashboardError = React.useCallback(() => {
    setDashboardError(null)
  }, [])

  // Dashboard background refresh every 30 seconds
  React.useEffect(() => {
    if (!isAuthenticated) return
    const interval = setInterval(() => {
      api.get("/api/dashboard").then((res) => {
        setDashboardData(res.data)
        setDashboardError(null)
      }).catch(() => {
        // silent background refresh failure — don't overwrite cached data
      })
    }, 30000)
    return () => clearInterval(interval)
  }, [isAuthenticated])

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
        setDashboardError(null)
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
        dashboardLoading,
        dashboardError,
        isInitialLoading,
        refreshPages,
        refreshPosts,
        refreshImageTemplates,
        refreshDashboard,
        setDashboardData,
        clearDashboardError,
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

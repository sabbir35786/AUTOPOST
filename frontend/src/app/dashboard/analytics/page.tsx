"use client"

import * as React from "react"
import { useApp } from "@/contexts/app-context"
import { useAuth } from "@/contexts/auth-context"
import { AnalyticsView } from "@/components/social-platform"
import { Loader2 } from "lucide-react"
import { api } from "@/lib/api"

type Analytics = {
  total_posts: number
  total_likes: number
  total_comments: number
  total_shares: number
  posts_per_day: { date: string; count: number }[]
}

export default function AnalyticsPage() {
  const { isInitialLoading } = useApp()
  const { isAuthenticated } = useAuth()
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null)

  React.useEffect(() => {
    if (isAuthenticated) {
      api.get<Analytics>("/analytics", { params: { days: 30 } })
        .then((res) => setAnalytics(res.data))
        .catch(() => setAnalytics(null))
    }
  }, [isAuthenticated])

  if (isInitialLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="size-6 animate-spin text-slate-400" /></div>
  }

  return <AnalyticsView analytics={analytics} setAnalytics={setAnalytics} />
}

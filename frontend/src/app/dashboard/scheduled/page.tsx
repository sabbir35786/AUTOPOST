"use client"

import { useApp } from "@/contexts/app-context"
import { useAuth } from "@/contexts/auth-context"
import { ScheduledSlotsView } from "@/components/social-platform"
import { Loader2 } from "lucide-react"

export default function ScheduledPage() {
  const { isInitialLoading } = useApp()
  const { user } = useAuth()
  const timezone = user?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"

  if (isInitialLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="size-6 animate-spin text-slate-400" /></div>
  }

  return <ScheduledSlotsView timezone={timezone} />
}

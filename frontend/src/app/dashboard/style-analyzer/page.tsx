"use client"

import { useApp } from "@/contexts/app-context"
import { StyleAnalyzerView } from "@/components/social-platform"
import { Loader2 } from "lucide-react"

export default function StyleAnalyzerPage() {
  const { pages, isInitialLoading } = useApp()

  if (isInitialLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="size-6 animate-spin text-slate-400" /></div>
  }

  return <StyleAnalyzerView pages={pages} />
}

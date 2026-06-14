"use client"

import * as React from "react"
import { Loader2, ServerCrash } from "lucide-react"
import { Button } from "@/components/ui/button"

export function NetworkOverlay() {
  const [isWakingUp, setIsWakingUp] = React.useState(false)
  const [hasTimeout, setHasTimeout] = React.useState(false)

  React.useEffect(() => {
    let activeRequests = 0

    const handleColdStart = (e: Event) => {
      const customEvent = e as CustomEvent<boolean>
      if (customEvent.detail) {
        activeRequests++
        setIsWakingUp(true)
      } else {
        activeRequests = Math.max(0, activeRequests - 1)
        if (activeRequests === 0) {
          setIsWakingUp(false)
        }
      }
    }

    const handleTimeout = () => {
      setIsWakingUp(false)
      setHasTimeout(true)
      activeRequests = 0
    }

    window.addEventListener("backend-cold-start", handleColdStart)
    window.addEventListener("backend-timeout", handleTimeout)

    return () => {
      window.removeEventListener("backend-cold-start", handleColdStart)
      window.removeEventListener("backend-timeout", handleTimeout)
    }
  }, [])

  if (hasTimeout) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/50 backdrop-blur-sm p-4">
        <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-2xl text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-red-100 mb-4">
            <ServerCrash className="size-6 text-red-600" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 mb-2">Connection Timeout</h2>
          <p className="text-sm text-slate-500 mb-6">
            The background server took too long to respond. This occasionally happens if the free-tier instance needs extra time to boot up.
          </p>
          <Button 
            className="w-full bg-blue-700 hover:bg-blue-800"
            onClick={() => window.location.reload()}
          >
            Retry Connection
          </Button>
        </div>
      </div>
    )
  }

  if (isWakingUp) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/40 backdrop-blur-sm p-4 transition-all animate-in fade-in duration-500">
        <div className="flex flex-col md:flex-row items-center gap-4 rounded-xl md:rounded-full bg-white px-6 py-4 shadow-2xl border border-slate-200 text-center md:text-left">
          <div className="rounded-full bg-blue-50 p-2 shrink-0">
            <Loader2 className="size-6 animate-spin text-blue-600" />
          </div>
          <span className="text-sm font-medium text-slate-700">
            Waking up secure background servers (this may take up to 30 seconds on the free tier)...
          </span>
        </div>
      </div>
    )
  }

  return null
}

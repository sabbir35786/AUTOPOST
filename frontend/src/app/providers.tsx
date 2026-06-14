"use client"

import { AppNav } from "@/components/layout/app-nav"
import { Toaster } from "@/components/ui/toaster"
import { AuthProvider } from "@/contexts/auth-context"
import { AppProvider } from "@/contexts/app-context"
import { NetworkOverlay } from "@/components/layout/network-overlay"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AppProvider>
        <AppNav />
        {children}
        <NetworkOverlay />
        <Toaster />
      </AppProvider>
    </AuthProvider>
  )
}

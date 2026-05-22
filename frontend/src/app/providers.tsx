"use client"

import { AppNav } from "@/components/layout/app-nav"
import { Toaster } from "@/components/ui/toaster"
import { AuthProvider } from "@/contexts/auth-context"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AppNav />
      {children}
      <Toaster />
    </AuthProvider>
  )
}

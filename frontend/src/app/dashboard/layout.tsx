"use client"

/**
 * dashboard/layout.tsx — Persistent Dashboard Shell
 *
 * WHY THIS FILE EXISTS:
 * ---------------------
 * Previously, every dashboard route rendered the full <SocialPlatform> component
 * which included the sidebar, auth guard, and the view content all in one component.
 * When a user navigated between tabs (e.g. /dashboard/create → /dashboard/scheduled),
 * Next.js would unmount and remount the entire SocialPlatform component because each
 * page.tsx was rendering a new instance of it. This caused:
 *   - Sidebar to flicker/re-render on every navigation
 *   - Auth guard to re-run and flash the loading spinner
 *   - AppContext data to be re-fetched unnecessarily
 *
 * HOW THIS FIXES IT:
 * ------------------
 * By placing the sidebar and auth guard here in layout.tsx, Next.js App Router
 * keeps this layout mounted across all /dashboard/* navigations. Only the
 * {children} slot (the individual view) swaps out. The sidebar, auth state,
 * and AppContext data all persist in memory between tab switches.
 *
 * STATE SURVIVAL TABLE:
 * ┌──────────────────────────────┬──────────────────────────┐
 * │ State                        │ Survives tab switch?     │
 * ├──────────────────────────────┼──────────────────────────┤
 * │ useAuth() token + user       │ ✅ Yes (AuthProvider)    │
 * │ useApp() pages / posts       │ ✅ Yes (AppProvider)     │
 * │ Sidebar active link          │ ✅ Yes (usePathname)     │
 * │ Per-view local state         │ ❌ No (expected)         │
 * └──────────────────────────────┴──────────────────────────┘
 */

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  BarChart3,
  CalendarClock,
  FileText,
  Home,
  Image,
  Loader2,
  Menu,
  PenLine,
  Radar,
  Search,
  Settings,
  Sparkles,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { useAuth } from "@/contexts/auth-context"
import { useApp } from "@/contexts/app-context"
import { cn } from "@/lib/utils"

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Home },
  { href: "/dashboard/create", label: "Create Post", icon: PenLine },
  { href: "/dashboard/ai-settings", label: "Prompt Studio", icon: Sparkles },
  { href: "/dashboard/style-analyzer", label: "Style Analyzer", icon: Search },
  { href: "/dashboard/page-tracker", label: "Page Tracker", icon: Radar },
  { href: "/dashboard/templates", label: "Templates", icon: Image },
  { href: "/dashboard/scheduled", label: "Scheduled Posts", icon: CalendarClock },
  { href: "/dashboard/published", label: "Published Posts", icon: FileText },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isLoading, logout } = useAuth()
  const { pages } = useApp()
  const [mobileOpen, setMobileOpen] = React.useState(false)

  // Auth guard — redirect unauthenticated visitors to the login page.
  // Runs here (in the layout) so it fires once and survives tab navigation.
  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login")
    }
  }, [isAuthenticated, isLoading, router])

  // Show a full-screen spinner while the auth state is being hydrated from
  // localStorage on the first load. This prevents a flash of the login redirect.
  if (isLoading || !isAuthenticated) {
    return (
      <main className="grid min-h-screen place-items-center">
        <Loader2 className="size-5 animate-spin" />
      </main>
    )
  }

  const connectedPage = pages.find((page) => page.connection_status === "connected") || pages[0]

  function signOut() {
    logout()
    router.push("/login")
  }

  const sidebar = (
    <aside className="flex h-full w-60 flex-col border-r bg-white">
      <div className="border-b p-6 text-lg font-semibold text-slate-950">PagePilot</div>
      <nav className="grid gap-1 p-3">
        {navItems.map((item) => {
          const Icon = item.icon
          // Exact match for /dashboard, prefix match for sub-routes
          const active =
            item.href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-blue-50 hover:text-blue-700",
                active && "bg-blue-50 text-blue-700",
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div className="mt-auto border-t p-4">
        {connectedPage ? (
          <div className="flex items-center gap-2 text-sm text-slate-700">
            {connectedPage.page_picture_url && (
              <img
                src={connectedPage.page_picture_url}
                alt={connectedPage.page_name}
                className="size-8 rounded-full object-cover"
              />
            )}
            <span className="truncate font-medium">{connectedPage.page_name}</span>
          </div>
        ) : (
          <p className="text-sm text-slate-500">No page connected</p>
        )}
        <Button variant="outline" className="mt-3 w-full" onClick={signOut}>
          Sign out
        </Button>
      </div>
    </aside>
  )

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      {/* Desktop sidebar — fixed on the left, stays mounted across all navigations */}
      <div className="fixed inset-y-0 left-0 hidden md:block">{sidebar}</div>

      {/* Mobile top bar with drawer */}
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-white px-4 md:hidden">
        <span className="font-semibold">PagePilot</span>
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button size="icon" variant="outline">
              <Menu className="size-4" />
            </Button>
          </SheetTrigger>
          <SheetContent className="p-0">{sidebar}</SheetContent>
        </Sheet>
      </header>

      {/* Main content area — only {children} swaps on navigation */}
      <main className="mx-auto grid max-w-6xl gap-6 p-4 md:ml-60 md:p-8">
        {children}
      </main>
    </div>
  )
}

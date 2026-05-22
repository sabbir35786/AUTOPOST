"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { Menu } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { useAuth } from "@/contexts/auth-context"
import { cn } from "@/lib/utils"

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/login", label: "Login" },
  { href: "/register", label: "Register" },
]

export function AppNav() {
  const pathname = usePathname()
  const router = useRouter()
  const { isAuthenticated, logout } = useAuth()

  const visibleItems = navItems.filter((item) =>
    isAuthenticated ? item.href === "/dashboard" : item.href !== "/dashboard"
  )

  function handleLogout() {
    logout()
    router.push("/login")
  }

  const navLinks = (
    <>
      {visibleItems.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={cn(
            "rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
            pathname === item.href && "bg-muted text-foreground"
          )}
        >
          {item.label}
        </Link>
      ))}
      {isAuthenticated ? (
        <Button variant="outline" onClick={handleLogout}>
          Sign out
        </Button>
      ) : null}
    </>
  )

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4">
        <Link href="/" className="text-sm font-semibold">
          Auto Poster
        </Link>
        <nav className="hidden items-center gap-2 md:flex">{navLinks}</nav>
        <div className="md:hidden">
          <Sheet>
            <SheetTrigger asChild>
              <Button aria-label="Open menu" variant="outline" size="icon">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent>
              <nav className="flex flex-col gap-2">{navLinks}</nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}

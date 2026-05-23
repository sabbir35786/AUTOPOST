"use client"

import * as React from "react"
import { Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useAuth } from "@/contexts/auth-context"
import { api } from "@/lib/api"

type FacebookPage = {
  page_id: string
  page_name: string
}

function FacebookCallbackContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { isAuthenticated, isLoading } = useAuth()
  const [pages, setPages] = React.useState<FacebookPage[]>([])
  const [isConnecting, setIsConnecting] = React.useState(true)
  const [selectedPageId, setSelectedPageId] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (isLoading) {
      return
    }
    if (!isAuthenticated) {
      router.replace("/login")
      return
    }

    const code = searchParams.get("code")
    const state = searchParams.get("state")
    if (!code) {
      toast.error("Facebook did not return an authorization code.")
      setIsConnecting(false)
      return
    }

    async function connect() {
      setIsConnecting(true)
      try {
        const response = await api.post<{ pages: FacebookPage[] }>(
          "/facebook/connect",
          {
            code,
            state,
            redirect_uri: window.location.href.split("?")[0],
          }
        )
        setPages(response.data.pages)
        if (!response.data.pages.length) {
          toast.error("No Facebook pages were returned.")
        }
      } catch {
        toast.error("Could not connect Facebook.")
      } finally {
        setIsConnecting(false)
      }
    }

    connect()
  }, [isAuthenticated, isLoading, router, searchParams])

  async function selectPage(page: FacebookPage) {
    setSelectedPageId(page.page_id)
    try {
      await api.post("/facebook/select-page", { page_id: page.page_id })
      toast.success(`Connected ${page.page_name}.`)
      if (window.opener) {
        window.opener.postMessage({ type: "facebook-connected" }, window.location.origin)
        window.close()
        return
      }
      router.push("/dashboard")
    } catch {
      toast.error("Could not select that page.")
    } finally {
      setSelectedPageId(null)
    }
  }

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-8">
      <Card className="w-full max-w-md md:max-w-lg">
        <CardHeader>
          <CardTitle>Select Facebook Page</CardTitle>
          <CardDescription>
            Choose which page should receive scheduled posts.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {isConnecting ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Connecting Facebook
            </div>
          ) : pages.length ? (
            pages.map((page) => (
              <div
                key={page.page_id}
                className="flex flex-col gap-3 rounded-lg border p-3 md:flex-row md:items-center md:justify-between"
              >
                <div>
                  <p className="font-medium">{page.page_name}</p>
                  <p className="text-xs text-muted-foreground">{page.page_id}</p>
                </div>
                <Button
                  className="w-full md:w-auto"
                  onClick={() => selectPage(page)}
                  disabled={selectedPageId === page.page_id}
                >
                  {selectedPageId === page.page_id ? "Selecting..." : "Select"}
                </Button>
              </div>
            ))
          ) : (
            <Button variant="outline" onClick={() => router.push("/dashboard")}>
              Return to dashboard
            </Button>
          )}
        </CardContent>
      </Card>
    </main>
  )
}

export default function FacebookCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-8">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading Facebook callback
          </div>
        </main>
      }
    >
      <FacebookCallbackContent />
    </Suspense>
  )
}

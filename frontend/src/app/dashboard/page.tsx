"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { CalendarClock, Loader2, PenLine, Share2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/contexts/auth-context"
import { api } from "@/lib/api"

type FacebookStatus = {
  connected: boolean
  is_connected?: boolean
  page_name?: string
  page_id?: string
}

type Schedule = {
  niche: string
  post_time: string
  timezone: string
  active: boolean
}

type GeneratedPost = {
  id: number
  content: string
}

type PostHistoryItem = {
  id: number
  content: string
  status: "draft" | "success" | "failed" | string
  posted_at: string | null
}

const timezones = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Asia/Dhaka",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
]

export default function DashboardPage() {
  const router = useRouter()
  const { isAuthenticated, isLoading } = useAuth()
  const [status, setStatus] = React.useState<FacebookStatus | null>(null)
  const [schedule, setSchedule] = React.useState<Schedule>({
    niche: "",
    post_time: "10:00",
    timezone: "UTC",
    active: true,
  })
  const [isSaving, setIsSaving] = React.useState(false)
  const [isPageLoading, setIsPageLoading] = React.useState(true)
  const [generatedPost, setGeneratedPost] = React.useState<GeneratedPost | null>(null)
  const [postHistory, setPostHistory] = React.useState<PostHistoryItem[]>([])
  const [isGenerating, setIsGenerating] = React.useState(false)
  const [isPublishing, setIsPublishing] = React.useState(false)

  const nextScheduledPost = React.useMemo(
    () => getNextScheduledPostText(schedule),
    [schedule]
  )

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login")
    }
  }, [isAuthenticated, isLoading, router])

  React.useEffect(() => {
    if (!isAuthenticated) {
      return
    }

    async function loadDashboard() {
      setIsPageLoading(true)
      try {
        const [statusResponse, scheduleResponse] = await Promise.all([
          api.get<FacebookStatus>("/facebook/status"),
          api.get<Schedule | null>("/schedule"),
        ])
        setStatus(statusResponse.data)
        if (scheduleResponse.data) {
          setSchedule(scheduleResponse.data)
        }
      } catch {
        toast.error("Could not load dashboard data.")
      } finally {
        setIsPageLoading(false)
      }
    }

    loadDashboard()
    loadPostHistory()
  }, [isAuthenticated])

  function connectFacebook() {
    const appId = process.env.NEXT_PUBLIC_FACEBOOK_APP_ID
    if (!appId) {
      toast.error("Facebook app id is not configured.")
      return
    }

    const redirectUri = "http://localhost:3000/auth/facebook/callback"
    const params = new URLSearchParams({
      client_id: appId,
      redirect_uri: redirectUri,
      response_type: "code",
      scope: "pages_show_list,pages_manage_posts,instagram_basic",
    })
    window.location.href = `https://www.facebook.com/v19.0/dialog/oauth?${params.toString()}`
  }

  async function saveSchedule(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!schedule.niche.trim()) {
      toast.error("Add a niche before saving.")
      return
    }

    setIsSaving(true)
    try {
      const response = await api.put<Schedule>("/schedule", schedule)
      setSchedule(response.data)
      toast.success("Schedule saved.")
    } catch {
      toast.error("Could not save schedule.")
    } finally {
      setIsSaving(false)
    }
  }

  async function loadPostHistory() {
    try {
      const response = await api.get<PostHistoryItem[]>("/posts/history", {
        params: { limit: 5 },
      })
      setPostHistory(response.data)
    } catch {
      toast.error("Could not load post history.")
    }
  }

  async function generatePost() {
    setIsGenerating(true)
    try {
      const response = await api.post<GeneratedPost>("/posts/generate")
      setGeneratedPost(response.data)
      toast.success("Draft generated.")
      await loadPostHistory()
    } catch {
      toast.error("Could not generate a post. Check your schedule and connection.")
    } finally {
      setIsGenerating(false)
    }
  }

  async function publishGeneratedPost() {
    if (!generatedPost) {
      return
    }

    setIsPublishing(true)
    try {
      const response = await api.post<{
        success: boolean
        status: string
        error_message?: string | null
      }>(`/posts/${generatedPost.id}/publish`)
      if (response.data.success) {
        toast.success("Post published.")
        setGeneratedPost(null)
      } else {
        toast.error(response.data.error_message || "Facebook rejected the post.")
      }
      await loadPostHistory()
    } catch {
      toast.error("Could not publish the post.")
    } finally {
      setIsPublishing(false)
    }
  }

  if (isLoading || !isAuthenticated) {
    return (
      <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
        <Loader2 className="size-5 animate-spin" />
      </main>
    )
  }

  return (
    <main className="mx-auto grid min-h-[calc(100vh-3.5rem)] w-full max-w-6xl grid-cols-1 gap-6 px-4 py-6 md:grid-cols-[14rem_1fr] md:py-8">
      <aside className="hidden rounded-lg border bg-card p-3 md:block">
        <nav className="grid gap-1 text-sm">
          <a className="rounded-lg bg-muted px-3 py-2 font-medium" href="#connection">
            Connection
          </a>
          <a className="rounded-lg px-3 py-2 text-muted-foreground hover:bg-muted" href="#schedule">
            Schedule
          </a>
          <a className="rounded-lg px-3 py-2 text-muted-foreground hover:bg-muted" href="#posts">
            Posts
          </a>
        </nav>
      </aside>

      <section className="grid gap-6">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold md:text-3xl">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Manage the page connection and posting schedule.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Card id="connection">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Share2 className="size-4" />
                Connection Status
              </CardTitle>
              <CardDescription>
                Connect the Facebook page that will receive generated posts.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              {isPageLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Loading status
                </div>
              ) : status?.connected ? (
                <div className="rounded-lg border bg-muted/40 p-3 text-sm">
                  <p className="font-medium">Connected</p>
                  <p className="text-muted-foreground">{status.page_name}</p>
                </div>
              ) : (
                <Button onClick={connectFacebook} className="w-full md:w-fit">
                  Connect Facebook
                </Button>
              )}
            </CardContent>
          </Card>

          <Card id="schedule">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarClock className="size-4" />
                Schedule
              </CardTitle>
              <CardDescription>
                Choose when and what the automation should post.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form className="grid gap-4" onSubmit={saveSchedule}>
                <div className="grid gap-2">
                  <Label htmlFor="niche">Niche</Label>
                  <Textarea
                    id="niche"
                    placeholder="e.g., vegan meal prep tips"
                    value={schedule.niche}
                    onChange={(event) =>
                      setSchedule((current) => ({
                        ...current,
                        niche: event.target.value,
                      }))
                    }
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="post_time">Post time</Label>
                    <Input
                      id="post_time"
                      type="time"
                      value={schedule.post_time}
                      onChange={(event) =>
                        setSchedule((current) => ({
                          ...current,
                          post_time: event.target.value,
                        }))
                      }
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="timezone">Timezone</Label>
                    <Select
                      id="timezone"
                      value={schedule.timezone}
                      onChange={(event) =>
                        setSchedule((current) => ({
                          ...current,
                          timezone: event.target.value,
                        }))
                      }
                    >
                      {timezones.map((timezone) => (
                        <option key={timezone} value={timezone}>
                          {timezone}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>

                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <Label htmlFor="active">Active</Label>
                    <p className="text-xs text-muted-foreground">
                      Allow scheduled posting for this account.
                    </p>
                  </div>
                  <Switch
                    id="active"
                    checked={schedule.active}
                    onCheckedChange={(active) =>
                      setSchedule((current) => ({ ...current, active }))
                    }
                  />
                </div>

                <div className="rounded-lg border bg-muted/40 p-3 text-sm">
                  <p className="font-medium">Next Scheduled Post</p>
                  <p className="text-muted-foreground">{nextScheduledPost}</p>
                </div>

                <Button type="submit" className="w-full md:w-fit" disabled={isSaving}>
                  {isSaving ? "Saving..." : "Save schedule"}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>

        <div id="posts" className="grid gap-4 md:grid-cols-[1fr_1fr]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <PenLine className="size-4" />
                Generate Post
              </CardTitle>
              <CardDescription>
                Create a draft from your schedule niche, then publish it when ready.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Button
                onClick={generatePost}
                className="w-full md:w-fit"
                disabled={isGenerating}
              >
                {isGenerating ? "Generating..." : "Generate Post"}
              </Button>

              {generatedPost ? (
                <div className="grid gap-3 rounded-lg border bg-muted/30 p-4">
                  <p className="whitespace-pre-wrap text-sm leading-6">
                    {generatedPost.content}
                  </p>
                  <Button
                    onClick={publishGeneratedPost}
                    className="w-full md:w-fit"
                    disabled={isPublishing}
                  >
                    {isPublishing ? "Posting..." : "Post Now"}
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Last Posts</CardTitle>
              <CardDescription>Recent drafts and publishing attempts.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {postHistory.length ? (
                postHistory.map((post) => (
                  <div key={post.id} className="grid gap-2 rounded-lg border p-3">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <StatusBadge status={post.status} />
                      <span className="text-xs text-muted-foreground">
                        {formatPostDate(post.posted_at)}
                      </span>
                    </div>
                    <p className="line-clamp-3 text-sm text-muted-foreground">
                      {post.content}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">No posts yet.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  )
}

function StatusBadge({ status }: { status: string }) {
  const styles =
    status === "success"
      ? "border-green-200 bg-green-50 text-green-700"
      : status === "failed"
        ? "border-red-200 bg-red-50 text-red-700"
        : "border-yellow-200 bg-yellow-50 text-yellow-700"

  return (
    <span className={`w-fit rounded-full border px-2 py-1 text-xs font-medium ${styles}`}>
      {status}
    </span>
  )
}

function formatPostDate(value: string | null) {
  if (!value) {
    return "Not posted"
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function getNextScheduledPostText(schedule: Schedule) {
  if (!schedule.active) {
    return "Schedule is inactive"
  }
  if (!schedule.post_time) {
    return "Choose a posting time"
  }

  try {
    const now = new Date()
    const [hours, minutes] = schedule.post_time.split(":").map(Number)
    const scheduled = new Date(now)
    scheduled.setHours(hours, minutes, 0, 0)
    if (scheduled <= now) {
      scheduled.setDate(scheduled.getDate() + 1)
    }

    return `${schedule.post_time} ${schedule.timezone} (${new Intl.DateTimeFormat(
      undefined,
      {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }
    ).format(scheduled)})`
  } catch {
    return `${schedule.post_time} ${schedule.timezone}`
  }
}

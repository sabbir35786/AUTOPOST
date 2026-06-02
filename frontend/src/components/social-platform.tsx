"use client"

import * as React from "react"
import axios from "axios"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  BarChart3,
  CalendarClock,
  Check,
  FileText,
  Home,
  Loader2,
  Menu,
  PenLine,
  Plus,
  Plug,
  Radar,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  Sparkles,
  Trash2,
  X,
  Image,
  LayoutTemplate,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/contexts/auth-context"
import { API_BASE_URL, BACKEND_ORIGIN, api, getApiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

type PageConnection = {
  id: number
  facebook_page_id?: string
  page_id: string
  page_name: string
  profile_picture_url?: string | null
  page_picture_url?: string | null
  connection_status: string
  connected_at: string
  disconnected_at?: string | null
  reconnect_count?: number
  post_count?: number
  scheduled_post_count?: number
  paused_post_count?: number
}

type Post = {
  id: number
  content: string
  status: string
  posted_at?: string | null
  scheduled_at?: string | null
  media_urls: string[]
  link_url?: string | null
  page_name?: string | null
  page_picture_url?: string | null
  failure_reason?: string | null
  ai_generated: boolean
  auto_generated: boolean
  likes_count?: number
  comments_count?: number
  shares_count?: number
  reach_count?: number
  engagement_score?: number
  low_engagement?: boolean
}

type AIPersona = {
  id?: number
  page_connection_id?: number
  persona_name: string
  niche: string
  tone_tags: string[]
  custom_instructions: string | null
  prompt_config?: PromptStudioConfig | null
  custom_prompt?: string | null
  creativity_level: number
  language: string
  hashtags_enabled: boolean
  hashtag_count: number
  always_include_engagement_hook: boolean
  assigned_days: string[]
  posting_time_slots: string[]
  priority_level: "High" | "Normal" | "Low"
  is_active: boolean
  learning_mode_enabled: boolean
  minimum_engagement_threshold: number
  performance_score?: number
  template_image_generation_enabled?: boolean
  template_logo_url?: string | null
  total_posts_published?: number
  learned_patterns_summary?: string | null
}

type PromptStudioConfig = {
  template: string
  audience: string
  goal: string
  brand_personality: string[]
  always_topics: string[]
  never_topics: string[]
  every_post_includes: string[]
  never_do: string[]
  length: "Short" | "Medium" | "Long"
  vary_length: boolean
  structure: string
  examples: string
}

type PerformanceInsights = {
  enabled: boolean
  reason?: string | null
  persona_scores: { id: number; name: string; score: number }[]
  time_slot_heatmap: { day: string; hour: number; average_score: number }[]
  top_posts: {
    id: number
    content: string
    persona_name: string
    published_at?: string | null
    likes_count: number
    comments_count: number
    shares_count: number
    reach_count: number
    engagement_score: number
  }[]
  recommendations: { id: number; text: string; generated_at: string }[]
}

type Analytics = {
  total_posts: number
  total_likes: number
  total_comments: number
  total_shares: number
  posts_per_day: { date: string; count: number }[]
}

type DashboardIntelligence = {
  next_scheduled_post?: { id: number; content: string; scheduled_at?: string | null; minutes_until: number } | null
  last_published_post?: { id: number; content: string; posted_at?: string | null; likes_count: number; comments_count: number; shares_count: number; reach_count: number; engagement_score: number } | null
  facebook_connections: { id: number; page_name: string; status: string; token_expires_at?: string | null }[]
  cron_health: { ok: boolean; last_run_at?: string | null; age_seconds?: number | null }
  onboarding_steps: { label: string; done: boolean; href: string }[]
  learned_insights: {
    best_post?: { id: number; content: string; score: number; insight: string } | null
    best_time_slot?: { slot: string; score: number; insight: string } | null
    best_persona?: { id: number; name: string; score: number; insight: string } | null
  }
  action_items: { id: string; text: string; action_label: string; href: string; priority: string }[]
  warnings: { level: "red" | "amber"; text: string; href: string }[]
}

type StyleAnalysis = {
  id: number
  source_type: string
  source_identifier: string
  page_name?: string | null
  report: any
  created_at: string
}

type TrackerDashboard = {
  tracked_pages: { id: number; nickname: string; page_identifier: string; page_name?: string | null; is_active: boolean; last_checked_at?: string | null }[]
  posts: { id: number; page_name: string; content: string; posted_at?: string | null; likes_count: number; comments_count: number; shares_count: number; engagement_score: number; topic?: string | null }[]
  comparison: { id: number; nickname: string; posts: number; average_likes: number; average_comments: number; average_shares: number; most_active_day: string; most_used_topics: string }[]
  trends: { id: number; topic: string; summary: string; page_count: number; generated_at: string }[]
}

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Home },
  { href: "/dashboard/create", label: "Create Post", icon: PenLine },
  { href: "/dashboard/templates", label: "Templates", icon: LayoutTemplate },
  { href: "/dashboard/ai-settings", label: "Prompt Studio", icon: Sparkles },
  { href: "/dashboard/style-analyzer", label: "Style Analyzer", icon: Search },
  { href: "/dashboard/page-tracker", label: "Page Tracker", icon: Radar },
  { href: "/dashboard/scheduled", label: "Scheduled Posts", icon: CalendarClock },
  { href: "/dashboard/published", label: "Published Posts", icon: FileText },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
]

export function SocialPlatform({ view }: { view: "home" | "create" | "templates" | "ai-settings" | "style-analyzer" | "page-tracker" | "scheduled" | "published" | "analytics" | "settings" }) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isLoading, logout } = useAuth()
  const [pages, setPages] = React.useState<PageConnection[]>([])
  const [posts, setPosts] = React.useState<Post[]>([])
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [mobileOpen, setMobileOpen] = React.useState(false)

  const timezone = user?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  const connectedPage = pages.find((page) => page.connection_status === "connected") || pages[0]

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/login")
  }, [isAuthenticated, isLoading, router])

  const load = React.useCallback(async () => {
    if (!isAuthenticated) return
    setLoading(true)
    try {
      // health check (unprotected)
      await api.get("/health")
      // Load pages – if none are connected, show empty state without error
      let pageResponse
      try {
        pageResponse = await api.get<PageConnection[]>("/api/pages")
        setPages(pageResponse.data)
      } catch (err) {
        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        if (status && status >= 400 && status < 500) {
          // Likely unauthorized or not found – treat as no pages
          setPages([])
        } else {
          console.error("Failed to load pages:", err)
          toast.error(axios.isAxiosError(err) ? err.response?.data?.detail || err.message : String(err))
        }
      }
      // Load posts – this can fail if no posts yet, show empty list
      try {
        const postResponse = await api.get<Post[]>("/posts", { params: { limit: 50 } })
        setPosts(postResponse.data)
      } catch (err) {
        console.error("Failed to load posts:", err)
        // If no posts exist, API may return 404 or empty list – treat as empty
        setPosts([])
      }
      if (view === "analytics") {
        const analyticsResponse = await api.get<Analytics>("/analytics", { params: { days: 30 } })
        setAnalytics(analyticsResponse.data)
      }
    } catch (error) {
      const status = axios.isAxiosError(error) ? error.response?.status : undefined
      if (status === 401 || status === 403) {
        logout()
        router.replace("/login")
        return
      }
      const errMsg = axios.isAxiosError(error) ? error.response?.data?.detail || error.message : String(error)
      console.error("Workspace load error:", errMsg)
      toast.error(errMsg || "Could not load your workspace.")
    } finally {
      setLoading(false)
    }
  }, [isAuthenticated, logout, router, view])

  React.useEffect(() => {
    load()
  }, [load])

  function signOut() {
    logout()
    router.push("/login")
  }

  if (isLoading || !isAuthenticated) {
    return <main className="grid min-h-screen place-items-center"><Loader2 className="size-5 animate-spin" /></main>
  }

  const sidebar = (
    <aside className="flex h-full w-60 flex-col border-r bg-white">
      <div className="border-b p-6 text-lg font-semibold text-slate-950">PagePilot</div>
      <nav className="grid gap-1 p-3">
        {navItems.map((item) => {
          const Icon = item.icon
          const active = pathname === item.href
          return (
            <Link key={item.href} href={item.href} onClick={() => setMobileOpen(false)} className={cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-blue-50 hover:text-blue-700", active && "bg-blue-50 text-blue-700")}>
              <Icon className="size-4" />
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div className="mt-auto border-t p-4">
        {connectedPage ? <PageMini page={connectedPage} /> : <p className="text-sm text-slate-500">No page connected</p>}
        <Button variant="outline" className="mt-3 w-full" onClick={signOut}>Sign out</Button>
      </div>
    </aside>
  )

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <div className="fixed inset-y-0 left-0 hidden md:block">{sidebar}</div>
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-white px-4 md:hidden">
        <span className="font-semibold">PagePilot</span>
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild><Button size="icon" variant="outline"><Menu className="size-4" /></Button></SheetTrigger>
          <SheetContent className="p-0">{sidebar}</SheetContent>
        </Sheet>
      </header>
      <main className="mx-auto grid max-w-6xl gap-6 p-4 md:ml-60 md:p-8">
        {loading ? <SkeletonPage /> : null}
        {!loading && view === "home" ? <HomeView pages={pages} posts={posts} onConnected={load} timezone={timezone} /> : null}
        {!loading && view === "create" ? <Composer pages={pages} timezone={timezone} onSaved={load} /> : null}
        {!loading && view === "templates" ? <TemplateLibraryView /> : null}
        {!loading && view === "ai-settings" ? <AISettingsView pages={pages} /> : null}
        {!loading && view === "style-analyzer" ? <StyleAnalyzerView pages={pages} /> : null}
        {!loading && view === "page-tracker" ? <PageTrackerView pages={pages} /> : null}
        {!loading && view === "scheduled" ? <PostList title="Scheduled Posts" posts={posts.filter((post) => post.status === "scheduled")} emptyAction="/dashboard/create" emptyText="No upcoming posts yet." timezone={timezone} onChanged={load} /> : null}
        {!loading && view === "published" ? <PostList title="Published Posts" posts={posts.filter((post) => post.status === "published" || post.status === "success")} emptyAction="/dashboard/create" emptyText="No published posts yet." timezone={timezone} published onChanged={load} /> : null}
        {!loading && view === "analytics" ? <AnalyticsView analytics={analytics} setAnalytics={setAnalytics} /> : null}
        {!loading && view === "settings" ? <SettingsView pages={pages} timezone={timezone} onChanged={load} /> : null}
      </main>
    </div>
  )
}

function HomeView({ pages, posts, onConnected, timezone }: { pages: PageConnection[]; posts: Post[]; onConnected: () => void; timezone: string }) {
  const [intel, setIntel] = React.useState<DashboardIntelligence | null>(null)
  React.useEffect(() => {
    api.get<DashboardIntelligence>("/api/dashboard/intelligence").then((response) => setIntel(response.data)).catch(() => setIntel(null))
  }, [])
  const published = posts.filter((post) => post.status === "published" || post.status === "success").length
  const scheduled = posts.filter((post) => post.status === "scheduled").length
  const failed = posts.filter((post) => post.status.includes("failed")).length
  const onboardingDone = intel?.onboarding_steps.every((step) => step.done)
  return (
    <>
      <PageTitle title="Smart Dashboard" subtitle="Live status, learned patterns, and the next best action." />
      {intel?.warnings.map((warning) => <div key={warning.text} className={cn("rounded-md border p-4 text-sm", warning.level === "red" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-700")}><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><span>{warning.text}</span><Button asChild variant="outline"><Link href={warning.href}>Fix Now</Link></Button></div></div>)}
      <DashboardHintsCard />
      {!pages.length ? <ConnectEmpty onConnected={onConnected} /> : <ConnectedPagesSection pages={pages} onConnected={onConnected} />}
      <section className="grid gap-4 md:grid-cols-3">
        <Stat label="Posts Published This Month" value={published} tone="green" />
        <Stat label="Posts Scheduled" value={scheduled} tone="amber" />
        <Stat label="Posts Failed" value={failed} tone="red" />
      </section>
      {intel ? <section className="grid gap-4 lg:grid-cols-3">
        <Card><CardHeader><CardTitle>What Is Happening Right Now</CardTitle></CardHeader><CardContent className="grid gap-3 text-sm"><div><p className="font-medium">Next scheduled post</p><p className="text-slate-500">{intel.next_scheduled_post ? `Publishes in ${intel.next_scheduled_post.minutes_until} minutes` : "No scheduled post"}</p></div><div><p className="font-medium">Last published post</p><p className="line-clamp-2 text-slate-500">{intel.last_published_post?.content || "No published posts yet"}</p>{intel.last_published_post ? <p className="mt-1 text-xs text-slate-500">Likes {intel.last_published_post.likes_count} · Comments {intel.last_published_post.comments_count} · Shares {intel.last_published_post.shares_count} · Score {intel.last_published_post.engagement_score.toFixed(1)}</p> : null}</div><div><p className="font-medium">System health</p><p className={cn("flex items-center gap-2", intel.cron_health.ok ? "text-green-700" : "text-red-700")}><span className={cn("size-2 rounded-full", intel.cron_health.ok ? "bg-green-600" : "bg-red-600")} />Cron {intel.cron_health.ok ? "healthy" : "needs attention"}</p><p className="text-xs text-slate-500">{intel.facebook_connections.every((page) => page.status === "connected") ? "Facebook connections healthy" : "A Facebook page needs attention"}</p></div></CardContent></Card>
        {!onboardingDone ? <Card><CardHeader><CardTitle>Contextual Onboarding</CardTitle></CardHeader><CardContent className="grid gap-2">{intel.onboarding_steps.map((step, index) => <div key={step.label} className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm"><span className={step.done ? "text-slate-500 line-through" : "font-medium"}>{index + 1}. {step.label}</span>{step.done ? <span className="text-green-700">Done</span> : <Button asChild size="sm" variant="outline"><Link href={step.href}>Do this now</Link></Button>}</div>)}</CardContent></Card> : <LearnedInsightsPanel insights={intel.learned_insights} />}
        <Card><CardHeader><CardTitle>What You Should Do Next</CardTitle></CardHeader><CardContent className="grid gap-3">{intel.action_items.map((item) => <div key={item.id} className="grid gap-2 rounded-md border p-3 text-sm"><p>{item.text}</p><Button asChild className="w-fit bg-blue-700 hover:bg-blue-800"><Link href={item.href}>{item.action_label}</Link></Button></div>)}{!intel.action_items.length ? <p className="text-sm text-slate-500">No urgent actions. Keep publishing and let the system gather more signal.</p> : null}</CardContent></Card>
      </section> : null}
      {intel && onboardingDone ? <LearnedInsightsPanel insights={intel.learned_insights} wide /> : null}
      <Card><CardHeader><CardTitle>Recent Activity</CardTitle></CardHeader><CardContent className="grid gap-3">{posts.slice(0, 10).map((post) => <PostRow key={post.id} post={post} timezone={timezone} />)} {!posts.length ? <Empty text="No activity yet." action="/dashboard/create" /> : null}</CardContent></Card>
    </>
  )
}

function LearnedInsightsPanel({ insights, wide }: { insights: DashboardIntelligence["learned_insights"]; wide?: boolean }) {
  const items = [
    { label: "Best post, last 7 days", value: insights.best_post ? `Score ${insights.best_post.score.toFixed(1)}` : "Not enough data", detail: insights.best_post?.insight },
    { label: "Best time slot", value: insights.best_time_slot ? `${insights.best_time_slot.slot}` : "Not enough data", detail: insights.best_time_slot?.insight },
    { label: "Best persona", value: insights.best_persona ? insights.best_persona.name : "Not enough data", detail: insights.best_persona?.insight },
  ]
  return <Card className={wide ? "" : ""}><CardHeader><CardTitle>What The System Has Learned</CardTitle></CardHeader><CardContent className={cn("grid gap-3", wide && "md:grid-cols-3")}>{items.map((item) => <div key={item.label} className="rounded-md border p-3"><p className="text-sm text-slate-500">{item.label}</p><p className="mt-1 font-semibold">{item.value}</p><p className="mt-2 text-sm text-slate-600">{item.detail || "Publish more posts and collect engagement snapshots to unlock this insight."}</p></div>)}</CardContent></Card>
}

function ConnectEmpty({ onConnected }: { onConnected: () => void }) {
  return <Card><CardContent className="grid gap-4 p-6 text-center"><Plug className="mx-auto size-10 text-blue-700" /><div><h2 className="text-lg font-semibold">You have no connected pages yet.</h2><p className="text-sm text-slate-500">Connect your first Facebook Page.</p></div><FacebookConnectButton className="mx-auto" onConnected={onConnected} /></CardContent></Card>
}

function FacebookConnectButton({ onConnected, className, urgent }: { onConnected: () => void; className?: string; urgent?: boolean }) {
  const [busy, setBusy] = React.useState(false)
  const connectionSucceededRef = React.useRef(false)
  const popupCheckerRef = React.useRef<number | null>(null)

  function isAllowedOrigin(origin: string) {
    return origin === BACKEND_ORIGIN || origin === window.location.origin
  }

  function connect() {
    setBusy(true)
    connectionSucceededRef.current = false

    const handleMessage = (event: MessageEvent) => {
      if (!isAllowedOrigin(event.origin)) return
      if (event.data?.type === "FACEBOOK_CONNECT_SUCCESS") {
        connectionSucceededRef.current = true
        window.removeEventListener("message", handleMessage)
        if (popupCheckerRef.current !== null) {
          window.clearInterval(popupCheckerRef.current)
          popupCheckerRef.current = null
        }
        setBusy(false)
        onConnected()
        toast.success("Facebook Page connected successfully")
      } else if (event.data?.type === "FACEBOOK_CONNECT_ERROR") {
        connectionSucceededRef.current = true
        window.removeEventListener("message", handleMessage)
        if (popupCheckerRef.current !== null) {
          window.clearInterval(popupCheckerRef.current)
          popupCheckerRef.current = null
        }
        setBusy(false)
        toast.error(event.data.message || "Connection failed.")
      }
    }

    window.addEventListener("message", handleMessage)

    try {
      const token = window.localStorage.getItem("auth_token")
      if (!token) throw new Error("Missing auth token")
      const width = 600
      const height = 700
      const left = window.screenX + (window.outerWidth - width) / 2
      const top = window.screenY + (window.outerHeight - height) / 2
      const popup = window.open(
        `${API_BASE_URL}/auth/facebook/start?token=${encodeURIComponent(token)}`,
        "facebook_oauth",
        `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes`
      )
      if (!popup) throw new Error("Popup blocked")

      popupCheckerRef.current = window.setInterval(() => {
        if (popup.closed) {
          if (popupCheckerRef.current !== null) {
            window.clearInterval(popupCheckerRef.current)
            popupCheckerRef.current = null
          }
          window.removeEventListener("message", handleMessage)
          setBusy(false)
          if (!connectionSucceededRef.current) {
            toast.info("Connection cancelled")
          }
        }
      }, 500)
    } catch {
      window.removeEventListener("message", handleMessage)
      if (popupCheckerRef.current !== null) {
        window.clearInterval(popupCheckerRef.current)
        popupCheckerRef.current = null
      }
      toast.error("Could not open the Facebook connection window.")
      setBusy(false)
    }
  }

  return (
    <Button
      className={cn(
        urgent ? "bg-amber-600 text-white hover:bg-amber-700" : "bg-[#1877F2] text-white hover:bg-[#0f66d0]",
        className
      )}
      onClick={connect}
      disabled={busy}
    >
      {busy ? <Loader2 className="size-4 animate-spin" /> : <span className="grid size-4 place-items-center rounded-full bg-white text-xs font-bold text-[#1877F2]">f</span>}
      {busy ? "Connecting..." : urgent ? "Reconnect Now" : "Connect Facebook Page"}
    </Button>
  )
}

function Composer({ pages, timezone, onSaved }: { pages: PageConnection[]; timezone: string; onSaved: () => void }) {
  const router = useRouter()
  const publishablePages = pages.filter((page) => page.connection_status === "connected")
  const [selectedPageId, setSelectedPageId] = React.useState<number | null>(publishablePages[0]?.id ?? null)
  const [content, setContent] = React.useState("")
  const [media, setMedia] = React.useState("")
  const [scheduleLater, setScheduleLater] = React.useState(false)
  const [scheduledAt, setScheduledAt] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  const [aiSettingsReady, setAiSettingsReady] = React.useState(false)
  const [topicHint, setTopicHint] = React.useState("")
  const [generating, setGenerating] = React.useState(false)
  const [hasAiDraft, setHasAiDraft] = React.useState(false)
  const remaining = 63206 - content.length
  const selectedPage = publishablePages.find((page) => page.id === selectedPageId) || publishablePages[0]
  const url = content.match(/https?:\/\/\S+/)?.[0] || ""
  const [templates, setTemplates] = React.useState<any[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = React.useState<string>("")
  const [visualTopic, setVisualTopic] = React.useState("")
  const [generatingLayered, setGeneratingLayered] = React.useState(false)

  React.useEffect(() => {
    api.get<any[]>("/api/images/templates")
      .then((res) => setTemplates(res.data))
      .catch((err) => console.error("Error loading templates:", err))
  }, [])

  React.useEffect(() => {
    if (!selectedPage?.id) return setAiSettingsReady(false)
    api.get<AIPersona | null>(`/api/ai/settings/${selectedPage.id}`)
      .then((response) => setAiSettingsReady(Boolean(response.data?.niche)))
      .catch(() => setAiSettingsReady(false))
  }, [selectedPage?.id])
  async function generateWithAI() {
    if (!selectedPage) return toast.error("Connect a page before generating.")
    setGenerating(true)
    try {
      const response = await api.post<{ content: string }>("/api/ai/generate", {
        page_connection_id: selectedPage.id,
        topic_hint: topicHint || null,
      })
      setContent(response.data.content)
      setHasAiDraft(true)
      toast.success("AI draft generated.")
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || "AI generation failed.")
    } finally {
      setGenerating(false)
    }
  }

  async function generateLayeredGraphic() {
    if (!selectedTemplateId) return toast.error("Please select a template first.")
    const topic = visualTopic || topicHint || "Product"
    setGeneratingLayered(true)
    try {
      const response = await api.post("/api/images/generate-layered", {
        template_id: selectedTemplateId,
        topic: topic,
        post_text: content
      })
      setMedia(response.data.image_url)
      toast.success("Layered image generated and composited successfully!")
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Layered graphic generation failed.")
    } finally {
      setGeneratingLayered(false)
    }
  }
  async function submit(saveAsDraft = false) {
    if (!content.trim()) return toast.error("Write post content first.")
    if (!selectedPage) return toast.error("Connect a page before publishing.")
    if (remaining < 0) return toast.error("Post too long")
    setSaving(true)
    try {
      const response = await api.post<{ success: boolean; error_message?: string }>("/posts/publish", {
        message: content,
        page_connection_id: selectedPage.id,
        media_urls: media ? [media] : [],
        link_url: url || null,
        link_preview_data: url ? { title: url, description: "Link preview detected from your post text." } : null,
        scheduled_at: scheduleLater && scheduledAt ? new Date(scheduledAt).toISOString() : null,
        save_as_draft: saveAsDraft,
      })
      if (!response.data.success && !saveAsDraft && !scheduleLater) {
        toast.error(response.data.error_message || "Publishing failed. Please try again.")
        onSaved()
        return
      }
      toast.success(saveAsDraft ? "Draft saved." : scheduleLater ? `Scheduled for ${formatDate(new Date(scheduledAt).toISOString(), timezone)}.` : "Your post was published to Facebook successfully.")
      if (!saveAsDraft && !scheduleLater) setContent("")
      onSaved()
      router.push(scheduleLater ? "/dashboard/scheduled" : "/dashboard")
    } catch (error: any) {
      toast.error(getApiErrorMessage(error, "Publishing failed. Please try again."))
    } finally {
      setSaving(false)
    }
  }
  return (
    <>
      <PageTitle title="Create Post" subtitle="Compose, preview, publish now, or schedule for later." />
      <Card><CardContent className="grid gap-5 p-6">
        {publishablePages.length > 1 ? <Select value={String(selectedPageId ?? publishablePages[0].id)} onChange={(event) => setSelectedPageId(Number(event.target.value))}>{publishablePages.map((page) => <option key={page.id} value={String(page.id)}>{page.page_name}</option>)}</Select> : publishablePages[0] ? <PageMini page={publishablePages[0]} /> : <Empty text="Connect a page before publishing." action="/dashboard/settings" />}
        {selectedPage ? <div className="grid gap-3 rounded-md border border-purple-200 bg-purple-50/60 p-3">
          <div className="flex flex-col gap-2 lg:flex-row">
            {aiSettingsReady ? <>
              <Input value={topicHint} onChange={(event) => setTopicHint(event.target.value)} placeholder="Optional: give a topic hint, e.g. morning motivation, new year tips." />
              <Button className="bg-purple-700 text-white hover:bg-purple-800" onClick={generateWithAI} disabled={generating}>
                {generating ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                {generating ? "Generating..." : hasAiDraft ? "Regenerate" : "Generate with AI"}
              </Button>
            </> : <Button asChild variant="outline"><Link href="/dashboard/ai-settings">Set up an AI persona</Link></Button>}
          </div>
        </div> : null}
        <div className="grid gap-2"><Label>Post content</Label><Textarea className="min-h-56" placeholder="Write your post..." value={content} onChange={(event) => setContent(event.target.value)} /></div>
        {hasAiDraft ? <p className="text-sm text-purple-700">Generated by AI - feel free to edit before publishing.</p> : null}
        <div className={cn("text-right text-sm", remaining < 100 ? "text-red-600" : remaining < 500 ? "text-amber-600" : "text-slate-500")}>{content.length} / 63,206 characters</div>
        <div className="grid gap-2 border border-slate-200 rounded-md p-4 bg-slate-50">
          <Label>Use Image Template</Label>
          <Select value={selectedTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)}>
            <option value="">No Template (Direct Upload/Generate)</option>
            {templates.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>{tpl.name}</option>
            ))}
          </Select>
          
          {selectedTemplateId ? (
            <div className="grid gap-4 mt-3 animate-in fade-in duration-300">
              <div className="grid gap-2">
                <Label>Graphic Topic</Label>
                <Input
                  value={visualTopic}
                  onChange={(e) => setVisualTopic(e.target.value)}
                  placeholder="e.g. Modern Office Workspace (Defaults to topic hint or topic name)"
                />
              </div>
              <Button
                type="button"
                className="bg-purple-700 hover:bg-purple-800 text-white w-full"
                onClick={generateLayeredGraphic}
                disabled={generatingLayered}
              >
                {generatingLayered ? <Loader2 className="size-4 animate-spin mr-2" /> : <Sparkles className="size-4 mr-2" />}
                {generatingLayered ? "Generating & Compositing Design..." : "Generate & Composite Layered Graphic"}
              </Button>
              
              {/* Dynamic Design Layer Preview */}
              <div className="mt-3">
                <Label className="mb-2 block text-xs font-semibold uppercase text-slate-500">Live Design Compositor Preview</Label>
                <div className="relative aspect-square w-full max-w-sm mx-auto overflow-hidden rounded-md border bg-gradient-to-tr from-slate-900 to-indigo-950 text-white p-4 flex flex-col justify-between">
                  {media ? (
                    <img src={media} alt="Composited Graphic" className="absolute inset-0 h-full w-full object-cover z-0" />
                  ) : null}
                  
                  {/* Simulated Layers when media is not rendered yet */}
                  {!media && (() => {
                    const tpl = templates.find((t) => t.id === selectedTemplateId);
                    if (!tpl) return null;
                    const logo = tpl.layers_json?.logo_position;
                    const text_boxes = tpl.layers_json?.text_boxes || [];
                    return (
                      <div className="absolute inset-0 z-10 w-full h-full pointer-events-none">
                        {logo ? (
                          <div
                            className="absolute bg-white/20 border border-dashed border-white/50 flex items-center justify-center text-[10px]"
                            style={{
                              left: `${logo.x_pct}%`,
                              top: `${logo.y_pct}%`,
                              width: `${logo.width_pct}%`,
                              height: `${logo.height_pct}%`
                            }}
                          >
                            [LOGO]
                          </div>
                        ) : null}
                        {text_boxes.map((box: any, i: number) => (
                          <div
                            key={i}
                            className="absolute bg-black/40 border border-dashed border-purple-400/50 p-1 text-[10px] rounded"
                            style={{
                              left: `${box.x_pct}%`,
                              top: `${box.y_pct}%`,
                              transform: box.alignment === 'center' ? 'translateX(-50%)' : box.alignment === 'right' ? 'translateX(-100%)' : 'none',
                              color: box.color_hex || '#FFFFFF',
                              textAlign: box.alignment || 'left'
                            }}
                          >
                            {box.purpose || 'Text Layer'}
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                  
                  {/* Overlay text in mockup mode if no generated image */}
                  {!media ? (
                    <div className="absolute bottom-2 left-2 z-10 bg-black/60 rounded px-2 py-1 text-[10px] text-slate-300">
                      Mockup layout (Click Generate above to render actual layout via backend)
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid gap-2"><Label>Image or video URL</Label><Input value={media} onChange={(event) => setMedia(event.target.value)} placeholder="https://example.com/media.jpg" /></div>
        {url ? <div className="flex items-start justify-between rounded-md border bg-slate-50 p-3 text-sm"><div><p className="font-medium">Link Preview</p><p className="text-slate-500">{url}</p></div><Button size="icon" variant="ghost" onClick={() => setContent(content.replace(url, ""))}><X className="size-4" /></Button></div> : null}
        <div className="flex items-center justify-between rounded-md border p-3"><div><p className="font-medium">Schedule for Later</p><p className="text-sm text-slate-500">{timezone}</p></div><Switch checked={scheduleLater} onCheckedChange={setScheduleLater} /></div>
        {scheduleLater ? <Input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /> : null}
        <div className="flex flex-col gap-2 sm:flex-row"><Button variant="outline" onClick={() => submit(true)} disabled={saving}>Save as Draft</Button><Button title={remaining < 0 ? "Post too long" : undefined} className="bg-blue-700 hover:bg-blue-800" onClick={() => submit(false)} disabled={saving || remaining < 0 || !content.trim() || !publishablePages.length}>{saving ? "Publishing..." : scheduleLater ? "Schedule" : "Publish to Facebook"}</Button><Button variant="ghost" onClick={() => router.push("/dashboard")}>Cancel</Button></div>
      </CardContent></Card>
    </>
  )
}

function StyleAnalyzerView({ pages }: { pages: PageConnection[] }) {
  const router = useRouter()
  const [step, setStep] = React.useState<"input" | "more_posts" | "analyzing">("input")
  const [primaryPost, setPrimaryPost] = React.useState("")
  const [extraPosts, setExtraPost] = React.useState("")
  const [loadingStep, setLoadingStep] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (step !== "analyzing") { setLoadingStep(""); return }
    const steps = [
      "Reading your writing style...",
      "Detecting tone and patterns...",
      "Identifying your content topics...",
      "Mapping your audience signals...",
      "Building your persona profile...",
    ]
    let i = 0
    setLoadingStep(steps[0])
    const interval = setInterval(() => {
      i = Math.min(i + 1, steps.length - 1)
      setLoadingStep(steps[i])
    }, 2200)
    return () => clearInterval(interval)
  }, [step])

  async function startAnalysis() {
    if (!primaryPost.trim()) return toast.error("Please paste at least one post first.")
    setStep("more_posts")
  }

  async function runAnalysis(skipExtra = false) {
    setStep("analyzing")
    setError(null)
    try {
      const allPosts = [primaryPost.trim()]
      if (!skipExtra && extraPosts.trim()) {
        const extras = extraPosts.split(/\n\n+/).filter((p) => p.trim())
        allPosts.push(...extras)
      }
      const response = await api.post("/api/ai/generate-persona-from-posts", { posts: allPosts })
      localStorage.setItem("ai_persona_prefill", JSON.stringify(response.data))
      toast.success("Persona generated! Opening Prompt Studio...")
      setTimeout(() => router.push("/dashboard/ai-settings"), 1200)
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not generate persona. Check your AI model in Settings and try again.")
      setStep("input")
    }
  }

  if (step === "analyzing") {
    return (
      <>
        <PageTitle title="Style Analyzer" subtitle="Analyzing your posts and building your AI persona…" aiPowered />
        <Card>
          <CardContent className="flex flex-col items-center gap-8 py-16">
            <div className="size-20 rounded-full bg-purple-100 flex items-center justify-center">
              <Sparkles className="size-9 text-purple-600 animate-pulse" />
            </div>
            <div className="text-center grid gap-2">
              <p className="text-lg font-semibold text-slate-800">{loadingStep}</p>
              <p className="text-sm text-slate-500">This usually takes 10–20 seconds…</p>
            </div>
            <div className="w-full max-w-xs h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-2 bg-purple-600 rounded-full animate-pulse" style={{ width: "65%" }} />
            </div>
          </CardContent>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageTitle title="Style Analyzer" subtitle="Paste your posts and let the AI build a persona that perfectly matches your writing style." aiPowered />

      {step === "more_posts" ? (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="size-5 text-purple-600" />
                Want a more accurate persona?
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <p className="text-sm text-slate-600">
                Your first post is ready. Add more sample posts below (optional) — the more examples you provide, the sharper and more tailored your generated persona will be.
              </p>
              <p className="text-xs text-slate-400">Tip: Separate each post with a blank line.</p>
              <Textarea
                className="min-h-44"
                placeholder={"Post 2 content...\n\nPost 3 content...\n\nPost 4 content..."}
                value={extraPosts}
                onChange={(e) => setExtraPost(e.target.value)}
              />
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button id="run-analysis-btn" className="flex-1 bg-purple-700 hover:bg-purple-800" onClick={() => runAnalysis(false)}>
                  <Sparkles className="size-4 mr-2" />
                  {extraPosts.trim() ? "Add More & Analyze" : "Analyze Now"}
                </Button>
                <Button variant="outline" className="flex-1" onClick={() => runAnalysis(true)}>
                  Skip, Analyze with 1 Post
                </Button>
                <Button variant="ghost" onClick={() => setStep("input")}>Back</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Paste Your Post(s)</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <p className="text-sm text-slate-500">
            Paste one or more of your real social-media posts. The AI will analyze tone, topics, audience, structure, and writing patterns — then automatically build a complete AI persona in Prompt Studio.
          </p>
          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
          ) : null}
          <Textarea
            id="style-analyzer-input"
            className="min-h-52"
            placeholder={"Paste your post here…\n\nYou can also paste multiple posts — just leave a blank line between each one."}
            value={primaryPost}
            onChange={(e) => setPrimaryPost(e.target.value)}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-slate-400">
              {primaryPost.trim()
                ? `${primaryPost.trim().split(/\s+/).length} words · ${primaryPost.split(/\n\n+/).filter((p) => p.trim()).length} post(s) detected`
                : "Paste your content above to get started"}
            </p>
            <Button
              id="analyze-style-btn"
              className="bg-purple-700 hover:bg-purple-800"
              onClick={startAnalysis}
              disabled={!primaryPost.trim()}
            >
              <Sparkles className="size-4 mr-2" />
              Analyze &amp; Build Persona
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>How it works</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="grid gap-4 text-sm text-slate-600">
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 size-6 rounded-full bg-purple-100 text-purple-700 font-semibold text-xs flex items-center justify-center mt-0.5">1</span>
              <span>Paste one or more of your real posts. The AI reads the tone, rhythm, topics, and patterns across everything you share.</span>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 size-6 rounded-full bg-purple-100 text-purple-700 font-semibold text-xs flex items-center justify-center mt-0.5">2</span>
              <span>Optionally add more posts for a richer sample — more examples = sharper persona with better audience targeting.</span>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 size-6 rounded-full bg-purple-100 text-purple-700 font-semibold text-xs flex items-center justify-center mt-0.5">3</span>
              <span>A complete AI persona is generated and auto-filled in Prompt Studio. You only need to assign which days it posts on.</span>
            </li>
          </ol>
        </CardContent>
      </Card>
    </>
  )
}

function PageTrackerView({ pages }: { pages: PageConnection[] }) {
  const [data, setData] = React.useState<TrackerDashboard | null>(null)
  const [url, setUrl] = React.useState("")
  const [name, setName] = React.useState("")
  const [addingPostsFor, setAddingPostsFor] = React.useState<any | null>(null)
  const [manualPosts, setManualPosts] = React.useState("")
  const [loading, setLoading] = React.useState(false)
  const [personas, setPersonas] = React.useState<AIPersona[]>([])
  const [personaId, setPersonaId] = React.useState("")
  const [visibleCount, setVisibleCount] = React.useState(10)
  const loaderRef = React.useRef<HTMLDivElement>(null)
  const selectedPage = pages[0]
  const load = React.useCallback(() => api.get<TrackerDashboard>("/api/tracker").then((response) => setData(response.data)), [])
  React.useEffect(() => { load().catch(() => setData(null)) }, [load])
  React.useEffect(() => {
    if (!selectedPage?.id) return
    api.get<AIPersona[]>(`/api/ai/personas/${selectedPage.id}`).then((response) => setPersonas(response.data)).catch(() => setPersonas([]))
  }, [selectedPage?.id])

  React.useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        setVisibleCount((v) => v + 10)
      }
    }, { threshold: 0.1 })
    if (loaderRef.current) observer.observe(loaderRef.current)
    return () => observer.disconnect()
  }, [])
  async function addPage() {
    if (!url || !name) return toast.error("Provide URL and Name.")
    setLoading(true)
    try {
      await api.post("/api/tracker/pages", { url, name })
      setUrl("")
      setName("")
      toast.success("Page added to tracker.")
      await load()
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || "Could not add page.")
    } finally {
      setLoading(false)
    }
  }
  async function submitManualPosts() {
    if (!manualPosts.trim()) return
    setLoading(true)
    try {
      const postsArray = manualPosts.split("\n\n").filter((p) => p.trim())
      await api.post(`/api/tracker/pages/${addingPostsFor.id}/posts`, { posts: postsArray })
      setManualPosts("")
      setAddingPostsFor(null)
      toast.success("Posts added successfully.")
      await load()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Could not add posts.")
    } finally {
      setLoading(false)
    }
  }
  async function useInspiration(content: string) {
    if (!personaId) return toast.error("Choose a persona first.")
    await api.post("/api/style/apply", { persona_id: Number(personaId), inspiration_post: content })
    toast.success("Post added as style inspiration.")
  }
  return <><PageTitle title="Page Tracker" subtitle="Track public pages, spot winning posts, and borrow style inspiration responsibly." aiPowered /><Sheet open={!!addingPostsFor} onOpenChange={(open) => !open && setAddingPostsFor(null)}><SheetContent className="overflow-y-auto w-full max-w-md"><div className="grid gap-4 mt-6"><h2 className="text-lg font-semibold">Add Posts to {addingPostsFor?.nickname}</h2><p className="text-sm text-slate-500">Paste recent posts from this page. Separate multiple posts by double newlines.</p><Textarea className="min-h-64" value={manualPosts} onChange={(e) => setManualPosts(e.target.value)} placeholder="Post 1 content...&#10;&#10;Post 2 content..." /><Button onClick={submitManualPosts} disabled={loading}>{loading ? <Loader2 className="size-4 animate-spin mr-2" /> : null} Save Posts</Button></div></SheetContent></Sheet><Card><CardContent className="grid gap-3 p-5"><div className="grid gap-2 md:grid-cols-[1fr_220px_auto]"><Input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Facebook Page URL" /><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Page Name" /><Button className="bg-blue-700 hover:bg-blue-800" onClick={addPage} disabled={loading}>Add Page</Button></div><Select className="max-w-sm" value={personaId} onChange={(event) => setPersonaId(event.target.value)}><option value="">Persona for style inspiration</option>{personas.map((persona) => <option key={persona.id} value={persona.id}>{persona.persona_name}</option>)}</Select><p className="text-xs text-slate-500">{data?.tracked_pages.length || 0}/10 pages tracked.</p></CardContent></Card>{data?.trends.map((trend) => <div key={trend.id} className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><span>{trend.summary}</span><Button asChild variant="outline"><Link href={`/dashboard/create?topic=${encodeURIComponent(trend.topic)}`}>Generate</Link></Button></div></div>)}<Card><CardHeader><CardTitle>Top Tracked Posts This Week</CardTitle></CardHeader><CardContent className="grid gap-3">{data?.posts.slice(0, visibleCount).map((post) => <div key={post.id} className="grid gap-2 rounded-md border p-3"><div className="flex flex-wrap justify-between gap-2 text-sm"><span className="font-medium">{post.page_name}</span><span className="text-slate-500">Score {post.engagement_score.toFixed(1)}</span></div><p className="whitespace-pre-wrap text-sm text-slate-700">{post.content}</p><p className="text-xs text-slate-500">Likes {post.likes_count} · Comments {post.comments_count} · Shares {post.shares_count} · Topic {post.topic || "-"}</p><Button variant="outline" className="w-fit" onClick={() => useInspiration(post.content)}>Use This as Style Inspiration</Button></div>)}{!data?.posts.length ? <p className="text-sm text-slate-500">No tracked posts yet. Add a page to start collecting examples.</p> : null}{data?.posts && data.posts.length > visibleCount ? <div ref={loaderRef} className="py-4 text-center text-slate-500 flex justify-center"><Loader2 className="size-4 animate-spin" /></div> : null}</CardContent></Card><Card><CardHeader><CardTitle>Weekly Comparison</CardTitle></CardHeader><CardContent className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="text-left text-slate-500"><th className="p-2">Page</th><th className="p-2">Posts</th><th className="p-2">Avg Likes</th><th className="p-2">Avg Comments</th><th className="p-2">Avg Shares</th><th className="p-2">Active Day</th><th className="p-2">Topics</th><th className="p-2">Actions</th></tr></thead><tbody>{data?.comparison.map((row) => <tr key={row.id} className="border-t"><td className="p-2 font-medium">{row.nickname}</td><td className="p-2">{row.posts}</td><td className="p-2">{row.average_likes}</td><td className="p-2">{row.average_comments}</td><td className="p-2">{row.average_shares}</td><td className="p-2">{row.most_active_day}</td><td className="p-2">{row.most_used_topics}</td><td className="p-2"><Button variant="outline" size="sm" onClick={() => setAddingPostsFor(row)}>Add Posts</Button></td></tr>)}</tbody></table></CardContent></Card></>
}

function MiniBars({ items }: { items: { label: string; value: number }[] }) {
  const max = Math.max(...items.map((item) => item.value), 1)
  return <div className="grid gap-2">{items.slice(0, 12).map((item) => <div key={item.label} className="grid grid-cols-[64px_1fr_56px] items-center gap-2 text-xs"><span>{item.label}</span><div className="h-3 rounded bg-slate-100"><div className="h-3 rounded bg-blue-700" style={{ width: `${Math.max(4, (item.value / max) * 100)}%` }} /></div><span className="text-right text-slate-500">{item.value.toFixed(1)}</span></div>)}</div>
}

const toneOptions = ["Friendly", "Professional", "Bold", "Witty", "Empathetic", "Authoritative", "Casual", "Luxury", "Rebellious", "Minimalist", "Energetic", "Calm"]
const languages = ["English", "Bengali", "Hindi", "Arabic", "Spanish", "French", "Indonesian", "Portuguese", "Auto-detect from examples"]
const dayOptions = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const personaColors = ["bg-blue-50 text-blue-800 border-blue-200", "bg-emerald-50 text-emerald-800 border-emerald-200", "bg-amber-50 text-amber-800 border-amber-200", "bg-rose-50 text-rose-800 border-rose-200", "bg-violet-50 text-violet-800 border-violet-200"]
const templateNames = ["Custom (blank)", "E-commerce Product Page", "Personal Brand / Creator", "Local Restaurant", "Real Estate Agent", "Fitness Coach", "Educational Content", "News and Commentary", "Motivational Page", "Tech and Startup"]
const goalOptions = ["Educate my audience", "Sell a product or service", "Build a community", "Entertain", "Inspire and motivate", "Drive traffic to my website"]
const includeOptions = ["A question at the end", "A call to action", "Emojis", "A personal story angle", "A surprising fact", "A numbered list", "A relatable struggle"]
const neverOptions = ["Use formal language", "Use slang", "Make promises", "Use more than 5 hashtags", "Start with the word 'I'", "Use exclamation marks excessively"]
const structureOptions = ["No fixed structure, let AI decide", "Hook then value then CTA", "Story then lesson then question", "Fact then explanation then opinion", "List format", "Single powerful statement"]
const llmProviderModels: Record<string, string[]> = {
  mistral: ["mistral-large-latest", "mistral-small-latest"],
  gemini: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
}

type ModelPreference = {
  provider_name: string
  model_name: string
  configured?: boolean
}

type ModelProviderOption = {
  id: string
  label: string
  models: { id: string; label: string }[]
  configured: boolean
}

function emptyPromptConfig(): PromptStudioConfig {
  return {
    template: "Custom (blank)",
    audience: "",
    goal: "Educate my audience",
    brand_personality: ["Friendly", "Professional"],
    always_topics: [],
    never_topics: [],
    every_post_includes: ["A question at the end"],
    never_do: ["Make promises"],
    length: "Medium",
    vary_length: true,
    structure: "No fixed structure, let AI decide",
    examples: "",
  }
}

type PersonaTemplateDefault = Omit<Partial<AIPersona>, "prompt_config"> & { prompt_config?: Partial<PromptStudioConfig> }

const templateDefaults: Record<string, PersonaTemplateDefault> = {
  "E-commerce Product Page": { niche: "products that help customers solve everyday problems", tone_tags: ["Friendly", "Professional"], prompt_config: { goal: "Sell a product or service", every_post_includes: ["A call to action", "A question at the end"], structure: "Hook then value then CTA" } },
  "Personal Brand / Creator": { niche: "personal stories, lessons, and useful ideas from a creator", tone_tags: ["Friendly", "Casual"], prompt_config: { goal: "Build a community", every_post_includes: ["A personal story angle", "A question at the end"], structure: "Story then lesson then question" } },
  "Local Restaurant": { niche: "local food, menu highlights, offers, and community moments", tone_tags: ["Friendly", "Energetic"], prompt_config: { goal: "Sell a product or service", every_post_includes: ["Emojis", "A call to action"], structure: "Hook then value then CTA" } },
  "Real Estate Agent": { niche: "real estate advice, market updates, and property buying guidance", tone_tags: ["Professional", "Authoritative"], prompt_config: { goal: "Educate my audience", structure: "Fact then explanation then opinion" } },
  "Fitness Coach": { niche: "fitness, nutrition, consistency, and healthy lifestyle coaching", tone_tags: ["Energetic", "Empathetic"], prompt_config: { goal: "Inspire and motivate", every_post_includes: ["A relatable struggle", "A call to action"] } },
  "Educational Content": { niche: "clear educational posts that make complex topics simple", tone_tags: ["Professional", "Friendly"], prompt_config: { goal: "Educate my audience", every_post_includes: ["A surprising fact", "A question at the end"], structure: "Fact then explanation then opinion" } },
  "News and Commentary": { niche: "timely news, commentary, and analysis", tone_tags: ["Authoritative", "Professional"], prompt_config: { goal: "Educate my audience", structure: "Fact then explanation then opinion" } },
  "Motivational Page": { niche: "motivation, mindset, discipline, and personal growth", tone_tags: ["Bold", "Empathetic"], prompt_config: { goal: "Inspire and motivate", structure: "Single powerful statement" } },
  "Tech and Startup": { niche: "technology, startups, product building, and business lessons", tone_tags: ["Witty", "Professional"], prompt_config: { goal: "Educate my audience", structure: "Hook then value then CTA" } },
}

function emptyPersona(): AIPersona {
  return {
    persona_name: "",
    niche: "",
    tone_tags: ["Professional"],
    custom_instructions: "",
    prompt_config: emptyPromptConfig(),
    custom_prompt: "",
    creativity_level: 7,
    language: "English",
    hashtags_enabled: false,
    hashtag_count: 5,
    always_include_engagement_hook: false,
    assigned_days: [],
    posting_time_slots: ["09:00"],
    priority_level: "Normal",
    is_active: true,
    learning_mode_enabled: true,
    minimum_engagement_threshold: 0,
  }
}

function promptConfig(persona: AIPersona): PromptStudioConfig {
  return { ...emptyPromptConfig(), ...(persona.prompt_config || {}), brand_personality: persona.tone_tags.length ? persona.tone_tags : persona.prompt_config?.brand_personality || [] }
}

function buildSimplePrompt(persona: AIPersona) {
  const config = promptConfig(persona)
  const parts = [
    `Write a Facebook post for a page about ${persona.niche || "[what this page is about]"}.`,
    config.audience ? `The audience is ${config.audience}.` : "",
    config.goal ? `The main goal is to ${config.goal.toLowerCase()}.` : "",
    persona.tone_tags.length ? `Use a ${persona.tone_tags.join(", ").toLowerCase()} brand personality.` : "",
    config.always_topics.length ? `Always write about: ${config.always_topics.join(", ")}.` : "",
    config.never_topics.length ? `Never write about: ${config.never_topics.join(", ")}.` : "",
    config.every_post_includes.length ? `Every post should include: ${config.every_post_includes.join(", ")}.` : "",
    config.never_do.length ? `Posts must never: ${config.never_do.join(", ").toLowerCase()}.` : "",
    config.vary_length ? `Vary post length, rotating around ${config.length.toLowerCase()} posts.` : `Aim for ${config.length.toLowerCase()} length.`,
    config.structure !== "No fixed structure, let AI decide" ? `Structure posts as: ${config.structure}.` : "Use the best structure for the idea.",
    persona.language ? `Write in ${persona.language}.` : "",
    config.examples ? `Study these style examples and match their feel:\n${config.examples}` : "",
    persona.custom_instructions ? persona.custom_instructions : "",
  ].filter(Boolean)
  return parts.join(" ")
}

function buildRawPrompt(persona: AIPersona) {
  return [
    "SYSTEM: You are a professional Facebook content writer. Return only the finished post text, with no labels or commentary.",
    `CREATIVITY: ${persona.creativity_level}/10.`,
    `USER PROMPT: ${buildSimplePrompt(persona)}`,
  ].join("\n\n")
}

function applyTemplate(persona: AIPersona, template: string): AIPersona {
  const baseConfig = promptConfig(persona)
  const defaults = templateDefaults[template] || {}
  return {
    ...persona,
    ...defaults,
    prompt_config: { ...baseConfig, ...(defaults.prompt_config || {}), template },
    tone_tags: defaults.tone_tags || persona.tone_tags,
  }
}

function AISettingsView({ pages }: { pages: PageConnection[] }) {
  const [selectedPageId, setSelectedPageId] = React.useState<number | null>(pages[0]?.id ?? null)
  const [personas, setPersonas] = React.useState<AIPersona[]>([])
  const [editing, setEditing] = React.useState<AIPersona | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [sample, setSample] = React.useState("")
  const [previewTab, setPreviewTab] = React.useState<"simple" | "raw">("simple")
  const [insights, setInsights] = React.useState<PerformanceInsights | null>(null)
  const [strategy, setStrategy] = React.useState<any>(null)
  const [prefilled, setPrefilled] = React.useState(false)
  const selectedPage = pages.find((page) => page.id === selectedPageId) || pages[0]

  React.useEffect(() => {
    if (editing?.id) {
      api.get(`/api/ai/personas/${editing.id}/strategy`).then(res => setStrategy(res.data)).catch(() => setStrategy(null))
    } else {
      setStrategy(null)
    }
  }, [editing?.id])

  const loadPersonas = React.useCallback(() => {
    if (!selectedPage?.id) return
    api.get<AIPersona[]>(`/api/ai/personas/${selectedPage.id}`).then((response) => {
      setPersonas(response.data)
    })
    api.get<PerformanceInsights>(`/api/ai/performance/${selectedPage.id}`).then((response) => setInsights(response.data)).catch(() => setInsights(null))
  }, [selectedPage?.id])

  React.useEffect(() => { loadPersonas() }, [loadPersonas])

  // Pre-fill persona from Style Analyzer redirect
  React.useEffect(() => {
    try {
      const stored = localStorage.getItem("ai_persona_prefill")
      if (!stored) return
      localStorage.removeItem("ai_persona_prefill")
      const data = JSON.parse(stored)
      const merged: AIPersona = {
        ...emptyPersona(),
        persona_name: data.persona_name || "AI-Generated Persona",
        niche: data.niche || "",
        tone_tags: Array.isArray(data.tone_tags) && data.tone_tags.length ? data.tone_tags : ["Professional"],
        custom_instructions: data.custom_instructions || null,
        hashtags_enabled: typeof data.hashtags_enabled === "boolean" ? data.hashtags_enabled : false,
        hashtag_count: typeof data.hashtag_count === "number" ? data.hashtag_count : 3,
        always_include_engagement_hook: typeof data.always_include_engagement_hook === "boolean" ? data.always_include_engagement_hook : false,
        creativity_level: typeof data.creativity_level === "number" ? data.creativity_level : 7,
        language: data.language || "English",
        prompt_config: data.prompt_config ? {
          ...emptyPromptConfig(),
          ...data.prompt_config,
          template: "Custom (blank)",
          brand_personality: Array.isArray(data.tone_tags) && data.tone_tags.length ? data.tone_tags : ["Professional"],
        } : emptyPromptConfig(),
      }
      setEditing(merged)
      setPrefilled(true)
    } catch {
      // ignore parse errors
    }
  }, [])

  const draft = editing || emptyPersona()
  const config = promptConfig(draft)
  const simplePrompt = buildSimplePrompt(draft)
  const rawPrompt = draft.custom_prompt?.trim() ? draft.custom_prompt : buildRawPrompt(draft)
  const dayOwners = Object.fromEntries(dayOptions.map((day) => [day, personas.find((persona) => persona.assigned_days.includes(day))]))

  function toggleTone(tone: string) {
    setEditing((value) => value ? ({
      ...value,
      tone_tags: value.tone_tags.includes(tone) ? value.tone_tags.filter((item) => item !== tone) : [...value.tone_tags, tone].slice(0, 4),
    }) : value)
  }
  function updateConfig(update: Partial<PromptStudioConfig>) {
    setEditing((value) => value ? ({ ...value, prompt_config: { ...promptConfig(value), ...update } }) : value)
  }
  function toggleConfigList(key: "every_post_includes" | "never_do", item: string) {
    const current = config[key]
    updateConfig({ [key]: current.includes(item) ? current.filter((value) => value !== item) : [...current, item] } as Partial<PromptStudioConfig>)
  }
  function addTag(key: "always_topics" | "never_topics", value: string) {
    const clean = value.trim()
    if (!clean || config[key].includes(clean)) return
    updateConfig({ [key]: [...config[key], clean] } as Partial<PromptStudioConfig>)
  }
  function toggleDay(day: string) {
    const owner = personas.find((persona) => persona.id !== draft.id && persona.assigned_days.includes(day))
    if (owner && !draft.assigned_days.includes(day)) toast.warning(`${dayName(day)} is already assigned to ${owner.persona_name}. Reassigning it will remove it from that persona.`)
    setEditing((value) => value ? ({ ...value, assigned_days: value.assigned_days.includes(day) ? value.assigned_days.filter((item) => item !== day) : [...value.assigned_days, day] }) : value)
  }
  async function savePersona(showToast = true) {
    if (!selectedPage) throw new Error("No page")
    if (!draft.persona_name.trim()) throw new Error("Persona name is required.")
    if (!draft.niche.trim()) throw new Error("What is your page about? is required.")
    if (!draft.tone_tags.length) throw new Error("Select at least one tone.")
    const payload = { ...draft, prompt_config: config, custom_prompt: rawPrompt }
    setSaving(true)
    try {
      if (draft.id) await api.put<AIPersona>(`/api/ai/personas/${draft.id}`, payload)
      else await api.post<AIPersona>(`/api/ai/personas/${selectedPage.id}`, payload)
      await loadPersonas()
      if (showToast) toast.success("AI persona saved.")
    } finally {
      setSaving(false)
    }
  }
  async function saveSettings() {
    try {
      await savePersona(true)
      setEditing(null)
      setPrefilled(false)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || error.message || "Could not save AI persona.")
    }
  }
  async function testSample() {
    try {
      await savePersona(false)
      const response = await api.post<{ content: string }>("/api/ai/generate", { page_connection_id: selectedPage?.id })
      setSample(response.data.content)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || error.message || "Could not generate sample.")
    }
  }
  async function resetLearning() {
    if (!draft.id || !window.confirm("Reset learning for this persona?")) return
    await api.post(`/api/ai/personas/${draft.id}/reset-learning`)
    toast.success("Learning reset.")
    await loadPersonas()
  }

  async function handleStrategyDecision(action: string, promptOverride?: string) {
    if (!draft.id) return
    try {
      await api.post(`/api/ai/personas/${draft.id}/strategy-decision`, { action, prompt: promptOverride })
      toast.success(action === "reject" ? "Suggestion rejected." : "Prompt updated.")
      setStrategy({ ...strategy, applied_to_prompt: true })
      setEditing(null)
      await loadPersonas()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Could not apply decision")
    }
  }

  return <><PageTitle title="Prompt Studio" subtitle="Build the exact AI prompt used by each scheduled persona." aiPowered />{!pages.length ? <Empty text="Connect a page before setting up AI personas." action="/dashboard/settings" /> : <div className="grid gap-5">
    {pages.length > 1 ? <Select value={String(selectedPageId ?? pages[0].id)} onChange={(event) => setSelectedPageId(Number(event.target.value))}>{pages.map((page) => <option key={page.id} value={String(page.id)}>{page.page_name}</option>)}</Select> : <PageMini page={pages[0]} />}
    <div className="grid grid-cols-2 gap-2 md:grid-cols-7">{dayOptions.map((day) => {
      const owner = dayOwners[day]
      const index = owner ? Math.max(0, personas.findIndex((persona) => persona.id === owner.id)) : 0
      return <button key={day} className={cn("min-h-24 rounded-md border p-3 text-left", owner ? personaColors[index % personaColors.length] : "border-dashed bg-white text-slate-500")} onClick={() => setEditing(owner || emptyPersona())}><div className="flex items-center justify-between"><span className="font-medium">{day}</span>{!owner ? <Plus className="size-4" /> : null}</div><p className="mt-3 text-xs">{owner?.persona_name || "Unassigned"}</p></button>
    })}</div>
    <div className="grid gap-4 md:grid-cols-2">{personas.map((persona, index) => <Card key={persona.id}><CardContent className="grid gap-3 p-5"><div className="flex items-start justify-between gap-3"><div><h2 className="font-semibold">{persona.persona_name}</h2><p className="text-sm text-slate-500">{persona.assigned_days.join(", ") || "No days assigned"}</p></div><span className={cn("rounded-full px-2 py-1 text-xs font-medium", persona.is_active ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-600")}>{persona.is_active ? "Active" : "Paused"}</span></div><div className="flex flex-wrap gap-2">{persona.tone_tags.map((tag) => <span key={tag} className={cn("rounded-full border px-2 py-1 text-xs", personaColors[index % personaColors.length])}>{tag}</span>)}</div><div className="flex items-center justify-between text-sm text-slate-500"><span>{persona.posting_time_slots.join(", ")}</span><span>Score {Number(persona.performance_score || 0.5).toFixed(2)}</span></div><Button variant="outline" onClick={() => setEditing(persona)}>Edit</Button></CardContent></Card>)}{personas.length < 5 ? <Button variant="outline" className="min-h-36 border-dashed" onClick={() => setEditing({ ...emptyPersona(), persona_name: `Persona ${personas.length + 1}` })}><Plus className="size-4" /> Add New Persona</Button> : null}</div>
    <PerformanceInsightsPanel insights={insights} personas={personas} timezone={Intl.DateTimeFormat().resolvedOptions().timeZone} />
  </div>}{editing ? <PromptStudioModal draft={draft} config={config} simplePrompt={simplePrompt} rawPrompt={rawPrompt} previewTab={previewTab} saving={saving} strategy={strategy} fromStyleAnalyzer={prefilled} onStrategyDecision={handleStrategyDecision} onPreviewTab={setPreviewTab} onChange={setEditing} onConfig={updateConfig} onToggleTone={toggleTone} onToggleDay={toggleDay} onToggleConfigList={toggleConfigList} onAddTag={addTag} onSave={saveSettings} onTest={testSample} onResetLearning={resetLearning} onClose={() => { setEditing(null); setPrefilled(false) }} /> : null}{sample ? <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 p-4"><Card className="max-w-xl"><CardHeader><CardTitle>Sample AI Post</CardTitle></CardHeader><CardContent className="grid gap-4"><p className="whitespace-pre-wrap text-sm text-slate-700">{sample}</p><Button className="w-fit bg-blue-700 hover:bg-blue-800" onClick={() => setSample("")}>Close</Button></CardContent></Card></div> : null}</>
}

function dayName(day: string) {
  return { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" }[day] || day
}

function PromptStudioModal({ draft, config, simplePrompt, rawPrompt, previewTab, saving, onPreviewTab, onChange, onConfig, onToggleTone, onToggleDay, onToggleConfigList, onAddTag, onSave, onTest, onResetLearning, onClose, strategy, onStrategyDecision, fromStyleAnalyzer }: {
  draft: AIPersona
  config: PromptStudioConfig
  simplePrompt: string
  rawPrompt: string
  previewTab: "simple" | "raw"
  saving: boolean
  fromStyleAnalyzer?: boolean
  onPreviewTab: (tab: "simple" | "raw") => void
  onChange: (persona: AIPersona | null) => void
  onConfig: (update: Partial<PromptStudioConfig>) => void
  onToggleTone: (tone: string) => void
  onToggleDay: (day: string) => void
  onToggleConfigList: (key: "every_post_includes" | "never_do", item: string) => void
  onAddTag: (key: "always_topics" | "never_topics", value: string) => void
  onSave: () => void
  onTest: () => void
  onResetLearning: () => void
  onClose: () => void
  strategy: any
  onStrategyDecision: (action: string, prompt?: string) => void
}) {
  const [typedPrompt, setTypedPrompt] = React.useState("")
  const [analyzing, setAnalyzing] = React.useState(false)
  const [testingImage, setTestingImage] = React.useState(false)
  const [testResult, setTestResult] = React.useState<any>(null)
  const [referenceImageFile, setReferenceImageFile] = React.useState<File | null>(null)
  const [logoImageFile, setLogoImageFile] = React.useState<File | null>(null)

  async function analyzeReferenceImage() {
    if (!draft.id || !referenceImageFile) {
      toast.error("Please save the persona first and select a reference image.")
      return
    }
    setAnalyzing(true)
    try {
      const formData = new FormData()
      formData.append("persona_id", String(draft.id))
      formData.append("reference_image", referenceImageFile)
      if (logoImageFile) {
        formData.append("logo", logoImageFile)
      }
      const response = await api.post("/api/images/analyze-template-reference", formData, {
        headers: { "Content-Type": "multipart/form-data" }
      })
      toast.success("Reference image analyzed successfully!")
      setTestResult(response.data)
      setReferenceImageFile(null)
      setLogoImageFile(null)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || "Failed to analyze reference image.")
    } finally {
      setAnalyzing(false)
    }
  }

  async function testTemplateGeneration() {
    if (!draft.id) {
      toast.error("Please save the persona first.")
      return
    }
    setTestingImage(true)
    try {
      const response = await api.post("/api/images/test-template-generation", {
        persona_id: draft.id,
        topic_hint: "test topic"
      })
      setTestResult(response.data)
      if (response.data.success) {
        toast.success("Template generation test successful!")
      } else {
        toast.error("Template generation test failed.")
      }
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || "Failed to test template generation.")
    } finally {
      setTestingImage(false)
    }
  }

  React.useEffect(() => {
    const text = previewTab === "simple" ? simplePrompt : rawPrompt
    setTypedPrompt("")
    let i = 0
    const interval = setInterval(() => {
      setTypedPrompt(text.slice(0, i))
      i += Math.max(1, Math.floor(text.length / 50))
      if (i > text.length) {
        setTypedPrompt(text)
        clearInterval(interval)
      }
    }, 15)
    return () => clearInterval(interval)
  }, [simplePrompt, rawPrompt, previewTab])
  return <div className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-4"><Card className="mx-auto my-6 max-w-6xl"><CardHeader><CardTitle className="flex items-center gap-2">Prompt Studio <Sparkles className="size-4 text-purple-600" /></CardTitle></CardHeader><CardContent className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
    <div className="grid gap-5">
      {fromStyleAnalyzer ? <div className="rounded-md border-2 border-purple-400 bg-purple-50 p-4 animate-in fade-in zoom-in duration-300"><div className="flex items-center gap-2 font-semibold text-purple-900 mb-1"><Sparkles className="size-4" /> Persona auto-generated from your posts!</div><p className="text-sm text-purple-800">All fields have been filled in by the AI based on your writing style. Review them, then scroll down to <strong>assign posting days</strong> and hit <strong>Save Prompt</strong>.</p></div> : null}
      <div className="grid gap-3 rounded-md border p-4 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards" style={{ animationDelay: '0ms' }}><Label>Start from a Template</Label><Select value={config.template} onChange={(event) => onChange(applyTemplate(draft, event.target.value))}>{templateNames.map((template) => <option key={template}>{template}</option>)}</Select><div className="grid gap-3 md:grid-cols-2"><div className="grid gap-2"><Label>Persona Name</Label><Input value={draft.persona_name} onChange={(event) => onChange({ ...draft, persona_name: event.target.value })} /></div><div className="grid gap-2"><Label>Priority Level</Label><Select value={draft.priority_level} onChange={(event) => onChange({ ...draft, priority_level: event.target.value as AIPersona["priority_level"] })}><option>High</option><option>Normal</option><option>Low</option></Select></div></div></div>
      <div className="grid gap-3 rounded-md border p-4 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards" style={{ animationDelay: '150ms' }}><h2 className="font-semibold">Identity Questions</h2><div className="grid gap-2"><Label>What is this page about?</Label><Input value={draft.niche} onChange={(event) => onChange({ ...draft, niche: event.target.value })} placeholder="personal finance tips for young professionals in Bangladesh" /></div><div className="grid gap-2"><Label>Who is your audience?</Label><Input value={config.audience} onChange={(event) => onConfig({ audience: event.target.value })} /></div><div className="grid gap-2"><Label>What is the main goal of your posts?</Label><Select value={config.goal} onChange={(event) => onConfig({ goal: event.target.value })}>{goalOptions.map((goal) => <option key={goal}>{goal}</option>)}<option>Other</option></Select></div><div className="grid gap-2"><Label>What is your brand personality?</Label><div className="flex flex-wrap gap-2">{toneOptions.map((tone) => <Button key={tone} type="button" variant={draft.tone_tags.includes(tone) ? "default" : "outline"} className={draft.tone_tags.includes(tone) ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => onToggleTone(tone)}>{draft.tone_tags.includes(tone) ? <Check className="size-4" /> : null}{tone}</Button>)}</div><p className="text-xs text-slate-500">Select up to 4.</p></div></div>
      <div className="grid gap-3 rounded-md border p-4 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards" style={{ animationDelay: '300ms' }}><h2 className="font-semibold">Content Rules</h2><TagInput label="What topics should the AI always write about?" values={config.always_topics} onAdd={(value) => onAddTag("always_topics", value)} onRemove={(value) => onConfig({ always_topics: config.always_topics.filter((item) => item !== value) })} /><TagInput label="What topics should the AI NEVER write about?" values={config.never_topics} onAdd={(value) => onAddTag("never_topics", value)} onRemove={(value) => onConfig({ never_topics: config.never_topics.filter((item) => item !== value) })} /><div className="grid gap-2"><Label>What should every post include?</Label><div className="flex flex-wrap gap-2">{includeOptions.map((item) => <Button key={item} type="button" variant={config.every_post_includes.includes(item) ? "default" : "outline"} onClick={() => onToggleConfigList("every_post_includes", item)}>{item}</Button>)}</div></div><div className="grid gap-2"><Label>What should posts NEVER do?</Label><div className="flex flex-wrap gap-2">{neverOptions.map((item) => <Button key={item} type="button" variant={config.never_do.includes(item) ? "default" : "outline"} onClick={() => onToggleConfigList("never_do", item)}>{item}</Button>)}</div></div><div className="grid gap-2"><Label>How long should posts be?</Label><input type="range" min={0} max={2} value={["Short", "Medium", "Long"].indexOf(config.length)} onChange={(event) => onConfig({ length: (["Short", "Medium", "Long"] as const)[Number(event.target.value)] })} /><div className="flex justify-between text-xs text-slate-500"><span>Short</span><span>Medium</span><span>Long</span></div><div className="flex items-center justify-between rounded-md border p-3"><Label>Vary the length automatically</Label><Switch checked={config.vary_length} onCheckedChange={(checked) => onConfig({ vary_length: checked })} /></div></div></div>
      <div className="grid gap-3 rounded-md border p-4 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards" style={{ animationDelay: '450ms' }}><h2 className="font-semibold">Format and Style Rules</h2><div className="grid gap-2"><Label>How should posts be structured?</Label><Select value={config.structure} onChange={(event) => onConfig({ structure: event.target.value })}>{structureOptions.map((item) => <option key={item}>{item}</option>)}</Select></div><div className="grid gap-2"><Label>What writing style examples do you love?</Label><Textarea className="min-h-28" value={config.examples} onChange={(event) => onConfig({ examples: event.target.value })} placeholder="Paste example posts that feel like what you want. The AI will study these." /></div><div className="grid gap-2"><Label>What language should posts be written in?</Label><Select value={draft.language} onChange={(event) => onChange({ ...draft, language: event.target.value })}>{languages.map((language) => <option key={language}>{language}</option>)}</Select></div></div>
      <div className="grid gap-3 rounded-md border p-4 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards" style={{ animationDelay: '600ms' }}><h2 className="font-semibold">Advanced Control</h2><div className="grid gap-2"><Label>Write any additional instructions in your own words</Label><Textarea className="min-h-28" value={draft.custom_instructions || ""} onChange={(event) => onChange({ ...draft, custom_instructions: event.target.value })} /></div><div className="grid gap-2"><Label>Rate how creative vs safe you want the AI to be: {draft.creativity_level}/10</Label><input type="range" min={1} max={10} value={draft.creativity_level} onChange={(event) => onChange({ ...draft, creativity_level: Number(event.target.value) })} /><div className="flex justify-between text-xs text-slate-500"><span>Very safe, predictable, consistent.</span><span>Very creative, experimental, surprising.</span></div></div><div className="grid gap-3 md:grid-cols-2"><div className="grid gap-2"><Label>Assigned Days</Label><div className="flex flex-wrap gap-2">{dayOptions.map((day) => <Button key={day} type="button" variant={draft.assigned_days.includes(day) ? "default" : "outline"} onClick={() => onToggleDay(day)}>{day}</Button>)}</div></div><div className="grid gap-2"><Label>Posting Times</Label>{draft.posting_time_slots.map((slot, index) => <Input key={`${slot}-${index}`} type="time" value={slot} onChange={(event) => onChange({ ...draft, posting_time_slots: draft.posting_time_slots.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })} />)}</div></div><div className="flex items-center justify-between rounded-md border p-3"><Label>Learning Mode</Label><Switch checked={draft.learning_mode_enabled} onCheckedChange={(checked) => onChange({ ...draft, learning_mode_enabled: checked })} /></div>{draft.learned_patterns_summary ? <p className="text-sm text-slate-500">{draft.learned_patterns_summary}</p> : null}</div>
      <div className="grid gap-3 rounded-md border p-4 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards" style={{ animationDelay: '750ms' }}><h2 className="font-semibold flex items-center gap-2"><LayoutTemplate className="size-4" /> Advanced Template Image Generation</h2><div className="flex items-center justify-between rounded-md border p-3 bg-slate-50"><Label className="cursor-pointer">Enable Template-Based Image Generation (Advanced Mode)</Label><Switch checked={draft.template_image_generation_enabled || false} onCheckedChange={(checked) => onChange({ ...draft, template_image_generation_enabled: checked })} /></div>{draft.template_image_generation_enabled ? <div className="grid gap-3 mt-3"><div className="grid gap-2"><Label>Reference Image (Upload to analyze template structure)</Label><Input type="file" accept="image/*" onChange={(event) => setReferenceImageFile(event.target.files?.[0] || null)} /></div><div className="grid gap-2"><Label>Logo Image (Optional - will use global logo if not provided)</Label><Input type="file" accept="image/*" onChange={(event) => setLogoImageFile(event.target.files?.[0] || null)} /></div><Button className="w-fit" onClick={analyzeReferenceImage} disabled={analyzing || !referenceImageFile}>{analyzing ? <><Loader2 className="size-4 animate-spin mr-2" /> Analyzing...</> : <><Sparkles className="size-4 mr-2" /> Analyze Reference Image</>}</Button>{testResult?.layers_json ? <div className="rounded-md border p-3 bg-slate-50"><h3 className="font-semibold text-sm mb-2">Template Structure Extracted:</h3><div className="text-xs text-slate-600"><p><strong>Background:</strong> {testResult.layers_json.background?.type || "N/A"} - {testResult.layers_json.background?.description || "N/A"}</p><p><strong>Text Boxes:</strong> {testResult.layers_json.text_boxes?.length || 0} found</p>{testResult.layers_json.text_boxes?.map((box: any, i: number) => <p key={i} className="ml-2">• {box.purpose} at ({box.x_pct}%, {box.y_pct}%)</p>)}</div></div> : null}<Button className="w-fit" onClick={testTemplateGeneration} disabled={testingImage}>{testingImage ? <><Loader2 className="size-4 animate-spin mr-2" /> Testing...</> : <><RefreshCw className="size-4 mr-2" /> Test Image Generation</>}</Button>{testResult?.image_url ? <div className="rounded-md border p-3 bg-slate-50"><h3 className="font-semibold text-sm mb-2">Generated Image Preview:</h3><img src={testResult.image_url} alt="Generated" className="max-w-full h-auto rounded-md" /></div> : null}</div> : <div className="rounded-md border border-dashed p-3 text-center text-sm text-slate-500"><p>Template generation is disabled. Enable the toggle above to access advanced multi-layer image generation features.</p></div>}</div>
    </div>
    <aside className="grid h-fit gap-3 rounded-md border bg-slate-50 p-4 lg:sticky lg:top-4 overflow-y-auto max-h-[85vh]">
      {strategy && !strategy.applied_to_prompt && strategy.suggested_prompt ? (
        <div className="rounded-md border-2 border-purple-400 bg-purple-50 p-3 mb-2 animate-in fade-in zoom-in duration-300">
          <div className="flex items-center gap-2 font-semibold text-purple-900 mb-2">
            <Sparkles className="size-4" /> AI Strategy Update Available
          </div>
          <p className="text-sm text-purple-800 mb-3">Based on your recent engagement and edits, the AI suggests updating this persona's prompt.</p>
          <div className="text-xs bg-white border border-purple-200 rounded p-2 mb-3">
            <div className="text-red-600 line-through mb-1 break-all whitespace-pre-wrap">{rawPrompt.slice(0, 100)}...</div>
            <div className="text-green-600 break-all whitespace-pre-wrap">{strategy.suggested_prompt.slice(0, 100)}...</div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button size="sm" className="bg-purple-700 hover:bg-purple-800 flex-1" onClick={() => onStrategyDecision("accept")}>Accept</Button>
            <Button size="sm" variant="outline" className="flex-1" onClick={() => onStrategyDecision("partial", strategy.suggested_prompt)}>Edit First</Button>
            <Button size="sm" variant="ghost" className="text-purple-700 flex-1" onClick={() => onStrategyDecision("reject")}>Reject</Button>
          </div>
        </div>
      ) : null}
      <div className="flex gap-2"><Button type="button" variant={previewTab === "simple" ? "default" : "outline"} onClick={() => onPreviewTab("simple")}>Simple view</Button><Button type="button" variant={previewTab === "raw" ? "default" : "outline"} onClick={() => onPreviewTab("raw")}>Raw view</Button></div>
      {previewTab === "simple" ? <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-white p-3 text-sm text-slate-700 border-l-4 border-blue-500 min-h-[100px] transition-all relative">
        {typedPrompt}
        <span className="animate-pulse absolute inline-block w-1.5 h-4 bg-blue-500 ml-1 top-3"></span>
      </pre> : <Textarea className="min-h-[520px] font-mono text-xs" value={previewTab === "raw" && typedPrompt.length < rawPrompt.length ? typedPrompt : rawPrompt} onChange={(event) => onChange({ ...draft, custom_prompt: event.target.value })} />}
      <div className="grid gap-2 sm:grid-cols-2"><Button className="bg-blue-700 hover:bg-blue-800" onClick={onTest} disabled={saving}>{saving ? "Testing..." : "Test This Prompt"}</Button><Button className="bg-blue-700 hover:bg-blue-800" onClick={onSave} disabled={saving}>{saving ? "Saving..." : "Save Prompt"}</Button><Button variant="outline" onClick={() => onChange({ ...emptyPersona(), persona_name: draft.persona_name || "Default Persona" })}><RotateCcw className="size-4" /> Reset to Default</Button>{draft.id ? <Button type="button" variant="outline" onClick={onResetLearning}>Reset Learning</Button> : null}<Button variant="ghost" onClick={onClose}>Cancel</Button></div>
    </aside>
  </CardContent></Card></div>
}

function DashboardHintsCard() {
  const [preference, setPreference] = React.useState<ModelPreference | null>(null)
  React.useEffect(() => {
    api.get<ModelPreference>("/api/models/preference").then((response) => setPreference(response.data)).catch(() => setPreference(null))
  }, [])
  const providerLabel = preference?.provider_name === "gemini" ? "Google Gemini" : "Mistral"
  const modelLabel = preference?.model_name || "mistral-small-latest"
  return (
    <Card className="border-blue-200 bg-blue-50/40">
      <CardHeader>
        <CardTitle className="text-base">Quick start</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm text-slate-700">
        <p>Connect a Facebook page in <Link className="font-medium text-blue-700 underline" href="/dashboard/settings">Settings</Link>, choose your AI model there (Mistral or Gemini), then build personas in <Link className="font-medium text-blue-700 underline" href="/dashboard/ai-settings">Prompt Studio</Link>.</p>
        <p className="rounded-md border border-blue-100 bg-white px-3 py-2">
          Current AI model: <span className="font-medium">{providerLabel}</span> · <span className="font-medium">{modelLabel}</span>
          {preference && preference.configured === false ? <span className="ml-2 text-amber-700">— server key missing for this provider</span> : null}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline"><Link href="/dashboard/settings">AI model & account</Link></Button>
          <Button asChild size="sm" variant="outline"><Link href="/dashboard/ai-settings">Prompt Studio</Link></Button>
          <Button asChild size="sm" className="bg-blue-700 hover:bg-blue-800"><Link href="/dashboard/create">Create a post</Link></Button>
        </div>
      </CardContent>
    </Card>
  )
}

function AIModelSettingsCard() {
  const [preference, setPreference] = React.useState<ModelPreference>({ provider_name: "mistral", model_name: "mistral-small-latest" })
  const [providers, setProviders] = React.useState<ModelProviderOption[]>([])
  const [saving, setSaving] = React.useState(false)
  const [testing, setTesting] = React.useState(false)

  React.useEffect(() => {
    Promise.all([
      api.get<{ providers: ModelProviderOption[] }>("/api/models/options"),
      api.get<ModelPreference>("/api/models/preference"),
    ]).then(([optionsResponse, preferenceResponse]) => {
      setProviders(optionsResponse.data.providers)
      setPreference(preferenceResponse.data)
    }).catch(() => null)
  }, [])

  const models = llmProviderModels[preference.provider_name] || llmProviderModels.mistral
  const selectedProvider = providers.find((item) => item.id === preference.provider_name)

  function changeProvider(providerName: string) {
    const firstModel = llmProviderModels[providerName]?.[0] || preference.model_name
    setPreference({ ...preference, provider_name: providerName, model_name: firstModel })
  }

  async function savePreference() {
    setSaving(true)
    try {
      const response = await api.put<ModelPreference>("/api/models/preference", preference)
      setPreference(response.data)
      toast.success("AI model saved.")
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Could not save AI model."))
    } finally {
      setSaving(false)
    }
  }

  async function testPreference() {
    setTesting(true)
    try {
      const response = await api.post<{ success: boolean; message?: string; error?: string }>("/api/models/test", {
        provider_name: preference.provider_name,
        model_name: preference.model_name,
      })
      response.data.success ? toast.success(response.data.message || "Model works.") : toast.error(response.data.error || "Model test failed.")
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Model test failed."))
    } finally {
      setTesting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI model</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-slate-500">Choose which model writes posts, scores quality, and powers analysis. API keys are managed on the server — you do not need to paste keys here.</p>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="grid gap-2">
            <Label>Provider</Label>
            <Select value={preference.provider_name} onChange={(event) => changeProvider(event.target.value)}>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id} disabled={!provider.configured}>
                  {provider.label}{provider.configured ? "" : " (not configured on server)"}
                </option>
              ))}
              {!providers.length ? Object.keys(llmProviderModels).map((provider) => <option key={provider} value={provider}>{provider}</option>) : null}
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>Model</Label>
            <Select value={preference.model_name} onChange={(event) => setPreference({ ...preference, model_name: event.target.value })}>
              {models.map((model) => <option key={model} value={model}>{model}</option>)}
            </Select>
          </div>
        </div>
        {selectedProvider && !selectedProvider.configured ? (
          <p className="text-sm text-amber-700">This provider is not available until the administrator adds its API key to the server environment.</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button className="bg-blue-700 hover:bg-blue-800" onClick={savePreference} disabled={saving}>
            {saving ? <Loader2 className="size-4 animate-spin" /> : null}
            Save AI model
          </Button>
          <Button variant="outline" onClick={testPreference} disabled={testing}>
            {testing ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
            Test connection
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function TagInput({ label, values, onAdd, onRemove }: { label: string; values: string[]; onAdd: (value: string) => void; onRemove: (value: string) => void }) {
  const [value, setValue] = React.useState("")
  return <div className="grid gap-2"><Label>{label}</Label><Input value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onAdd(value); setValue("") } }} placeholder="Type a topic and press Enter" /><div className="flex flex-wrap gap-2">{values.map((item) => <button key={item} type="button" className="inline-flex items-center gap-1 rounded-full border bg-white px-2 py-1 text-xs" onClick={() => onRemove(item)}>{item}<X className="size-3" /></button>)}</div></div>
}

function PerformanceInsightsPanel({ insights, personas, timezone }: { insights: PerformanceInsights | null; personas: AIPersona[]; timezone: string }) {
  if (!insights) return null
  if (!insights.enabled) return <Card><CardHeader><CardTitle>Performance Insights</CardTitle></CardHeader><CardContent><p className="text-sm text-slate-500">{insights.reason}</p></CardContent></Card>
  const maxScore = Math.max(...insights.persona_scores.map((item) => item.score), 1)
  const heatMax = Math.max(...insights.time_slot_heatmap.map((item) => item.average_score), 1)
  const heatByKey = Object.fromEntries(insights.time_slot_heatmap.map((item) => [`${item.day}-${item.hour}`, item.average_score]))
  return <section className="grid gap-4"><PageTitle title="Performance Insights" subtitle="Engagement learning across personas, slots, and recent winners." /><Card><CardHeader><CardTitle>Persona Comparison</CardTitle></CardHeader><CardContent className="grid gap-3">{insights.persona_scores.map((item) => {
    const index = Math.max(0, personas.findIndex((persona) => persona.id === item.id))
    return <div key={item.id} className="grid gap-1"><div className="flex justify-between text-sm"><span>{item.name}</span><span>{item.score.toFixed(2)}</span></div><div className="h-3 rounded bg-slate-100"><div className={cn("h-3 rounded border", personaColors[index % personaColors.length])} style={{ width: `${Math.max(8, (item.score / maxScore) * 100)}%` }} /></div></div>
  })}</CardContent></Card><Card><CardHeader><CardTitle>Best Performing Time Slots</CardTitle></CardHeader><CardContent className="overflow-x-auto"><div className="grid min-w-[760px] grid-cols-[56px_repeat(24,minmax(20px,1fr))] gap-1 text-xs">{["", ...Array.from({ length: 24 }, (_, hour) => String(hour))].map((label, index) => <span key={`${label}-${index}`} className="text-center text-slate-400">{label}</span>)}{dayOptions.map((day) => <React.Fragment key={day}><span className="py-1 text-slate-500">{day}</span>{Array.from({ length: 24 }, (_, hour) => {
    const value = heatByKey[`${day}-${hour}`] || 0
    return <div key={hour} title={`${day} ${hour}:00 - ${value.toFixed(1)}`} className="h-5 rounded-sm border border-white" style={{ backgroundColor: `rgba(22, 163, 74, ${Math.min(0.9, value / heatMax)})` }} />
  })}</React.Fragment>)}</div></CardContent></Card><div className="grid gap-4 lg:grid-cols-2"><Card><CardHeader><CardTitle>Top 3 Posts This Month</CardTitle></CardHeader><CardContent className="grid gap-3">{insights.top_posts.map((post) => <div key={post.id} className="grid gap-2 rounded-md border p-3"><div className="flex justify-between gap-3 text-sm"><span className="font-medium">{post.persona_name}</span><span className="text-slate-500">{formatDate(post.published_at || null, timezone)}</span></div><p className="line-clamp-3 text-sm text-slate-600">{post.content}</p><div className="flex flex-wrap gap-3 text-xs text-slate-500"><span>Likes {post.likes_count}</span><span>Comments {post.comments_count}</span><span>Shares {post.shares_count}</span><span>Reach {post.reach_count}</span><span>Score {post.engagement_score.toFixed(1)}</span></div></div>)}{!insights.top_posts.length ? <p className="text-sm text-slate-500">No engagement snapshots yet.</p> : null}</CardContent></Card><Card><CardHeader><CardTitle>AI Recommendations</CardTitle></CardHeader><CardContent className="grid gap-2">{insights.recommendations.map((item) => <p key={item.id} className="rounded-md border p-3 text-sm text-slate-600">{item.text}</p>)}{!insights.recommendations.length ? <p className="text-sm text-slate-500">Recommendations will appear after the weekly learning job has enough data.</p> : null}</CardContent></Card></div></section>
}

function PostList({ title, posts, emptyText, emptyAction, timezone, published, onChanged }: { title: string; posts: Post[]; emptyText: string; emptyAction: string; timezone: string; published?: boolean; onChanged: () => void }) {
  const [aiFilter, setAiFilter] = React.useState<"all" | "manual" | "ai">("all")
  const [publishing, setPublishing] = React.useState<number | null>(null)
  const visiblePosts = published ? posts.filter((post) => aiFilter === "all" || (aiFilter === "ai" ? post.ai_generated : !post.ai_generated)) : posts
  async function remove(id: number) {
    if (!window.confirm("Are you sure you want to delete this post? This action cannot be undone.")) return
    await api.delete(`/posts/${id}`)
    toast.success("Post removed.")
    onChanged()
  }
  async function publishNow(id: number) {
    setPublishing(id)
    try {
      await api.post(`/posts/${id}/publish`)
      toast.success("Post published to Facebook successfully!")
      onChanged()
    } catch (error: any) {
      toast.error(getApiErrorMessage(error, "Publishing failed. Please try again."))
    } finally {
      setPublishing(null)
    }
  }
  return <><PageTitle title={title} subtitle={published ? "Live posts with engagement snapshots from the learning optimizer." : "Upcoming posts sorted by scheduled time."} />{published ? <div className="flex flex-wrap gap-2">{(["all", "manual", "ai"] as const).map((value) => <Button key={value} variant={aiFilter === value ? "default" : "outline"} className={aiFilter === value ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setAiFilter(value)}>{value === "all" ? "Show All" : value === "manual" ? "Manual Only" : "AI Generated Only"}</Button>)}</div> : null}<div className="grid gap-4">{visiblePosts.map((post) => <Card key={post.id}><CardContent className="grid gap-3 p-6"><PostRow post={post} timezone={timezone} />{published ? <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">{post.low_engagement ? <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">Low engagement</span> : null}<span>Likes {post.likes_count || 0}</span><span>Comments {post.comments_count || 0}</span><span>Shares {post.shares_count || 0}</span><span>Reach {post.reach_count || 0}</span><span>Score {Number(post.engagement_score || 0).toFixed(1)}</span><Button size="icon" variant="ghost"><RefreshCw className="size-4" /></Button></div> : null}<div className="flex flex-wrap gap-2"><Button variant="outline" asChild><Link href="/dashboard/create">Edit</Link></Button>{!published ? <Button className="bg-green-700 text-white hover:bg-green-800" onClick={() => publishNow(post.id)} disabled={publishing === post.id}>{publishing === post.id ? <><Loader2 className="size-4 animate-spin" /> Publishing...</> : "Publish Now"}</Button> : null}<Button variant="destructive" onClick={() => remove(post.id)}><Trash2 className="size-4" /> {published ? "Delete from Facebook" : "Delete"}</Button></div></CardContent></Card>)} {!visiblePosts.length ? <Empty text={emptyText} action={emptyAction} /> : null}</div></>
}

function AnalyticsView({ analytics, setAnalytics }: { analytics: Analytics | null; setAnalytics: (value: Analytics) => void }) {
  async function changeRange(value: string) {
    const response = await api.get<Analytics>("/analytics", { params: { days: Number(value) } })
    setAnalytics(response.data)
  }
  const max = Math.max(...(analytics?.posts_per_day.map((day) => day.count) || [0]), 1) + 2
  return <><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><PageTitle title="Analytics" subtitle="Current performance across published posts." /><Select className="w-44" defaultValue="30" onChange={(event) => changeRange(event.target.value)}><option value="7">Last 7 Days</option><option value="30">Last 30 Days</option><option value="90">Last 3 Months</option></Select></div>{analytics ? <><section className="grid gap-4 md:grid-cols-4"><Stat label="Total posts published" value={analytics.total_posts} /><Stat label="Total likes received" value={analytics.total_likes} /><Stat label="Total comments received" value={analytics.total_comments} /><Stat label="Total shares received" value={analytics.total_shares} /></section><Card><CardContent className="flex h-64 items-end gap-1 p-6">{analytics.posts_per_day.map((day) => <div key={day.date} className="flex flex-1 flex-col items-center gap-2"><div className="w-full rounded-t bg-blue-700" style={{ height: `${Math.max(4, (day.count / max) * 210)}px` }} /><span className="hidden text-[10px] text-slate-500 md:block">{day.date.slice(5)}</span></div>)}</CardContent></Card></> : <Empty text="No analytics yet." action="/dashboard/create" />}</>
}

function SettingsView({ pages, timezone, onChanged }: { pages: PageConnection[]; timezone: string; onChanged: () => void }) {
  const { user } = useAuth()
  const [email, setEmail] = React.useState(user?.email || "")
  const [tz, setTz] = React.useState(timezone)
  const [manualPageId, setManualPageId] = React.useState("")
  const [manualToken, setManualToken] = React.useState("")
  const [syncingPageId, setSyncingPageId] = React.useState<number | null>(null)

  async function saveAccount() {
    await api.patch("/users/me", { email, timezone: tz })
    toast.success("Settings saved.")
  }
  async function manualConnect() {
    await api.post("/facebook/manual-connect", { page_id: manualPageId, page_access_token: manualToken })
    setManualPageId("")
    setManualToken("")
    toast.success("Facebook Page connected.")
    onChanged()
  }
  async function disconnect(id: number) {
    if (!window.confirm("Are you sure? Your post history will be saved.")) return
    try {
      const response = await api.delete<{ success: boolean; message: string; paused_posts: number }>(
        `/api/pages/${id}/disconnect`
      )
      toast.success(response.data.message)
      onChanged()
    } catch (e: any) {
      console.error(e)
      toast.error(e?.response?.data?.detail || "Could not disconnect page.")
    }
  }
  async function syncHistory(id: number) {
    setSyncingPageId(id)
    const toastId = toast.loading("Syncing your post history from Facebook...")
    try {
      const response = await api.post<{ success: boolean; synced_posts_count: number }>(`/facebook/pages/recover-history/${id}`)
      toast.success(`Synced ${response.data.synced_posts_count} historical posts to your dashboard.`, { id: toastId })
      onChanged()
    } catch (e: any) {
      console.error(e)
      toast.error(e?.response?.data?.detail || "Could not sync history. Backend error.", { id: toastId })
    } finally {
      setSyncingPageId(null)
    }
  }

  return <><PageTitle title="Settings" subtitle="Account, AI model, page connections, and timezone." /><AIModelSettingsCard /><Card><CardHeader><CardTitle>Account</CardTitle></CardHeader><CardContent className="grid gap-3"><Label>Email</Label><Input value={email} onChange={(event) => setEmail(event.target.value)} /><Button className="w-fit bg-blue-700 hover:bg-blue-800" onClick={saveAccount}>Save Account</Button></CardContent></Card><Card><CardHeader><CardTitle>Connected Pages</CardTitle></CardHeader><CardContent className="grid gap-3">{pages.map((page) => (
    <PageConnectionCard
      key={page.id}
      page={page}
      isSyncing={syncingPageId === page.id}
      onSyncHistory={() => syncHistory(page.id)}
      onDisconnect={() => disconnect(page.id)}
      onChanged={onChanged}
    />
  ))}<div className="grid gap-2 rounded-md border p-3"><p className="font-medium">Manual connection</p><Input placeholder="Facebook Page ID" value={manualPageId} onChange={(event) => setManualPageId(event.target.value)} /><Textarea placeholder="Long-lived Page Access Token" value={manualToken} onChange={(event) => setManualToken(event.target.value)} /><Button className="w-fit bg-blue-700 hover:bg-blue-800" onClick={manualConnect}>Validate Page</Button></div></CardContent></Card><Card><CardHeader><CardTitle>Timezone</CardTitle></CardHeader><CardContent className="grid gap-3"><Input value={tz} onChange={(event) => setTz(event.target.value)} /><p className="text-sm text-slate-500">Default was detected from your browser. All stored schedule times are converted to UTC.</p></CardContent></Card></>
}

function PageTitle({ title, subtitle, aiPowered }: { title: string; subtitle: string; aiPowered?: boolean }) {
  return <div><h1 className="text-2xl font-semibold flex items-center gap-2">{title} {aiPowered ? <Sparkles className="size-5 text-purple-600" /> : null}</h1><p className="text-sm text-slate-500">{subtitle}</p></div>
}

function PageMini({ page }: { page: PageConnection }) {
  const picture = page.profile_picture_url || page.page_picture_url
  return <div className="flex items-center gap-3"><img alt="" className="size-9 rounded-full bg-slate-100" src={picture || `${API_BASE_URL}/favicon.ico`} /><div><p className="text-sm font-medium">{page.page_name}</p><p className="text-xs text-slate-500">Manage Connection</p></div></div>
}

function PageStatusBadge({ status }: { status: string }) {
  if (status === "connected") {
    return <span className="rounded-full bg-green-50 px-2 py-1 text-xs font-medium text-green-700">Connected</span>
  }
  if (status === "needs-reconnection") {
    return <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">Token Expired</span>
  }
  if (status === "disconnected") {
    return <span className="rounded-full bg-red-50 px-2 py-1 text-xs font-medium text-red-700">Disconnected</span>
  }
  return <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">{status}</span>
}

function ConnectedPagesSection({ pages, onConnected }: { pages: PageConnection[]; onConnected: () => void }) {
  async function disconnect(id: number) {
    if (!window.confirm("Are you sure? Your post history will be saved.")) return
    try {
      const response = await api.delete<{ success: boolean; message: string; paused_posts: number }>(
        `/api/pages/${id}/disconnect`
      )
      toast.success(response.data.message)
      onConnected()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Could not disconnect page.")
    }
  }

  return (
    <section className="grid gap-4">
      <PageTitle title="Your Pages" subtitle="All connected and disconnected pages with preserved history." />
      {pages.map((page) => (
        <PageConnectionCard
          key={page.id}
          page={page}
          onChanged={onConnected}
          onDisconnect={() => disconnect(page.id)}
          showDashboardActions
        />
      ))}
      <div className="flex justify-end">
        <FacebookConnectButton onConnected={onConnected} />
      </div>
    </section>
  )
}

function PageConnectionCard({
  page,
  onChanged,
  onSyncHistory,
  onDisconnect,
  isSyncing,
  showDashboardActions,
}: {
  page: PageConnection
  onChanged: () => void
  onSyncHistory?: () => void
  onDisconnect?: () => void
  isSyncing?: boolean
  showDashboardActions?: boolean
}) {
  const status = page.connection_status
  const postCount = page.post_count ?? 0
  const pausedCount = page.paused_post_count ?? 0

  return (
    <Card>
      <CardContent className="grid gap-4 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <PageMini page={page} />
            <PageStatusBadge status={status} />
          </div>
          <div className="flex flex-wrap gap-2">
            {status === "connected" && showDashboardActions ? (
              <>
                <Button asChild variant="outline"><Link href="/dashboard/create">Create Post</Link></Button>
                <Button asChild variant="outline"><Link href="/dashboard/published">View Posts</Link></Button>
                {onDisconnect ? <Button variant="destructive" onClick={onDisconnect}>Disconnect</Button> : null}
              </>
            ) : null}
            {status === "connected" && !showDashboardActions ? (
              <>
                {onSyncHistory ? (
                  <Button variant="outline" disabled={isSyncing} onClick={onSyncHistory}>
                    {isSyncing ? "Syncing..." : "Sync History"}
                  </Button>
                ) : null}
                <Button
                  variant="outline"
                  disabled={isSyncing}
                  onClick={async () => {
                    await api.post(`/facebook/pages/${page.id}/refresh-token`)
                    toast.success("Token refreshed.")
                    onChanged()
                  }}
                >
                  Refresh Token
                </Button>
                {onDisconnect ? (
                  <Button variant="destructive" disabled={isSyncing} onClick={onDisconnect}>
                    Disconnect
                  </Button>
                ) : null}
              </>
            ) : null}
            {(status === "disconnected" || status === "needs-reconnection") ? (
              <FacebookConnectButton onConnected={onChanged} urgent={status === "needs-reconnection"} />
            ) : null}
          </div>
        </div>

        {status === "connected" ? (
          <p className="text-sm text-slate-600">
            {postCount} posts in history
            {(page.scheduled_post_count ?? 0) > 0 ? ` · ${page.scheduled_post_count} scheduled` : ""}
          </p>
        ) : null}

        {status === "disconnected" ? (
          <div className="grid gap-1 text-sm text-slate-600">
            <p>{postCount} posts saved · Your post history is preserved</p>
            {pausedCount > 0 ? (
              <p className="text-amber-700">
                {pausedCount} scheduled posts are paused. They will resume when you reconnect.
              </p>
            ) : null}
          </div>
        ) : null}

        {status === "needs-reconnection" ? (
          <p className="text-sm text-amber-700">Please reconnect to resume posting.</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ConnectedBanner({ page, onConnected }: { page: PageConnection; onConnected: () => void }) {
  return <PageConnectionCard page={page} onChanged={onConnected} showDashboardActions />
}

function Stat({ label, value, tone = "blue" }: { label: string; value: number; tone?: "blue" | "green" | "amber" | "red" }) {
  const colors = { blue: "text-blue-700", green: "text-green-700", amber: "text-amber-700", red: "text-red-700" }
  return <Card><CardContent className="p-6"><p className="text-sm text-slate-500">{label}</p><p className={cn("mt-2 text-3xl font-semibold", colors[tone])}>{value}</p></CardContent></Card>
}

function PostRow({ post, timezone }: { post: Post; timezone: string }) {
  return <div className="grid gap-2 rounded-md border p-3"><div className="flex items-center justify-between gap-2"><div className="flex flex-wrap gap-2"><span className={cn("rounded-full px-2 py-1 text-xs font-medium", badgeClass(post.status))}>{post.status}</span>{post.ai_generated ? <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-1 text-xs font-medium text-purple-700"><Sparkles className="size-3" /> AI Generated</span> : null}</div><span className="text-xs text-slate-500">{formatDate(post.posted_at || post.scheduled_at || null, timezone)}</span></div><p className="line-clamp-3 text-sm text-slate-600">{post.content}</p>{post.media_urls?.[0] ? <img alt="" className="h-24 w-32 rounded-md object-cover" src={post.media_urls[0]} /> : null}</div>
}

function Empty({ text, action }: { text: string; action: string }) {
  return <div className="grid gap-3 rounded-md border border-dashed bg-white p-8 text-center"><FileText className="mx-auto size-10 text-blue-700" /><p className="text-sm text-slate-500">{text}</p><Button asChild className="mx-auto bg-blue-700 hover:bg-blue-800"><Link href={action}>Create Post</Link></Button></div>
}

function SkeletonPage() {
  return <div className="grid gap-4">{[1, 2, 3].map((item) => <div key={item} className="h-28 animate-pulse rounded-md bg-slate-200" />)}</div>
}

function badgeClass(status: string) {
  if (status === "published" || status === "success") return "bg-green-50 text-green-700"
  if (status.includes("failed")) return "bg-red-50 text-red-700"
  if (status === "scheduled") return "bg-amber-50 text-amber-700"
  return "bg-blue-50 text-blue-700"
}

function formatDate(value: string | null, timezone: string) {
  if (!value) return "Not scheduled"
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: timezone }).format(new Date(value))
}


function TemplateLibraryView() {
  const [templates, setTemplates] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(true)
  const [analyzing, setAnalyzing] = React.useState(false)
  const [name, setName] = React.useState("")
  const [file, setFile] = React.useState<File | null>(null)

  const loadTemplates = React.useCallback(async () => {
    setLoading(true)
    try {
      const response = await api.get<any[]>("/api/images/templates")
      setTemplates(response.data)
    } catch (err) {
      console.error("Failed to load templates:", err)
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadTemplates()
  }, [loadTemplates])

  async function handleAnalyze(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !file) {
      toast.error("Please enter a template name and choose a reference image.")
      return
    }
    setAnalyzing(true)
    try {
      const formData = new FormData()
      formData.append("name", name)
      formData.append("file", file)
      await api.post("/api/images/analyze-template", formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      })
      toast.success("Image analyzed and template created successfully!")
      setName("")
      setFile(null)
      loadTemplates()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Template analysis failed.")
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Are you sure you want to delete this template?")) return
    try {
      await api.delete(`/api/images/templates/${id}`)
      toast.success("Template deleted successfully")
      loadTemplates()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Delete failed.")
    }
  }

  return (
    <>
      <PageTitle title="Template Library" subtitle="Upload reference layouts. The AI visual intelligence maps design layers for pixel-perfect automation." />
      <div className="grid gap-6 md:grid-cols-3 animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-backwards">
        <Card className="md:col-span-1 h-fit">
          <CardHeader>
            <CardTitle>Create Design Template</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAnalyze} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="template-name">Template Name</Label>
                <Input
                  id="template-name"
                  placeholder="e.g. Minimalist Product Slide"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={analyzing}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="reference-file">Reference Image</Label>
                <Input
                  id="reference-file"
                  type="file"
                  accept="image/*"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  disabled={analyzing}
                />
              </div>
              <Button type="submit" className="bg-purple-700 text-white hover:bg-purple-800 w-full" disabled={analyzing}>
                {analyzing ? <Loader2 className="size-4 animate-spin mr-2" /> : <Sparkles className="size-4 mr-2" />}
                {analyzing ? "Analyzing Design layers..." : "Extract Design Layers"}
              </Button>
            </form>
          </CardContent>
        </Card>
        
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Your Layout Templates</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            {loading ? (
              <div className="col-span-2 text-center py-10"><Loader2 className="size-6 animate-spin mx-auto text-slate-400" /></div>
            ) : templates.length === 0 ? (
              <div className="col-span-2 text-center py-10 text-slate-500">No layout templates saved. Upload one to get started!</div>
            ) : (
              templates.map((tpl) => (
                <div key={tpl.id} className="relative overflow-hidden rounded-lg border bg-white shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow">
                  <div className="relative aspect-video w-full overflow-hidden bg-slate-100 border-b">
                    <img src={tpl.reference_image_url} alt={tpl.name} className="h-full w-full object-cover" />
                    <div className="absolute inset-0 bg-black/60 opacity-0 hover:opacity-100 transition-opacity flex items-center justify-center p-3 text-white text-xs overflow-auto">
                      <div className="grid gap-1">
                        <p className="font-semibold text-center uppercase tracking-wider text-purple-400 mb-1">Detected Composition</p>
                        <p>Background: <span className="font-medium text-slate-300">{tpl.layers_json?.background?.type || 'photographic'}</span></p>
                        <p>Logo: <span className="font-medium text-slate-300">{tpl.layers_json?.logo_position ? 'Yes' : 'No'}</span></p>
                        <p>Text Boxes: <span className="font-medium text-slate-300">{tpl.layers_json?.text_boxes?.length || 0}</span></p>
                      </div>
                    </div>
                  </div>
                  <div className="p-4 flex items-center justify-between">
                    <div>
                      <h3 className="font-semibold text-slate-800">{tpl.name}</h3>
                      <p className="text-xs text-slate-500">Created: {new Date(tpl.created_at).toLocaleDateString()}</p>
                    </div>
                    <Button variant="ghost" size="icon" className="text-red-500 hover:text-red-700 hover:bg-red-50" onClick={() => handleDelete(tpl.id)}>
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}


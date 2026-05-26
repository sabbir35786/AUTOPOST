"use client"

import * as React from "react"
import axios from "axios"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  BarChart3,
  CalendarClock,
  FileText,
  Home,
  Loader2,
  Menu,
  PenLine,
  Plus,
  Plug,
  RefreshCw,
  RotateCcw,
  Settings,
  Sparkles,
  Trash2,
  X,
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
import { API_BASE_URL, api } from "@/lib/api"
import { cn } from "@/lib/utils"

type PageConnection = {
  id: number
  page_id: string
  page_name: string
  page_picture_url?: string | null
  connection_status: string
  connected_at: string
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
  total_posts_published?: number
  learned_patterns_summary?: string | null
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

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Home },
  { href: "/dashboard/create", label: "Create Post", icon: PenLine },
  { href: "/dashboard/ai-settings", label: "AI Personas", icon: Sparkles },
  { href: "/dashboard/scheduled", label: "Scheduled Posts", icon: CalendarClock },
  { href: "/dashboard/published", label: "Published Posts", icon: FileText },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
]

export function SocialPlatform({ view }: { view: "home" | "create" | "ai-settings" | "scheduled" | "published" | "analytics" | "settings" }) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isLoading, logout } = useAuth()
  const [pages, setPages] = React.useState<PageConnection[]>([])
  const [posts, setPosts] = React.useState<Post[]>([])
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [mobileOpen, setMobileOpen] = React.useState(false)

  const timezone = user?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  const connectedPage = pages[0]

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
        pageResponse = await api.get<PageConnection[]>("/facebook/pages")
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
        {!loading && view === "ai-settings" ? <AISettingsView pages={pages} /> : null}
        {!loading && view === "scheduled" ? <PostList title="Scheduled Posts" posts={posts.filter((post) => post.status === "scheduled")} emptyAction="/dashboard/create" emptyText="No upcoming posts yet." timezone={timezone} onChanged={load} /> : null}
        {!loading && view === "published" ? <PostList title="Published Posts" posts={posts.filter((post) => post.status === "published" || post.status === "success")} emptyAction="/dashboard/create" emptyText="No published posts yet." timezone={timezone} published onChanged={load} /> : null}
        {!loading && view === "analytics" ? <AnalyticsView analytics={analytics} setAnalytics={setAnalytics} /> : null}
        {!loading && view === "settings" ? <SettingsView pages={pages} timezone={timezone} onChanged={load} /> : null}
      </main>
    </div>
  )
}

function HomeView({ pages, posts, onConnected, timezone }: { pages: PageConnection[]; posts: Post[]; onConnected: () => void; timezone: string }) {
  const published = posts.filter((post) => post.status === "published" || post.status === "success").length
  const scheduled = posts.filter((post) => post.status === "scheduled").length
  const failed = posts.filter((post) => post.status.includes("failed")).length
  return (
    <>
      <PageTitle title="Dashboard" subtitle="Manage your Facebook Page posts without touching the API." />
      {!pages.length ? <ConnectEmpty onConnected={onConnected} /> : <ConnectedBanner page={pages[0]} onConnected={onConnected} />}
      <section className="grid gap-4 md:grid-cols-3">
        <Stat label="Posts Published This Month" value={published} tone="green" />
        <Stat label="Posts Scheduled" value={scheduled} tone="amber" />
        <Stat label="Posts Failed" value={failed} tone="red" />
      </section>
      <Card><CardHeader><CardTitle>Recent Activity</CardTitle></CardHeader><CardContent className="grid gap-3">{posts.slice(0, 10).map((post) => <PostRow key={post.id} post={post} timezone={timezone} />)} {!posts.length ? <Empty text="No activity yet." action="/dashboard/create" /> : null}</CardContent></Card>
    </>
  )
}

function ConnectEmpty({ onConnected }: { onConnected: () => void }) {
  return <Card><CardContent className="grid gap-4 p-6 text-center"><Plug className="mx-auto size-10 text-blue-700" /><div><h2 className="text-lg font-semibold">You have no connected pages yet.</h2><p className="text-sm text-slate-500">Connect your first Facebook Page.</p></div><FacebookConnectButton className="mx-auto" onConnected={onConnected} /></CardContent></Card>
}

function FacebookConnectButton({ onConnected, className }: { onConnected: () => void; className?: string }) {
  const [busy, setBusy] = React.useState(false)
  const completedRef = React.useRef(false)
  React.useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== API_BASE_URL && event.origin !== window.location.origin) return
      if (event.data?.type === "facebook-connected") {
        completedRef.current = true
        setBusy(false)
        onConnected()
        toast.success("Facebook Page connected.")
      } else if (event.data?.type === "facebook-connection-failed") {
        completedRef.current = true
        setBusy(false)
        toast.error(event.data.message || "Connection was not completed.")
      }
    }
    window.addEventListener("message", handleMessage)
    return () => window.removeEventListener("message", handleMessage)
  }, [onConnected])
  function connect() {
    setBusy(true)
    completedRef.current = false
    try {
      const token = window.localStorage.getItem("auth_token")
      if (!token) throw new Error("Missing auth token")
      const width = 600
      const height = 700
      const left = Math.max(0, window.screenX + (window.outerWidth - width) / 2)
      const top = Math.max(0, window.screenY + (window.outerHeight - height) / 2)
      const popup = window.open(
        `${API_BASE_URL}/auth/facebook/start?token=${encodeURIComponent(token)}`,
        "facebook-oauth",
        `toolbar=no,menubar=no,scrollbars=yes,resizable=yes,width=${width},height=${height},left=${left},top=${top}`
      )
      if (!popup) throw new Error("Popup blocked")
      const timer = window.setInterval(() => {
        if (popup?.closed) {
          window.clearInterval(timer)
          setBusy(false)
          if (!completedRef.current) {
            toast.info("Connection was not completed. You can try again anytime.")
          }
        }
      }, 500)
    } catch {
      toast.error("Could not open the Facebook connection window.")
      setBusy(false)
    }
  }
  return <Button className={cn("bg-[#1877F2] text-white hover:bg-[#0f66d0]", className)} onClick={connect} disabled={busy}>{busy ? <Loader2 className="size-4 animate-spin" /> : <span className="grid size-4 place-items-center rounded-full bg-white text-xs font-bold text-[#1877F2]">f</span>} {busy ? "Connecting..." : "Connect Facebook Page"}</Button>
}

function Composer({ pages, timezone, onSaved }: { pages: PageConnection[]; timezone: string; onSaved: () => void }) {
  const router = useRouter()
  const [selectedPageId, setSelectedPageId] = React.useState<number | null>(pages[0]?.id ?? null)
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
  const selectedPage = pages.find((page) => page.id === selectedPageId) || pages[0]
  const url = content.match(/https?:\/\/\S+/)?.[0] || ""
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
      toast.error(error?.response?.data?.detail || "Publishing failed. Please try again.")
    } finally {
      setSaving(false)
    }
  }
  return (
    <>
      <PageTitle title="Create Post" subtitle="Compose, preview, publish now, or schedule for later." />
      <Card><CardContent className="grid gap-5 p-6">
        {pages.length > 1 ? <Select value={String(selectedPageId ?? pages[0].id)} onChange={(event) => setSelectedPageId(Number(event.target.value))}>{pages.map((page) => <option key={page.id} value={String(page.id)}>{page.page_name}</option>)}</Select> : pages[0] ? <PageMini page={pages[0]} /> : <Empty text="Connect a page before publishing." action="/dashboard/settings" />}
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
        <div className="grid gap-2"><Label>Image or video URL</Label><Input value={media} onChange={(event) => setMedia(event.target.value)} placeholder="https://example.com/media.jpg" /></div>
        {url ? <div className="flex items-start justify-between rounded-md border bg-slate-50 p-3 text-sm"><div><p className="font-medium">Link Preview</p><p className="text-slate-500">{url}</p></div><Button size="icon" variant="ghost" onClick={() => setContent(content.replace(url, ""))}><X className="size-4" /></Button></div> : null}
        <div className="flex items-center justify-between rounded-md border p-3"><div><p className="font-medium">Schedule for Later</p><p className="text-sm text-slate-500">{timezone}</p></div><Switch checked={scheduleLater} onCheckedChange={setScheduleLater} /></div>
        {scheduleLater ? <Input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /> : null}
        <div className="flex flex-col gap-2 sm:flex-row"><Button variant="outline" onClick={() => submit(true)} disabled={saving}>Save as Draft</Button><Button title={remaining < 0 ? "Post too long" : undefined} className="bg-blue-700 hover:bg-blue-800" onClick={() => submit(false)} disabled={saving || remaining < 0 || !content.trim() || !pages.length}>{saving ? "Publishing..." : scheduleLater ? "Schedule" : "Publish to Facebook"}</Button><Button variant="ghost" onClick={() => router.push("/dashboard")}>Cancel</Button></div>
      </CardContent></Card>
    </>
  )
}

const toneOptions = ["Professional", "Casual", "Funny", "Inspirational", "Educational", "Promotional", "Storytelling", "Controversial", "Friendly", "Bold"]
const languages = ["English", "Bengali", "Hindi", "Arabic", "Spanish", "French", "Portuguese", "Indonesian"]
const dayOptions = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const personaColors = ["bg-blue-50 text-blue-800 border-blue-200", "bg-emerald-50 text-emerald-800 border-emerald-200", "bg-amber-50 text-amber-800 border-amber-200", "bg-rose-50 text-rose-800 border-rose-200", "bg-violet-50 text-violet-800 border-violet-200"]

function emptyPersona(): AIPersona {
  return {
    persona_name: "",
    niche: "",
    tone_tags: ["Professional"],
    custom_instructions: "",
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

function AISettingsView({ pages }: { pages: PageConnection[] }) {
  const [selectedPageId, setSelectedPageId] = React.useState<number | null>(pages[0]?.id ?? null)
  const [personas, setPersonas] = React.useState<AIPersona[]>([])
  const [editing, setEditing] = React.useState<AIPersona | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [sample, setSample] = React.useState("")
  const [insights, setInsights] = React.useState<PerformanceInsights | null>(null)
  const selectedPage = pages.find((page) => page.id === selectedPageId) || pages[0]

  const loadPersonas = React.useCallback(() => {
    if (!selectedPage?.id) return
    api.get<AIPersona[]>(`/api/ai/personas/${selectedPage.id}`).then((response) => {
      setPersonas(response.data)
      setEditing(null)
    })
    api.get<PerformanceInsights>(`/api/ai/performance/${selectedPage.id}`).then((response) => setInsights(response.data)).catch(() => setInsights(null))
  }, [selectedPage?.id])

  React.useEffect(() => { loadPersonas() }, [loadPersonas])

  const draft = editing || emptyPersona()
  const dayOwners = Object.fromEntries(dayOptions.map((day) => [day, personas.find((persona) => persona.assigned_days.includes(day))]))

  function toggleTone(tone: string) {
    setEditing((value) => value ? ({
      ...value,
      tone_tags: value.tone_tags.includes(tone) ? value.tone_tags.filter((item) => item !== tone) : [...value.tone_tags, tone],
    }) : value)
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
    setSaving(true)
    try {
      if (draft.id) await api.put<AIPersona>(`/api/ai/personas/${draft.id}`, draft)
      else await api.post<AIPersona>(`/api/ai/personas/${selectedPage.id}`, draft)
      await loadPersonas()
      if (showToast) toast.success("AI persona saved.")
    } finally {
      setSaving(false)
    }
  }
  async function saveSettings() {
    try {
      await savePersona(true)
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

  return <><PageTitle title="AI Personas" subtitle="Create up to five page-specific AI personas with their own tone and schedule." />{!pages.length ? <Empty text="Connect a page before setting up AI personas." action="/dashboard/settings" /> : <div className="grid gap-5">
    {pages.length > 1 ? <Select value={String(selectedPageId ?? pages[0].id)} onChange={(event) => setSelectedPageId(Number(event.target.value))}>{pages.map((page) => <option key={page.id} value={String(page.id)}>{page.page_name}</option>)}</Select> : <PageMini page={pages[0]} />}
    <div className="grid grid-cols-2 gap-2 md:grid-cols-7">{dayOptions.map((day) => {
      const owner = dayOwners[day]
      const index = owner ? Math.max(0, personas.findIndex((persona) => persona.id === owner.id)) : 0
      return <button key={day} className={cn("min-h-24 rounded-md border p-3 text-left", owner ? personaColors[index % personaColors.length] : "border-dashed bg-white text-slate-500")} onClick={() => setEditing(owner || emptyPersona())}><div className="flex items-center justify-between"><span className="font-medium">{day}</span>{!owner ? <Plus className="size-4" /> : null}</div><p className="mt-3 text-xs">{owner?.persona_name || "Unassigned"}</p></button>
    })}</div>
    <div className="grid gap-4 md:grid-cols-2">{personas.map((persona, index) => <Card key={persona.id}><CardContent className="grid gap-3 p-5"><div className="flex items-start justify-between gap-3"><div><h2 className="font-semibold">{persona.persona_name}</h2><p className="text-sm text-slate-500">{persona.assigned_days.join(", ") || "No days assigned"}</p></div><span className={cn("rounded-full px-2 py-1 text-xs font-medium", persona.is_active ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-600")}>{persona.is_active ? "Active" : "Paused"}</span></div><div className="flex flex-wrap gap-2">{persona.tone_tags.map((tag) => <span key={tag} className={cn("rounded-full border px-2 py-1 text-xs", personaColors[index % personaColors.length])}>{tag}</span>)}</div><div className="flex items-center justify-between text-sm text-slate-500"><span>{persona.posting_time_slots.join(", ")}</span><span>Score {Number(persona.performance_score || 0.5).toFixed(2)}</span></div><Button variant="outline" onClick={() => setEditing(persona)}>Edit</Button></CardContent></Card>)}{personas.length < 5 ? <Button variant="outline" className="min-h-36 border-dashed" onClick={() => setEditing({ ...emptyPersona(), persona_name: `Persona ${personas.length + 1}` })}><Plus className="size-4" /> Add New Persona</Button> : null}</div>
    <PerformanceInsightsPanel insights={insights} personas={personas} timezone={Intl.DateTimeFormat().resolvedOptions().timeZone} />
  </div>}{editing ? <div className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-4"><Card className="mx-auto my-6 max-w-3xl"><CardHeader><CardTitle>{editing.id ? "Edit Persona" : "Add New Persona"}</CardTitle></CardHeader><CardContent className="grid gap-5"><div className="grid gap-2"><Label>Persona Name</Label><Input value={draft.persona_name} onChange={(event) => setEditing({ ...draft, persona_name: event.target.value })} placeholder="Motivational Mondays" /></div><div className="grid gap-2"><Label>What is your page about?</Label><Input value={draft.niche} onChange={(event) => setEditing({ ...draft, niche: event.target.value })} placeholder="e.g. fitness and healthy living, tech news, motivational quotes." /></div><div className="grid gap-2"><Label>Tone and Style</Label><div className="flex flex-wrap gap-2">{toneOptions.map((tone) => <Button key={tone} type="button" variant={draft.tone_tags.includes(tone) ? "default" : "outline"} className={draft.tone_tags.includes(tone) ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => toggleTone(tone)}>{tone}</Button>)}</div></div><div className="grid gap-2"><Label>Additional instructions for the AI.</Label><Textarea className="min-h-28" value={draft.custom_instructions || ""} onChange={(event) => setEditing({ ...draft, custom_instructions: event.target.value })} /></div><div className="grid gap-3 md:grid-cols-2"><div className="grid gap-2"><Label>Post Language</Label><Select value={draft.language} onChange={(event) => setEditing({ ...draft, language: event.target.value })}>{languages.map((language) => <option key={language}>{language}</option>)}</Select></div><div className="grid gap-2"><Label>Priority Level</Label><Select value={draft.priority_level} onChange={(event) => setEditing({ ...draft, priority_level: event.target.value as AIPersona["priority_level"] })}><option>High</option><option>Normal</option><option>Low</option></Select></div></div><div className="grid gap-2"><Label>Assigned Days</Label><div className="flex flex-wrap gap-2">{dayOptions.map((day) => <Button key={day} type="button" variant={draft.assigned_days.includes(day) ? "default" : "outline"} className={draft.assigned_days.includes(day) ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => toggleDay(day)}>{day}</Button>)}</div></div><div className="grid gap-2"><Label>Posting Times</Label>{draft.posting_time_slots.map((slot, index) => <div key={`${slot}-${index}`} className="flex gap-2"><Input type="time" value={slot} onChange={(event) => setEditing({ ...draft, posting_time_slots: draft.posting_time_slots.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })} />{draft.posting_time_slots.length > 1 ? <Button size="icon" variant="outline" onClick={() => setEditing({ ...draft, posting_time_slots: draft.posting_time_slots.filter((_, itemIndex) => itemIndex !== index) })}><X className="size-4" /></Button> : null}</div>)}{draft.posting_time_slots.length < 4 ? <Button variant="outline" className="w-fit" onClick={() => setEditing({ ...draft, posting_time_slots: [...draft.posting_time_slots, "18:00"] })}><Plus className="size-4" /> Add Time</Button> : null}</div><div className="grid gap-3 rounded-md border p-3"><div className="flex items-center justify-between"><Label>Automatically add hashtags to posts.</Label><Switch checked={draft.hashtags_enabled} onCheckedChange={(checked) => setEditing({ ...draft, hashtags_enabled: checked })} /></div>{draft.hashtags_enabled ? <Input type="number" min={1} max={30} value={draft.hashtag_count} onChange={(event) => setEditing({ ...draft, hashtag_count: Number(event.target.value) })} /> : null}</div><div className="flex items-center justify-between rounded-md border p-3"><Label>Persona Active</Label><Switch checked={draft.is_active} onCheckedChange={(checked) => setEditing({ ...draft, is_active: checked })} /></div><div className="grid gap-3 rounded-md border p-3"><div className="flex items-center justify-between"><Label>Learning Mode</Label><Switch checked={draft.learning_mode_enabled} onCheckedChange={(checked) => setEditing({ ...draft, learning_mode_enabled: checked })} /></div><div className="grid gap-2"><Label>Minimum Engagement Threshold</Label><Input type="number" min={0} value={draft.minimum_engagement_threshold} onChange={(event) => setEditing({ ...draft, minimum_engagement_threshold: Number(event.target.value) })} /></div>{draft.learned_patterns_summary ? <p className="text-sm text-slate-500">{draft.learned_patterns_summary}</p> : null}{draft.id ? <Button type="button" variant="outline" className="w-fit" onClick={resetLearning}><RotateCcw className="size-4" /> Reset Learning</Button> : null}</div><div className="flex flex-col gap-2 sm:flex-row"><Button className="bg-blue-700 hover:bg-blue-800" onClick={saveSettings} disabled={saving}>{saving ? "Saving..." : "Save Persona"}</Button><Button variant="outline" onClick={testSample} disabled={saving}>Test Sample</Button><Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button></div></CardContent></Card></div> : null}{sample ? <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 p-4"><Card className="max-w-xl"><CardHeader><CardTitle>Sample AI Post</CardTitle></CardHeader><CardContent className="grid gap-4"><p className="whitespace-pre-wrap text-sm text-slate-700">{sample}</p><Button className="w-fit bg-blue-700 hover:bg-blue-800" onClick={() => setSample("")}>Close</Button></CardContent></Card></div> : null}</>
}

function dayName(day: string) {
  return { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" }[day] || day
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
  const visiblePosts = published ? posts.filter((post) => aiFilter === "all" || (aiFilter === "ai" ? post.ai_generated : !post.ai_generated)) : posts
  async function remove(id: number) {
    if (!window.confirm("Are you sure? This cannot be undone.")) return
    await api.delete(`/posts/${id}`)
    toast.success("Post removed.")
    onChanged()
  }
  return <><PageTitle title={title} subtitle={published ? "Live posts with engagement snapshots from the learning optimizer." : "Upcoming posts sorted by scheduled time."} />{published ? <div className="flex flex-wrap gap-2">{(["all", "manual", "ai"] as const).map((value) => <Button key={value} variant={aiFilter === value ? "default" : "outline"} className={aiFilter === value ? "bg-blue-700 hover:bg-blue-800" : ""} onClick={() => setAiFilter(value)}>{value === "all" ? "Show All" : value === "manual" ? "Manual Only" : "AI Generated Only"}</Button>)}</div> : null}<div className="grid gap-4">{visiblePosts.map((post) => <Card key={post.id}><CardContent className="grid gap-3 p-6"><PostRow post={post} timezone={timezone} />{published ? <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">{post.low_engagement ? <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">Low engagement</span> : null}<span>Likes {post.likes_count || 0}</span><span>Comments {post.comments_count || 0}</span><span>Shares {post.shares_count || 0}</span><span>Reach {post.reach_count || 0}</span><span>Score {Number(post.engagement_score || 0).toFixed(1)}</span><Button size="icon" variant="ghost"><RefreshCw className="size-4" /></Button></div> : null}<div className="flex flex-wrap gap-2"><Button variant="outline" asChild><Link href="/dashboard/create">Edit</Link></Button>{!published ? <Button variant="outline">Reschedule</Button> : null}<Button variant="destructive" onClick={() => remove(post.id)}><Trash2 className="size-4" /> {published ? "Delete from Facebook" : "Delete"}</Button></div></CardContent></Card>)} {!visiblePosts.length ? <Empty text={emptyText} action={emptyAction} /> : null}</div></>
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
    if (!window.confirm("Disconnect this page and pause its scheduled posts?")) return
    await api.delete(`/facebook/pages/${id}`)
    toast.success("Page disconnected.")
    onChanged()
  }
  return <><PageTitle title="Settings" subtitle="Account, page connections, and timezone." /><Card><CardHeader><CardTitle>Account</CardTitle></CardHeader><CardContent className="grid gap-3"><Label>Email</Label><Input value={email} onChange={(event) => setEmail(event.target.value)} /><Button className="w-fit bg-blue-700 hover:bg-blue-800" onClick={saveAccount}>Save Account</Button></CardContent></Card><Card><CardHeader><CardTitle>Connected Pages</CardTitle></CardHeader><CardContent className="grid gap-3">{pages.map((page) => <div key={page.id} className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between"><PageMini page={page} /><div className="flex gap-2"><Button variant="outline" onClick={async () => { await api.post(`/facebook/pages/${page.id}/refresh-token`); toast.success("Token refreshed."); onChanged() }}>Refresh Token</Button><Button variant="destructive" onClick={() => disconnect(page.id)}>Disconnect</Button></div></div>)}<div className="grid gap-2 rounded-md border p-3"><p className="font-medium">Manual connection</p><Input placeholder="Facebook Page ID" value={manualPageId} onChange={(event) => setManualPageId(event.target.value)} /><Textarea placeholder="Long-lived Page Access Token" value={manualToken} onChange={(event) => setManualToken(event.target.value)} /><Button className="w-fit bg-blue-700 hover:bg-blue-800" onClick={manualConnect}>Validate Page</Button></div></CardContent></Card><Card><CardHeader><CardTitle>Timezone</CardTitle></CardHeader><CardContent className="grid gap-3"><Input value={tz} onChange={(event) => setTz(event.target.value)} /><p className="text-sm text-slate-500">Default was detected from your browser. All stored schedule times are converted to UTC.</p></CardContent></Card></>
}

function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return <div><h1 className="text-2xl font-semibold">{title}</h1><p className="text-sm text-slate-500">{subtitle}</p></div>
}

function PageMini({ page }: { page: PageConnection }) {
  return <div className="flex items-center gap-3"><img alt="" className="size-9 rounded-full bg-slate-100" src={page.page_picture_url || `${API_BASE_URL}/favicon.ico`} /><div><p className="text-sm font-medium">{page.page_name}</p><p className="text-xs text-slate-500">Manage Connection</p></div></div>
}

function ConnectedBanner({ page, onConnected }: { page: PageConnection; onConnected: () => void }) {
  const needsReconnect = page.connection_status === "needs-reconnection"
  return <div className="flex flex-col gap-3 rounded-md border bg-white p-4 sm:flex-row sm:items-center sm:justify-between"><PageMini page={page} /><div className="flex items-center gap-2"><span className={cn("rounded-full px-2 py-1 text-xs font-medium", needsReconnect ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700")}>{needsReconnect ? "Reconnection Needed" : "Connected"}</span>{needsReconnect ? <FacebookConnectButton onConnected={onConnected} /> : null}</div></div>
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


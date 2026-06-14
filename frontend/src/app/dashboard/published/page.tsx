"use client"

import { useApp } from "@/contexts/app-context"
import { useAuth } from "@/contexts/auth-context"
import { PostList } from "@/components/social-platform"
import { Loader2 } from "lucide-react"

export default function PublishedPostsPage() {
  const { posts, isInitialLoading, refreshPosts } = useApp()
  const { user } = useAuth()
  const timezone = user?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"

  if (isInitialLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="size-6 animate-spin text-slate-400" /></div>
  }

  const publishedPosts = posts.filter((post: any) => post.status === "published" || post.status === "success")

  return (
    <PostList 
      title="Published Posts" 
      posts={publishedPosts} 
      emptyAction="/dashboard/create" 
      emptyText="No published posts yet." 
      timezone={timezone} 
      published={true} 
      onChanged={refreshPosts} 
    />
  )
}

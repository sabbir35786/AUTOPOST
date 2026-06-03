"use client"

import * as React from "react"
import { toast } from "sonner"

import { api, getApiErrorMessage } from "@/lib/api"
import type { BackgroundAsset, FontAsset } from "@/lib/template-types"

export function useTemplateAssets() {
  const [backgroundAssets, setBackgroundAssets] = React.useState<BackgroundAsset[]>([])
  const [fontAssets, setFontAssets] = React.useState<FontAsset[]>([])
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const [bgRes, fontRes] = await Promise.all([
          api.get<BackgroundAsset[]>("/api/template-assets/backgrounds"),
          api.get<FontAsset[]>("/api/template-assets/fonts"),
        ])
        if (!cancelled) {
          setBackgroundAssets(bgRes.data)
          setFontAssets(fontRes.data)
        }
      } catch (err) {
        if (!cancelled) toast.error(getApiErrorMessage(err, "Failed to load design assets."))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return { backgroundAssets, fontAssets, loading }
}

"use client"

import * as React from "react"
import { Check, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, getApiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

type BackgroundOption = { asset_id: string; label: string }

type LlmLayerInstruction = {
  layer_id: string
  text?: string
  font_asset_id?: string
  color_hex?: string
  font_size_percent?: number
  text_align?: string
  opacity?: number
}

type ImageGenerationStatus = {
  can_edit_photocard?: boolean
  chosen_background_asset_id?: string
  background_options?: BackgroundOption[]
  llm_instructions?: {
    chosen_background_asset_id?: string
    layers?: LlmLayerInstruction[]
  }
  final_image_url?: string | null
  image_url?: string | null
}

type BackgroundAsset = {
  id: string
  asset_type: string
  label: string | null
  preview_url: string | null
  value_json: Record<string, unknown>
}

function backgroundSwatchStyle(asset: {
  asset_type: string
  value_json: Record<string, unknown>
}): React.CSSProperties {
  const v = asset.value_json || {}
  if (asset.asset_type === "gradient" && Array.isArray(v.stops)) {
    return { background: `linear-gradient(135deg, ${(v.stops as string[]).join(", ")})` }
  }
  return { backgroundColor: String(v.color_hex || "#334155") }
}

type PostPhotocardEditorProps = {
  postId: number
  onSaved: () => void
}

export function PostPhotocardEditor({ postId, onSaved }: PostPhotocardEditorProps) {
  const [loading, setLoading] = React.useState(true)
  const [saving, setSaving] = React.useState(false)
  const [status, setStatus] = React.useState<ImageGenerationStatus | null>(null)
  const [backgroundAssets, setBackgroundAssets] = React.useState<BackgroundAsset[]>([])
  const [selectedBackgroundId, setSelectedBackgroundId] = React.useState("")
  const [textEdits, setTextEdits] = React.useState<Record<string, string>>({})
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const [genRes, assetsRes] = await Promise.all([
          api.get<ImageGenerationStatus>(`/api/posts/${postId}/image-status`),
          api.get<BackgroundAsset[]>("/api/template-assets/backgrounds"),
        ])
        if (cancelled) return
        const gen = genRes.data
        setStatus(gen)
        setPreviewUrl(gen.final_image_url || gen.image_url || null)

        const allowedIds = new Set((gen.background_options || []).map((b) => b.asset_id))
        setBackgroundAssets(assetsRes.data.filter((a) => allowedIds.has(a.id)))

        const chosen =
          gen.chosen_background_asset_id ||
          gen.llm_instructions?.chosen_background_asset_id ||
          ""
        setSelectedBackgroundId(chosen)

        const edits: Record<string, string> = {}
        for (const layer of gen.llm_instructions?.layers || []) {
          if (layer.layer_id && layer.text != null) {
            edits[layer.layer_id] = layer.text
          }
        }
        setTextEdits(edits)
      } catch (err) {
        if (!cancelled) toast.error(getApiErrorMessage(err, "Could not load photocard editor."))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [postId])

  const textLayers = (status?.llm_instructions?.layers || []).filter((l) => l.text != null)

  async function applyChanges() {
    if (!status?.can_edit_photocard) return
    setSaving(true)
    try {
      const form = new FormData()
      const currentBg =
        status.chosen_background_asset_id || status.llm_instructions?.chosen_background_asset_id || ""
      if (selectedBackgroundId && selectedBackgroundId !== currentBg) {
        form.append("override_background_asset_id", selectedBackgroundId)
      }

      const textOverrides = textLayers
        .filter((layer) => {
          const original = layer.text || ""
          const edited = textEdits[layer.layer_id] ?? original
          return edited.trim() !== original.trim()
        })
        .map((layer) => ({
          layer_id: layer.layer_id,
          text: (textEdits[layer.layer_id] ?? layer.text ?? "").trim(),
        }))
      if (textOverrides.length) {
        form.append("text_overrides", JSON.stringify(textOverrides))
      }

      if (!form.has("override_background_asset_id") && !form.has("text_overrides")) {
        toast.message("No changes to apply.")
        return
      }

      const res = await api.patch<ImageGenerationStatus>(`/api/posts/${postId}/image`, form)
      setStatus(res.data)
      setPreviewUrl(res.data.final_image_url || res.data.image_url || previewUrl)
      toast.success("Photocard updated.")
      onSaved()
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not update photocard."))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (!status?.can_edit_photocard) {
    return (
      <p className="text-sm text-slate-600 py-4">
        This post image was not built with a manual template photocard, so background and text options cannot be edited here.
      </p>
    )
  }

  return (
    <div className="grid gap-5">
      {previewUrl ? (
        <div className="flex justify-center rounded-lg border bg-slate-100 p-3">
          <img src={previewUrl} alt="Post photocard" className="max-h-64 max-w-full rounded shadow-sm object-contain" />
        </div>
      ) : null}

      <div className="grid gap-3">
        <Label>Background</Label>
        <p className="text-xs text-slate-500">Pick a background from this template&apos;s allowed options. No AI call — instant re-render.</p>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {backgroundAssets.map((asset) => {
            const selected = selectedBackgroundId === asset.id
            const optionLabel = status.background_options?.find((b) => b.asset_id === asset.id)?.label
            return (
              <button
                key={asset.id}
                type="button"
                onClick={() => setSelectedBackgroundId(asset.id)}
                className={cn(
                  "relative aspect-square rounded-lg border-2 overflow-hidden",
                  selected ? "border-purple-600 ring-2 ring-purple-200" : "border-slate-200 hover:border-slate-400",
                )}
              >
                <div className="absolute inset-0" style={backgroundSwatchStyle(asset)} />
                {asset.preview_url ? (
                  <img src={asset.preview_url} alt="" className="absolute inset-0 h-full w-full object-cover" />
                ) : null}
                <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[10px] px-1 py-0.5 truncate">
                  {optionLabel || asset.label || "Background"}
                </span>
                {selected ? (
                  <span className="absolute top-1 right-1 rounded-full bg-purple-600 p-0.5 text-white">
                    <Check className="size-3" />
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>
      </div>

      {textLayers.length > 0 ? (
        <div className="grid gap-3">
          <Label>Overlay text</Label>
          {textLayers.map((layer) => (
            <div key={layer.layer_id} className="grid gap-1">
              <Label className="text-xs text-slate-500">{layer.layer_id}</Label>
              <Input
                value={textEdits[layer.layer_id] ?? layer.text ?? ""}
                onChange={(e) =>
                  setTextEdits((prev) => ({ ...prev, [layer.layer_id]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
      ) : null}

      <Button
        className="bg-purple-700 text-white hover:bg-purple-800 w-full sm:w-auto"
        onClick={applyChanges}
        disabled={saving}
      >
        {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
        Apply changes
      </Button>
    </div>
  )
}

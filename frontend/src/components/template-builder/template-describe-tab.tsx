"use client"

import * as React from "react"
import { Check, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { api, getApiErrorMessage } from "@/lib/api"
import { backgroundSwatchStyle } from "@/lib/template-state"
import type { AspectKey, BackgroundAsset, ManualTemplateJson } from "@/lib/template-types"
import { cn } from "@/lib/utils"

type Props = {
  aspectRatio: AspectKey
  backgrounds: BackgroundAsset[]
  loadingAssets: boolean
  onGenerated: (json: ManualTemplateJson) => void
}

export function TemplateDescribeTab({
  aspectRatio,
  backgrounds,
  loadingAssets,
  onGenerated,
}: Props) {
  const [description, setDescription] = React.useState("")
  const [selectedBgIds, setSelectedBgIds] = React.useState<string[]>([])
  const [generating, setGenerating] = React.useState(false)

  function toggleBg(id: string) {
    setSelectedBgIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 3) {
        toast.error("Select at most 3 backgrounds as mood hints.")
        return prev
      }
      return [...prev, id]
    })
  }

  async function generate() {
    if (!description.trim()) {
      toast.error("Enter a description first.")
      return
    }
    setGenerating(true)
    try {
      const res = await api.post<{ template_json: ManualTemplateJson }>(
        "/api/image-templates/generate-from-description",
        {
          description: description.trim(),
          canvas_aspect_ratio: aspectRatio,
          available_background_asset_ids: selectedBgIds,
        },
      )
      onGenerated(res.data.template_json)
      toast.success(
        "Template generated. Review it in the JSON Editor or Visual Builder, then save.",
      )
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Generation failed."))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="grid gap-4 max-w-2xl">
      <div className="grid gap-2">
        <Label>Describe your template</Label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={8}
          placeholder="Describe your template in plain language. For example: I want a dark background with a bold white headline in the center, a smaller subtitle below it, and my logo in the top right corner. The style should feel professional and modern."
          className="w-full rounded-md border px-3 py-2 text-sm min-h-[160px]"
        />
      </div>
      <div className="grid gap-2">
        <Label>Background mood (optional, 1–3)</Label>
        <p className="text-xs text-slate-500">
          Pick backgrounds to tell the LLM which assets are available.
        </p>
        {loadingAssets ? (
          <Loader2 className="size-6 animate-spin text-slate-400" />
        ) : (
          <div className="flex gap-2 overflow-x-auto pb-2">
            {backgrounds.map((asset) => {
              const selected = selectedBgIds.includes(asset.id)
              return (
                <button
                  key={asset.id}
                  type="button"
                  onClick={() => toggleBg(asset.id)}
                  className={cn(
                    "relative shrink-0 size-16 rounded-lg border-2 overflow-hidden",
                    selected ? "border-purple-600 ring-2 ring-purple-200" : "border-slate-200",
                  )}
                >
                  <div className="absolute inset-0" style={backgroundSwatchStyle(asset)} />
                  {selected ? (
                    <span className="absolute top-1 right-1 rounded-full bg-purple-600 p-0.5 text-white">
                      <Check className="size-3" />
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
        )}
      </div>
      <Button
        type="button"
        className="bg-purple-700 text-white hover:bg-purple-800 w-fit"
        onClick={generate}
        disabled={generating}
      >
        {generating ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
        Generate Template
      </Button>
    </div>
  )
}

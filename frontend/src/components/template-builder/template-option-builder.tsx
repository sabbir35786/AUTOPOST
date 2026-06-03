"use client"

import * as React from "react"
import {
  Check,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Image as ImageIcon,
  Layers,
  Loader2,
  Plus,
  Trash2,
  Type,
} from "lucide-react"
import { toast } from "sonner"

import { TemplateLayerFields } from "@/components/template-builder/template-layer-fields"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { api, getApiErrorMessage } from "@/lib/api"
import {
  backgroundSwatchStyle,
  createDefaultLogoLayer,
  createDefaultOverlayLayer,
  createDefaultTextLayer,
  nextLayerId,
  nextZIndex,
} from "@/lib/template-state"
import type {
  AspectKey,
  BackgroundAsset,
  BackgroundOption,
  FontAsset,
  ManualTemplateJson,
  TemplateLayer,
  TemplateState,
} from "@/lib/template-types"
import { ASPECT_PRESETS } from "@/lib/template-types"
import { layerLabel } from "@/lib/template-validation"
import { cn } from "@/lib/utils"

type Props = {
  state: TemplateState
  backgrounds: BackgroundAsset[]
  fonts: FontAsset[]
  loadingAssets: boolean
  onStateChange: (state: TemplateState) => void
}

function layerIcon(type: string) {
  if (type === "text") return <Type className="size-4" />
  if (type === "logo") return <ImageIcon className="size-4" />
  return <Layers className="size-4" />
}

export function TemplateOptionBuilder({
  state,
  backgrounds,
  fonts,
  loadingAssets,
  onStateChange,
}: Props) {
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({})
  const [search, setSearch] = React.useState("")
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = React.useState(false)
  const previewRef = React.useRef<string | null>(null)
  const dragLayerId = React.useRef<string | null>(null)

  const json = state.templateJson
  const selectedIds = new Set(json.background_options.map((b) => b.asset_id))

  const filteredBgs = backgrounds.filter((b) => {
    const q = search.toLowerCase()
    if (!q) return true
    return (b.label || b.asset_type).toLowerCase().includes(q)
  })

  React.useEffect(() => {
    const controller = new AbortController()
    if (!json.background_options.length) {
      setPreviewUrl(null)
      return
    }
    const t = setTimeout(async () => {
      setPreviewLoading(true)
      try {
        const res = await api.post(
          "/api/image-templates/preview",
          { template_json: json, persona_id: null },
          { responseType: "blob", signal: controller.signal },
        )
        const url = URL.createObjectURL(res.data)
        if (previewRef.current) URL.revokeObjectURL(previewRef.current)
        previewRef.current = url
        setPreviewUrl(url)
      } catch (err) {
        if (!controller.signal.aborted) setPreviewUrl(null)
      } finally {
        if (!controller.signal.aborted) setPreviewLoading(false)
      }
    }, 500)
    return () => {
      clearTimeout(t)
      controller.abort()
    }
  }, [json])

  React.useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [],
  )

  function setJson(patch: Partial<ManualTemplateJson>) {
    onStateChange({ ...state, templateJson: { ...json, ...patch } })
  }

  function setAspect(ratio: AspectKey) {
    const preset = ASPECT_PRESETS[ratio]
    onStateChange({
      ...state,
      aspectRatio: ratio,
      canvasWidth: preset.width,
      canvasHeight: preset.height,
      templateJson: {
        ...json,
        aspect_ratio: ratio,
        canvas_width: preset.width,
        canvas_height: preset.height,
      },
    })
  }

  function toggleBackground(asset: BackgroundAsset) {
    const exists = json.background_options.find((b) => b.asset_id === asset.id)
    let next: BackgroundOption[]
    if (exists) {
      next = json.background_options.filter((b) => b.asset_id !== asset.id)
    } else {
      if (json.background_options.length >= 6) {
        toast.error("Maximum 6 backgrounds.")
        return
      }
      next = [
        ...json.background_options,
        { asset_id: asset.id, label: asset.label || "Background" },
      ]
    }
    setJson({ background_options: next })
    if (!state.previewBackgroundAssetId && next[0]) {
      onStateChange({
        ...state,
        templateJson: { ...json, background_options: next },
        previewBackgroundAssetId: next[0].asset_id,
      })
    } else {
      setJson({ background_options: next })
    }
  }

  function updateBgLabel(assetId: string, label: string) {
    setJson({
      background_options: json.background_options.map((b) =>
        b.asset_id === assetId ? { ...b, label } : b,
      ),
    })
  }

  function updateLayer(id: string, patch: Partial<TemplateLayer>) {
    setJson({
      layers: json.layers.map((l) => (l.id === id ? ({ ...l, ...patch } as TemplateLayer) : l)),
    })
  }

  function removeLayer(id: string) {
    setJson({ layers: json.layers.filter((l) => l.id !== id) })
  }

  function addLayer(type: "text" | "logo" | "overlay") {
    const id = nextLayerId(json.layers)
    const z = nextZIndex(json.layers)
    let layer: TemplateLayer
    if (type === "text") layer = createDefaultTextLayer(z, id, fonts)
    else if (type === "overlay") layer = createDefaultOverlayLayer(z, id)
    else layer = createDefaultLogoLayer(z, id)
    setJson({ layers: [...json.layers, layer] })
    setExpanded((e) => ({ ...e, [id]: true }))
  }

  function reorderLayers(fromId: string, toId: string) {
    if (fromId === toId) return
    const sorted = [...json.layers].sort((a, b) => a.z_index - b.z_index)
    const fromIdx = sorted.findIndex((l) => l.id === fromId)
    const toIdx = sorted.findIndex((l) => l.id === toId)
    if (fromIdx < 0 || toIdx < 0) return
    const [moved] = sorted.splice(fromIdx, 1)
    sorted.splice(toIdx, 0, moved)
    const reindexed = sorted.map((l, i) => ({ ...l, z_index: i }))
    setJson({ layers: reindexed })
  }

  const sortedLayers = [...json.layers].sort((a, b) => a.z_index - b.z_index)

  return (
    <div className="grid lg:grid-cols-[1fr_220px] gap-6">
      <div className="grid gap-6 max-h-[70vh] overflow-y-auto pr-2">
        <section className="grid gap-3">
          <h3 className="font-semibold text-sm">Canvas settings</h3>
          <div className="grid sm:grid-cols-2 gap-3 max-w-lg">
            <div className="grid gap-2">
              <Label>Aspect ratio</Label>
              <Select
                value={state.aspectRatio}
                onChange={(e) => setAspect(e.target.value as AspectKey)}
              >
                {Object.entries(ASPECT_PRESETS).map(([key, p]) => (
                  <option key={key} value={key}>
                    {p.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Template name</Label>
              <Input
                value={state.name}
                onChange={(e) => onStateChange({ ...state, name: e.target.value })}
                placeholder="e.g. Bold Quote Card"
              />
            </div>
          </div>
        </section>

        <section className="grid gap-3">
          <h3 className="font-semibold text-sm">Background options</h3>
          <Input
            placeholder="Search backgrounds…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-xs"
          />
          {loadingAssets ? (
            <Loader2 className="size-6 animate-spin text-slate-400" />
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              {filteredBgs.map((asset) => {
                const selected = selectedIds.has(asset.id)
                return (
                  <button
                    key={asset.id}
                    type="button"
                    onClick={() => toggleBackground(asset)}
                    className={cn(
                      "relative aspect-square rounded-lg border-2 overflow-hidden",
                      selected ? "border-purple-600" : "border-slate-200",
                    )}
                  >
                    <div className="absolute inset-0" style={backgroundSwatchStyle(asset)} />
                    {selected ? (
                      <span className="absolute top-1 right-1 rounded-full bg-purple-600 p-0.5 text-white">
                        <Check className="size-4" />
                      </span>
                    ) : null}
                  </button>
                )
              })}
            </div>
          )}
          {json.background_options.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {json.background_options.map((bg) => {
                const asset = backgrounds.find((a) => a.id === bg.asset_id)
                return (
                  <div key={bg.asset_id} className="rounded-md border p-2 min-w-[140px] flex-1">
                    <div
                      className="h-8 rounded mb-2"
                      style={asset ? backgroundSwatchStyle(asset) : undefined}
                    />
                    <Input
                      value={bg.label}
                      onChange={(e) => updateBgLabel(bg.asset_id, e.target.value)}
                      className="text-xs h-8"
                    />
                  </div>
                )
              })}
            </div>
          ) : null}
        </section>

        <section className="grid gap-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm">Layers</h3>
            <div className="flex gap-1">
              <Button type="button" size="sm" variant="outline" onClick={() => addLayer("text")}>
                <Plus className="size-3 mr-1" /> Text
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => addLayer("logo")}>
                Logo
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => addLayer("overlay")}>
                Overlay
              </Button>
            </div>
          </div>
          <ul className="grid gap-2">
            {sortedLayers.map((layer) => {
              const isOpen = expanded[layer.id] ?? false
              return (
                <li
                  key={layer.id}
                  className="rounded-lg border bg-white"
                  draggable
                  onDragStart={() => {
                    dragLayerId.current = layer.id
                  }}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => {
                    if (dragLayerId.current) reorderLayers(dragLayerId.current, layer.id)
                    dragLayerId.current = null
                  }}
                >
                  <div className="flex items-center gap-2 p-3 border-b">
                    <GripVertical className="size-4 text-slate-400 cursor-grab shrink-0" />
                    <button
                      type="button"
                      className="flex items-center gap-2 flex-1 text-left text-sm"
                      onClick={() =>
                        setExpanded((e) => ({ ...e, [layer.id]: !isOpen }))
                      }
                    >
                      {isOpen ? (
                        <ChevronDown className="size-4" />
                      ) : (
                        <ChevronRight className="size-4" />
                      )}
                      {layerIcon(layer.type)}
                      <span className="font-medium">{layerLabel(layer)}</span>
                    </button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="text-red-500"
                      onClick={() => removeLayer(layer.id)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  {isOpen ? (
                    <div className="p-3">
                      <TemplateLayerFields
                        layer={layer}
                        fontAssets={fonts}
                        onChange={(patch) => updateLayer(layer.id, patch)}
                        compact
                      />
                    </div>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>
      </div>

      <aside className="sticky top-4 self-start">
        <Label className="text-xs text-slate-500">Live preview</Label>
        <div className="mt-2 size-[200px] rounded-lg border bg-slate-100 flex items-center justify-center overflow-hidden">
          {previewLoading ? (
            <Loader2 className="size-6 animate-spin text-slate-400" />
          ) : previewUrl ? (
            <img src={previewUrl} alt="" className="max-w-full max-h-full object-contain" />
          ) : (
            <span className="text-xs text-slate-400 text-center px-2">Add backgrounds to preview</span>
          )}
        </div>
      </aside>
    </div>
  )
}

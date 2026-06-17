"use client"

import * as React from "react"
import { Check, ChevronLeft, ChevronRight, Layers, Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { api, getApiErrorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

const STEPS = ["Canvas", "Backgrounds", "Layers", "Preview"] as const

const ASPECT_PRESETS = {
  "1:1": { width: 1080, height: 1080, label: "1:1 (1080×1080)" },
  "4:5": { width: 1080, height: 1350, label: "4:5 (1080×1350)" },
  "9:16": { width: 1080, height: 1920, label: "9:16 (1080×1920)" },
  "16:9": { width: 1920, height: 1080, label: "16:9 (1920×1080)" },
} as const

type AspectKey = keyof typeof ASPECT_PRESETS

type BackgroundAsset = {
  id: string
  type: string
  label: string | null
  preview_url: string | null
  config: Record<string, unknown>
}

type FontAsset = {
  id: string
  display_name: string
  weight: string
  font_file_url: string
}

type SelectedBackground = {
  asset_id: string
  label: string
  preview_url: string | null
  type: string
  config: Record<string, unknown>
}

type ColorOptionDraft = { color_hex: string; label: string }
type OverlayColorDraft = { color_hex: string; opacity: number; label: string }

type TextLayerDraft = {
  id: string
  type: "text"
  role: "headline" | "subheadline" | "body"
  z_index: number
  position_x_percent: number
  position_y_percent: number
  width_percent: number
  height_percent: number
  font_asset_ids: string[]
  color_options: ColorOptionDraft[]
  font_size_min_percent: number
  font_size_max_percent: number
  text_align_options: ("left" | "center" | "right")[]
  font_weight: "bold" | "regular"
}

type OverlayLayerDraft = {
  id: string
  type: "overlay"
  z_index: number
  position_x_percent: number
  position_y_percent: number
  width_percent: number
  height_percent: number
  color_options: OverlayColorDraft[]
}

type LogoLayerDraft = {
  id: string
  type: "logo"
  z_index: number
  position_x_percent: number
  position_y_percent: number
  width_percent: number
  height_percent: number
}

type LayerDraft = TextLayerDraft | OverlayLayerDraft | LogoLayerDraft

type BuilderState = {
  step: number
  name: string
  aspectRatio: AspectKey
  canvasWidth: number
  canvasHeight: number
  selectedBackgrounds: SelectedBackground[]
  layers: LayerDraft[]
}

function nextLayerId(layers: LayerDraft[]): string {
  const nums = layers
    .map((l) => /^layer_(\d+)$/.exec(l.id)?.[1])
    .filter(Boolean)
    .map((n) => Number(n))
  const next = (nums.length ? Math.max(...nums) : 0) + 1
  return `layer_${next}`
}

function backgroundSwatchStyle(asset: BackgroundAsset | SelectedBackground): React.CSSProperties {
  const v = asset.config || {}
  if (asset.type === "gradient_linear" && v.from_hex && v.to_hex) {
    return { background: `linear-gradient(${v.angle_deg || 135}deg, ${v.from_hex}, ${v.to_hex})` }
  }
  if (asset.type === "gradient_radial" && v.center_hex && v.edge_hex) {
    return { background: `radial-gradient(circle, ${v.center_hex}, ${v.edge_hex})` }
  }
  const hex = String(v.hex || v.color_hex || "#334155")
  return { backgroundColor: hex }
}

function serializeLayers(layers: LayerDraft[], fonts: FontAsset[]) {
  const fontMap = Object.fromEntries(fonts.map((f) => [f.id, f]))
  return layers.map((layer) => {
    const base = {
      id: layer.id,
      type: layer.type,
      z_index: layer.z_index,
      position_x_percent: layer.position_x_percent,
      position_y_percent: layer.position_y_percent,
      width_percent: layer.width_percent,
      height_percent: layer.height_percent,
    }
    if (layer.type === "text") {
      return {
        ...base,
        role: layer.role,
        font_options: layer.font_asset_ids.map((fid) => ({
          font_asset_id: fid,
          label: fontMap[fid]?.display_name || "Font",
        })),
        color_options: layer.color_options,
        font_size_min_percent: layer.font_size_min_percent,
        font_size_max_percent: layer.font_size_max_percent,
        text_align_options: layer.text_align_options,
        font_weight: layer.font_weight,
      }
    }
    if (layer.type === "overlay") {
      return { ...base, color_options: layer.color_options }
    }
    return base
  })
}

function buildTemplateJsonFromState(state: BuilderState, fonts: FontAsset[]) {
  return {
    canvas_width: state.canvasWidth,
    canvas_height: state.canvasHeight,
    aspect_ratio: state.aspectRatio,
    background_options: state.selectedBackgrounds.map((b) => ({
      asset_id: b.asset_id,
      label: b.label.trim() || "Background",
    })),
    layers: serializeLayers(state.layers, fonts),
  }
}

type ManualTemplateBuilderProps = {
  onCancel: () => void
  onSaved: () => void
}

export function ManualTemplateBuilder({ onCancel, onSaved }: ManualTemplateBuilderProps) {
  const [state, setState] = React.useState<BuilderState>(() => ({
    step: 1,
    name: "",
    aspectRatio: "1:1",
    canvasWidth: 1080,
    canvasHeight: 1080,
    selectedBackgrounds: [],
    layers: [],
  }))
  const [backgroundAssets, setBackgroundAssets] = React.useState<BackgroundAsset[]>([])
  const [fontAssets, setFontAssets] = React.useState<FontAsset[]>([])
  const [loadingAssets, setLoadingAssets] = React.useState(true)
  const [saving, setSaving] = React.useState(false)
  const [showAddLayerPanel, setShowAddLayerPanel] = React.useState(false)
  const [editingLayerId, setEditingLayerId] = React.useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = React.useState(false)
  const [bgTab, setBgTab] = React.useState<"colors" | "gradients" | "photos">("colors")
  const [uploadingBg, setUploadingBg] = React.useState(false)
  const previewUrlRef = React.useRef<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoadingAssets(true)
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
        if (!cancelled) setLoadingAssets(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  React.useEffect(() => {
    if (state.step !== 4) return

    const controller = new AbortController()
    const templateJson = buildTemplateJsonFromState(state, fontAssets)

    ;(async () => {
      setPreviewLoading(true)
      try {
        const response = await api.post(
          "/api/image-templates/preview",
          { template_json: templateJson, persona_id: null },
          { responseType: "blob", signal: controller.signal },
        )
        const url = URL.createObjectURL(response.data)
        if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
        previewUrlRef.current = url
        setPreviewUrl(url)
      } catch (err) {
        if (!controller.signal.aborted) {
          toast.error(getApiErrorMessage(err, "Preview failed."))
          setPreviewUrl(null)
        }
      } finally {
        if (!controller.signal.aborted) setPreviewLoading(false)
      }
    })()

    return () => {
      controller.abort()
    }
  }, [
    state.step,
    state.canvasWidth,
    state.canvasHeight,
    state.aspectRatio,
    state.selectedBackgrounds,
    state.layers,
    fontAssets,
  ])

  React.useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current)
        previewUrlRef.current = null
      }
    }
  }, [])

  function setAspect(ratio: AspectKey) {
    const preset = ASPECT_PRESETS[ratio]
    setState((s) => ({
      ...s,
      aspectRatio: ratio,
      canvasWidth: preset.width,
      canvasHeight: preset.height,
    }))
  }

  function toggleBackground(asset: BackgroundAsset) {
    setState((s) => {
      const exists = s.selectedBackgrounds.find((b) => b.asset_id === asset.id)
      if (exists) {
        return { ...s, selectedBackgrounds: s.selectedBackgrounds.filter((b) => b.asset_id !== asset.id) }
      }
      if (s.selectedBackgrounds.length >= 6) {
        toast.error("Maximum 6 backgrounds allowed.")
        return s
      }
      return {
        ...s,
        selectedBackgrounds: [
          ...s.selectedBackgrounds,
          {
            asset_id: asset.id,
            label: asset.label || "Background",
            preview_url: asset.preview_url,
            type: asset.type,
            config: asset.config,
          },
        ],
      }
    })
  }

  async function handlePhotoUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingBg(true)
    try {
      const formData = new FormData()
      formData.append("image", file)
      formData.append("name", file.name.split(".")[0])
      
      const res = await api.post<BackgroundAsset>("/api/template-assets/backgrounds/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      
      setBackgroundAssets((prev) => [...prev, res.data])
      toggleBackground(res.data)
      toast.success("Photo uploaded successfully.")
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to upload photo."))
    } finally {
      setUploadingBg(false)
      if (e.target) e.target.value = ""
    }
  }

  function updateBackgroundLabel(assetId: string, label: string) {
    setState((s) => ({
      ...s,
      selectedBackgrounds: s.selectedBackgrounds.map((b) =>
        b.asset_id === assetId ? { ...b, label } : b,
      ),
    }))
  }

  function addLayer(type: "text" | "logo" | "overlay") {
    const id = nextLayerId(state.layers)
    const z = state.layers.length ? Math.max(...state.layers.map((l) => l.z_index)) + 1 : 1
    let layer: LayerDraft
    if (type === "text") {
      layer = {
        id,
        type: "text",
        role: "headline",
        z_index: z,
        position_x_percent: 10,
        position_y_percent: 38,
        width_percent: 80,
        height_percent: 20,
        font_asset_ids: fontAssets[0] ? [fontAssets[0].id] : [],
        color_options: [{ color_hex: "#ffffff", label: "White" }],
        font_size_min_percent: 4,
        font_size_max_percent: 7,
        text_align_options: ["center"],
        font_weight: "bold",
      }
    } else if (type === "overlay") {
      layer = {
        id,
        type: "overlay",
        z_index: z,
        position_x_percent: 0,
        position_y_percent: 0,
        width_percent: 100,
        height_percent: 100,
        color_options: [{ color_hex: "#000000", opacity: 0.4, label: "Dark" }],
      }
    } else {
      layer = {
        id,
        type: "logo",
        z_index: z,
        position_x_percent: 78,
        position_y_percent: 4,
        width_percent: 18,
        height_percent: 12,
      }
    }
    setState((s) => ({ ...s, layers: [...s.layers, layer] }))
    setShowAddLayerPanel(false)
    setEditingLayerId(id)
  }

  function updateLayer(id: string, patch: Partial<LayerDraft>) {
    setState((s) => ({
      ...s,
      layers: s.layers.map((l) => (l.id === id ? ({ ...l, ...patch } as LayerDraft) : l)),
    }))
  }

  function removeLayer(id: string) {
    setState((s) => ({ ...s, layers: s.layers.filter((l) => l.id !== id) }))
    if (editingLayerId === id) setEditingLayerId(null)
  }

  function validateStep(step: number): boolean {
    if (step === 1) {
      if (!state.name.trim()) {
        toast.error("Enter a template name.")
        return false
      }
      return true
    }
    if (step === 2) {
      if (state.selectedBackgrounds.length < 1) {
        toast.error("Select at least one background.")
        return false
      }
      if (state.selectedBackgrounds.some((b) => !b.label.trim())) {
        toast.error("Name each selected background.")
        return false
      }
      return true
    }
    if (step === 3) {
      for (const layer of state.layers) {
        if (layer.type === "text") {
          if (!layer.font_asset_ids.length) {
            toast.error(`Layer ${layer.id}: pick at least one font.`)
            return false
          }
          if (!layer.color_options.length) {
            toast.error(`Layer ${layer.id}: add at least one color.`)
            return false
          }
          if (!layer.text_align_options.length) {
            toast.error(`Layer ${layer.id}: pick at least one text alignment.`)
            return false
          }
        }
        if (layer.type === "overlay" && !layer.color_options.length) {
          toast.error(`Layer ${layer.id}: add at least one overlay color.`)
          return false
        }
      }
      return true
    }
    return true
  }

  function goNext() {
    if (!validateStep(state.step)) return
    setState((s) => ({ ...s, step: Math.min(4, s.step + 1) }))
  }

  function goBack() {
    setState((s) => ({ ...s, step: Math.max(1, s.step - 1) }))
  }

  async function saveTemplate() {
    if (!validateStep(1) || !validateStep(2) || !validateStep(3)) return
    setSaving(true)
    try {
      const payload = {
        name: state.name.trim(),
        canvas_width: state.canvasWidth,
        canvas_height: state.canvasHeight,
        aspect_ratio: state.aspectRatio,
        template_json: buildTemplateJsonFromState(state, fontAssets),
      }
      await api.post("/api/image-templates/manual", payload)
      toast.success("Template saved successfully.")
      onSaved()
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to save template."))
    } finally {
      setSaving(false)
    }
  }

  const editingLayer = state.layers.find((l) => l.id === editingLayerId)

  return (
    <Card className="border-purple-200">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2">
          <span>Build Template Manually</span>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            <X className="size-4 mr-1" /> Cancel
          </Button>
        </CardTitle>
        <div className="flex gap-2 mt-2">
          {STEPS.map((label, i) => {
            const n = i + 1
            const active = state.step === n
            const done = state.step > n
            return (
              <div
                key={label}
                className={cn(
                  "flex-1 rounded-md border px-2 py-1.5 text-center text-xs font-medium",
                  active && "border-purple-600 bg-purple-50 text-purple-900",
                  done && !active && "border-green-300 bg-green-50 text-green-800",
                  !active && !done && "border-slate-200 text-slate-500",
                )}
              >
                {n}. {label}
              </div>
            )
          })}
        </div>
      </CardHeader>
      <CardContent className="grid gap-6">
        {state.step === 1 ? (
          <div className="grid gap-4 max-w-md">
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
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label>Canvas width</Label>
                <Input type="number" value={state.canvasWidth} readOnly className="bg-slate-50" />
              </div>
              <div className="grid gap-2">
                <Label>Canvas height</Label>
                <Input type="number" value={state.canvasHeight} readOnly className="bg-slate-50" />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>Template name</Label>
              <Input
                placeholder="e.g. Bold Quote Card"
                value={state.name}
                onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))}
              />
            </div>
          </div>
        ) : null}

        {state.step === 2 ? (
          <div className="grid gap-4">
            <p className="text-sm text-slate-600">
              Select 1–6 backgrounds. Click a tile to toggle; selected tiles show a checkmark.
            </p>
            
            <div className="flex border-b">
              {(["colors", "gradients", "photos"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setBgTab(tab)}
                  className={cn(
                    "px-4 py-2 text-sm font-medium border-b-2 capitalize",
                    bgTab === tab ? "border-purple-600 text-purple-600" : "border-transparent text-slate-500 hover:text-slate-700"
                  )}
                >
                  {tab}
                </button>
              ))}
            </div>

            {loadingAssets ? (
              <div className="py-8 text-center">
                <Loader2 className="size-6 animate-spin mx-auto text-slate-400" />
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {bgTab === "photos" && (
                  <label className="relative aspect-square rounded-lg border-2 border-dashed border-slate-300 hover:border-purple-400 flex flex-col items-center justify-center cursor-pointer transition-colors bg-slate-50">
                    <input type="file" className="hidden" accept="image/jpeg,image/png" onChange={handlePhotoUpload} disabled={uploadingBg} />
                    {uploadingBg ? (
                      <Loader2 className="size-6 animate-spin text-purple-600" />
                    ) : (
                      <>
                        <Plus className="size-6 text-slate-400 mb-2" />
                        <span className="text-xs font-medium text-slate-600">Upload Photo</span>
                      </>
                    )}
                  </label>
                )}
                {backgroundAssets
                  .filter((a) => {
                    if (bgTab === "colors") return a.type === "solid"
                    if (bgTab === "gradients") return a.type.startsWith("gradient")
                    return a.type === "image"
                  })
                  .map((asset) => {
                  const selected = state.selectedBackgrounds.some((b) => b.asset_id === asset.id)
                  return (
                    <button
                      key={asset.id}
                      type="button"
                      onClick={() => toggleBackground(asset)}
                      className={cn(
                        "relative aspect-square rounded-lg border-2 overflow-hidden transition-all",
                        selected ? "border-purple-600 ring-2 ring-purple-200" : "border-slate-200 hover:border-slate-400",
                      )}
                    >
                      <div className="absolute inset-0" style={backgroundSwatchStyle(asset)} />
                      {asset.preview_url ? (
                        <img
                          src={asset.preview_url}
                          alt=""
                          className="absolute inset-0 h-full w-full object-cover"
                        />
                      ) : null}
                      <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-xs px-2 py-1 truncate">
                        {asset.label || asset.type}
                      </span>
                      {selected ? (
                        <span className="absolute top-2 right-2 rounded-full bg-purple-600 p-1 text-white">
                          <Check className="size-4" />
                        </span>
                      ) : null}
                    </button>
                  )
                })}
              </div>
            )}
            {state.selectedBackgrounds.length > 0 ? (
              <div className="grid gap-3 rounded-md border p-4 bg-slate-50">
                <Label>Selected backgrounds</Label>
                {state.selectedBackgrounds.map((bg) => (
                  <div key={bg.asset_id} className="flex items-center gap-3">
                    <div
                      className="size-10 shrink-0 rounded border"
                      style={backgroundSwatchStyle(bg)}
                    />
                    <Input
                      placeholder="Label e.g. Dark mood"
                      value={bg.label}
                      onChange={(e) => updateBackgroundLabel(bg.asset_id, e.target.value)}
                      className="flex-1"
                    />
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {state.step === 3 ? (
          <div className="grid gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowAddLayerPanel((v) => !v)}
              >
                <Plus className="size-4 mr-1" /> Add Layer
              </Button>
            </div>
            {showAddLayerPanel ? (
              <div className="flex flex-wrap gap-2 rounded-md border p-3 bg-slate-50">
                <Button type="button" size="sm" onClick={() => addLayer("text")}>
                  Text
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => addLayer("logo")}>
                  Logo
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => addLayer("overlay")}>
                  Overlay
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setShowAddLayerPanel(false)}>
                  Cancel
                </Button>
              </div>
            ) : null}

            {state.layers.length === 0 ? (
              <p className="text-sm text-slate-500 py-4">No layers yet. Add text, logo, or overlay layers.</p>
            ) : (
              <ul className="grid gap-2">
                {[...state.layers]
                  .sort((a, b) => a.z_index - b.z_index)
                  .map((layer) => (
                    <li
                      key={layer.id}
                      className="flex items-center justify-between gap-2 rounded-md border p-3 bg-white"
                    >
                      <div className="flex items-center gap-2 text-sm">
                        <Layers className="size-4 text-slate-400" />
                        <span className="font-medium capitalize">{layer.type}</span>
                        {layer.type === "text" ? (
                          <span className="text-slate-500">· {layer.role}</span>
                        ) : null}
                        <span className="text-slate-400">z={layer.z_index}</span>
                      </div>
                      <div className="flex gap-1">
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          onClick={() => setEditingLayerId(editingLayerId === layer.id ? null : layer.id)}
                        >
                          <Pencil className="size-4" />
                        </Button>
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
                    </li>
                  ))}
              </ul>
            )}

            {editingLayer ? (
              <LayerEditor
                layer={editingLayer}
                fontAssets={fontAssets}
                onChange={(patch) => updateLayer(editingLayer.id, patch)}
                onClose={() => setEditingLayerId(null)}
              />
            ) : null}
          </div>
        ) : null}

        {state.step === 4 ? (
          <div className="grid gap-4">
            <p className="text-sm text-slate-600">
              Server-rendered preview: first background, first font/color per text layer, midpoint font sizes, and placeholder copy.
            </p>
            <div className="flex justify-center rounded-lg border bg-slate-100 p-4 overflow-auto min-h-[280px]">
              {previewLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="size-8 animate-spin text-slate-400" />
                </div>
              ) : previewUrl ? (
                <img
                  src={previewUrl}
                  alt="Template preview"
                  className="max-w-full max-h-[480px] h-auto shadow-md rounded"
                />
              ) : (
                <p className="text-sm text-slate-500 py-16">Preview unavailable.</p>
              )}
            </div>
          </div>
        ) : null}

        <div className="flex justify-between border-t pt-4">
          <Button type="button" variant="outline" onClick={state.step === 1 ? onCancel : goBack}>
            <ChevronLeft className="size-4 mr-1" />
            {state.step === 1 ? "Cancel" : "Back"}
          </Button>
          {state.step < 4 ? (
            <Button type="button" className="bg-purple-700 text-white hover:bg-purple-800" onClick={goNext}>
              Next <ChevronRight className="size-4 ml-1" />
            </Button>
          ) : (
            <Button
              type="button"
              className="bg-purple-700 text-white hover:bg-purple-800"
              onClick={saveTemplate}
              disabled={saving}
            >
              {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
              Save Template
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

type LayerLayoutKey =
  | "position_x_percent"
  | "position_y_percent"
  | "width_percent"
  | "height_percent"
  | "z_index"

function LayerEditor({
  layer,
  fontAssets,
  onChange,
  onClose,
}: {
  layer: LayerDraft
  fontAssets: FontAsset[]
  onChange: (patch: Partial<LayerDraft>) => void
  onClose: () => void
}) {
  const num = (label: string, key: LayerLayoutKey, min = 0, max = 100) => (
    <div className="grid gap-1">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={min}
        max={max}
        step={0.1}
        value={Number(layer[key])}
        onChange={(e) => onChange({ [key]: Number(e.target.value) } as Partial<LayerDraft>)}
      />
    </div>
  )

  return (
    <div className="rounded-lg border-2 border-purple-200 p-4 grid gap-4 bg-purple-50/30">
      <div className="flex justify-between items-center">
        <h3 className="font-semibold capitalize">Edit {layer.type} layer</h3>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {num("Position X %", "position_x_percent")}
        {num("Position Y %", "position_y_percent")}
        {num("Width %", "width_percent")}
        {num("Height %", "height_percent")}
        {num("Z-index", "z_index", 0, 99)}
      </div>

      {layer.type === "text" ? (
        <>
          <div className="grid gap-2">
            <Label>Role</Label>
            <Select
              value={layer.role}
              onChange={(e) =>
                onChange({ role: e.target.value as TextLayerDraft["role"] })
              }
            >
              <option value="headline">Headline</option>
              <option value="subheadline">Subheadline</option>
              <option value="body">Body</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>Allowed fonts (multi-select)</Label>
            <div className="flex flex-wrap gap-2">
              {fontAssets.map((f) => {
                const on = layer.font_asset_ids.includes(f.id)
                return (
                  <Button
                    key={f.id}
                    type="button"
                    size="sm"
                    variant={on ? "default" : "outline"}
                    onClick={() => {
                      const ids = on
                        ? layer.font_asset_ids.filter((id) => id !== f.id)
                        : [...layer.font_asset_ids, f.id]
                      onChange({ font_asset_ids: ids })
                    }}
                  >
                    {on ? <Check className="size-3 mr-1" /> : null}
                    {f.display_name}
                  </Button>
                )
              })}
            </div>
          </div>
          <TextColorEditor
            options={layer.color_options}
            onChange={(color_options) => onChange({ color_options })}
          />
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1">
              <Label className="text-xs">Font size min %</Label>
              <Input
                type="number"
                min={0.5}
                max={50}
                step={0.1}
                value={layer.font_size_min_percent}
                onChange={(e) => onChange({ font_size_min_percent: Number(e.target.value) })}
              />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">Font size max %</Label>
              <Input
                type="number"
                min={0.5}
                max={50}
                step={0.1}
                value={layer.font_size_max_percent}
                onChange={(e) => onChange({ font_size_max_percent: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label>Text align options</Label>
            <div className="flex gap-3">
              {(["left", "center", "right"] as const).map((align) => (
                <label key={align} className="flex items-center gap-1 text-sm capitalize">
                  <input
                    type="checkbox"
                    checked={layer.text_align_options.includes(align)}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...layer.text_align_options, align]
                        : layer.text_align_options.filter((a) => a !== align)
                      onChange({ text_align_options: next })
                    }}
                  />
                  {align}
                </label>
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <Label>Font weight</Label>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant={layer.font_weight === "bold" ? "default" : "outline"}
                onClick={() => onChange({ font_weight: "bold" })}
              >
                Bold
              </Button>
              <Button
                type="button"
                size="sm"
                variant={layer.font_weight === "regular" ? "default" : "outline"}
                onClick={() => onChange({ font_weight: "regular" })}
              >
                Regular
              </Button>
            </div>
          </div>
        </>
      ) : null}

      {layer.type === "overlay" ? (
        <OverlayColorEditor
          options={layer.color_options}
          onChange={(color_options) => onChange({ color_options })}
        />
      ) : null}

      {layer.type === "logo" ? (
        <p className="text-sm text-slate-600 italic">Logo image comes from persona settings.</p>
      ) : null}
    </div>
  )
}

function TextColorEditor({
  options,
  onChange,
}: {
  options: ColorOptionDraft[]
  onChange: (o: ColorOptionDraft[]) => void
}) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <Label>Color options</Label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            onChange([...options, { color_hex: "#ffffff", label: "New color" }])
          }
        >
          <Plus className="size-3 mr-1" /> Add
        </Button>
      </div>
      {options.map((opt, i) => (
        <div key={i} className="flex gap-2 items-center">
          <input
            type="color"
            value={opt.color_hex}
            onChange={(e) => {
              const next = [...options]
              next[i] = { ...opt, color_hex: e.target.value }
              onChange(next)
            }}
            className="size-9 rounded border cursor-pointer"
          />
          <Input
            placeholder="Label"
            value={opt.label}
            onChange={(e) => {
              const next = [...options]
              next[i] = { ...opt, label: e.target.value }
              onChange(next)
            }}
            className="flex-1"
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="text-red-500"
            disabled={options.length <= 1}
            onClick={() => onChange(options.filter((_, j) => j !== i))}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
    </div>
  )
}

function OverlayColorEditor({
  options,
  onChange,
}: {
  options: OverlayColorDraft[]
  onChange: (o: OverlayColorDraft[]) => void
}) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <Label>Overlay color options</Label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            onChange([...options, { color_hex: "#000000", opacity: 0.3, label: "Overlay" }])
          }
        >
          <Plus className="size-3 mr-1" /> Add
        </Button>
      </div>
      {options.map((opt, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-[auto_1fr_80px_1fr_auto] items-center">
          <input
            type="color"
            value={opt.color_hex}
            onChange={(e) => {
              const next = [...options]
              next[i] = { ...opt, color_hex: e.target.value }
              onChange(next)
            }}
            className="size-9 rounded border"
          />
          <Input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={opt.opacity}
            onChange={(e) => {
              const next = [...options]
              next[i] = { ...opt, opacity: Number(e.target.value) }
              onChange(next)
            }}
          />
          <span className="text-xs text-slate-500">opacity</span>
          <Input
            value={opt.label}
            onChange={(e) => {
              const next = [...options]
              next[i] = { ...opt, label: e.target.value }
              onChange(next)
            }}
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="text-red-500"
            disabled={options.length <= 1}
            onClick={() => onChange(options.filter((_, j) => j !== i))}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
    </div>
  )
}

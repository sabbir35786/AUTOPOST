"use client"

import * as React from "react"
import {
  Check,
  Eye,
  EyeOff,
  GripVertical,
  Image as ImageIcon,
  Layers,
  Lock,
  Plus,
  Trash2,
  Type,
  Unlock,
} from "lucide-react"
import { toast } from "sonner"

import { TemplateLayerFields } from "@/components/template-builder/template-layer-fields"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  backgroundSwatchStyle,
  canvasDisplaySize,
  createDefaultLogoLayer,
  createDefaultOverlayLayer,
  createDefaultTextLayer,
  findBackgroundAsset,
  nextLayerId,
  nextZIndex,
  percentToPx,
  pxToPercent,
  snapPercent,
} from "@/lib/template-state"
import type {
  BackgroundAsset,
  FontAsset,
  TemplateLayer,
  TemplateState,
  TextLayer,
} from "@/lib/template-types"
import { cn } from "@/lib/utils"

type Props = {
  state: TemplateState
  backgrounds: BackgroundAsset[]
  fonts: FontAsset[]
  onStateChange: (state: TemplateState) => void
  onExportToJson: () => void
}

type HandleId =
  | "nw"
  | "n"
  | "ne"
  | "e"
  | "se"
  | "s"
  | "sw"
  | "w"
  | "rotate"
  | "move"

type DragState = {
  mode: HandleId
  layerIds: string[]
  startX: number
  startY: number
  snapshots: Record<string, { x: number; y: number; w: number; h: number; rot: number }>
}

const HANDLE_CURSORS: Record<string, string> = {
  nw: "nwse-resize",
  se: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
}

function layerIcon(type: string) {
  if (type === "text") return <Type className="size-3.5" />
  if (type === "logo") return <ImageIcon className="size-3.5" />
  return <Layers className="size-3.5" />
}

export function TemplateVisualBuilder({
  state,
  backgrounds,
  fonts,
  onStateChange,
  onExportToJson,
}: Props) {
  const [showGrid, setShowGrid] = React.useState(true)
  const [selectedIds, setSelectedIds] = React.useState<string[]>([])
  const [showAddLayer, setShowAddLayer] = React.useState(false)
  const dragRef = React.useRef<DragState | null>(null)
  const canvasRef = React.useRef<HTMLDivElement>(null)
  const listDragId = React.useRef<string | null>(null)
  const stateRef = React.useRef(state)
  stateRef.current = state

  const json = state.templateJson
  const { width: displayW, height: displayH } = canvasDisplaySize(
    json.canvas_width,
    json.canvas_height,
  )

  const previewBg = findBackgroundAsset(backgrounds, state.previewBackgroundAssetId)
  const sortedLayers = [...json.layers].sort((a, b) => a.z_index - b.z_index)

  function isHidden(id: string) {
    return state.visualMeta[id]?.hidden ?? false
  }
  function isLocked(id: string) {
    return state.visualMeta[id]?.locked ?? false
  }

  function setLayers(layers: TemplateLayer[]) {
    onStateChange({ ...state, templateJson: { ...json, layers } })
  }

  function updateLayers(updater: (layers: TemplateLayer[]) => TemplateLayer[]) {
    setLayers(updater(json.layers))
  }

  function patchLayer(id: string, patch: Partial<TemplateLayer>) {
    updateLayers((layers) =>
      layers.map((l) => (l.id === id ? ({ ...l, ...patch } as TemplateLayer) : l)),
    )
  }

  function patchLayers(ids: string[], patch: Partial<TemplateLayer>) {
    const idSet = new Set(ids)
    updateLayers((layers) =>
      layers.map((l) => (idSet.has(l.id) ? ({ ...l, ...patch } as TemplateLayer) : l)),
    )
  }

  function toggleMeta(id: string, key: "hidden" | "locked") {
    onStateChange({
      ...state,
      visualMeta: {
        ...state.visualMeta,
        [id]: { ...state.visualMeta[id], [key]: !state.visualMeta[id]?.[key] },
      },
    })
  }

  function selectLayer(id: string, shift: boolean) {
    if (isLocked(id)) return
    if (shift) {
      setSelectedIds((prev) =>
        prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
      )
    } else {
      setSelectedIds([id])
    }
  }

  function startDrag(
    e: React.MouseEvent | React.TouchEvent,
    mode: HandleId,
    layerId: string,
  ) {
    e.stopPropagation()
    if (isLocked(layerId)) return
    const clientX = "touches" in e ? e.touches[0].clientX : e.clientX
    const clientY = "touches" in e ? e.touches[0].clientY : e.clientY
    const ids = selectedIds.includes(layerId) ? selectedIds : [layerId]
    const snapshots: DragState["snapshots"] = {}
    for (const lid of ids) {
      const l = json.layers.find((x) => x.id === lid)
      if (!l) continue
      snapshots[lid] = {
        x: l.position_x_percent,
        y: l.position_y_percent,
        w: l.width_percent,
        h: l.height_percent,
        rot: l.rotation_degrees ?? 0,
      }
    }
    dragRef.current = { mode, layerIds: ids, startX: clientX, startY: clientY, snapshots }
  }

  React.useEffect(() => {
    function onMove(clientX: number, clientY: number) {
      const drag = dragRef.current
      if (!drag || !canvasRef.current) return
      const rect = canvasRef.current.getBoundingClientRect()
      const dxPct = pxToPercent(clientX - drag.startX, rect.width)
      const dyPct = pxToPercent(clientY - drag.startY, rect.height)

      const current = stateRef.current
      const curLayers = current.templateJson.layers
      const nextLayers = curLayers.map((layer) => {
          const snap = drag.snapshots[layer.id]
          if (!snap) return layer
          let { x, y, w, h, rot } = snap

          if (drag.mode === "move") {
            x = snapPercent(snap.x + dxPct, showGrid)
            y = snapPercent(snap.y + dyPct, showGrid)
          } else if (drag.mode === "rotate") {
            const cx = percentToPx(snap.x + snap.w / 2, rect.width)
            const cy = percentToPx(snap.y + snap.h / 2, rect.height)
            const startAngle = Math.atan2(drag.startY - rect.top - cy, drag.startX - rect.left - cx)
            const curAngle = Math.atan2(clientY - rect.top - cy, clientX - rect.left - cx)
            rot = snap.rot + ((curAngle - startAngle) * 180) / Math.PI
          } else {
            const handles = drag.mode
            if (handles.includes("e")) w = snapPercent(snap.w + dxPct, showGrid)
            if (handles.includes("w")) {
              w = snapPercent(snap.w - dxPct, showGrid)
              x = snapPercent(snap.x + dxPct, showGrid)
            }
            if (handles.includes("s")) h = snapPercent(snap.h + dyPct, showGrid)
            if (handles.includes("n")) {
              h = snapPercent(snap.h - dyPct, showGrid)
              y = snapPercent(snap.y + dyPct, showGrid)
            }
            w = Math.max(2, w)
            h = Math.max(2, h)
          }

          return {
            ...layer,
            position_x_percent: Math.max(0, Math.min(100 - w, x)),
            position_y_percent: Math.max(0, Math.min(100 - h, y)),
            width_percent: w,
            height_percent: h,
            rotation_degrees: rot,
          }
      })
      onStateChange({
        ...current,
        templateJson: { ...current.templateJson, layers: nextLayers },
      })
    }

    function onMouseMove(e: MouseEvent) {
      onMove(e.clientX, e.clientY)
    }
    function onTouchMove(e: TouchEvent) {
      if (e.touches[0]) onMove(e.touches[0].clientX, e.touches[0].clientY)
    }
    function onEnd() {
      dragRef.current = null
    }

    window.addEventListener("mousemove", onMouseMove)
    window.addEventListener("mouseup", onEnd)
    window.addEventListener("touchmove", onTouchMove, { passive: false })
    window.addEventListener("touchend", onEnd)
    return () => {
      window.removeEventListener("mousemove", onMouseMove)
      window.removeEventListener("mouseup", onEnd)
      window.removeEventListener("touchmove", onTouchMove)
      window.removeEventListener("touchend", onEnd)
    }
  }, [showGrid, onStateChange])

  function addLayer(type: "text" | "logo" | "overlay") {
    const id = nextLayerId(json.layers)
    const z = nextZIndex(json.layers)
    let layer: TemplateLayer
    if (type === "text") layer = createDefaultTextLayer(z, id, fonts)
    else if (type === "overlay") layer = createDefaultOverlayLayer(z, id)
    else layer = createDefaultLogoLayer(z, id)
    setLayers([...json.layers, layer])
    setSelectedIds([id])
    setShowAddLayer(false)
  }

  function removeLayer(id: string) {
    setLayers(json.layers.filter((l) => l.id !== id))
    setSelectedIds((s) => s.filter((x) => x !== id))
  }

  function reorderList(fromId: string, toId: string) {
    const sorted = [...json.layers].sort((a, b) => a.z_index - b.z_index)
    const fromIdx = sorted.findIndex((l) => l.id === fromId)
    const toIdx = sorted.findIndex((l) => l.id === toId)
    if (fromIdx < 0 || toIdx < 0) return
    const [moved] = sorted.splice(fromIdx, 1)
    sorted.splice(toIdx, 0, moved)
    setLayers(sorted.map((l, i) => ({ ...l, z_index: i })))
  }

  function toggleBackground(asset: BackgroundAsset, ctrl: boolean) {
    const exists = json.background_options.find((b) => b.asset_id === asset.id)
    let next = json.background_options
    if (exists && !ctrl) {
      onStateChange({
        ...state,
        previewBackgroundAssetId: asset.id,
      })
      return
    }
    if (exists) {
      next = json.background_options.filter((b) => b.asset_id !== asset.id)
    } else {
      if (json.background_options.length >= 6) {
        toast.error("Maximum 6 backgrounds.")
        return
      }
      next = [...json.background_options, { asset_id: asset.id, label: asset.label || "Background" }]
    }
    onStateChange({
      ...state,
      templateJson: { ...json, background_options: next },
      previewBackgroundAssetId: asset.id,
    })
  }

  const primarySelected = selectedIds[0]
  const primaryLayer = json.layers.find((l) => l.id === primarySelected)

  const canvasBgStyle: React.CSSProperties = state.previewBackgroundImageBase64
    ? {
        backgroundImage: `url(${state.previewBackgroundImageBase64})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : state.previewBackgroundColor
    ? {
        backgroundColor: state.previewBackgroundColor,
      }
    : previewBg
    ? {
        ...backgroundSwatchStyle(previewBg),
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : { backgroundColor: "#1e293b" }


  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2 items-center">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showGrid} onChange={(e) => setShowGrid(e.target.checked)} />
          Show grid (5% snap)
        </label>
        <Button type="button" size="sm" variant="outline" onClick={onExportToJson}>
          Current canvas state → JSON Editor
        </Button>
      </div>

      <div className="grid lg:grid-cols-[200px_1fr_260px] gap-4">
        {/* Layer list */}
        <aside className="grid gap-2 content-start">
          <div className="flex items-center justify-between">
            <Label className="text-xs font-semibold">Layers</Label>
            <Button type="button" size="sm" variant="outline" onClick={() => setShowAddLayer((v) => !v)}>
              <Plus className="size-3" />
            </Button>
          </div>
          {showAddLayer ? (
            <div className="flex flex-col gap-1">
              <Button type="button" size="sm" onClick={() => addLayer("text")}>
                Text
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => addLayer("logo")}>
                Logo
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => addLayer("overlay")}>
                Overlay
              </Button>
            </div>
          ) : null}
          <ul className="grid gap-1 max-h-[400px] overflow-y-auto">
            {[...sortedLayers].reverse().map((layer) => (
              <li
                key={layer.id}
                draggable
                onDragStart={() => {
                  listDragId.current = layer.id
                }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => {
                  if (listDragId.current) reorderList(listDragId.current, layer.id)
                }}
                className={cn(
                  "flex items-center gap-1 rounded border px-1 py-1 text-xs",
                  selectedIds.includes(layer.id) && "border-purple-600 bg-purple-50",
                  isHidden(layer.id) && "opacity-50",
                )}
              >
                <GripVertical className="size-3 text-slate-400 shrink-0 cursor-grab" />
                <button
                  type="button"
                  className="flex-1 flex items-center gap-1 text-left truncate"
                  onClick={() => selectLayer(layer.id, false)}
                >
                  {layerIcon(layer.type)}
                  <span className="truncate">
                    {layer.type === "text" ? (layer as TextLayer).role : layer.type}
                  </span>
                </button>
                <button type="button" onClick={() => toggleMeta(layer.id, "hidden")} className="p-0.5">
                  {isHidden(layer.id) ? (
                    <EyeOff className="size-3" />
                  ) : (
                    <Eye className="size-3" />
                  )}
                </button>
                <button type="button" onClick={() => toggleMeta(layer.id, "locked")} className="p-0.5">
                  {isLocked(layer.id) ? (
                    <Lock className="size-3" />
                  ) : (
                    <Unlock className="size-3" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => removeLayer(layer.id)}
                  className="p-0.5 text-red-500"
                >
                  <Trash2 className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        {/* Canvas */}
        <div className="flex flex-col items-center gap-3">
          <div
            ref={canvasRef}
            className="relative border-2 border-slate-300 rounded-lg overflow-hidden shadow-inner"
            style={{ width: displayW, height: displayH, ...canvasBgStyle }}
            onMouseDown={() => setSelectedIds([])}
          >
            {showGrid ? (
              <div
                className="absolute inset-0 pointer-events-none opacity-30"
                style={{
                  backgroundImage: `
                    linear-gradient(to right, rgba(255,255,255,0.4) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(255,255,255,0.4) 1px, transparent 1px)
                  `,
                  backgroundSize: `${displayW / 20}px ${displayH / 20}px`,
                }}
              />
            ) : null}

            {sortedLayers.map((layer) => {
              if (isHidden(layer.id)) return null
              const left = percentToPx(layer.position_x_percent, displayW)
              const top = percentToPx(layer.position_y_percent, displayH)
              const w = percentToPx(layer.width_percent, displayW)
              const h = percentToPx(layer.height_percent, displayH)
              const selected = selectedIds.includes(layer.id)
              const rot = layer.rotation_degrees ?? 0

              let bg = "rgba(99,102,241,0.25)"
              let border = "1px dashed rgba(99,102,241,0.8)"
              if (layer.type === "text") {
                const tl = layer as TextLayer
                bg = tl.color_options[0]?.color_hex
                  ? `${tl.color_options[0].color_hex}33`
                  : bg
              } else if (layer.type === "overlay") {
                const c = layer.color_options[0]
                if (c) bg = `${c.color_hex}${Math.round(c.opacity * 255).toString(16).padStart(2, "0")}`
              }

              let textContent = ""
              let textStyle: React.CSSProperties = {}
              if (layer.type === "text") {
                const tl = layer as TextLayer
                textContent = state.previewTexts?.[layer.id] || `[Preview ${tl.role}]`
                const textColor = tl.color_options[0]?.color_hex || "#ffffff"
                const textAlign = tl.text_align_options[0] || "center"
                const avgPct = (tl.font_size_min_percent + tl.font_size_max_percent) / 2
                const fontSizePx = displayH * (avgPct / 100)
                textStyle = {
                  color: textColor,
                  textAlign: textAlign,
                  fontSize: `${fontSizePx}px`,
                  fontWeight: tl.font_weight || "bold",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: textAlign === "left" ? "flex-start" : textAlign === "right" ? "flex-end" : "center",
                  padding: "4px",
                  wordBreak: "break-word",
                  whiteSpace: "pre-wrap",
                  height: "100%",
                  width: "100%",
                }
              }

              return (
                <div
                  key={layer.id}
                  className={cn(
                    "absolute box-border select-none touch-none",
                    selected && "ring-2 ring-purple-500",
                  )}
                  style={{
                    left,
                    top,
                    width: w,
                    height: h,
                    background: layer.type === "logo" ? (state.previewLogoBase64 ? "transparent" : "rgba(255,255,255,0.15)") : bg,
                    border,
                    transform: `rotate(${rot}deg)`,
                    transformOrigin: "center center",
                    cursor: isLocked(layer.id) ? "not-allowed" : "move",
                    zIndex: layer.z_index + 1,
                  }}
                  onMouseDown={(e) => {
                    e.stopPropagation()
                    selectLayer(layer.id, e.shiftKey)
                    startDrag(e, "move", layer.id)
                  }}
                  onTouchStart={(e) => {
                    e.stopPropagation()
                    selectLayer(layer.id, false)
                    startDrag(e, "move", layer.id)
                  }}
                >
                  {layer.type === "text" ? (
                    <div style={textStyle}>{textContent}</div>
                  ) : layer.type === "logo" && state.previewLogoBase64 ? (
                    <img src={state.previewLogoBase64} alt="logo" className="w-full h-full object-contain pointer-events-none" />
                  ) : (
                    <span className="absolute top-0 left-0 text-[9px] bg-black/50 text-white px-1 truncate max-w-full">
                      {layer.type === "text" ? (layer as TextLayer).role : layer.type}
                    </span>
                  )}
                  {selected && !isLocked(layer.id) ? (
                    <>
                      {(["nw", "n", "ne", "e", "se", "s", "sw", "w"] as const).map((h) => (
                        <div
                          key={h}
                          className="absolute size-2.5 bg-white border border-purple-600 rounded-sm"
                          style={{
                            cursor: HANDLE_CURSORS[h],
                            ...(h.includes("n") ? { top: -5 } : h.includes("s") ? { bottom: -5 } : { top: "50%", marginTop: -5 }),
                            ...(h.includes("w") ? { left: -5 } : h.includes("e") ? { right: -5 } : { left: "50%", marginLeft: -5 }),
                            ...(h === "n" || h === "s" ? { left: "50%", marginLeft: -5 } : {}),
                            ...(h === "e" || h === "w" ? { top: "50%", marginTop: -5 } : {}),
                          }}
                          onMouseDown={(e) => startDrag(e, h, layer.id)}
                          onTouchStart={(e) => startDrag(e, h, layer.id)}
                        />
                      ))}
                      <div
                        className="absolute left-1/2 -translate-x-1/2 -top-7 size-3 rounded-full bg-purple-600 border-2 border-white cursor-grab"
                        onMouseDown={(e) => startDrag(e, "rotate", layer.id)}
                        onTouchStart={(e) => startDrag(e, "rotate", layer.id)}
                      />
                    </>
                  ) : null}
                </div>
              )
            })}
          </div>

          <div className="w-full max-w-full">
            <Label className="text-xs text-slate-500">Backgrounds (Ctrl+click multi-select)</Label>
            <div className="flex gap-2 overflow-x-auto py-2">
              {backgrounds.map((asset) => {
                const selected = json.background_options.some((b) => b.asset_id === asset.id)
                const isPreview = state.previewBackgroundAssetId === asset.id
                return (
                  <button
                    key={asset.id}
                    type="button"
                    onClick={(e) => toggleBackground(asset, e.ctrlKey || e.metaKey)}
                    className={cn(
                      "relative shrink-0 size-14 rounded-lg border-2 overflow-hidden",
                      selected || isPreview ? "border-purple-600" : "border-slate-200",
                    )}
                  >
                    <div className="absolute inset-0" style={backgroundSwatchStyle(asset)} />
                    {selected ? (
                      <span className="absolute top-0.5 right-0.5 rounded-full bg-purple-600 p-0.5 text-white">
                        <Check className="size-3" />
                      </span>
                    ) : null}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* Properties */}
        <aside className="max-h-[520px] overflow-y-auto">
          {primaryLayer ? (
            <TemplateLayerFields
              layer={primaryLayer}
              fontAssets={fonts}
              onChange={(patch) => {
                if (selectedIds.length > 1) patchLayers(selectedIds, patch)
                else patchLayer(primaryLayer.id, patch)
              }}
              previewText={state.previewTexts?.[primaryLayer.id] || ""}
              onPreviewTextChange={(text) => {
                onStateChange({
                  ...state,
                  previewTexts: {
                    ...(state.previewTexts || {}),
                    [primaryLayer.id]: text
                  }
                })
              }}
              previewLogoBase64={state.previewLogoBase64}
              onLogoUpload={(base64) => {
                onStateChange({
                  ...state,
                  previewLogoBase64: base64
                })
              }}
            />
          ) : (
            <p className="text-sm text-slate-500">Select a layer on the canvas.</p>
          )}
        </aside>
      </div>
    </div>
  )
}

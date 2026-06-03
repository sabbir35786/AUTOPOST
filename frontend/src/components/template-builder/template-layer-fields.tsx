"use client"

import * as React from "react"
import { Check, Plus, Trash2, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import type { FontAsset, OverlayLayer, TemplateLayer, TextLayer } from "@/lib/template-types"

type LayerLayoutKey =
  | "position_x_percent"
  | "position_y_percent"
  | "width_percent"
  | "height_percent"
  | "z_index"
  | "rotation_degrees"

export function TemplateLayerFields({
  layer,
  fontAssets,
  onChange,
  onClose,
  compact = false,
}: {
  layer: TemplateLayer
  fontAssets: FontAsset[]
  onChange: (patch: Partial<TemplateLayer>) => void
  onClose?: () => void
  compact?: boolean
}) {
  const num = (label: string, key: LayerLayoutKey, min = 0, max = 100) => (
    <div className="grid gap-1">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={min}
        max={max}
        step={key === "rotation_degrees" ? 1 : 0.1}
        value={Number((layer as unknown as Record<string, number>)[key] ?? 0)}
        onChange={(e) => onChange({ [key]: Number(e.target.value) } as Partial<TemplateLayer>)}
      />
    </div>
  )

  return (
    <div
      className={
        compact
          ? "grid gap-3"
          : "rounded-lg border-2 border-purple-200 p-4 grid gap-4 bg-purple-50/30"
      }
    >
      {!compact ? (
        <div className="flex justify-between items-center">
          <h3 className="font-semibold capitalize">Edit {layer.type} layer</h3>
          {onClose ? (
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              <X className="size-4" />
            </Button>
          ) : null}
        </div>
      ) : null}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {num("Position X %", "position_x_percent")}
        {num("Position Y %", "position_y_percent")}
        {num("Width %", "width_percent")}
        {num("Height %", "height_percent")}
        {num("Z-index", "z_index", 0, 99)}
        {num("Rotation °", "rotation_degrees", -360, 360)}
      </div>

      {layer.type === "text" ? (
        <TextLayerFields layer={layer} fontAssets={fontAssets} onChange={onChange} />
      ) : null}
      {layer.type === "overlay" ? (
        <OverlayColorEditor
          options={layer.color_options}
          onChange={(color_options) => onChange({ color_options } as Partial<TemplateLayer>)}
        />
      ) : null}
      {layer.type === "logo" ? (
        <p className="text-sm text-slate-600 italic">Logo image comes from persona settings.</p>
      ) : null}
    </div>
  )
}

function TextLayerFields({
  layer,
  fontAssets,
  onChange,
}: {
  layer: TextLayer
  fontAssets: FontAsset[]
  onChange: (patch: Partial<TemplateLayer>) => void
}) {
  const fontIds = layer.font_options.map((f) => f.font_asset_id)

  return (
    <>
      <div className="grid gap-2">
        <Label>Role</Label>
        <Select
          value={layer.role}
          onChange={(e) => onChange({ role: e.target.value as TextLayer["role"] } as Partial<TemplateLayer>)}
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
            const on = fontIds.includes(f.id)
            return (
              <Button
                key={f.id}
                type="button"
                size="sm"
                variant={on ? "default" : "outline"}
                onClick={() => {
                  const next = on
                    ? layer.font_options.filter((o) => o.font_asset_id !== f.id)
                    : [...layer.font_options, { font_asset_id: f.id, label: f.display_name }]
                  onChange({ font_options: next } as Partial<TemplateLayer>)
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
        onChange={(color_options) => onChange({ color_options } as Partial<TemplateLayer>)}
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
            onChange={(e) =>
              onChange({ font_size_min_percent: Number(e.target.value) } as Partial<TemplateLayer>)
            }
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
            onChange={(e) =>
              onChange({ font_size_max_percent: Number(e.target.value) } as Partial<TemplateLayer>)
            }
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
                  onChange({ text_align_options: next } as Partial<TemplateLayer>)
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
            onClick={() => onChange({ font_weight: "bold" } as Partial<TemplateLayer>)}
          >
            Bold
          </Button>
          <Button
            type="button"
            size="sm"
            variant={layer.font_weight === "regular" ? "default" : "outline"}
            onClick={() => onChange({ font_weight: "regular" } as Partial<TemplateLayer>)}
          >
            Regular
          </Button>
        </div>
      </div>
    </>
  )
}

function TextColorEditor({
  options,
  onChange,
}: {
  options: { color_hex: string; label: string }[]
  onChange: (o: { color_hex: string; label: string }[]) => void
}) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <Label>Color options</Label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onChange([...options, { color_hex: "#ffffff", label: "New color" }])}
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
  options: OverlayLayer["color_options"]
  onChange: (o: OverlayLayer["color_options"]) => void
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

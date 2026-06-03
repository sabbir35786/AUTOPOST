export const ASPECT_PRESETS = {
  "1:1": { width: 1080, height: 1080, label: "1:1 (1080×1080)" },
  "4:5": { width: 1080, height: 1350, label: "4:5 (1080×1350)" },
  "9:16": { width: 1080, height: 1920, label: "9:16 (1080×1920)" },
  "16:9": { width: 1920, height: 1080, label: "16:9 (1920×1080)" },
} as const

export type AspectKey = keyof typeof ASPECT_PRESETS

export type BuilderTab = "visual" | "option" | "json" | "describe"

export type BackgroundAsset = {
  id: string
  asset_type: string
  label: string | null
  preview_url: string | null
  value_json: Record<string, unknown>
}

export type FontAsset = {
  id: string
  display_name: string
  weight: string
  font_file_url: string
}

export type ColorOption = { color_hex: string; label: string }
export type OverlayColorOption = { color_hex: string; opacity: number; label: string }

export type LayerBase = {
  id: string
  z_index: number
  position_x_percent: number
  position_y_percent: number
  width_percent: number
  height_percent: number
  rotation_degrees?: number
  hidden?: boolean
  locked?: boolean
}

export type TextLayer = LayerBase & {
  type: "text"
  role: "headline" | "subheadline" | "body"
  font_options: { font_asset_id: string; label: string }[]
  color_options: ColorOption[]
  font_size_min_percent: number
  font_size_max_percent: number
  text_align_options: ("left" | "center" | "right")[]
  font_weight: "bold" | "regular"
}

export type OverlayLayer = LayerBase & {
  type: "overlay"
  color_options: OverlayColorOption[]
}

export type LogoLayer = LayerBase & {
  type: "logo"
}

export type TemplateLayer = TextLayer | OverlayLayer | LogoLayer

export type BackgroundOption = {
  asset_id: string
  label: string
}

export type ManualTemplateJson = {
  canvas_width: number
  canvas_height: number
  aspect_ratio: string
  background_options: BackgroundOption[]
  layers: TemplateLayer[]
}

/** UI-only fields layered on top of template JSON for the visual builder. */
export type VisualLayerMeta = {
  hidden?: boolean
  locked?: boolean
}

export type TemplateState = {
  name: string
  aspectRatio: AspectKey
  canvasWidth: number
  canvasHeight: number
  templateJson: ManualTemplateJson
  /** First selected background for visual preview */
  previewBackgroundAssetId: string | null
  visualMeta: Record<string, VisualLayerMeta>
}

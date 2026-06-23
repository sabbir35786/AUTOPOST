import type { CSSProperties } from "react"
import type {
  AspectKey,
  BackgroundAsset,
  DividerLayer,
  FontAsset,
  LayerBase,
  ManualTemplateJson,
  TemplateLayer,
  TemplateState,
  TextLayer,
} from "./template-types"
import { ASPECT_PRESETS } from "./template-types"

export function createEmptyTemplateJson(aspect: AspectKey = "1:1"): ManualTemplateJson {
  const preset = ASPECT_PRESETS[aspect]
  return {
    canvas_width: preset.width,
    canvas_height: preset.height,
    aspect_ratio: aspect,
    background_options: [],
    layers: [],
  }
}

export function createInitialTemplateState(aspect: AspectKey = "1:1"): TemplateState {
  const preset = ASPECT_PRESETS[aspect]
  return {
    name: "",
    aspectRatio: aspect,
    canvasWidth: preset.width,
    canvasHeight: preset.height,
    templateJson: createEmptyTemplateJson(aspect),
    previewBackgroundAssetId: null,
    visualMeta: {},
  }
}

export function templateJsonSkeletonString(aspect: AspectKey = "1:1"): string {
  return JSON.stringify(createEmptyTemplateJson(aspect), null, 2)
}

export function nextLayerId(layers: { id: string }[]): string {
  const nums = layers
    .map((l) => /^layer_(\d+)$/.exec(l.id)?.[1])
    .filter(Boolean)
    .map((n) => Number(n))
  const next = (nums.length ? Math.max(...nums) : 0) + 1
  return `layer_${next}`
}

export function syncCanvasFieldsFromAspect(
  state: TemplateState,
  aspect: AspectKey,
): TemplateState {
  const preset = ASPECT_PRESETS[aspect]
  return {
    ...state,
    aspectRatio: aspect,
    canvasWidth: preset.width,
    canvasHeight: preset.height,
    templateJson: {
      ...state.templateJson,
      canvas_width: preset.width,
      canvas_height: preset.height,
      aspect_ratio: aspect,
    },
  }
}

export function applyTemplateJsonToState(
  state: TemplateState,
  json: ManualTemplateJson,
  name?: string,
): TemplateState {
  const aspect = (json.aspect_ratio in ASPECT_PRESETS
    ? json.aspect_ratio
    : state.aspectRatio) as AspectKey
  const firstBg = json.background_options[0]?.asset_id ?? state.previewBackgroundAssetId
  return {
    ...state,
    name: name ?? state.name,
    aspectRatio: aspect,
    canvasWidth: json.canvas_width,
    canvasHeight: json.canvas_height,
    templateJson: json,
    previewBackgroundAssetId: firstBg,
  }
}

export function stateWithTemplateJson(
  state: TemplateState,
  patch: Partial<ManualTemplateJson>,
): TemplateState {
  return {
    ...state,
    templateJson: { ...state.templateJson, ...patch },
  }
}

export function stateWithLayers(state: TemplateState, layers: TemplateLayer[]): TemplateState {
  return stateWithTemplateJson(state, { layers })
}

export function createDefaultTextLayer(
  z: number,
  id: string,
  fonts: FontAsset[],
): TextLayer {
  return {
    id,
    type: "text",
    role: "headline",
    z_index: z,
    position_x_percent: 10,
    position_y_percent: 38,
    width_percent: 80,
    height_percent: 20,
    rotation_degrees: 0,
    font_options: fonts[0]
      ? [{ font_asset_id: fonts[0].id, label: fonts[0].display_name }]
      : [],
    color_options: [
      { color_hex: "#ffffff", label: "White" },
      { color_hex: "#f0f0f0", label: "Light" },
    ],
    font_size_min_percent: 4,
    font_size_max_percent: 7,
    text_align_options: ["center"],
    font_weight: "bold",
  }
}

export function createDefaultOverlayLayer(z: number, id: string): TemplateLayer {
  return {
    id,
    type: "overlay",
    z_index: z,
    position_x_percent: 0,
    position_y_percent: 0,
    width_percent: 100,
    height_percent: 100,
    rotation_degrees: 0,
    color_options: [{ color_hex: "#000000", opacity: 0.4, label: "Dark" }],
  }
}

export function createDefaultLogoLayer(z: number, id: string): TemplateLayer {
  return {
    id,
    type: "logo",
    z_index: z,
    position_x_percent: 78,
    position_y_percent: 4,
    width_percent: 18,
    height_percent: 12,
    rotation_degrees: 0,
  }
}

export function createDefaultShapeLayer(z: number, id: string): TemplateLayer {
  return {
    id,
    type: "shape",
    shape_type: "rectangle",
    z_index: z,
    position_x_percent: 10,
    position_y_percent: 10,
    width_percent: 80,
    height_percent: 20,
    rotation_degrees: 0,
    fill_color_options: [{ color_hex: "#ffffff", label: "White" }],
    stroke_color_options: [],
    stroke_width: 0,
    corner_radius: 0,
    opacity: 100,
  }
}

export function createDefaultDividerLayer(z: number, id: string): DividerLayer {
  return {
    id,
    type: "divider",
    orientation: "horizontal",
    z_index: z,
    position_x_percent: 0,
    position_y_percent: 50,
    width_percent: 100,
    height_percent: 1,
    rotation_degrees: 0,
    color_options: [
      { color_hex: "#ffffff", label: "White" },
      { color_hex: "#000000", label: "Black" },
    ],
    thickness_px: 2,
    opacity: 100,
    width_pct: 80,
    y_pct: 50,
    x_start_pct: 10,
    angle_deg: 0,
  }
}

export function nextZIndex(layers: TemplateLayer[]): number {
  return layers.length ? Math.max(...layers.map((l) => l.z_index)) + 1 : 1
}

/** Strip UI-only fields before sending to API. */
export function apiTemplateJson(state: TemplateState): ManualTemplateJson {
  const { templateJson } = state
  return {
    ...templateJson,
    layers: templateJson.layers.map((layer) => {
      const { hidden: _h, locked: _l, ...rest } = layer as LayerBase & {
        hidden?: boolean
        locked?: boolean
      }
      return rest as TemplateLayer
    }),
  }
}

export function backgroundSwatchStyle(asset: {
  asset_type: string
  value_json: Record<string, unknown>
}): CSSProperties {
  const v = asset.value_json || {}
  if (asset.asset_type === "gradient" && Array.isArray(v.stops)) {
    return { background: `linear-gradient(135deg, ${(v.stops as string[]).join(", ")})` }
  }
  const hex = String(v.color_hex || "#334155")
  return { backgroundColor: hex }
}

export function findBackgroundAsset(
  assets: BackgroundAsset[],
  assetId: string | null,
): BackgroundAsset | undefined {
  if (!assetId) return undefined
  return assets.find((a) => a.id === assetId)
}

/** Display size for visual canvas (max dimension 540). */
export function canvasDisplaySize(
  canvasWidth: number,
  canvasHeight: number,
  maxDim = 540,
): { width: number; height: number; scale: number } {
  const scale = maxDim / Math.max(canvasWidth, canvasHeight)
  return {
    width: Math.round(canvasWidth * scale),
    height: Math.round(canvasHeight * scale),
    scale,
  }
}

export function percentToPx(percent: number, total: number): number {
  return (percent / 100) * total
}

export function pxToPercent(px: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((px / total) * 1000) / 10
}

export function snapPercent(value: number, gridEnabled: boolean, step = 5): number {
  if (!gridEnabled) return Math.round(value * 10) / 10
  return Math.round(value / step) * step
}

import type {
  BackgroundAsset,
  FontAsset,
  ManualTemplateJson,
  TemplateLayer,
} from "./template-types"

export type ValidationError = {
  path: string
  message: string
}

const VALID_LAYER_TYPES = new Set(["text", "logo", "overlay", "shape", "divider"])
const VALID_ROLES = new Set(["headline", "subheadline", "body"])
const VALID_ALIGNS = new Set(["left", "center", "right"])
const VALID_WEIGHTS = new Set(["bold", "regular"])

function pctError(path: string, field: string, value: unknown): ValidationError | null {
  const n = Number(value)
  if (Number.isNaN(n) || n < 0 || n > 100) {
    return { path, message: `${field} must be between 0 and 100 (got ${value})` }
  }
  return null
}

function validateLayer(
  layer: Record<string, unknown>,
  index: number,
  backgroundIds: Set<string>,
  fontIds: Set<string>,
): ValidationError[] {
  const errors: ValidationError[] = []
  const prefix = `layers[${index}]`
  const layerNum = index + 1
  const id = String(layer.id ?? "")
  const type = String(layer.type ?? "").toLowerCase()

  if (!id) errors.push({ path: `${prefix}.id`, message: `Layer ${layerNum}: id is required` })
  if (!VALID_LAYER_TYPES.has(type)) {
    errors.push({
      path: `${prefix}.type`,
      message: `Layer ${layerNum}: type must be text, logo, or overlay`,
    })
    return errors
  }

  for (const field of [
    "position_x_percent",
    "position_y_percent",
    "width_percent",
    "height_percent",
  ] as const) {
    const err = pctError(`${prefix}.${field}`, field, layer[field])
    if (err) errors.push({ ...err, message: `Layer ${layerNum}: ${err.message}` })
  }

  if (layer.rotation_degrees !== undefined && layer.rotation_degrees !== null) {
    const rot = Number(layer.rotation_degrees)
    if (Number.isNaN(rot) || rot < -360 || rot > 360) {
      errors.push({
        path: `${prefix}.rotation_degrees`,
        message: `Layer ${layerNum}: rotation_degrees must be between -360 and 360`,
      })
    }
  }

  if (type === "text") {
    const role = String(layer.role ?? "")
    if (!VALID_ROLES.has(role)) {
      errors.push({ path: `${prefix}.role`, message: `Layer ${layerNum}: invalid role` })
    }
    const fontOpts = (layer.font_options as unknown[]) ?? []
    if (!fontOpts.length) {
      errors.push({ path: `${prefix}.font_options`, message: `Layer ${layerNum}: at least one font_option required` })
    }
    fontOpts.forEach((fo, fi) => {
      const fid = String((fo as Record<string, unknown>)?.font_asset_id ?? "")
      if (fid && !fontIds.has(fid)) {
        errors.push({
          path: `${prefix}.font_options[${fi}]`,
          message: `Layer ${layerNum}: font_asset_id ${fid} does not exist`,
        })
      }
    })
    const colorOpts = (layer.color_options as unknown[]) ?? []
    if (colorOpts.length < 1) {
      errors.push({
        path: `${prefix}.color_options`,
        message: `Layer ${layerNum}: at least one color_option required`,
      })
    }
    const aligns = (layer.text_align_options as unknown[]) ?? []
    if (!aligns.length) {
      errors.push({
        path: `${prefix}.text_align_options`,
        message: `Layer ${layerNum}: at least one text_align_option required`,
      })
    }
    aligns.forEach((a) => {
      if (!VALID_ALIGNS.has(String(a))) {
        errors.push({ path: `${prefix}.text_align_options`, message: `Layer ${layerNum}: invalid alignment` })
      }
    })
    const weight = String(layer.font_weight ?? "")
    if (!VALID_WEIGHTS.has(weight)) {
      errors.push({ path: `${prefix}.font_weight`, message: `Layer ${layerNum}: font_weight must be bold or regular` })
    }
    const minPct = Number(layer.font_size_min_percent)
    const maxPct = Number(layer.font_size_max_percent)
    if (Number.isNaN(minPct) || minPct <= 0) {
      errors.push({ path: `${prefix}.font_size_min_percent`, message: `Layer ${layerNum}: font_size_min_percent must be > 0` })
    }
    if (Number.isNaN(maxPct) || maxPct <= 0) {
      errors.push({ path: `${prefix}.font_size_max_percent`, message: `Layer ${layerNum}: font_size_max_percent must be > 0` })
    }
    if (!Number.isNaN(minPct) && !Number.isNaN(maxPct) && minPct > maxPct) {
      errors.push({
        path: `${prefix}.font_size_min_percent`,
        message: `Layer ${layerNum}: font_size_min_percent cannot exceed font_size_max_percent`,
      })
    }
  }

  if (type === "overlay") {
    const colorOpts = (layer.color_options as unknown[]) ?? []
    if (!colorOpts.length) {
      errors.push({
        path: `${prefix}.color_options`,
        message: `Layer ${layerNum}: at least one overlay color_option required`,
      })
    }
    colorOpts.forEach((co, ci) => {
      const op = Number((co as Record<string, unknown>)?.opacity)
      if (Number.isNaN(op) || op < 0 || op > 1) {
        errors.push({
          path: `${prefix}.color_options[${ci}].opacity`,
          message: `Layer ${layerNum}: opacity must be 0–1`,
        })
      }
    })
  }

  if (type === "shape") {
    const shapeType = String(layer.shape_type ?? "")
    if (!["rectangle", "circle", "pill"].includes(shapeType)) {
      errors.push({
        path: `${prefix}.shape_type`,
        message: `Layer ${layerNum}: shape_type must be rectangle, circle, or pill`,
      })
    }
    const fillOpts = (layer.fill_color_options as unknown[]) ?? []
    if (!fillOpts.length) {
      errors.push({
        path: `${prefix}.fill_color_options`,
        message: `Layer ${layerNum}: at least one fill_color_option required`,
      })
    }
    if (layer.opacity !== undefined && layer.opacity !== null) {
      const op = Number(layer.opacity)
      if (Number.isNaN(op) || op < 0 || op > 100) {
        errors.push({
          path: `${prefix}.opacity`,
          message: `Layer ${layerNum}: opacity must be 0–100`,
        })
      }
    }
    if (layer.stroke_width !== undefined && layer.stroke_width !== null) {
      const sw = Number(layer.stroke_width)
      if (Number.isNaN(sw) || sw < 0) {
        errors.push({
          path: `${prefix}.stroke_width`,
          message: `Layer ${layerNum}: stroke_width must be >= 0`,
        })
      }
    }
    if (layer.corner_radius !== undefined && layer.corner_radius !== null) {
      const cr = Number(layer.corner_radius)
      if (Number.isNaN(cr) || cr < 0) {
        errors.push({
          path: `${prefix}.corner_radius`,
          message: `Layer ${layerNum}: corner_radius must be >= 0`,
        })
      }
    }
  }

  if (type === "divider") {
    const orient = String(layer.orientation ?? "")
    if (!(orient === "horizontal" || orient === "diagonal")) {
      errors.push({
        path: `${prefix}.orientation`,
        message: `Layer ${layerNum}: orientation must be horizontal or diagonal`,
      })
    }
    const colorOpts = (layer.color_options as unknown[]) ?? []
    if (!colorOpts.length) {
      errors.push({
        path: `${prefix}.color_options`,
        message: `Layer ${layerNum}: at least one color_option required`,
      })
    }
    const thk = Number(layer.thickness_px)
    if (Number.isNaN(thk) || thk < 1) {
      errors.push({
        path: `${prefix}.thickness_px`,
        message: `Layer ${layerNum}: thickness_px must be >= 1`,
      })
    }
    const op = Number(layer.opacity)
    if (Number.isNaN(op) || op < 0 || op > 100) {
      errors.push({
        path: `${prefix}.opacity`,
        message: `Layer ${layerNum}: opacity must be 0–100`,
      })
    }
    const wp = Number(layer.width_pct)
    if (Number.isNaN(wp) || wp < 0 || wp > 100) {
      errors.push({
        path: `${prefix}.width_pct`,
        message: `Layer ${layerNum}: width_pct must be 0–100`,
      })
    }
    const yp = Number(layer.y_pct)
    if (Number.isNaN(yp) || yp < 0 || yp > 100) {
      errors.push({
        path: `${prefix}.y_pct`,
        message: `Layer ${layerNum}: y_pct must be 0–100`,
      })
    }
  }

  return errors
}

export function validateTemplateJson(
  raw: unknown,
  backgrounds: BackgroundAsset[],
  fonts: FontAsset[],
): { valid: boolean; json: ManualTemplateJson | null; errors: ValidationError[] } {
  const errors: ValidationError[] = []
  const bgIds = new Set(backgrounds.map((b) => b.id))
  const fontIds = new Set(fonts.map((f) => f.id))

  if (!raw || typeof raw !== "object") {
    return { valid: false, json: null, errors: [{ path: "", message: "Template must be a JSON object" }] }
  }

  const obj = raw as Record<string, unknown>

  const cw = Number(obj.canvas_width)
  const ch = Number(obj.canvas_height)
  if (!Number.isInteger(cw) || cw <= 0) {
    errors.push({ path: "canvas_width", message: "canvas_width must be a positive integer" })
  }
  if (!Number.isInteger(ch) || ch <= 0) {
    errors.push({ path: "canvas_height", message: "canvas_height must be a positive integer" })
  }
  if (!obj.aspect_ratio || typeof obj.aspect_ratio !== "string") {
    errors.push({ path: "aspect_ratio", message: "aspect_ratio is required" })
  }

  const bgOpts = (obj.background_options as unknown[]) ?? []
  if (!Array.isArray(bgOpts) || bgOpts.length < 1) {
    errors.push({ path: "background_options", message: "At least one background option is required" })
  } else if (bgOpts.length > 6) {
    errors.push({ path: "background_options", message: "Maximum 6 background options" })
  } else {
    bgOpts.forEach((item, i) => {
      const rec = item as Record<string, unknown>
      const aid = String(rec?.asset_id ?? "")
      if (!aid) {
        errors.push({ path: `background_options[${i}].asset_id`, message: "background asset_id is required" })
      } else if (!bgIds.has(aid)) {
        errors.push({
          path: `background_options[${i}].asset_id`,
          message: `background asset_id ${aid} does not exist`,
        })
      }
      if (!String(rec?.label ?? "").trim()) {
        errors.push({ path: `background_options[${i}].label`, message: "background label is required" })
      }
    })
  }

  const layers = (obj.layers as unknown[]) ?? []
  if (!Array.isArray(layers)) {
    errors.push({ path: "layers", message: "layers must be an array" })
  } else {
    const ids = new Set<string>()
    layers.forEach((layer, index) => {
      if (!layer || typeof layer !== "object") {
        errors.push({ path: `layers[${index}]`, message: `Layer ${index + 1}: must be an object` })
        return
      }
      const lid = String((layer as Record<string, unknown>).id ?? "")
      if (ids.has(lid)) {
        errors.push({ path: `layers[${index}].id`, message: `Duplicate layer id: ${lid}` })
      }
      if (lid) ids.add(lid)
      errors.push(...validateLayer(layer as Record<string, unknown>, index, bgIds, fontIds))
    })
  }

  if (errors.length) {
    return { valid: false, json: null, errors }
  }

  return {
    valid: true,
    json: obj as unknown as ManualTemplateJson,
    errors: [],
  }
}

export function parseJsonString(text: string): { data: unknown | null; parseError: string | null } {
  try {
    return { data: JSON.parse(text), parseError: null }
  } catch (e) {
    return { data: null, parseError: e instanceof Error ? e.message : "Invalid JSON" }
  }
}

export function validateForSave(
  state: { name: string; templateJson: ManualTemplateJson },
  backgrounds: BackgroundAsset[],
  fonts: FontAsset[],
): ValidationError[] {
  const errors: ValidationError[] = []
  if (!state.name.trim()) {
    errors.push({ path: "name", message: "Template name is required" })
  }
  const result = validateTemplateJson(state.templateJson, backgrounds, fonts)
  return [...errors, ...result.errors]
}

export function layerLabel(layer: TemplateLayer): string {
  if (layer.type === "text") return `${layer.role} (${layer.id})`
  return `${layer.type} (${layer.id})`
}

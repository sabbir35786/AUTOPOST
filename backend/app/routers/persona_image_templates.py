from __future__ import annotations

import base64
import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Response, UploadFile
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

# On Windows, add the gvsbuild GTK runtime DLLs to PATH so gi/pycairo can find them.
# Download from: https://github.com/wingtk/gvsbuild/releases → GTK3 bundle
_GTK_BIN = os.environ.get("GTK_BIN_PATH") or os.path.join("C:\\", "gtk", "bin")
if os.name == "nt" and os.path.isdir(_GTK_BIN):
    if _GTK_BIN not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _GTK_BIN + os.pathsep + os.environ.get("PATH", "")
    _typellb = os.path.join(os.path.dirname(_GTK_BIN), "lib", "girepository-1.0")
    if os.path.isdir(_typellb) and _typellb not in os.environ.get("GI_TYPELIB_PATH", ""):
        os.environ["GI_TYPELIB_PATH"] = _typellb + os.pathsep + os.environ.get("GI_TYPELIB_PATH", "")

_gi_import_error = None
try:
    import cairo
    import gi
    gi.require_version('Pango', '1.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo
except Exception as e:
    _gi_import_error = ImportError(
        "Pango/Cairo dependencies missing. This application requires Pango/Cairo for "
        "proper complex text layout (Bengali ligatures, Arabic shaping, etc.).\n\n"
        "On Windows:\n"
        "  1. Run setup_windows_gtk.ps1 (in the project root) as Administrator:\n"
        "       PowerShell .\\setup_windows_gtk.ps1\n"
        "  2. This downloads the GTK3 runtime from gvsbuild, installs PyGObject/PyCairo,\n"
        "     and adds C:\\gtk\\bin to your system PATH.\n"
        "  3. Alternatively, download manually from:\n"
        "       https://github.com/wingtk/gvsbuild/releases  (GTK3 bundle)\n"
        "     Extract to C:\\gtk and run: .\\setenv_gtk.cmd\n\n"
        "On Linux/Docker:\n"
        "  apt-get install python3-gi python3-gi-cairo gir1.2-pango-1.0 \\\n"
        "      libpango-1.0-0 libcairo2 libcairo2-dev\n\n"
        "Original error: " + str(e)
    )
    cairo = None
    Pango = None
    PangoCairo = None

from app import models, schemas
from app.auth import get_current_user
from app.config import CRON_SECRET, GEMINI_API_KEY, SUPABASE_SERVICE_KEY, SUPABASE_URL
from app.database import SessionLocal, get_db
from app.providers.image_providers import GeminiProvider, get_image_provider_for_user
from app.providers.llm_providers import ProviderConfigurationError, generate_text, generate_text_for_user
from app.providers.user_model_settings import generate_post_text_for_user

router = APIRouter(tags=["image-templates"])
logger = logging.getLogger(__name__)


def _get_font_family_name(font_path: str) -> str:
    try:
        from fontTools.ttLib import TTFont
        kwargs = {"fontNumber": 0} if font_path.lower().endswith(".ttc") else {}
        tt = TTFont(font_path, **kwargs)
        for record in tt["name"].names:
            if record.nameID == 1:
                return record.toUnicode()
    except Exception:
        pass
    import os
    name = os.path.splitext(os.path.basename(font_path))[0]
    return name.replace("-", " ").replace("_", " ")


def render_text_layer_pango(
    text: str,
    font_path: str,
    font_size_px: int,
    text_color_hex: str,
    layer_width_px: int,
    layer_height_px: int,
    text_align: str,
    font_weight: str
) -> Image.Image:
    if _gi_import_error is not None:
        raise _gi_import_error

    # Create transparent Cairo surface
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, layer_width_px, layer_height_px)
    ctx = cairo.Context(surface)
    
    # Transparent background
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    
    # Parse color
    hex_color = text_color_hex.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c*2 for c in hex_color)
    r = int(hex_color[0:2], 16) / 255
    g = int(hex_color[2:4], 16) / 255
    b = int(hex_color[4:6], 16) / 255
    ctx.set_source_rgba(r, g, b, 1.0)
    
    # Create Pango layout
    layout = PangoCairo.create_layout(ctx)
    layout.set_width(layer_width_px * Pango.SCALE)
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    
    # Set alignment
    align_map = {
        'center': Pango.Alignment.CENTER,
        'right': Pango.Alignment.RIGHT,
        'left': Pango.Alignment.LEFT
    }
    layout.set_alignment(align_map.get(text_align, Pango.Alignment.LEFT))
    
    # Set font using font description with script-aware fallbacks.
    # Pango accepts a comma-separated family list — it will use the first font
    # that has a glyph for each character. Pango + Harfbuzz handle the actual
    # shaping (Bengali conjuncts, Arabic cursive forms, Devanagari matras, etc.)
    # regardless of which font family is selected.
    font_desc = Pango.FontDescription()
    font_desc.set_absolute_size(font_size_px * Pango.SCALE)
    font_desc.set_weight(Pango.Weight.BOLD if font_weight == 'bold' else Pango.Weight.NORMAL)

    # Build a family list: custom font first, then cross-platform fallbacks
    # Windows: Nirmala UI covers Bengali, Devanagari; Segoe UI has wide coverage
    # Linux: Noto fonts cover all scripts
    custom_family = _get_font_family_name(font_path) if font_path else ""
    fallback_families = [
        "Nirmala UI",
        "Noto Sans Bengali",
        "Noto Serif Bengali",
        "Noto Sans Arabic",
        "Noto Sans Devanagari",
        "Noto Sans",
        "Segoe UI",
        "sans-serif",
    ]
    if custom_family:
        all_families = ", ".join([custom_family] + fallback_families)
    else:
        all_families = ", ".join(fallback_families)

    font_desc.set_family(all_families)
    layout.set_font_description(font_desc)
    layout.set_text(text, -1)
    
    # Calculate vertical centering
    text_width, text_height = layout.get_pixel_size()
    y_offset = max(0, (layer_height_px - text_height) // 2)
    
    ctx.move_to(0, y_offset)
    PangoCairo.show_layout(ctx, layout)
    
    # Convert Cairo surface to PIL Image
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        buf = surface.get_data()
    return Image.frombuffer("RGBA", (layer_width_px, layer_height_px), bytes(buf), "raw", "BGRA", 0, 1)


def register_fonts_with_fontconfig():
    fonts_dir = os.path.abspath("assets/fonts")
    if not os.path.isdir(fonts_dir) and os.path.isdir(os.path.abspath("backend/assets/fonts")):
        fonts_dir = os.path.abspath("backend/assets/fonts")
    
    fontconfig_dir = os.path.expanduser("~/.config/fontconfig")
    os.makedirs(fontconfig_dir, exist_ok=True)
    
    conf_path = os.path.join(fontconfig_dir, "fonts.conf")
    conf_content = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{fonts_dir}</dir>
</fontconfig>"""
    
    with open(conf_path, 'w') as f:
        f.write(conf_content)
    import subprocess
    if os.name == 'nt':
        print(f"[OK] Fonts registered with fontconfig from {fonts_dir} (skipped fc-cache on Windows)")
        return
    try:
        subprocess.run(['fc-cache', '-f', fonts_dir], capture_output=True)
        print(f"[OK] Fonts registered with fontconfig from {fonts_dir}")
    except Exception as e:
        print(f"[WARNING] Failed to register fonts with fc-cache: {e}")


def verify_pango_bengali():
    try:
        test_img = render_text_layer_pango(
            text="বাংলা পরীক্ষা",
            font_path="backend/assets/fonts/Roboto-Regular.ttf",
            font_size_px=40,
            text_color_hex="#000000",
            layer_width_px=400,
            layer_height_px=100,
            text_align="center",
            font_weight="regular"
        )
        print("[OK] Pango text rendering working correctly (complex scripts supported)")
    except Exception as e:
        print(f"[WARNING] Pango text rendering failed: {e}")


_VISION_SYSTEM_INSTRUCTION = (
    "You are an image layout analyst. Analyze this image and return ONLY a JSON object with no explanation, "
    "no markdown, no backticks. The JSON must have these exact keys: canvas_width (int), canvas_height (int), "
    "aspect_ratio (string like '1:1' or '4:5'), background_type (one of: solid_color, gradient, photo, illustration), "
    "background_color_hex (string or null), background_description (string describing what to generate if it is a photo "
    "or illustration), layers (array of layer objects). Each layer object must have: type (one of: background_image, "
    "subject_image, text, logo, overlay), position_x_percent (float 0-100, left edge), position_y_percent (float 0-100, "
    "top edge), width_percent (float 0-100), height_percent (float 0-100), content (string — for text layers write the "
    "actual text, for image layers describe what the image shows), font_size_percent (float, only for text layers — font "
    "size as percent of canvas height), font_weight (string, only for text layers: bold/regular/light), text_color_hex "
    "(string, only for text layers), text_align (string, only for text layers: left/center/right), z_index (int, draw "
    "order starting from 0). Return only the raw JSON."
)

_VISION_SYSTEM_INSTRUCTION = (
    "Analyze this image and return only a raw JSON object with these exact keys: canvas_width (int), "
    "canvas_height (int), aspect_ratio (string like 1:1 or 4:5 or 9:16), background_type (one of: "
    "solid_color, gradient, photo, illustration), background_color_hex (string or null), "
    "background_style_description (string - describe the visual mood, colors, subject, style of the background "
    "so it can be reproduced by an image generation API), layers (array). Each layer object: type (one of: "
    "background_image, text, logo, overlay), z_index (int, 0 is bottom), position_x_percent (float 0-100), "
    "position_y_percent (float 0-100), width_percent (float 0-100), height_percent (float 0-100), "
    "font_size_percent (float, text layers only - as percent of canvas height), font_weight (text layers only: "
    "bold or regular), text_color_hex (text layers only), text_align (text layers only: left center right), "
    "overlay_color_hex (overlay layers only), overlay_opacity (overlay layers only, float 0-1). "
    "Return only raw JSON."
)


def _clean_json_response(raw: str) -> str:
    text = (raw or "").strip()
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if start != -1 and end != -1 and end > start:
            text = text[start + 3:end].strip()
    text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("```")).strip()
    return text


def _parse_json_with_fallback(response_text: str, *, base64_image: str, model_name: str = "gemini-2.0-flash") -> dict:
    cleaned = _clean_json_response(response_text)
    try:
        return json.loads(cleaned)
    except Exception:
        try:
            repaired = generate_text(
                prompt=(
                    "The following text is supposed to be a valid JSON object but it is malformed. "
                    "Fix it and return only the raw valid JSON with no explanation, no markdown, no backticks:\n\n"
                    f"{response_text}"
                ),
                system_prompt="Return only valid raw JSON.",
                model_name=model_name,
                provider_name="gemini",
                api_key="",
                temperature=0.0,
                max_tokens=4096,
                images=[base64_image],
            )
            return json.loads(_clean_json_response(repaired or ""))
        except Exception:
            raise HTTPException(
                status_code=422,
                detail="Could not extract a valid template from this image. Please try a clearer image.",
            )


async def _upload_to_supabase(bucket: str, object_path: str, file_bytes: bytes, content_type: str) -> str:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("Supabase configuration missing.")
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
    }
    storage_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{object_path}"
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(storage_url, headers=headers, content=file_bytes)
        resp.raise_for_status()
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{object_path}"


async def _delete_from_supabase(bucket: str, object_path: str) -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    storage_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{object_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.delete(storage_url, headers=headers)


def _serialize_manual_template_json(payload: schemas.ManualImageTemplateCreate | schemas.ManualImageTemplateUpdate) -> dict:
    return payload.template_json.model_dump(mode="json")


def _validate_manual_template_assets(
    db: Session,
    user_id: int,
    template_json: dict,
) -> None:
    background_ids = {
        str(item.get("asset_id") or "").strip()
        for item in template_json.get("background_options") or []
    }
    background_ids.discard("")
    if not background_ids:
        raise HTTPException(status_code=400, detail="At least one background option is required.")

    font_ids: set[str] = set()
    for layer in template_json.get("layers") or []:
        if str(layer.get("type") or "").lower() != "text":
            continue
        for font_opt in layer.get("font_options") or []:
            fid = str(font_opt.get("font_asset_id") or "").strip()
            if fid:
                font_ids.add(fid)

    if background_ids:
        found_bg = {
            asset.id
            for asset in db.query(models.TemplateBackgroundAsset).filter(
                models.TemplateBackgroundAsset.user_id == user_id,
                models.TemplateBackgroundAsset.id.in_(background_ids),
            ).all()
        }
        missing_bg = background_ids - found_bg
        if missing_bg:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown background asset_id(s): {', '.join(sorted(missing_bg))}",
            )

    if font_ids:
        found_fonts = {
            asset.id
            for asset in db.query(models.TemplateFontAsset).filter(
                models.TemplateFontAsset.user_id == user_id,
                models.TemplateFontAsset.id.in_(font_ids),
            ).all()
        }
        missing_fonts = font_ids - found_fonts
        if missing_fonts:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown font_asset_id(s): {', '.join(sorted(missing_fonts))}",
            )


def _validate_manual_layer_constraints(template_json: dict) -> None:
    layer_ids: list[str] = []
    for layer in template_json.get("layers") or []:
        layer_id = str(layer.get("id") or "").strip()
        if not layer_id:
            raise HTTPException(status_code=400, detail="Each layer must have a non-empty id.")
        layer_ids.append(layer_id)
        if str(layer.get("type") or "").lower() == "text":
            min_pct = float(layer.get("font_size_min_percent") or 0)
            max_pct = float(layer.get("font_size_max_percent") or 0)
            if min_pct > max_pct:
                raise HTTPException(
                    status_code=400,
                    detail=f"Layer {layer_id}: font_size_min_percent cannot exceed font_size_max_percent.",
                )
    if len(layer_ids) != len(set(layer_ids)):
        raise HTTPException(status_code=400, detail="Layer ids must be unique.")


_DEFAULT_BACKGROUND_ASSETS = [
    ("Dark Navy", "solid_color", {"color_hex": "#1a1a2e"}),
    ("Deep Purple", "solid_color", {"color_hex": "#2d1b69"}),
    ("Charcoal Black", "solid_color", {"color_hex": "#222222"}),
    ("Warm Cream", "solid_color", {"color_hex": "#f5f0e8"}),
    ("Ocean Blue", "gradient", {"stops": ["#0f2027", "#203a43", "#2c5364"]}),
    ("Sunset Glow", "gradient", {"stops": ["#ff6b6b", "#feca57", "#ff9ff3"]}),
]

_DEFAULT_FONT_ASSETS = [
    ("Roboto Bold", "bold", "backend/assets/fonts/Roboto-Bold.ttf"),
    ("Roboto Regular", "regular", "backend/assets/fonts/Roboto-Regular.ttf"),
    ("Nirmala UI Regular", "regular", "C:\\Windows\\Fonts\\Nirmala.ttc"),
]


def _ensure_default_template_assets(db: Session, user_id: int) -> None:
    bg_count = (
        db.query(models.TemplateBackgroundAsset)
        .filter(models.TemplateBackgroundAsset.user_id == user_id)
        .count()
    )
    font_count = (
        db.query(models.TemplateFontAsset)
        .filter(models.TemplateFontAsset.user_id == user_id)
        .count()
    )
    if bg_count > 0 and font_count > 0:
        existing_font_paths = {
            str(row.font_file_url or "").strip().lower()
            for row in db.query(models.TemplateFontAsset)
            .filter(models.TemplateFontAsset.user_id == user_id)
            .all()
        }
        for display_name, weight, font_path in _DEFAULT_FONT_ASSETS:
            if font_path.lower() not in existing_font_paths and _resolve_font_path(font_path):
                db.add(
                    models.TemplateFontAsset(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        display_name=display_name,
                        font_file_url=font_path,
                        weight=weight,
                        created_at=datetime.now(timezone.utc),
                    )
                )
        db.commit()
        return

    now = datetime.now(timezone.utc)
    if bg_count == 0:
        for label, asset_type, value_json in _DEFAULT_BACKGROUND_ASSETS:
            db.add(
                models.TemplateBackgroundAsset(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    asset_type=asset_type,
                    label=label,
                    preview_url=None,
                    value_json=value_json,
                    created_at=now,
                )
            )

    if font_count == 0:
        for display_name, weight, font_path in _DEFAULT_FONT_ASSETS:
            db.add(
                models.TemplateFontAsset(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    display_name=display_name,
                    font_file_url=font_path,
                    weight=weight,
                    created_at=now,
                )
            )
    db.commit()


@router.get("/api/template-assets/backgrounds")
def list_background_assets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_default_template_assets(db, current_user.id)
    rows = (
        db.query(models.TemplateBackgroundAsset)
        .filter(models.TemplateBackgroundAsset.user_id == current_user.id)
        .order_by(models.TemplateBackgroundAsset.created_at.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "asset_type": row.asset_type,
            "label": row.label,
            "preview_url": row.preview_url,
            "value_json": row.value_json or {},
        }
        for row in rows
    ]


@router.get("/api/template-assets/fonts")
def list_font_assets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_default_template_assets(db, current_user.id)
    rows = (
        db.query(models.TemplateFontAsset)
        .filter(models.TemplateFontAsset.user_id == current_user.id)
        .order_by(models.TemplateFontAsset.created_at.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "display_name": row.display_name,
            "weight": row.weight,
            "font_file_url": row.font_file_url,
        }
        for row in rows
    ]


def _image_template_response(row: models.ImageTemplate) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "reference_image_url": row.reference_image_url,
        "creation_method": row.creation_method,
        "template_json": row.template_json,
        "canvas_width": row.canvas_width,
        "canvas_height": row.canvas_height,
        "aspect_ratio": row.aspect_ratio,
        "created_at": row.created_at,
    }


_PLACEHOLDER_BY_ROLE = {
    "headline": "Your Headline Here",
    "subheadline": "Supporting text goes here",
    "body": "Body text example",
}


def _lerp_channel(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _lerp_hex(c1: str, c2: str, t: float) -> tuple[int, int, int, int]:
    r1, g1, b1, _ = _parse_hex_color(c1, default=(0, 0, 0, 255))
    r2, g2, b2, _ = _parse_hex_color(c2, default=(255, 255, 255, 255))
    return (
        _lerp_channel(r1, r2, t),
        _lerp_channel(g1, g2, t),
        _lerp_channel(b1, b2, t),
        255,
    )


def _render_gradient_background(stops: list[str], canvas_w: int, canvas_h: int) -> Image.Image:
    if not stops:
        return Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))
    if len(stops) == 1:
        return Image.new("RGBA", (canvas_w, canvas_h), _parse_hex_color(stops[0], default=(30, 30, 30, 255)))
    img = Image.new("RGBA", (canvas_w, canvas_h))
    pixels = img.load()
    max_y = max(canvas_h - 1, 1)
    seg_count = len(stops) - 1
    for y in range(canvas_h):
        t = y / max_y
        seg = min(int(t * seg_count), seg_count - 1)
        local_t = (t * seg_count) - seg
        color = _lerp_hex(stops[seg], stops[seg + 1], local_t)
        for x in range(canvas_w):
            pixels[x, y] = color
    return img


def _resolve_font_path(font_file_url: str) -> str | None:
    raw = (font_file_url or "").strip()
    if not raw:
        return None
    if os.path.isfile(raw):
        return raw
    candidates = [
        raw,
        os.path.join(os.getcwd(), raw),
        os.path.join(os.path.dirname(__file__), "..", "..", raw),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _detect_script(text: str) -> str:
    for char in text or "":
        if char.isspace():
            continue
        cp = ord(char)
        if 0x0980 <= cp <= 0x09FF:
            return "bengali"
        if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF:
            return "arabic"
        if 0x0900 <= cp <= 0x097F:
            return "devanagari"
        if 0x0400 <= cp <= 0x04FF:
            return "cyrillic"
    return "latin"


def _font_candidates_for_script(script: str, weight: str, preferred_font_path: str | None = None) -> list[str]:
    w = (weight or "regular").strip().lower()
    bold = w == "bold"
    candidates: list[str] = []
    if script == "latin" and preferred_font_path:
        candidates.append(preferred_font_path)

    if script == "bengali":
        candidates.extend(
            [
                "backend/assets/fonts/NotoSansBengali-Bold.ttf" if bold else "backend/assets/fonts/NotoSansBengali-Regular.ttf",
                "assets/fonts/NotoSansBengali-Bold.ttf" if bold else "assets/fonts/NotoSansBengali-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansBengali-Bold.ttf" if bold else "/usr/share/fonts/opentype/noto/NotoSansBengali-Regular.ttf",
                "C:\\Windows\\Fonts\\Nirmala.ttc",
            ]
        )
    elif script == "arabic":
        candidates.extend(
            [
                "backend/assets/fonts/NotoSansArabic-Bold.ttf" if bold else "backend/assets/fonts/NotoSansArabic-Regular.ttf",
                "assets/fonts/NotoSansArabic-Bold.ttf" if bold else "assets/fonts/NotoSansArabic-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf" if bold else "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
            ]
        )
    elif script == "devanagari":
        candidates.extend(
            [
                "backend/assets/fonts/NotoSansDevanagari-Bold.ttf" if bold else "backend/assets/fonts/NotoSansDevanagari-Regular.ttf",
                "assets/fonts/NotoSansDevanagari-Bold.ttf" if bold else "assets/fonts/NotoSansDevanagari-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf" if bold else "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf",
                "C:\\Windows\\Fonts\\Nirmala.ttc",
                "C:\\Windows\\Fonts\\mangal.ttf",
            ]
        )
    elif script == "cyrillic":
        candidates.extend(
            [
                preferred_font_path or "",
                "backend/assets/fonts/NotoSans-Bold.ttf" if bold else "backend/assets/fonts/NotoSans-Regular.ttf",
                "assets/fonts/NotoSans-Bold.ttf" if bold else "assets/fonts/NotoSans-Regular.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                preferred_font_path or "",
                "backend/assets/fonts/Roboto-Bold.ttf" if bold else "backend/assets/fonts/Roboto-Regular.ttf",
                "assets/fonts/Roboto-Bold.ttf" if bold else "assets/fonts/Roboto-Regular.ttf",
                "backend/assets/fonts/NotoSans-Bold.ttf" if bold else "backend/assets/fonts/NotoSans-Regular.ttf",
                "assets/fonts/NotoSans-Bold.ttf" if bold else "assets/fonts/NotoSans-Regular.ttf",
                "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
            ]
        )

    candidates.extend(
        [
            "backend/assets/fonts/NotoSans-Bold.ttf" if bold else "backend/assets/fonts/NotoSans-Regular.ttf",
            "assets/fonts/NotoSans-Bold.ttf" if bold else "assets/fonts/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
            "C:\\Windows\\Fonts\\Nirmala.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
    )
    return [path for path in dict.fromkeys(candidates) if path]


def _get_font_for_text(
    text: str,
    font_asset: models.TemplateFontAsset | None,
    weight: str,
    size_px: int,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, str, str]:
    preferred = _resolve_font_path(font_asset.font_file_url) if font_asset else None
    script = _detect_script(text)
    for candidate in _font_candidates_for_script(script, weight, preferred):
        resolved = _resolve_font_path(candidate)
        if not resolved:
            continue
        try:
            return ImageFont.truetype(resolved, size_px), script, resolved
        except Exception:
            continue
    return _get_font(weight, size_px), script, "PIL default fallback"


def _get_font_for_asset(font_asset: models.TemplateFontAsset | None, weight: str, size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font, _, _ = _get_font_for_text("", font_asset, weight, size_px)
    return font


async def _load_background_asset_image(
    db: Session,
    user_id: int,
    asset_id: str,
    canvas_w: int,
    canvas_h: int,
) -> Image.Image:
    asset = (
        db.query(models.TemplateBackgroundAsset)
        .filter(
            models.TemplateBackgroundAsset.id == asset_id,
            models.TemplateBackgroundAsset.user_id == user_id,
        )
        .first()
    )
    if not asset:
        return Image.new("RGBA", (canvas_w, canvas_h), (40, 40, 40, 255))

    value = asset.value_json or {}
    asset_type = str(asset.asset_type or "").lower()
    if asset_type == "solid_color":
        return Image.new("RGBA", (canvas_w, canvas_h), _parse_hex_color(str(value.get("color_hex") or ""), default=(40, 40, 40, 255)))
    if asset_type == "gradient":
        stops = value.get("stops") or []
        if isinstance(stops, list) and stops:
            return _render_gradient_background([str(s) for s in stops], canvas_w, canvas_h)
    image_url = asset.preview_url or value.get("image_url")
    if image_url:
        blob = await _download_bytes(str(image_url))
        if blob:
            return Image.open(io.BytesIO(blob)).convert("RGBA").resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    return Image.new("RGBA", (canvas_w, canvas_h), _parse_hex_color(str(value.get("color_hex") or ""), default=(40, 40, 40, 255)))


_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def _layer_rotation_degrees(layer: dict) -> float | None:
    raw = layer.get("rotation_degrees")
    if raw is None:
        return None
    try:
        deg = float(raw)
    except (TypeError, ValueError):
        return None
    if abs(deg) < 0.01:
        return None
    return deg


def _composite_layer_onto_base(
    base: Image.Image,
    layer_img: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    rotation_degrees: float | None,
) -> Image.Image:
    """Paste layer content onto base, optionally rotating around the layer box center."""
    canvas_w, canvas_h = base.size
    content = layer_img
    if content.size != (w, h) and w > 0 and h > 0:
        content = content.resize((w, h), Image.Resampling.LANCZOS)

    layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if rotation_degrees is not None:
        rotated = content.rotate(-rotation_degrees, resample=Image.Resampling.BICUBIC, expand=True)
        cx = x + w // 2
        cy = y + h // 2
        paste_x = cx - rotated.width // 2
        paste_y = cy - rotated.height // 2
        layer_canvas.paste(rotated, (paste_x, paste_y), rotated)
    else:
        layer_canvas.paste(content, (x, y), content)
    return Image.alpha_composite(base, layer_canvas)


def _assemble_manual_template_preview(
    template_json: dict,
    background: Image.Image,
    logo_bytes: bytes | None,
    font_assets: dict[str, models.TemplateFontAsset],
) -> bytes:
    canvas_w = int(template_json.get("canvas_width") or 1024)
    canvas_h = int(template_json.get("canvas_height") or 1024)
    base = background.convert("RGBA").resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA") if logo_bytes else None

    layers = sorted(template_json.get("layers") or [], key=lambda layer: int(layer.get("z_index") or 0))
    for layer in layers:
        layer_type = str(layer.get("type") or "").lower()
        x = _pct(float(layer.get("position_x_percent") or 0), canvas_w)
        y = _pct(float(layer.get("position_y_percent") or 0), canvas_h)
        w = _pct(float(layer.get("width_percent") or 100), canvas_w)
        h = _pct(float(layer.get("height_percent") or 100), canvas_h)
        if w <= 0 or h <= 0:
            continue

        rotation = _layer_rotation_degrees(layer)

        if layer_type == "overlay":
            color_opts = layer.get("color_options") or []
            if not color_opts:
                continue
            opt = color_opts[0]
            r, g, b, _ = _parse_hex_color(str(opt.get("color_hex") or ""), default=(0, 0, 0, 255))
            opacity = max(0.0, min(1.0, float(opt.get("opacity") if opt.get("opacity") is not None else 0.35)))
            overlay = Image.new("RGBA", (w, h), (r, g, b, int(round(opacity * 255))))
            base = _composite_layer_onto_base(base, overlay, x, y, w, h, rotation)
        elif layer_type == "logo" and logo_img is not None:
            img_box = _fit_within(logo_img, w, h)
            base = _composite_layer_onto_base(base, img_box, x, y, w, h, rotation)
        elif layer_type == "text":
            role = str(layer.get("role") or "body").lower()
            text_str = _PLACEHOLDER_BY_ROLE.get(role, _PLACEHOLDER_BY_ROLE["body"])
            font_opts = layer.get("font_options") or []
            color_opts = layer.get("color_options") or []
            if not font_opts or not color_opts:
                continue
            font_id = str(font_opts[0].get("font_asset_id") or "")
            font_asset = font_assets.get(font_id)
            min_pct = float(layer.get("font_size_min_percent") or 4.0)
            max_pct = float(layer.get("font_size_max_percent") or 7.0)
            font_px = max(10, int(round(((min_pct + max_pct) / 2.0) * canvas_h / 100.0)))
            weight = str(layer.get("font_weight") or (font_asset.weight if font_asset else "regular"))
            _, script, font_path_used = _get_font_for_text(text_str, font_asset, weight, font_px)
            color_hex = str(color_opts[0].get("color_hex") or "#ffffff")
            align_opts = layer.get("text_align_options") or ["center"]
            align = str(align_opts[0] if align_opts else "center").strip().lower()
            
            text_layer = render_text_layer_pango(
                text=text_str,
                font_path=font_path_used,
                font_size_px=font_px,
                text_color_hex=color_hex,
                layer_width_px=w,
                layer_height_px=h,
                text_align=align,
                font_weight=weight
            )
            logger.info(
                'Text layer %s: script=%s font=%s size=%spx text="%s"',
                str(layer.get("id") or "preview"),
                script,
                font_path_used,
                font_px,
                text_str[:30],
            )
            base = _composite_layer_onto_base(base, text_layer, x, y, w, h, rotation)

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue()


_MANUAL_TEMPLATE_JSON_REFERENCE = """{
  "canvas_width": 1080,
  "canvas_height": 1080,
  "aspect_ratio": "1:1",
  "background_options": [{"asset_id": "uuid", "label": "string"}],
  "layers": [
    {
      "id": "layer_1",
      "type": "text",
      "role": "headline|subheadline|body",
      "z_index": 1,
      "position_x_percent": 10,
      "position_y_percent": 38,
      "width_percent": 80,
      "height_percent": 20,
      "rotation_degrees": 0,
      "font_options": [{"font_asset_id": "uuid", "label": "string"}],
      "color_options": [{"color_hex": "#ffffff", "label": "string"}],
      "font_size_min_percent": 4,
      "font_size_max_percent": 7,
      "text_align_options": ["center"],
      "font_weight": "bold|regular"
    },
    {
      "id": "layer_2",
      "type": "overlay",
      "z_index": 0,
      "position_x_percent": 0,
      "position_y_percent": 0,
      "width_percent": 100,
      "height_percent": 100,
      "rotation_degrees": 0,
      "color_options": [{"color_hex": "#000000", "opacity": 0.4, "label": "string"}]
    },
    {
      "id": "layer_3",
      "type": "logo",
      "z_index": 2,
      "position_x_percent": 78,
      "position_y_percent": 4,
      "width_percent": 18,
      "height_percent": 12,
      "rotation_degrees": 0
    }
  ]
}"""


def _infer_aspect_ratio_from_description(description: str, fallback: str = "1:1") -> str:
    text = description.lower()
    if any(k in text for k in ("16:9", "wide-angle", "wide angle", "widescreen", "landscape", "cinematic wide")):
        return "16:9"
    if any(k in text for k in ("9:16", "vertical", "story", "reel", "tiktok", "portrait full")):
        return "9:16"
    if any(k in text for k in ("4:5", "instagram portrait", "4x5")):
        return "4:5"
    if "square" in text or "1:1" in text:
        return "1:1"
    if any(k in text for k in ("wide", "cinematic", "banner", "youtube")):
        return "16:9"
    return fallback if fallback in _ASPECT_DIMENSIONS else "1:1"


def _suggested_template_name_from_description(description: str) -> str:
    line = (description.strip().split("\n")[0] or "AI Template").strip()
    if len(line) > 72:
        line = line[:69].rstrip() + "..."
    return line or "AI Template"


def _score_background_for_description(asset: models.TemplateBackgroundAsset, description: str) -> int:
    desc = description.lower()
    label = (asset.label or "").lower()
    value = asset.value_json or {}
    hex_color = str(value.get("color_hex") or "").lower()
    score = 0

    dark_terms = ("black", "dark", "space", "void", "navy", "charcoal", "night", "cinematic", "documentary")
    light_terms = ("white", "cream", "light", "bright", "warm")
    blue_terms = ("blue", "ocean", "earth", "atmosphere", "horizon")

    if any(t in desc for t in dark_terms):
        if any(t in label for t in ("dark", "black", "navy", "charcoal")):
            score += 12
        if hex_color in ("#000000", "#222222", "#1a1a2e", "#2d1b69"):
            score += 10
        if asset.asset_type == "gradient" and any(t in label for t in ("ocean", "blue")):
            score += 8
    if any(t in desc for t in light_terms):
        if "cream" in label or "warm" in label:
            score += 10
    if any(t in desc for t in blue_terms):
        if "ocean" in label or "blue" in label:
            score += 10
        if asset.asset_type == "gradient":
            score += 4
    if score == 0:
        score = 1
    return score


def _pick_backgrounds_for_description(
    description: str,
    assets: list[models.TemplateBackgroundAsset],
    *,
    max_count: int = 3,
) -> list[models.TemplateBackgroundAsset]:
    if not assets:
        return []
    ranked = sorted(assets, key=lambda a: _score_background_for_description(a, description), reverse=True)
    return ranked[:max_count]


def _normalize_generated_template_json(
    raw: dict,
    *,
    description: str,
    aspect: str,
    canvas_w: int,
    canvas_h: int,
    bg_assets: list[models.TemplateBackgroundAsset],
    font_rows: list[models.TemplateFontAsset],
) -> dict:
    """Fill gaps the LLM often misses so manual-template validation passes."""
    parsed = dict(raw)
    parsed["canvas_width"] = int(parsed.get("canvas_width") or canvas_w)
    parsed["canvas_height"] = int(parsed.get("canvas_height") or canvas_h)
    parsed["aspect_ratio"] = str(parsed.get("aspect_ratio") or aspect)

    valid_bg_ids = {a.id for a in bg_assets}
    bg_opts = parsed.get("background_options") or []
    cleaned_bg: list[dict] = []
    if isinstance(bg_opts, list):
        for item in bg_opts:
            if not isinstance(item, dict):
                continue
            aid = str(item.get("asset_id") or "").strip()
            if aid in valid_bg_ids:
                label = str(item.get("label") or "").strip() or "Background"
                cleaned_bg.append({"asset_id": aid, "label": label})
    if not cleaned_bg:
        for asset in _pick_backgrounds_for_description(description, bg_assets, max_count=3):
            cleaned_bg.append({"asset_id": asset.id, "label": asset.label or asset.asset_type or "Background"})
    parsed["background_options"] = cleaned_bg[:6]

    font_map = {f.id: f for f in font_rows}
    default_font = font_rows[0] if font_rows else None
    layers = parsed.get("layers") or []
    if not isinstance(layers, list):
        layers = []

    normalized_layers: list[dict] = []
    layer_num = 0
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        layer_num += 1
        layer_type = str(layer.get("type") or "").lower()
        if layer_type not in ("text", "logo", "overlay"):
            continue
        layer_id = str(layer.get("id") or f"layer_{layer_num}").strip() or f"layer_{layer_num}"
        try:
            z_index = int(layer.get("z_index") if layer.get("z_index") is not None else layer_num)
        except (TypeError, ValueError):
            z_index = layer_num

        base = {
            "id": layer_id,
            "type": layer_type,
            "z_index": z_index,
            "position_x_percent": float(layer.get("position_x_percent") or 0),
            "position_y_percent": float(layer.get("position_y_percent") or 0),
            "width_percent": float(layer.get("width_percent") or 100),
            "height_percent": float(layer.get("height_percent") or 100),
        }
        rot = layer.get("rotation_degrees")
        if rot is not None:
            try:
                base["rotation_degrees"] = float(rot)
            except (TypeError, ValueError):
                pass

        if layer_type == "text":
            role = str(layer.get("role") or "headline").lower()
            if role not in ("headline", "subheadline", "body"):
                role = "headline"
            font_opts = []
            for fo in layer.get("font_options") or []:
                if not isinstance(fo, dict):
                    continue
                fid = str(fo.get("font_asset_id") or "").strip()
                if fid in font_map:
                    font_opts.append(
                        {"font_asset_id": fid, "label": str(fo.get("label") or font_map[fid].display_name)}
                    )
            if not font_opts and default_font:
                font_opts = [{"font_asset_id": default_font.id, "label": default_font.display_name}]
            colors = []
            for co in layer.get("color_options") or []:
                if isinstance(co, dict) and co.get("color_hex"):
                    colors.append(
                        {
                            "color_hex": str(co.get("color_hex")),
                            "label": str(co.get("label") or "Color"),
                        }
                    )
            default_colors = [
                {"color_hex": "#ffffff", "label": "White"},
                {"color_hex": "#facc15", "label": "Yellow"},
            ]
            while len(colors) < 2 and default_colors:
                colors.append(default_colors[len(colors)])
            aligns = layer.get("text_align_options") or ["center"]
            if not isinstance(aligns, list) or not aligns:
                aligns = ["center"]
            aligns = [a for a in aligns if str(a).lower() in ("left", "center", "right")] or ["center"]
            weight = str(layer.get("font_weight") or "bold").lower()
            if weight not in ("bold", "regular"):
                weight = "bold"
            normalized_layers.append(
                {
                    **base,
                    "role": role,
                    "font_options": font_opts,
                    "color_options": colors,
                    "font_size_min_percent": float(layer.get("font_size_min_percent") or 4),
                    "font_size_max_percent": float(layer.get("font_size_max_percent") or 7),
                    "text_align_options": aligns,
                    "font_weight": weight,
                }
            )
        elif layer_type == "overlay":
            colors = []
            for co in layer.get("color_options") or []:
                if isinstance(co, dict) and co.get("color_hex") is not None:
                    try:
                        opacity = float(co.get("opacity") if co.get("opacity") is not None else 0.35)
                    except (TypeError, ValueError):
                        opacity = 0.35
                    colors.append(
                        {
                            "color_hex": str(co.get("color_hex")),
                            "opacity": max(0.0, min(1.0, opacity)),
                            "label": str(co.get("label") or "Overlay"),
                        }
                    )
            if not colors:
                colors = [{"color_hex": "#000000", "opacity": 0.4, "label": "Dark overlay"}]
            normalized_layers.append({**base, "color_options": colors})
        else:
            normalized_layers.append(base)

    if not any(str(l.get("type")) == "text" for l in normalized_layers) and default_font:
        normalized_layers.append(
            {
                "id": f"layer_{layer_num + 1}",
                "type": "text",
                "role": "headline",
                "z_index": max((int(l.get("z_index") or 0) for l in normalized_layers), default=0) + 1,
                "position_x_percent": 8,
                "position_y_percent": 62,
                "width_percent": 84,
                "height_percent": 28,
                "font_options": [{"font_asset_id": default_font.id, "label": default_font.display_name}],
                "color_options": [
                    {"color_hex": "#ffffff", "label": "White"},
                    {"color_hex": "#facc15", "label": "Yellow"},
                ],
                "font_size_min_percent": 5,
                "font_size_max_percent": 8,
                "text_align_options": ["center"],
                "font_weight": "bold",
            }
        )
    if not any(str(l.get("type")) == "logo" for l in normalized_layers):
        normalized_layers.append(
            {
                "id": f"layer_{layer_num + 2}",
                "type": "logo",
                "z_index": max((int(l.get("z_index") or 0) for l in normalized_layers), default=0) + 1,
                "position_x_percent": 78,
                "position_y_percent": 82,
                "width_percent": 16,
                "height_percent": 12,
            }
        )

    parsed["layers"] = sorted(normalized_layers, key=lambda l: int(l.get("z_index") or 0))
    return parsed


def _call_llm_for_template_json(
    *,
    user_id: int,
    db: Session,
    description: str,
    system_prompt: str,
) -> str:
    try:
        response_text = generate_text_for_user(
            user_id=user_id,
            task_category="template_generation",
            prompt=description,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=4096,
            db=db,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if response_text:
        return response_text

    from app.providers.llm_providers import _get_first_configured_provider

    fallback = _get_first_configured_provider()
    if not fallback:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider is configured. Add an API key (Mistral, OpenAI, etc.) in server settings.",
        )
    provider_name, model_name = fallback
    response_text = generate_text(
        prompt=description,
        system_prompt=system_prompt,
        model_name=model_name,
        provider_name=provider_name,
        api_key="",
        temperature=0.2,
        max_tokens=4096,
    )
    if not response_text:
        raise HTTPException(status_code=500, detail="LLM returned empty response")
    return response_text


@router.post(
    "/api/image-templates/generate-from-description",
    response_model=schemas.GenerateTemplateFromDescriptionResponse,
)
async def generate_template_from_description(
    payload: schemas.GenerateTemplateFromDescriptionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    description = (payload.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required.")

    _ensure_default_template_assets(db, current_user.id)

    requested_aspect = (payload.canvas_aspect_ratio or "1:1").strip()
    aspect = _infer_aspect_ratio_from_description(description, requested_aspect)
    canvas_w, canvas_h = _ASPECT_DIMENSIONS.get(aspect, _ASPECT_DIMENSIONS["1:1"])

    bg_ids = [str(i).strip() for i in payload.available_background_asset_ids if str(i).strip()]
    bg_query = db.query(models.TemplateBackgroundAsset).filter(
        models.TemplateBackgroundAsset.user_id == current_user.id,
    )
    if bg_ids:
        bg_assets = bg_query.filter(models.TemplateBackgroundAsset.id.in_(bg_ids)).all()
    else:
        bg_assets = bg_query.all()

    font_rows = (
        db.query(models.TemplateFontAsset)
        .filter(models.TemplateFontAsset.user_id == current_user.id)
        .all()
    )

    bg_lines = [
        f"asset_id: {a.id}, label: {a.label or a.asset_type}, type: {a.asset_type}"
        for a in bg_assets
    ]
    font_lines = [f"asset_id: {f.id}, name: {f.display_name}" for f in font_rows]

    system_prompt = (
        "You are a JSON template generator for a photocard design system. "
        "The user will describe a design and you must output a valid template JSON object and nothing else. "
        "No explanation. No markdown. No backticks. Raw JSON only.\n"
        f"The canvas is {canvas_w}x{canvas_h} pixels ({aspect}).\n"
        "Available background assets (you MUST pick 1-3 for background_options using exact asset_id values):\n"
        + ("\n".join(bg_lines) if bg_lines else "(none — omit background_options)")
        + "\nAvailable font assets (use exact font_asset_id in font_options):\n"
        + ("\n".join(font_lines) if font_lines else "(none)")
        + "\nThe template JSON must follow this exact structure:\n"
        + _MANUAL_TEMPLATE_JSON_REFERENCE
        + "\nRules:\n"
        "- position values are percentages 0-100\n"
        "- font_size_min_percent and font_size_max_percent must be realistic "
        "(headline: 4-8%, subheadline: 2-4%, body: 1.5-3%)\n"
        "- z_index starts at 0 (background overlay) and increases\n"
        "- logo layer position must be in a corner or edge (e.g. bottom-right for corporate logo)\n"
        "- every text layer must have at least 2 color_options and 1 font_option\n"
        "- use only asset_id / font_asset_id values from the lists above\n"
        "- for multi-color text (e.g. white and yellow), list both in color_options\n"
        "- place main headline text in the lower third when the design has a top image and bottom text area\n"
        f"\nUSER DESCRIPTION:\n{description}\n"
        "Return only the raw JSON object."
    )

    try:
        response_text = _call_llm_for_template_json(
            user_id=current_user.id,
            db=db,
            description=description,
            system_prompt=system_prompt,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM request failed: {exc}") from exc

    try:
        parsed = _parse_json_with_fallback(response_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse LLM JSON: {exc}") from exc

    normalized = _normalize_generated_template_json(
        parsed,
        description=description,
        aspect=aspect,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        bg_assets=bg_assets,
        font_rows=font_rows,
    )

    try:
        validated = schemas.ManualTemplateJson.model_validate(normalized)
        template_json = validated.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Generated JSON failed validation: {exc}") from exc

    _validate_manual_layer_constraints(template_json)
    _validate_manual_template_assets(db, current_user.id, template_json)

    suggested_name = _suggested_template_name_from_description(description)

    return schemas.GenerateTemplateFromDescriptionResponse(
        template_json=template_json,
        suggested_name=suggested_name,
        aspect_ratio=aspect,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
    )


@router.post("/api/image-templates/preview")
async def preview_template_image(
    payload: schemas.ImageTemplatePreviewRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    template_json = payload.template_json.model_dump(mode="json")
    _validate_manual_layer_constraints(template_json)

    bg_options = template_json.get("background_options") or []
    if not bg_options:
        raise HTTPException(status_code=400, detail="At least one background option is required for preview.")

    first_bg_id = str(bg_options[0].get("asset_id") or "").strip()
    if not first_bg_id:
        raise HTTPException(status_code=400, detail="Invalid background asset_id.")

    canvas_w = int(template_json.get("canvas_width") or 1080)
    canvas_h = int(template_json.get("canvas_height") or 1080)
    background = await _load_background_asset_image(db, current_user.id, first_bg_id, canvas_w, canvas_h)

    font_ids: set[str] = set()
    for layer in template_json.get("layers") or []:
        if str(layer.get("type") or "").lower() != "text":
            continue
        for font_opt in layer.get("font_options") or []:
            fid = str(font_opt.get("font_asset_id") or "").strip()
            if fid:
                font_ids.add(fid)
    font_assets: dict[str, models.TemplateFontAsset] = {}
    if font_ids:
        rows = (
            db.query(models.TemplateFontAsset)
            .filter(
                models.TemplateFontAsset.user_id == current_user.id,
                models.TemplateFontAsset.id.in_(font_ids),
            )
            .all()
        )
        font_assets = {row.id: row for row in rows}

    logo_bytes = None
    if payload.persona_id is not None:
        persona = (
            db.query(models.AIPersona)
            .filter(models.AIPersona.id == payload.persona_id, models.AIPersona.user_id == current_user.id)
            .first()
        )
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        settings = db.query(models.ImagePromptSettings).filter(models.ImagePromptSettings.persona_id == persona.id).first()
        logo_url = settings.template_logo_url if settings else None
        if logo_url:
            try:
                logo_bytes = await _download_bytes(logo_url)
            except Exception:
                logo_bytes = None

    png_bytes = _assemble_manual_template_preview(template_json, background, logo_bytes, font_assets)
    return Response(content=png_bytes, media_type="image/png")


@router.post("/api/image-templates/manual")
def create_manual_template(
    payload: schemas.ManualImageTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required.")

    template_json = _serialize_manual_template_json(payload)
    _validate_manual_layer_constraints(template_json)
    _validate_manual_template_assets(db, current_user.id, template_json)

    row = models.ImageTemplate(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=name,
        reference_image_url="",
        template_json=template_json,
        canvas_width=payload.canvas_width,
        canvas_height=payload.canvas_height,
        aspect_ratio=payload.aspect_ratio,
        creation_method="manual",
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _image_template_response(row)


@router.put("/api/image-templates/{template_id}")
def update_manual_template(
    template_id: str,
    payload: schemas.ManualImageTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    if row.creation_method != "manual":
        raise HTTPException(
            status_code=400,
            detail="Only manually built templates can be updated with this endpoint.",
        )

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required.")

    template_json = _serialize_manual_template_json(payload)
    _validate_manual_layer_constraints(template_json)
    _validate_manual_template_assets(db, current_user.id, template_json)

    row.name = name
    row.template_json = template_json
    row.canvas_width = payload.template_json.canvas_width
    row.canvas_height = payload.template_json.canvas_height
    row.aspect_ratio = payload.template_json.aspect_ratio
    db.commit()
    db.refresh(row)
    return _image_template_response(row)


@router.post("/api/image-templates/analyze")
async def analyze_template(
    name: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Reference image is empty.")
    content_type = image.content_type or "image/png"
    object_path = f"{current_user.id}/{uuid.uuid4()}.png"
    try:
        reference_public_url = await _upload_to_supabase("image-templates", object_path, image_bytes, content_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload reference image: {str(exc)}")

    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{content_type};base64,{b64}"
        response_text = generate_text(
            prompt="",
            system_prompt=_VISION_SYSTEM_INSTRUCTION,
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.1,
            max_tokens=4096,
            images=[data_uri],
        )
        if not response_text:
            raise HTTPException(status_code=500, detail="Gemini returned empty response")
        template_json = _parse_json_with_fallback(response_text, base64_image=data_uri)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to analyze reference image: {str(exc)}")

    canvas_width = int(template_json.get("canvas_width") or 1024)
    canvas_height = int(template_json.get("canvas_height") or 1024)
    aspect_ratio = str(template_json.get("aspect_ratio") or "1:1")
    row = models.ImageTemplate(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=name.strip(),
        reference_image_url=reference_public_url,
        template_json=template_json,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        aspect_ratio=aspect_ratio,
        creation_method="extracted",
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _image_template_response(row)


@router.get("/api/image-templates")
def list_templates(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rows = (
        db.query(models.ImageTemplate)
        .filter(models.ImageTemplate.user_id == current_user.id)
        .order_by(models.ImageTemplate.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "reference_image_url": r.reference_image_url,
            "creation_method": r.creation_method,
            "aspect_ratio": r.aspect_ratio,
            "canvas_width": r.canvas_width,
            "canvas_height": r.canvas_height,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/api/image-templates/{template_id}")
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return _image_template_response(row)


@router.delete("/api/image-templates/{template_id}")
async def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")

    marker = "/storage/v1/object/public/image-templates/"
    object_path = None
    if row.reference_image_url and marker in row.reference_image_url:
        object_path = row.reference_image_url.split(marker, 1)[-1]
    if object_path:
        await _delete_from_supabase("image-templates", object_path)
    db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.image_template_id == row.id
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return {"success": True}


@router.post("/api/personas/{persona_id}/assign-image-template")
def assign_template(
    persona_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == persona_id,
        models.AIPersona.user_id == current_user.id,
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    template_id = str(payload.get("image_template_id") or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="image_template_id is required")
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    assignment = db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.persona_id == persona_id
    ).first()
    if assignment:
        assignment.image_template_id = template_id
        assignment.assigned_at = datetime.now(timezone.utc)
    else:
        db.add(
            models.PersonaImageTemplateAssignment(
                persona_id=persona_id,
                image_template_id=template_id,
                assigned_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
    return {"success": True}


@router.delete("/api/personas/{persona_id}/assign-image-template")
def unassign_template(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == persona_id,
        models.AIPersona.user_id == current_user.id,
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.persona_id == persona_id
    ).delete(synchronize_session=False)
    db.commit()
    return {"success": True}


@router.get("/api/personas/{persona_id}/assign-image-template")
def get_assigned_template(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == persona_id,
        models.AIPersona.user_id == current_user.id,
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    assignment = db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.persona_id == persona_id
    ).first()
    if not assignment:
        return {"image_template_id": None, "name": None}
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == assignment.image_template_id,
        models.ImageTemplate.user_id == current_user.id,
    ).first()
    if not template:
        return {"image_template_id": None, "name": None}
    return {"image_template_id": template.id, "name": template.name}


@router.get("/api/personas/{persona_id}/image-template")
def get_persona_image_template(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == persona_id,
        models.AIPersona.user_id == current_user.id,
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    assignment = db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.persona_id == persona_id
    ).first()
    if not assignment:
        return None
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == assignment.image_template_id,
        models.ImageTemplate.user_id == current_user.id,
    ).first()
    if not template:
        return None
    return {
        "id": template.id,
        "name": template.name,
        "reference_image_url": template.reference_image_url,
        "template_json": template.template_json,
        "canvas_width": template.canvas_width,
        "canvas_height": template.canvas_height,
        "aspect_ratio": template.aspect_ratio,
        "assigned_at": assignment.assigned_at,
    }


def _pct(value: float, total: int) -> int:
    return int(round((float(value) / 100.0) * total))


def _parse_hex_color(value: str | None, *, default=(0, 0, 0, 0)) -> tuple[int, int, int, int]:
    if not value:
        return default
    s = value.strip()
    if not s.startswith("#"):
        s = f"#{s}"
    if len(s) == 7:
        r = int(s[1:3], 16)
        g = int(s[3:5], 16)
        b = int(s[5:7], 16)
        return (r, g, b, 255)
    return default


def _get_font(weight: str, size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[str] = []
    w = (weight or "regular").strip().lower()
    if w == "bold":
        candidates.extend(
            [
                "backend/assets/fonts/Roboto-Bold.ttf",
                "assets/fonts/Roboto-Bold.ttf",
                "C:\\Windows\\Fonts\\arialbd.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "backend/assets/fonts/Roboto-Regular.ttf",
                "assets/fonts/Roboto-Regular.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
            ]
        )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size_px)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_within(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    if target_w <= 0 or target_h <= 0:
        return Image.new("RGBA", (max(target_w, 1), max(target_h, 1)), (0, 0, 0, 0))
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    out.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2), resized)
    return out


async def _generate_imagen_rgba(prompt: str, aspect_ratio: str, canvas_w: int, canvas_h: int) -> Image.Image:
    try:
        provider = GeminiProvider()
        import asyncio
        image_bytes = await asyncio.to_thread(
            provider.generate,
            prompt=prompt,
            negative_prompt="text, letters, words, watermark, signature",
            aspect_ratio=aspect_ratio or "1:1",
            model_name="imagen-3.0-generate-001",
            api_key=GEMINI_API_KEY,
        )
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        return img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    except Exception:
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))


def _template_payload(row: models.ImageTemplate) -> dict:
    tpl = dict(row.template_json or {})
    tpl["canvas_width"] = int(row.canvas_width or tpl.get("canvas_width") or 1024)
    tpl["canvas_height"] = int(row.canvas_height or tpl.get("canvas_height") or 1024)
    tpl["aspect_ratio"] = row.aspect_ratio or str(tpl.get("aspect_ratio") or "1:1")
    return tpl


def _text_layers(template_json: dict) -> list[tuple[int, dict]]:
    return [
        (idx, layer)
        for idx, layer in enumerate(template_json.get("layers") or [])
        if str(layer.get("type") or "").lower() == "text"
    ]


def _generation_payload(row: models.PostImageGeneration | None, template: models.ImageTemplate | None = None) -> dict:
    if not row:
        return {"status": "not_started", "final_image_url": None, "error_message": None}
    llm = row.llm_instructions or {}
    template_json = (template.template_json if template else None) or {}
    manual = _is_manual_template(template, template_json) if template else bool(llm.get("chosen_background_asset_id"))
    return {
        "id": row.id,
        "post_id": row.post_id,
        "template_id": row.template_id,
        "status": row.status,
        "background_generation_prompt": row.background_generation_prompt,
        "overlay_texts": row.overlay_texts or [],
        "llm_instructions": llm,
        "chosen_background_asset_id": llm.get("chosen_background_asset_id"),
        "background_options": template_json.get("background_options") or [],
        "template_creation_method": template.creation_method if template else None,
        "can_edit_photocard": manual and bool(llm),
        "background_image_url": row.background_image_url,
        "logo_url": row.logo_url,
        "final_image_url": row.final_image_url,
        "image_url": row.final_image_url,
        "layer_overrides": row.layer_overrides or [],
        "error_message": row.error_message,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _download_bytes(url: str | None) -> bytes | None:
    if not url:
        return None
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _resolve_template_for_post(
    db: Session,
    post: models.PostLog,
    user_id: int,
    template_id: str | None = None,
) -> models.ImageTemplate:
    template = None
    if template_id:
        template = (
            db.query(models.ImageTemplate)
            .filter(models.ImageTemplate.id == template_id, models.ImageTemplate.user_id == user_id)
            .first()
        )
    elif post.ai_persona_id:
        assignment = (
            db.query(models.PersonaImageTemplateAssignment)
            .filter(models.PersonaImageTemplateAssignment.persona_id == post.ai_persona_id)
            .first()
        )
        if assignment:
            template = (
                db.query(models.ImageTemplate)
                .filter(models.ImageTemplate.id == assignment.image_template_id, models.ImageTemplate.user_id == user_id)
                .first()
            )
    if not template:
        raise HTTPException(status_code=400, detail="No image template found. Please assign a template to this persona.")
    return template


def _generate_background_prompt(db: Session, post: models.PostLog, persona: models.AIPersona, template_json: dict) -> str:
    tone_tags = persona.tone_tags or "clear, useful"
    prompt = (
        "Write an image generation prompt for a social media post background. "
        f"The post is about: {(post.content or '')[:200]}. "
        f"The persona niche is: {persona.niche}. "
        "The background style should match this description: "
        f"{template_json.get('background_style_description') or template_json.get('background_description') or 'clean social media background'}. "
        f"The tone is: {tone_tags}. Return only the image generation prompt text, nothing else. "
        "No explanation. Max 200 words."
    )
    result = generate_post_text_for_user(
        user_id=post.user_id,
        prompt=prompt,
        system_prompt="You are an expert at writing prompts for AI image generation. You write vivid, detailed, professional image generation prompts.",
        temperature=0.7,
        max_tokens=360,
        db=db,
    )
    if result is None:
        result = generate_text(
            prompt=prompt,
            system_prompt="You are an expert at writing prompts for AI image generation. You write vivid, detailed, professional image generation prompts.",
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.7,
            max_tokens=360,
        )
    return (result or "").strip() or "clean professional social media background, no text, no logos"


def _generate_overlay_texts(db: Session, post: models.PostLog, persona: models.AIPersona, template_json: dict) -> list[dict]:
    layers = _text_layers(template_json)
    if not layers:
        return []
    prompt = (
        "Based on this post content, generate overlay text for a social media image. "
        f"The post content is: {post.content}. The persona tone is: {persona.tone_tags}. "
        f"The language must be: {persona.language}. I need exactly {len(layers)} text strings where N is the number of text layers. "
        "The first text should be a short headline (max 8 words). If there are more text layers, each should be a supporting line "
        '(max 12 words each). Return only a JSON array of strings like: ["headline here", "supporting text here"]. Nothing else.'
    )
    result = generate_post_text_for_user(
        user_id=post.user_id,
        prompt=prompt,
        system_prompt="You are an expert social media copywriter. You write short, punchy, high-impact text for social media image overlays.",
        temperature=0.6,
        max_tokens=400,
        db=db,
    )
    if result is None:
        result = generate_text(
            prompt=prompt,
            system_prompt="You are an expert social media copywriter. You write short, punchy, high-impact text for social media image overlays.",
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.6,
            max_tokens=400,
        )
    try:
        values = json.loads(_clean_json_response(result or "[]"))
    except Exception:
        values = []
    if not isinstance(values, list):
        values = []
    values = [str(item).strip() for item in values if str(item).strip()]
    while len(values) < len(layers):
        values.append((post.content or "Learn more").strip().splitlines()[0][:80])
    return [{"layer_index": layer_index, "text": values[index]} for index, (layer_index, _) in enumerate(layers)]


def _is_manual_template(template: models.ImageTemplate, template_json: dict) -> bool:
    if str(template.creation_method or "").lower() == "manual":
        return True
    return bool(template_json.get("background_options"))


def build_image_instruction_prompt(
    template_json: dict,
    input_text: str,
    persona: models.AIPersona | None = None,
) -> tuple[str, str]:
    """
    Build system and user messages for LLM template instructions.
    Returns (system_message, user_message) tuple.
    
    Dynamically constructs prompts based on actual template structure.
    No hardcoding. Precise. Mirrors template exactly.
    """
    # System message (constant)
    system_message = (
        "You are a creative director for social media photocards.\n"
        "You will be given a post and a set of design options from a template.\n"
        "You must make design decisions strictly within the provided options.\n"
        "You must return ONLY a raw JSON object. No explanation. No markdown. No backticks. Raw JSON only.\n"
        "Every decision you make must come from the options listed. Do not invent values outside the provided lists."
    )
    
    # Build user message dynamically
    user_parts = []
    
    # 1. Post content
    user_parts.append(f"POST CONTENT:\n{input_text or ''}")
    
    # 2. Persona info (if provided)
    if persona:
        user_parts.append(f"TONE: {persona.tone_tags or 'neutral'}")
        user_parts.append(f"NICHE: {persona.niche or 'general'}")
        user_parts.append(f"LANGUAGE: {persona.language or 'English'}")
    
    # 3. Background options (only if they exist)
    bg_options = template_json.get("background_options") or []
    if bg_options:
        bg_lines = ["BACKGROUND — choose exactly one:"]
        for opt in bg_options:
            asset_id = opt.get("asset_id")
            label = opt.get("label", "Unnamed")
            bg_lines.append(f"- asset_id: {asset_id} | label: {label}")
        user_parts.append("\n".join(bg_lines))
    
    # 4. Layers sorted by z_index
    layers = sorted(template_json.get("layers") or [], key=lambda x: int(x.get("z_index") or 0))
    
    for layer in layers:
        layer_type = str(layer.get("type") or "").lower()
        layer_id = layer.get("id")
        
        if layer_type == "text":
            role = layer.get("role") or "body"
            min_font = layer.get("font_size_min_percent", 4.0)
            max_font = layer.get("font_size_max_percent", 10.0)
            
            # Determine max words based on role
            max_words_map = {"headline": 6, "subheadline": 12, "body": 20}
            max_words = max_words_map.get(role, 20)
            
            text_lines = [f"TEXT LAYER {layer_id} — role: {role}"]
            
            # Font options
            font_opts = layer.get("font_options") or []
            if font_opts:
                text_lines.append("Choose font from:")
                for fopt in font_opts:
                    fid = fopt.get("font_asset_id")
                    fname = fopt.get("label", "Unnamed")
                    text_lines.append(f"- font_asset_id: {fid} | name: {fname}")
            
            # Color options
            color_opts = layer.get("color_options") or []
            if color_opts:
                text_lines.append("Choose color from:")
                for copt in color_opts:
                    chex = copt.get("color_hex")
                    clbl = copt.get("label", chex)
                    text_lines.append(f"- color_hex: {chex} | label: {clbl}")
            
            # Font size range
            text_lines.append(f"Choose font_size_percent between {min_font} and {max_font}")
            
            # Text align options
            align_opts = layer.get("text_align_options") or ["center"]
            text_lines.append(f"Choose text_align from: {', '.join(align_opts)}")
            
            # Generation instruction
            language = persona.language if persona else "English"
            text_lines.append(f"Generate the text content for this layer based on the post. Max words: {max_words}")
            text_lines.append(f"Language must be: {language}")
            
            user_parts.append("\n".join(text_lines))
        
        elif layer_type == "overlay":
            overlay_lines = [f"OVERLAY LAYER {layer_id}"]
            overlay_lines.append("Choose color and opacity from:")
            
            color_opts = layer.get("color_options") or []
            for copt in color_opts:
                chex = copt.get("color_hex")
                opac = copt.get("opacity", 0.35)
                clbl = copt.get("label", chex)
                overlay_lines.append(f"- color_hex: {chex} | opacity: {opac} | label: {clbl}")
            
            user_parts.append("\n".join(overlay_lines))
        
        # Logo layers: no prompt section, LLM doesn't decide anything
    
    # 5. Expected response format (dynamic based on actual layers)
    response_lines = ["Return a JSON object with exactly this structure:"]
    response_lines.append("{")
    
    # Background if it exists
    if bg_options:
        response_lines.append('  "chosen_background_asset_id": "one of the asset_ids listed above",')
    
    response_lines.append('  "layers": [')
    
    # For each text layer
    text_layers = [l for l in layers if str(l.get("type") or "").lower() == "text"]
    for idx, tlayer in enumerate(text_layers):
        response_lines.append("    {")
        response_lines.append(f'      "layer_id": "{tlayer.get("id")}",')
        response_lines.append('      "text": "generated text here",')
        response_lines.append('      "font_asset_id": "one of the font_asset_ids listed above",')
        response_lines.append('      "color_hex": "one of the color_hex values listed above",')
        response_lines.append('      "font_size_percent": 5.5,')
        response_lines.append('      "text_align": "one of the text_align_options listed above"')
        response_lines.append("    }" + ("," if idx < len(text_layers) - 1 else ""))
    
    # For each overlay layer
    overlay_layers = [l for l in layers if str(l.get("type") or "").lower() == "overlay"]
    if overlay_layers and text_layers:
        response_lines.append("    ,")
    
    for idx, olayer in enumerate(overlay_layers):
        response_lines.append("    {")
        response_lines.append(f'      "layer_id": "{olayer.get("id")}",')
        response_lines.append('      "color_hex": "one of the color_hex values listed above",')
        response_lines.append('      "opacity": 0.35')
        response_lines.append("    }" + ("," if idx < len(overlay_layers) - 1 else ""))
    
    response_lines.append("  ]")
    response_lines.append("}")
    
    user_parts.append("\n".join(response_lines))
    
    user_message = "\n\n".join(user_parts)
    return system_message, user_message


def _build_llm_instruction_prompt(
    post: models.PostLog,
    persona: models.AIPersona,
    template_json: dict,
) -> str:
    """Backward compatibility wrapper. Use the new build_image_instruction_prompt."""
    system_msg, user_msg = build_image_instruction_prompt(template_json, post.content or "", persona)
    # Return combined message for backward compatibility
    return f"{system_msg}\n\n{user_msg}"


def _first_option(options: list, key: str):
    if not options:
        return None
    return options[0].get(key) if isinstance(options[0], dict) else None


def _validate_and_clamp_llm_instructions(template_json: dict, raw: dict, logger: logging.Logger | None = None) -> dict:
    """
    Validate LLM response strictly. Every value must come from template options.
    Use first option as fallback. Log every fallback used.
    
    Background section always uses first background if missing or invalid.
    Each layer that's missing from response uses first option for all fields.
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    bg_options = template_json.get("background_options") or []
    allowed_bg = {str(o.get("asset_id")) for o in bg_options if o.get("asset_id")}
    first_bg = str(bg_options[0].get("asset_id")) if bg_options else ""

    chosen_bg = str(raw.get("chosen_background_asset_id") or "").strip()
    if chosen_bg not in allowed_bg:
        if chosen_bg:
            logger.warning(f"Invalid background asset_id '{chosen_bg}', using fallback '{first_bg}'")
        chosen_bg = first_bg

    template_layers = {str(layer.get("id")): layer for layer in template_json.get("layers") or [] if layer.get("id")}
    raw_layers = raw.get("layers") if isinstance(raw.get("layers"), list) else []
    raw_by_id = {
        str(item.get("layer_id")): item for item in raw_layers if isinstance(item, dict) and item.get("layer_id")
    }

    clamped_layers: list[dict] = []
    for layer_id, layer in template_layers.items():
        layer_type = str(layer.get("type") or "").lower()
        incoming = raw_by_id.get(layer_id, {})
        
        if not incoming:
            logger.warning(f"Layer {layer_id}: LLM did not return this layer, using all defaults")

        if layer_type == "text":
            font_options = layer.get("font_options") or []
            color_options = layer.get("color_options") or []
            align_options = layer.get("text_align_options") or []
            allowed_fonts = {str(f.get("font_asset_id")) for f in font_options if f.get("font_asset_id")}
            allowed_colors = {str(c.get("color_hex")).lower() for c in color_options if c.get("color_hex")}

            # Font validation
            font_id = str(incoming.get("font_asset_id") or "").strip()
            first_font = str(_first_option(font_options, "font_asset_id") or "")
            if font_id not in allowed_fonts:
                if font_id:
                    logger.warning(f"Layer {layer_id}: LLM returned invalid font_asset_id '{font_id}', using fallback '{first_font}'")
                font_id = first_font

            # Color validation
            color_hex = str(incoming.get("color_hex") or "").strip().lower()
            if color_hex and not color_hex.startswith("#"):
                color_hex = f"#{color_hex}"
            first_color = str(_first_option(color_options, "color_hex") or "#ffffff")
            if color_hex.lower() not in allowed_colors:
                if color_hex:
                    logger.warning(f"Layer {layer_id}: LLM returned invalid color_hex '{color_hex}', using fallback '{first_color}'")
                color_hex = first_color

            # Font size validation
            min_pct = float(layer.get("font_size_min_percent") or 1.0)
            max_pct = float(layer.get("font_size_max_percent") or min_pct)
            try:
                font_size = float(incoming.get("font_size_percent"))
                if font_size < min_pct or font_size > max_pct:
                    clamped_size = max(min_pct, min(max_pct, font_size))
                    logger.warning(f"Layer {layer_id}: LLM font_size_percent {font_size} outside range [{min_pct}, {max_pct}], clamped to {clamped_size}")
                    font_size = clamped_size
            except (TypeError, ValueError):
                font_size = (min_pct + max_pct) / 2.0
                logger.warning(f"Layer {layer_id}: LLM returned invalid font_size_percent, using midpoint {font_size}")

            # Text align validation
            text_align = str(incoming.get("text_align") or "").strip().lower()
            first_align = str(align_options[0]).lower() if align_options else "center"
            if text_align not in [str(a).lower() for a in align_options]:
                if text_align:
                    logger.warning(f"Layer {layer_id}: LLM returned invalid text_align '{text_align}', using fallback '{first_align}'")
                text_align = first_align

            # Text content
            text = str(incoming.get("text") or "").strip()
            if not text:
                role = layer.get("role") or "headline"
                text_map = {"headline": "Your Headline Here", "subheadline": "Supporting text", "body": "Content"}
                text = text_map.get(role, "Content")
                logger.warning(f"Layer {layer_id}: LLM did not provide text, using default '{text}'")
            
            clamped_layers.append(
                {
                    "layer_id": layer_id,
                    "text": text,
                    "font_asset_id": font_id,
                    "color_hex": color_hex,
                    "font_size_percent": font_size,
                    "text_align": text_align,
                }
            )
        elif layer_type == "overlay":
            color_options = layer.get("color_options") or []
            allowed = {
                (str(c.get("color_hex")).lower(), float(c.get("opacity") if c.get("opacity") is not None else 0.35))
                for c in color_options
                if c.get("color_hex") is not None
            }
            
            color_hex = str(incoming.get("color_hex") or "").strip().lower()
            if color_hex and not color_hex.startswith("#"):
                color_hex = f"#{color_hex}"
            
            try:
                opacity = float(incoming.get("opacity"))
            except (TypeError, ValueError):
                opacity = None
            
            first = color_options[0] if color_options else {}
            first_color_hex = str(first.get("color_hex") or "#000000").lower()
            if not first_color_hex.startswith("#"):
                first_color_hex = f"#{first_color_hex}"
            first_opacity = float(first.get("opacity") if first.get("opacity") is not None else 0.35)
            
            if (color_hex, opacity) not in allowed:
                if color_hex or opacity is not None:
                    logger.warning(f"Layer {layer_id}: LLM overlay values invalid, using fallback color={first_color_hex} opacity={first_opacity}")
                color_hex = first_color_hex
                opacity = first_opacity

            clamped_layers.append(
                {
                    "layer_id": layer_id,
                    "color_hex": color_hex,
                    "opacity": max(0.0, min(1.0, opacity)),
                }
            )

    return {"chosen_background_asset_id": chosen_bg, "layers": clamped_layers}


def _generate_llm_instructions(
    db: Session,
    post: models.PostLog,
    persona: models.AIPersona,
    template_json: dict,
) -> dict:
    prompt = _build_llm_instruction_prompt(post, persona, template_json)
    result = generate_post_text_for_user(
        user_id=post.user_id,
        prompt=prompt,
        system_prompt=(
            "You are a creative director for social media photocards. "
            "Return only valid raw JSON matching the requested structure."
        ),
        temperature=0.6,
        max_tokens=1200,
        db=db,
    )
    if result is None:
        result = generate_text(
            prompt=prompt,
            system_prompt=(
                "You are a creative director for social media photocards. "
                "Return only valid raw JSON matching the requested structure."
            ),
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.6,
            max_tokens=1200,
        )
    try:
        parsed = json.loads(_clean_json_response(result or "{}"))
    except Exception:
        try:
            repaired = generate_text(
                prompt=(
                    "Fix this malformed JSON and return only raw valid JSON with no markdown:\n\n"
                    f"{result}"
                ),
                system_prompt="Return only valid raw JSON.",
                model_name="gemini-2.0-flash",
                provider_name="gemini",
                api_key="",
                temperature=0.0,
                max_tokens=1200,
            )
            parsed = json.loads(_clean_json_response(repaired or "{}"))
        except Exception:
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return _validate_and_clamp_llm_instructions(template_json, parsed)


def _allowed_background_asset_ids(template_json: dict) -> set[str]:
    return {
        str(opt.get("asset_id")).strip()
        for opt in template_json.get("background_options") or []
        if opt.get("asset_id")
    }


def _validate_background_override(template_json: dict, asset_id: str) -> str:
    asset_id = asset_id.strip()
    if not asset_id:
        raise HTTPException(status_code=400, detail="override_background_asset_id is empty.")
    allowed = _allowed_background_asset_ids(template_json)
    if asset_id not in allowed:
        raise HTTPException(
            status_code=400,
            detail="override_background_asset_id is not in this template's background_options.",
        )
    return asset_id


def _instructions_with_background_override(llm_instructions: dict, asset_id: str) -> dict:
    merged = dict(llm_instructions or {})
    merged["chosen_background_asset_id"] = asset_id
    return merged


def _merge_llm_instructions_with_overrides(
    llm_instructions: dict,
    layer_overrides: list[dict] | None,
) -> dict:
    if not layer_overrides:
        return llm_instructions
    merged = {
        "chosen_background_asset_id": llm_instructions.get("chosen_background_asset_id"),
        "layers": [dict(layer) for layer in llm_instructions.get("layers") or []],
    }
    by_id = {str(layer.get("layer_id")): layer for layer in merged["layers"]}
    for override in layer_overrides or []:
        layer_id = str(override.get("layer_id") or "").strip()
        if not layer_id and override.get("layer_index") is not None:
            continue
        if layer_id not in by_id:
            continue
        target = by_id[layer_id]
        if override.get("text") is not None or override.get("new_text") is not None:
            target["text"] = str(override.get("new_text") or override.get("text") or target.get("text") or "")
        for key in ("font_asset_id", "color_hex", "font_size_percent", "text_align", "opacity"):
            if override.get(key) is not None:
                target[key] = override[key]
    return merged


def _image_to_png_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _assemble_from_llm_instructions(
    template_json: dict,
    background: Image.Image,
    logo_bytes: bytes | None,
    llm_instructions: dict,
    db: Session,
    user_id: int,
    layer_overrides: list[dict] | None = None,
) -> bytes:
    instructions = _merge_llm_instructions_with_overrides(llm_instructions, layer_overrides)
    layer_map = {
        str(item.get("layer_id")): item for item in instructions.get("layers") or [] if item.get("layer_id")
    }

    font_ids: set[str] = set()
    for item in layer_map.values():
        fid = str(item.get("font_asset_id") or "").strip()
        if fid:
            font_ids.add(fid)
    font_assets: dict[str, models.TemplateFontAsset] = {}
    if font_ids:
        rows = (
            db.query(models.TemplateFontAsset)
            .filter(
                models.TemplateFontAsset.user_id == user_id,
                models.TemplateFontAsset.id.in_(font_ids),
            )
            .all()
        )
        font_assets = {row.id: row for row in rows}

    canvas_w = int(template_json.get("canvas_width") or 1024)
    canvas_h = int(template_json.get("canvas_height") or 1024)
    base = background.convert("RGBA").resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA") if logo_bytes else None

    layers = sorted(template_json.get("layers") or [], key=lambda layer: int(layer.get("z_index") or 0))
    for layer in layers:
        layer_id = str(layer.get("id") or "")
        layer_type = str(layer.get("type") or "").lower()
        x = _pct(float(layer.get("position_x_percent") or 0), canvas_w)
        y = _pct(float(layer.get("position_y_percent") or 0), canvas_h)
        w = _pct(float(layer.get("width_percent") or 100), canvas_w)
        h = _pct(float(layer.get("height_percent") or 100), canvas_h)
        if w <= 0 or h <= 0:
            continue

        rotation = _layer_rotation_degrees(layer)
        instr = layer_map.get(layer_id, {})
        if layer_type == "overlay":
            color_hex = str(instr.get("color_hex") or _first_option(layer.get("color_options") or [], "color_hex") or "#000000")
            try:
                opacity = float(instr.get("opacity"))
            except (TypeError, ValueError):
                opacity = float(
                    (layer.get("color_options") or [{}])[0].get("opacity")
                    if layer.get("color_options")
                    else 0.35
                )
            r, g, b, _ = _parse_hex_color(color_hex, default=(0, 0, 0, 255))
            opacity = max(0.0, min(1.0, opacity))
            overlay = Image.new("RGBA", (w, h), (r, g, b, int(round(opacity * 255))))
            base = _composite_layer_onto_base(base, overlay, x, y, w, h, rotation)
        elif layer_type == "logo" and logo_img is not None:
            img_box = _fit_within(logo_img, w, h)
            base = _composite_layer_onto_base(base, img_box, x, y, w, h, rotation)
        elif layer_type == "text":
            text_str = str(instr.get("text") or "").strip()
            if not text_str:
                continue
            font_id = str(instr.get("font_asset_id") or "")
            font_asset = font_assets.get(font_id)
            try:
                font_size_pct = float(instr.get("font_size_percent"))
            except (TypeError, ValueError):
                min_pct = float(layer.get("font_size_min_percent") or 4.0)
                max_pct = float(layer.get("font_size_max_percent") or 7.0)
                font_size_pct = (min_pct + max_pct) / 2.0
            font_px = max(10, int(round(font_size_pct * canvas_h / 100.0)))
            weight = str(layer.get("font_weight") or (font_asset.weight if font_asset else "regular"))
            _, script, font_path_used = _get_font_for_text(text_str, font_asset, weight, font_px)
            color_hex = str(instr.get("color_hex") or "#ffffff")
            align = str(instr.get("text_align") or "center").strip().lower()
            
            text_layer = render_text_layer_pango(
                text=text_str,
                font_path=font_path_used,
                font_size_px=font_px,
                text_color_hex=color_hex,
                layer_width_px=w,
                layer_height_px=h,
                text_align=align,
                font_weight=weight
            )
            logger.info(
                'Text layer %s: script=%s font=%s size=%spx text="%s"',
                layer_id,
                script,
                font_path_used,
                font_px,
                text_str[:30],
            )
            base = _composite_layer_onto_base(base, text_layer, x, y, w, h, rotation)

    return _image_to_png_bytes(base)




def _assemble_template_image(
    template_json: dict,
    background_bytes: bytes | None,
    logo_bytes: bytes | None,
    overlay_texts: list[dict],
    layer_overrides: list[dict] | None = None,
) -> bytes:
    canvas_w = int(template_json.get("canvas_width") or 1024)
    canvas_h = int(template_json.get("canvas_height") or 1024)
    base = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    bg_type = str(template_json.get("background_type") or "").lower()
    if bg_type == "solid_color":
        base = Image.new("RGBA", (canvas_w, canvas_h), _parse_hex_color(template_json.get("background_color_hex"), default=(255, 255, 255, 255)))

    text_map = {int(item.get("layer_index")): str(item.get("text") or "") for item in overlay_texts or [] if item.get("layer_index") is not None}
    for item in layer_overrides or []:
        if item.get("layer_index") is not None:
            text_map[int(item.get("layer_index"))] = str(item.get("new_text") or item.get("text") or "")

    background_img = None
    if background_bytes:
        background_img = Image.open(io.BytesIO(background_bytes)).convert("RGBA").resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA") if logo_bytes else None

    indexed_layers = list(enumerate(template_json.get("layers") or []))
    indexed_layers.sort(key=lambda item: int(item[1].get("z_index") or 0))
    for layer_index, layer in indexed_layers:
        layer_type = str(layer.get("type") or "").lower()
        x = _pct(float(layer.get("position_x_percent") or 0), canvas_w)
        y = _pct(float(layer.get("position_y_percent") or 0), canvas_h)
        w = _pct(float(layer.get("width_percent") or 100), canvas_w)
        h = _pct(float(layer.get("height_percent") or 100), canvas_h)
        if w <= 0 or h <= 0:
            continue
        if layer_type == "background_image" and background_img is not None:
            base = Image.alpha_composite(base, background_img)
        elif layer_type == "overlay":
            r, g, b, _ = _parse_hex_color(layer.get("overlay_color_hex"), default=(0, 0, 0, 255))
            opacity = max(0.0, min(1.0, float(layer.get("overlay_opacity") if layer.get("overlay_opacity") is not None else 0.35)))
            overlay = Image.new("RGBA", (w, h), (r, g, b, int(round(opacity * 255))))
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(overlay, (x, y), overlay)
            base = Image.alpha_composite(base, layer_canvas)
        elif layer_type == "logo" and logo_img is not None:
            img_box = _fit_within(logo_img, w, h)
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(img_box, (x, y), img_box)
            base = Image.alpha_composite(base, layer_canvas)
        elif layer_type == "text":
            text_str = text_map.get(layer_index, "")
            if not text_str:
                continue
            font_px = max(10, int(round(float(layer.get("font_size_percent") or 5.0) * canvas_h / 100.0)))
            weight = str(layer.get("font_weight") or "regular")
            _, script, font_path_used = _get_font_for_text(text_str, None, weight, font_px)
            color_hex = str(layer.get("text_color_hex") or "#ffffff")
            align = str(layer.get("text_align") or "left").strip().lower()
            
            text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            shadow_layer = render_text_layer_pango(
                text=text_str,
                font_path=font_path_used,
                font_size_px=font_px,
                text_color_hex="#000000",
                layer_width_px=w,
                layer_height_px=h,
                text_align=align,
                font_weight=weight
            )
            text_layer.paste(shadow_layer, (1, 1), mask=shadow_layer)
            
            main_text_img = render_text_layer_pango(
                text=text_str,
                font_path=font_path_used,
                font_size_px=font_px,
                text_color_hex=color_hex,
                layer_width_px=w,
                layer_height_px=h,
                text_align=align,
                font_weight=weight
            )
            text_layer.paste(main_text_img, (0, 0), mask=main_text_img)
            
            logger.info(
                'Text layer %s: script=%s font=%s size=%spx text="%s"',
                str(layer.get("id") or layer_index),
                script,
                font_path_used,
                font_px,
                text_str[:30],
            )
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(text_layer, (x, y), text_layer)
            base = Image.alpha_composite(base, layer_canvas)

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue()


async def _run_post_image_generation(
    db: Session,
    post_id: int,
    user_id: int,
    template_id: str | None = None,
    logo_bytes: bytes | None = None,
    raise_errors: bool = True,
) -> models.PostImageGeneration:
    generation = None
    try:
        print(f"\n{'='*60}")
        print(f"[IMG-GEN] Starting image generation for post_id={post_id}, user_id={user_id}")
        print(f"{'='*60}")

        post = db.query(models.PostLog).filter(models.PostLog.id == post_id, models.PostLog.user_id == user_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not post.ai_persona_id:
            raise HTTPException(status_code=400, detail="Post has no persona_id")
        persona = db.query(models.AIPersona).filter(models.AIPersona.id == post.ai_persona_id, models.AIPersona.user_id == user_id).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        print(f"[IMG-GEN] Persona: {persona.persona_name} (id={persona.id}), niche={persona.niche}")

        print(f"[IMG-GEN] Resolving template...")
        template = _resolve_template_for_post(db, post, user_id, template_id)
        template_json = _template_payload(template)
        print(f"[IMG-GEN] Template resolved: '{template.name}' (id={template.id}, method={template.creation_method})")

        generation = db.query(models.PostImageGeneration).filter(models.PostImageGeneration.post_id == post.id).first()
        if generation is None:
            generation = models.PostImageGeneration(post_id=post.id, template_id=template.id, status="pending")
            db.add(generation)
            db.flush()
        generation.template_id = template.id
        generation.error_message = None
        generation.updated_at = datetime.now(timezone.utc)

        manual_template = _is_manual_template(template, template_json)
        print(f"[IMG-GEN] Template type: {'manual (asset-based)' if manual_template else 'extracted (AI-generated bg)'}")

        if manual_template:
            generation.status = "generating_styling"
            db.commit()

            print(f"[IMG-GEN] Generating LLM styling instructions (background pick, text, colors)...")
            llm_instructions = _generate_llm_instructions(db, post, persona, template_json)
            print(f"[IMG-GEN] LLM chose background asset: {llm_instructions.get('chosen_background_asset_id')}")
            print(f"[IMG-GEN] LLM generated {len(llm_instructions.get('layers', []))} layer instructions")
            generation.llm_instructions = llm_instructions
            generation.overlay_texts = []
            generation.background_generation_prompt = None
            db.commit()

            canvas_w = int(template_json.get("canvas_width") or 1080)
            canvas_h = int(template_json.get("canvas_height") or 1080)
            bg_asset_id = str(llm_instructions.get("chosen_background_asset_id") or "")
            print(f"[IMG-GEN] Loading background asset image ({canvas_w}x{canvas_h})...")
            background_img = await _load_background_asset_image(db, user_id, bg_asset_id, canvas_w, canvas_h)
            bg_bytes = _image_to_png_bytes(background_img)
            print(f"[IMG-GEN] Uploading background to Supabase storage...")
            background_url = await _upload_to_supabase(
                "generated-images",
                f"post-images/{post.id}/background.png",
                bg_bytes,
                "image/png",
            )
            generation.background_image_url = background_url
            print(f"[IMG-GEN] Background uploaded: {background_url[:80]}...")
        else:
            generation.status = "generating_background"
            db.commit()

            print(f"[IMG-GEN] Generating background prompt via LLM...")
            bg_prompt = _generate_background_prompt(db, post, persona, template_json)
            print(f"[IMG-GEN] Background prompt: {bg_prompt[:120]}...")
            generation.background_generation_prompt = bg_prompt
            db.commit()

            print(f"[IMG-GEN] Generating background image via image provider...")
            provider_instance, model_name, api_key = get_image_provider_for_user(user_id, db)
            print(f"[IMG-GEN] Using image provider: {type(provider_instance).__name__}, model: {model_name}")
            import asyncio

            bg_bytes = await asyncio.to_thread(
                provider_instance.generate,
                prompt=bg_prompt,
                negative_prompt="text, letters, words, logo, watermark, signature",
                aspect_ratio=template_json.get("aspect_ratio") or "1:1",
                model_name=model_name,
                api_key=api_key,
            )
            print(f"[IMG-GEN] Background image generated ({len(bg_bytes)} bytes)")
            print(f"[IMG-GEN] Uploading background to Supabase storage...")
            background_url = await _upload_to_supabase(
                "generated-images",
                f"post-images/{post.id}/background.png",
                bg_bytes,
                "image/png",
            )
            generation.background_image_url = background_url
            print(f"[IMG-GEN] Background uploaded: {background_url[:80]}...")
            generation.status = "generating_text"
            generation.updated_at = datetime.now(timezone.utc)
            db.commit()

            print(f"[IMG-GEN] Generating overlay text via LLM...")
            generation.overlay_texts = _generate_overlay_texts(db, post, persona, template_json)
            print(f"[IMG-GEN] Generated {len(generation.overlay_texts)} overlay text(s)")
            for ot in generation.overlay_texts:
                print(f"  -> layer_index={ot.get('layer_index')}: \"{ot.get('text', '')[:60]}\"")
            generation.llm_instructions = {}

        print(f"[IMG-GEN] Resolving logo...")
        if logo_bytes:
            print(f"[IMG-GEN] Uploading provided logo ({len(logo_bytes)} bytes)...")
            generation.logo_url = await _upload_to_supabase("generated-images", f"logos/{user_id}/logo.png", logo_bytes, "image/png")
        elif not generation.logo_url:
            settings = db.query(models.ImagePromptSettings).filter(models.ImagePromptSettings.persona_id == persona.id).first()
            logo_url = settings.template_logo_url if settings else None
            if logo_url:
                print(f"[IMG-GEN] Using persona's saved logo: {logo_url[:80]}...")
                generation.logo_url = logo_url
            else:
                previous = (
                    db.query(models.PostImageGeneration)
                    .join(models.PostLog, models.PostLog.id == models.PostImageGeneration.post_id)
                    .filter(
                        models.PostLog.ai_persona_id == persona.id,
                        models.PostImageGeneration.logo_url.isnot(None),
                        models.PostImageGeneration.post_id != post.id,
                    )
                    .order_by(models.PostImageGeneration.created_at.desc())
                    .first()
                )
                if previous:
                    print(f"[IMG-GEN] Using logo from previous generation")
                    generation.logo_url = previous.logo_url
                else:
                    print(f"[IMG-GEN] No logo found — skipping logo layer")
        else:
            print(f"[IMG-GEN] Reusing existing logo: {generation.logo_url[:80] if generation.logo_url else '(none)'}")
        generation.status = "assembling"
        generation.updated_at = datetime.now(timezone.utc)
        db.commit()

        print(f"[IMG-GEN] Assembling layers into final image...")
        logo_blob = logo_bytes or await _download_bytes(generation.logo_url)
        if manual_template and generation.llm_instructions:
            canvas_w = int(template_json.get("canvas_width") or 1080)
            canvas_h = int(template_json.get("canvas_height") or 1080)
            bg_asset_id = str(generation.llm_instructions.get("chosen_background_asset_id") or "")
            print(f"[IMG-GEN] Assembling via LLM instructions (manual template path)")
            background_img = await _load_background_asset_image(db, user_id, bg_asset_id, canvas_w, canvas_h)
            final_bytes = _assemble_from_llm_instructions(
                template_json,
                background_img,
                logo_blob,
                generation.llm_instructions,
                db,
                user_id,
                generation.layer_overrides,
            )
        else:
            print(f"[IMG-GEN] Assembling via overlay texts (extracted template path)")
            bg_bytes = await _download_bytes(generation.background_image_url)
            final_bytes = _assemble_template_image(
                template_json,
                bg_bytes,
                logo_blob,
                generation.overlay_texts,
                generation.layer_overrides,
            )
        print(f"[IMG-GEN] Final image assembled ({len(final_bytes)} bytes)")
        print(f"[IMG-GEN] Uploading final image to Supabase storage...")
        final_url = await _upload_to_supabase("generated-images", f"post-images/{post.id}/final.png", final_bytes, "image/png")
        generation.final_image_url = final_url
        generation.status = "completed"
        generation.updated_at = datetime.now(timezone.utc)
        post.image_url = final_url
        post.media_urls = [final_url]
        post.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(generation)
        print(f"[IMG-GEN] ✅ Image generation COMPLETE — {final_url[:80]}...")
        print(f"{'='*60}\n")
        return generation
    except Exception as exc:
        print(f"[IMG-GEN] ❌ Image generation FAILED: {exc}")
        print(f"{'='*60}\n")
        if generation is not None:
            generation.status = "failed"
            generation.error_message = str(getattr(exc, "detail", None) or exc)
            generation.updated_at = datetime.now(timezone.utc)
            db.commit()
        if raise_errors:
            if isinstance(exc, HTTPException):
                raise exc
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return generation


async def generate_post_image_background(post_id: int, user_id: int, template_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        await _run_post_image_generation(db, post_id, user_id, template_id=template_id, raise_errors=False)
    finally:
        db.close()


@router.post("/api/posts/{post_id}/generate-image")
async def generate_post_image(
    post_id: int,
    template_id: str | None = Form(default=None),
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logo_bytes = await logo.read() if logo else None
    generation = await _run_post_image_generation(
        db,
        post_id,
        current_user.id,
        template_id=template_id,
        logo_bytes=logo_bytes,
        raise_errors=True,
    )
    return _generation_payload(generation)


@router.patch("/api/posts/{post_id}/image")
async def edit_post_image(
    post_id: int,
    text_overrides: str | None = Form(default=None),
    override_background_asset_id: str | None = Form(default=None),
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    post = db.query(models.PostLog).filter(models.PostLog.id == post_id, models.PostLog.user_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    generation = db.query(models.PostImageGeneration).filter(models.PostImageGeneration.post_id == post_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="No generated image found for this post.")
    template = db.query(models.ImageTemplate).filter(models.ImageTemplate.id == generation.template_id, models.ImageTemplate.user_id == current_user.id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template_json = _template_payload(template)
    manual_template = _is_manual_template(template, template_json)

    new_logo_bytes = await logo.read() if logo else None
    if new_logo_bytes:
        generation.logo_url = await _upload_to_supabase("generated-images", f"logos/{current_user.id}/logo.png", new_logo_bytes, "image/png")
    if text_overrides:
        try:
            incoming = json.loads(text_overrides)
            if not isinstance(incoming, list):
                raise ValueError("text_overrides must be an array")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid text_overrides JSON: {exc}")
        merged_by_index: dict[int, dict] = {}
        merged_by_id: dict[str, dict] = {}
        for item in generation.layer_overrides or []:
            if item.get("layer_id"):
                merged_by_id[str(item["layer_id"])] = dict(item)
            elif item.get("layer_index") is not None:
                merged_by_index[int(item["layer_index"])] = dict(item)
        for item in incoming:
            if item.get("layer_id"):
                merged_by_id[str(item["layer_id"])] = {**merged_by_id.get(str(item["layer_id"]), {}), **item}
            elif item.get("layer_index") is not None:
                merged_by_index[int(item["layer_index"])] = {**merged_by_index.get(int(item["layer_index"]), {}), **item}
        generation.layer_overrides = list(merged_by_index.values()) + list(merged_by_id.values())

    llm_instructions = dict(generation.llm_instructions or {})
    if override_background_asset_id:
        if not manual_template or not llm_instructions:
            raise HTTPException(
                status_code=400,
                detail="Background override is only supported for manually built template photocards.",
            )
        asset_id = _validate_background_override(template_json, override_background_asset_id)
        asset_row = (
            db.query(models.TemplateBackgroundAsset)
            .filter(
                models.TemplateBackgroundAsset.id == asset_id,
                models.TemplateBackgroundAsset.user_id == current_user.id,
            )
            .first()
        )
        if not asset_row:
            raise HTTPException(status_code=400, detail="Background asset not found.")
        llm_instructions = _instructions_with_background_override(llm_instructions, asset_id)
        generation.llm_instructions = llm_instructions

        canvas_w = int(template_json.get("canvas_width") or 1080)
        canvas_h = int(template_json.get("canvas_height") or 1080)
        background_img = await _load_background_asset_image(db, current_user.id, asset_id, canvas_w, canvas_h)
        bg_bytes = _image_to_png_bytes(background_img)
        generation.background_image_url = await _upload_to_supabase(
            "generated-images",
            f"post-images/{post.id}/background.png",
            bg_bytes,
            "image/png",
        )

    generation.status = "assembling"
    generation.updated_at = datetime.now(timezone.utc)
    db.commit()

    logo_bytes = new_logo_bytes or await _download_bytes(generation.logo_url)
    if manual_template and llm_instructions:
        canvas_w = int(template_json.get("canvas_width") or 1080)
        canvas_h = int(template_json.get("canvas_height") or 1080)
        bg_asset_id = str(llm_instructions.get("chosen_background_asset_id") or "")
        background_img = await _load_background_asset_image(db, current_user.id, bg_asset_id, canvas_w, canvas_h)
        final_bytes = _assemble_from_llm_instructions(
            template_json,
            background_img,
            logo_bytes,
            llm_instructions,
            db,
            current_user.id,
            generation.layer_overrides,
        )
    else:
        background_bytes = await _download_bytes(generation.background_image_url)
        final_bytes = _assemble_template_image(
            template_json,
            background_bytes,
            logo_bytes,
            generation.overlay_texts,
            generation.layer_overrides,
        )
    final_url = await _upload_to_supabase("generated-images", f"post-images/{post.id}/final.png", final_bytes, "image/png")
    generation.final_image_url = final_url
    generation.status = "completed"
    generation.updated_at = datetime.now(timezone.utc)
    post.image_url = final_url
    post.media_urls = [final_url]
    db.commit()
    db.refresh(generation)
    return _generation_payload(generation)


@router.get("/api/posts/{post_id}/image-status")
def get_post_image_status(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    post = db.query(models.PostLog).filter(models.PostLog.id == post_id, models.PostLog.user_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    generation = db.query(models.PostImageGeneration).filter(models.PostImageGeneration.post_id == post_id).first()
    template = None
    if generation:
        template = db.query(models.ImageTemplate).filter(models.ImageTemplate.id == generation.template_id).first()
    return _generation_payload(generation, template)


@router.get("/api/internal/debug-template/{persona_id}")
def debug_template(
    persona_id: int,
    x_cron_secret: str | None = Header(default=None, convert_underscores=False),
    db: Session = Depends(get_db),
):
    if not x_cron_secret or x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    assignment = db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.persona_id == persona_id
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="No template found for this persona.")
    row = db.query(models.ImageTemplate).filter(models.ImageTemplate.id == assignment.image_template_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No template found for this persona.")
    tpl = row.template_json or {}
    layers = list(tpl.get("layers") or [])
    return {
        "template_json": tpl,
        "layer_count": len(layers),
        "canvas_size": {"width": tpl.get("canvas_width"), "height": tpl.get("canvas_height")},
    }


from pydantic import BaseModel

class TemplateTestRequest(BaseModel):
    input_text: str

@router.post("/api/image-templates/{template_id}/test-llm")
async def test_image_template_llm(
    template_id: str,
    payload: TemplateTestRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger = logging.getLogger(__name__)
    
    # 1. Load the template
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    template_json = _template_payload(template)
    
    # 2. Check if template has background options
    background_options = template_json.get("background_options") or []
    if not background_options:
        raise HTTPException(
            status_code=400,
            detail="This template has no background options configured. Edit the template and add at least one background."
        )
        
    # 3. Find/mock persona
    persona = db.query(models.AIPersona).join(
        models.PersonaImageTemplateAssignment,
        models.PersonaImageTemplateAssignment.persona_id == models.AIPersona.id
    ).filter(
        models.PersonaImageTemplateAssignment.image_template_id == template.id,
        models.AIPersona.user_id == current_user.id
    ).first()
    
    if not persona:
        persona = db.query(models.AIPersona).filter(models.AIPersona.user_id == current_user.id).first()
        
    if not persona:
        class MockPersona:
            id = -1
            tone_tags = "clear, useful"
            niche = "general"
            language = "English"
        persona = MockPersona()
        
    # 4. Build prompt using the new function
    system_msg, user_msg = build_image_instruction_prompt(template_json, payload.input_text, persona)
    full_prompt = f"{system_msg}\n\n{user_msg}"
    
    # 5. Generate LLM instructions
    result = generate_post_text_for_user(
        user_id=current_user.id,
        prompt=user_msg,
        system_prompt=system_msg,
        temperature=0.6,
        max_tokens=1200,
        db=db,
    )
    if result is None:
        result = generate_text(
            prompt=user_msg,
            system_prompt=system_msg,
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.6,
            max_tokens=1200,
        )
    
    # Parse and validate LLM response
    try:
        parsed = json.loads(_clean_json_response(result or "{}"))
    except Exception:
        try:
            repaired = generate_text(
                prompt=(
                    "Fix this malformed JSON and return only raw valid JSON with no markdown:\n\n"
                    f"{result}"
                ),
                system_prompt="Return only valid raw JSON.",
                model_name="gemini-2.0-flash",
                provider_name="gemini",
                api_key="",
                temperature=0.0,
                max_tokens=1200,
            )
            parsed = json.loads(_clean_json_response(repaired or "{}"))
        except Exception:
            parsed = {}
    
    if not isinstance(parsed, dict):
        parsed = {}
    
    # Validate with strict rules
    llm_decisions = _validate_and_clamp_llm_instructions(template_json, parsed, logger)
    
    # Build enriched readable decisions for frontend display
    bg_label = "Unknown"
    for opt in template_json.get("background_options") or []:
        if str(opt.get("asset_id")) == str(llm_decisions.get("chosen_background_asset_id")):
            bg_label = opt.get("label") or "Unknown"
            break
            
    readable_decisions = [f"Background chosen: {bg_label}"]
    
    # Also check logo note here
    settings = db.query(models.ImagePromptSettings).filter(models.ImagePromptSettings.persona_id == persona.id).first()
    logo_url = settings.template_logo_url if settings else None
    if not logo_url:
        readable_decisions.append("No logo set for this template")
    else:
        readable_decisions.append("Logo will be applied")
        
    for l_instr in llm_decisions.get("layers") or []:
        layer_id = l_instr.get("layer_id")
        t_layer = next((l for l in template_json.get("layers") or [] if str(l.get("id")) == str(layer_id)), None)
        if not t_layer:
            continue
        role = t_layer.get("role") or t_layer.get("id") or "Text"
        l_type = str(t_layer.get("type") or "").lower()
        
        if l_type == "text":
            text_val = l_instr.get("text")
            font_label = "System Font"
            font_asset_id = l_instr.get("font_asset_id")
            for f in t_layer.get("font_options") or []:
                if str(f.get("font_asset_id")) == str(font_asset_id):
                    font_label = f.get("label") or "System Font"
                    break
            color_hex = l_instr.get("color_hex")
            color_label = color_hex
            for c in t_layer.get("color_options") or []:
                if str(c.get("color_hex")).lower() == str(color_hex).lower():
                    color_label = c.get("label") or color_hex
                    break
            font_size = l_instr.get("font_size_percent")
            readable_decisions.append(
                f"{role.capitalize()}: '{text_val}' — {font_label}, {color_label}, {font_size}%"
            )
        elif l_type == "overlay":
            color_hex = l_instr.get("color_hex")
            color_label = color_hex
            for c in t_layer.get("color_options") or []:
                if str(c.get("color_hex")).lower() == str(color_hex).lower():
                    color_label = c.get("label") or color_hex
                    break
            opacity = l_instr.get("opacity")
            readable_decisions.append(
                f"Overlay: {color_label} with {int(opacity * 100)}% opacity"
            )
            
    return {
        "prompt_sent": full_prompt,
        "llm_decisions": llm_decisions,
        "readable_decisions": readable_decisions
    }


class TemplateTestRenderRequest(BaseModel):
    llm_decisions: dict

@router.post("/api/image-templates/{template_id}/test-render")
async def test_image_template_render(
    template_id: str,
    payload: TemplateTestRenderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # 1. Load the template
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    template_json = _template_payload(template)
    llm_decisions = payload.llm_decisions

    # 2. Find/mock persona
    persona = db.query(models.AIPersona).join(
        models.PersonaImageTemplateAssignment,
        models.PersonaImageTemplateAssignment.persona_id == models.AIPersona.id
    ).filter(
        models.PersonaImageTemplateAssignment.image_template_id == template.id,
        models.AIPersona.user_id == current_user.id
    ).first()
    
    if not persona:
        persona = db.query(models.AIPersona).filter(models.AIPersona.user_id == current_user.id).first()
        
    if not persona:
        class MockPersona:
            id = -1
        persona = MockPersona()

    # 3. Load background asset and logo
    canvas_w = int(template_json.get("canvas_width") or 1080)
    canvas_h = int(template_json.get("canvas_height") or 1080)
    bg_asset_id = str(llm_decisions.get("chosen_background_asset_id") or "")
    
    background_img = await _load_background_asset_image(db, current_user.id, bg_asset_id, canvas_w, canvas_h)
    
    settings = db.query(models.ImagePromptSettings).filter(models.ImagePromptSettings.persona_id == persona.id).first()
    logo_url = settings.template_logo_url if settings else None
    logo_bytes = None
    
    if logo_url:
        try:
            logo_bytes = await _download_bytes(logo_url)
        except Exception as e:
            pass
            
    # 4. Assemble the final image via PIL
    try:
        final_bytes = _assemble_from_llm_instructions(
            template_json,
            background_img,
            logo_bytes,
            llm_decisions,
            db,
            current_user.id,
            layer_overrides=None
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"PIL assembly failed: {exc}"
        )
        
    # 5. Upload to Supabase temporary path
    object_path = f"template-tests/{template.id}/preview.png"
    try:
        await _delete_from_supabase("image-templates", object_path)
    except Exception:
        pass
        
    try:
        preview_image_url = await _upload_to_supabase("image-templates", object_path, final_bytes, "image/png")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Upload to storage failed: {exc}"
        )
        
    return {
        "preview_image_url": preview_image_url
    }

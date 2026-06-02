from __future__ import annotations

import base64
import io
import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Header, UploadFile
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app import models
from app.config import CRON_SECRET, GEMINI_API_KEY, SUPABASE_SERVICE_KEY, SUPABASE_URL
from app.database import get_db
from app.providers.image_providers import GeminiProvider
from app.providers.llm_providers import generate_text


router = APIRouter(tags=["persona-image-templates"])


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


def _clean_json_response(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


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
    # Prefer local Roboto fonts if the user has added them; otherwise fall back to common system fonts.
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
    candidates.extend(
        [
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    out.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2), resized)
    return out


async def _generate_imagen_rgba(
    prompt: str,
    aspect_ratio: str,
    canvas_w: int,
    canvas_h: int,
) -> Image.Image:
    # Wrap ALL Gemini calls in try/except and return blank on failure.
    try:
        provider = GeminiProvider()
        import asyncio
        image_bytes = await asyncio.to_thread(
            provider.generate,
            prompt=prompt,
            negative_prompt="text, letters, words, watermark, signature",
            aspect_ratio=aspect_ratio or "1:1",
            model_name="imagen-3.0-generate-002",
            api_key=GEMINI_API_KEY,
        )
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        return img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    except Exception as exc:
        print(f"[generate_imagen_rgba] failed: {exc}")
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))


@router.post("/api/personas/{persona_id}/image-template")
async def upsert_persona_image_template(
    persona_id: int,
    reference_image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Verify persona exists
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    ref_bytes = await reference_image.read()
    if not ref_bytes:
        raise HTTPException(status_code=400, detail="Reference image is empty.")

    # Upload reference image to Supabase Storage: bucket=image-templates, path={persona_id}/reference.png
    content_type = reference_image.content_type or "image/png"
    object_path = f"{persona_id}/reference.png"
    try:
        reference_public_url = await _upload_to_supabase(
            "image-templates",
            object_path,
            ref_bytes,
            content_type=content_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload reference image: {str(exc)}")

    # Gemini Vision analysis
    try:
        b64 = base64.b64encode(ref_bytes).decode("utf-8")
        data_uri = f"data:{content_type};base64,{b64}"
        response_text = generate_text(
            prompt="",
            system_prompt=_VISION_SYSTEM_INSTRUCTION,
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.1,
            max_tokens=2500,
            images=[data_uri],
        )
        if not response_text:
            raise RuntimeError("Gemini returned empty response")

        template_json = json.loads(_clean_json_response(response_text))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to analyze reference image: {str(exc)}")

    # Upsert by persona_id
    row = db.query(models.PersonaImageTemplate).filter(models.PersonaImageTemplate.persona_id == persona_id).first()
    if not row:
        row = models.PersonaImageTemplate(
            id=str(uuid.uuid4()),
            persona_id=persona_id,
            reference_image_url=reference_public_url,
            template_json=template_json,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
    else:
        row.reference_image_url = reference_public_url
        row.template_json = template_json

    db.commit()
    db.refresh(row)

    return row.template_json


@router.get("/api/personas/{persona_id}/image-template")
def get_persona_image_template(
    persona_id: int,
    db: Session = Depends(get_db),
):
    row = db.query(models.PersonaImageTemplate).filter(models.PersonaImageTemplate.persona_id == persona_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No image template found for this persona.")
    return row.template_json


@router.post("/api/posts/{post_id}/generate-image")
async def generate_post_image(
    post_id: int,
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    # 4a. Load data
    post = db.query(models.PostLog).filter(models.PostLog.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if not post.ai_persona_id:
        raise HTTPException(status_code=400, detail="Post has no persona_id")

    template_row = db.query(models.PersonaImageTemplate).filter(
        models.PersonaImageTemplate.persona_id == post.ai_persona_id
    ).first()
    if not template_row:
        raise HTTPException(
            status_code=400,
            detail="No image template found for this persona. Please upload a reference image first.",
        )

    tpl = template_row.template_json or {}
    canvas_w = int(tpl.get("canvas_width") or 1024)
    canvas_h = int(tpl.get("canvas_height") or 1024)
    aspect_ratio = str(tpl.get("aspect_ratio") or "1:1")

    layers = list(tpl.get("layers") or [])
    layers.sort(key=lambda x: int(x.get("z_index") or 0))

    post_text = post.content or ""
    lines = [ln.strip() for ln in post_text.splitlines() if ln.strip()]
    headline = lines[0] if lines else ""
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    topic_hint = (post_text[:100] or "").strip()

    # Optional logo bytes
    logo_img: Image.Image | None = None
    if logo is not None:
        try:
            logo_bytes = await logo.read()
            if logo_bytes:
                logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        except Exception as exc:
            print(f"[generate_post_image] logo read failed: {exc}")
            logo_img = None

    # 4b/4c. Build and composite
    base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Background handling (template-level)
    bg_type = str(tpl.get("background_type") or "").strip().lower()
    if bg_type == "solid_color":
        color = _parse_hex_color(tpl.get("background_color_hex"), default=(255, 255, 255, 255))
        base = Image.new("RGBA", (canvas_w, canvas_h), color)
    else:
        # photo/illustration/gradient or unknown -> generate from description
        desc = str(tpl.get("background_description") or "").strip()
        if desc:
            bg_img = await _generate_imagen_rgba(desc, aspect_ratio, canvas_w, canvas_h)
            base = Image.alpha_composite(base, bg_img)

    # Layer loop
    text_layer_seen = 0
    for layer in layers:
        layer_type = str(layer.get("type") or "").strip().lower()
        x = _pct(float(layer.get("position_x_percent") or 0), canvas_w)
        y = _pct(float(layer.get("position_y_percent") or 0), canvas_h)
        w = _pct(float(layer.get("width_percent") or 0), canvas_w)
        h = _pct(float(layer.get("height_percent") or 0), canvas_h)
        content = str(layer.get("content") or "").strip()

        if w <= 0 or h <= 0:
            continue

        if layer_type in ("background_image",):
            img = await _generate_imagen_rgba(content or str(tpl.get("background_description") or ""), aspect_ratio, canvas_w, canvas_h)
            base = Image.alpha_composite(base, img)
            continue

        if layer_type == "subject_image":
            prompt = f"{content}. Topic: {topic_hint}"
            img = await _generate_imagen_rgba(prompt, aspect_ratio, canvas_w, canvas_h)
            img_box = _fit_within(img, w, h)
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(img_box, (x, y), img_box)
            base = Image.alpha_composite(base, layer_canvas)
            continue

        if layer_type == "overlay":
            overlay_color = _parse_hex_color(content, default=(0, 0, 0, 255))
            r, g, b, _ = overlay_color
            overlay = Image.new("RGBA", (w, h), (r, g, b, int(round(255 * 0.4))))
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(overlay, (x, y), overlay)
            base = Image.alpha_composite(base, layer_canvas)
            continue

        if layer_type == "logo":
            if logo_img is None:
                continue
            try:
                img_box = _fit_within(logo_img, w, h)
                layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
                layer_canvas.paste(img_box, (x, y), img_box)
                base = Image.alpha_composite(base, layer_canvas)
            except Exception as exc:
                print(f"[generate_post_image] logo layer failed: {exc}")
            continue

        if layer_type == "text":
            # Map text layers to headline/body based on first-seen ordering.
            text_str = headline if text_layer_seen == 0 else body
            text_layer_seen += 1
            if not text_str:
                continue

            font_size_pct = float(layer.get("font_size_percent") or 5.0)
            font_px = max(10, int(round((font_size_pct / 100.0) * canvas_h)))
            weight = str(layer.get("font_weight") or "regular")
            font = _get_font(weight, font_px)

            color_hex = layer.get("text_color_hex")
            color = _parse_hex_color(str(color_hex) if color_hex is not None else None, default=(255, 255, 255, 255))
            align = str(layer.get("text_align") or "left").strip().lower()

            text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(text_layer)
            # Simple wrapping: honor newlines; no complex box-fitting.
            parts = text_str.split("\n")
            cursor_y = 0
            for part in parts:
                if not part:
                    cursor_y += int(round(font_px * 0.4))
                    continue
                try:
                    bbox = draw.textbbox((0, 0), part, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except Exception:
                    tw, th = draw.textsize(part, font=font)

                if align == "center":
                    tx = max(0, (w - tw) // 2)
                elif align == "right":
                    tx = max(0, w - tw)
                else:
                    tx = 0

                draw.text((tx + 1, cursor_y + 1), part, font=font, fill=(0, 0, 0, 160))
                draw.text((tx, cursor_y), part, font=font, fill=color)
                cursor_y += th + int(round(font_px * 0.25))
                if cursor_y > h:
                    break

            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(text_layer, (x, y), text_layer)
            base = Image.alpha_composite(base, layer_canvas)
            continue

    final_rgb = base.convert("RGB")
    out = io.BytesIO()
    final_rgb.save(out, format="PNG")
    final_bytes = out.getvalue()

    # 4d. Save and store
    try:
        object_path = f"{post_id}/final.png"
        public_url = await _upload_to_supabase("generated-images", object_path, final_bytes, content_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload generated image: {str(exc)}")

    post.image_url = public_url
    post.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"image_url": public_url}


@router.get("/api/internal/debug-template/{persona_id}")
def debug_template(
    persona_id: int,
    x_cron_secret: str | None = Header(default=None, convert_underscores=False),
    db: Session = Depends(get_db),
):
    if not x_cron_secret or x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    row = db.query(models.PersonaImageTemplate).filter(models.PersonaImageTemplate.persona_id == persona_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No template found for this persona.")

    tpl = row.template_json or {}
    canvas_w = tpl.get("canvas_width")
    canvas_h = tpl.get("canvas_height")
    layers = list(tpl.get("layers") or [])
    return {
        "template_json": tpl,
        "layer_count": len(layers),
        "canvas_size": {"width": canvas_w, "height": canvas_h},
    }


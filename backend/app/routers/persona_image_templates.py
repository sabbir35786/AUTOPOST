from __future__ import annotations

import base64
import io
import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, UploadFile
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.config import CRON_SECRET, GEMINI_API_KEY, SUPABASE_SERVICE_KEY, SUPABASE_URL
from app.database import get_db
from app.providers.image_providers import GeminiProvider
from app.providers.llm_providers import generate_text

router = APIRouter(tags=["image-templates"])

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

    row = models.ImageTemplate(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=name.strip(),
        reference_image_url=reference_public_url,
        template_json=template_json,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "reference_image_url": row.reference_image_url,
        "template_json": row.template_json,
        "created_at": row.created_at,
    }


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
    return [{"id": r.id, "name": r.name, "reference_image_url": r.reference_image_url, "created_at": r.created_at} for r in rows]


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
    return {
        "id": row.id,
        "name": row.name,
        "reference_image_url": row.reference_image_url,
        "template_json": row.template_json,
        "created_at": row.created_at,
    }


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
    object_path = row.reference_image_url.split(marker, 1)[-1] if marker in row.reference_image_url else None
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


@router.post("/api/posts/{post_id}/generate-image")
async def generate_post_image(
    post_id: int,
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    post = db.query(models.PostLog).filter(models.PostLog.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if not post.ai_persona_id:
        raise HTTPException(status_code=400, detail="Post has no persona_id")

    assignment = db.query(models.PersonaImageTemplateAssignment).filter(
        models.PersonaImageTemplateAssignment.persona_id == post.ai_persona_id
    ).first()
    if not assignment:
        raise HTTPException(
            status_code=400,
            detail="No image template assigned to this persona. Please assign one in the Templates page.",
        )
    template_row = db.query(models.ImageTemplate).filter(models.ImageTemplate.id == assignment.image_template_id).first()
    if not template_row:
        raise HTTPException(
            status_code=400,
            detail="No image template assigned to this persona. Please assign one in the Templates page.",
        )

    tpl = template_row.template_json or {}
    canvas_w = int(tpl.get("canvas_width") or 1024)
    canvas_h = int(tpl.get("canvas_height") or 1024)
    aspect_ratio = str(tpl.get("aspect_ratio") or "1:1")
    layers = sorted(list(tpl.get("layers") or []), key=lambda x: int(x.get("z_index") or 0))

    post_text = post.content or ""
    lines = [ln.strip() for ln in post_text.splitlines() if ln.strip()]
    headline = lines[0] if lines else ""
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    topic_hint = (post_text[:100] or "").strip()

    logo_img: Image.Image | None = None
    if logo is not None:
        try:
            logo_bytes = await logo.read()
            if logo_bytes:
                logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        except Exception:
            logo_img = None

    base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    bg_type = str(tpl.get("background_type") or "").strip().lower()
    if bg_type == "solid_color":
        base = Image.new("RGBA", (canvas_w, canvas_h), _parse_hex_color(tpl.get("background_color_hex"), default=(255, 255, 255, 255)))
    else:
        desc = str(tpl.get("background_description") or "").strip()
        if desc:
            base = Image.alpha_composite(base, await _generate_imagen_rgba(desc, aspect_ratio, canvas_w, canvas_h))

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

        if layer_type == "background_image":
            base = Image.alpha_composite(base, await _generate_imagen_rgba(content or str(tpl.get("background_description") or ""), aspect_ratio, canvas_w, canvas_h))
            continue
        if layer_type == "subject_image":
            img = await _generate_imagen_rgba(f"{content}. Topic: {topic_hint}", aspect_ratio, canvas_w, canvas_h)
            img_box = _fit_within(img, w, h)
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(img_box, (x, y), img_box)
            base = Image.alpha_composite(base, layer_canvas)
            continue
        if layer_type == "overlay":
            r, g, b, _ = _parse_hex_color(content, default=(0, 0, 0, 255))
            overlay = Image.new("RGBA", (w, h), (r, g, b, int(round(255 * 0.4))))
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(overlay, (x, y), overlay)
            base = Image.alpha_composite(base, layer_canvas)
            continue
        if layer_type == "logo" and logo_img is not None:
            img_box = _fit_within(logo_img, w, h)
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(img_box, (x, y), img_box)
            base = Image.alpha_composite(base, layer_canvas)
            continue
        if layer_type == "text":
            text_str = headline if text_layer_seen == 0 else body
            text_layer_seen += 1
            if not text_str:
                continue
            font_px = max(10, int(round((float(layer.get("font_size_percent") or 5.0) / 100.0) * canvas_h)))
            font = _get_font(str(layer.get("font_weight") or "regular"), font_px)
            color = _parse_hex_color(str(layer.get("text_color_hex") or ""), default=(255, 255, 255, 255))
            align = str(layer.get("text_align") or "left").strip().lower()
            text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(text_layer)
            cursor_y = 0
            for part in text_str.split("\n"):
                if not part:
                    cursor_y += int(round(font_px * 0.4))
                    continue
                try:
                    bbox = draw.textbbox((0, 0), part, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except Exception:
                    tw, th = draw.textsize(part, font=font)
                tx = max(0, (w - tw) // 2) if align == "center" else max(0, w - tw) if align == "right" else 0
                draw.text((tx + 1, cursor_y + 1), part, font=font, fill=(0, 0, 0, 160))
                draw.text((tx, cursor_y), part, font=font, fill=color)
                cursor_y += th + int(round(font_px * 0.25))
                if cursor_y > h:
                    break
            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(text_layer, (x, y), text_layer)
            base = Image.alpha_composite(base, layer_canvas)

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    final_bytes = out.getvalue()
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

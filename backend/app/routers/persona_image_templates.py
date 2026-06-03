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
from app.database import SessionLocal, get_db
from app.providers.image_providers import GeminiProvider, get_image_provider_for_user
from app.providers.llm_providers import generate_text
from app.providers.user_model_settings import generate_post_text_for_user

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
        "canvas_width": row.canvas_width,
        "canvas_height": row.canvas_height,
        "aspect_ratio": row.aspect_ratio,
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
    return [
        {
            "id": r.id,
            "name": r.name,
            "reference_image_url": r.reference_image_url,
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
    return {
        "id": row.id,
        "name": row.name,
        "reference_image_url": row.reference_image_url,
        "template_json": row.template_json,
        "canvas_width": row.canvas_width,
        "canvas_height": row.canvas_height,
        "aspect_ratio": row.aspect_ratio,
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


def _generation_payload(row: models.PostImageGeneration | None) -> dict:
    if not row:
        return {"status": "not_started", "final_image_url": None, "error_message": None}
    return {
        "id": row.id,
        "post_id": row.post_id,
        "template_id": row.template_id,
        "status": row.status,
        "background_generation_prompt": row.background_generation_prompt,
        "overlay_texts": row.overlay_texts or [],
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


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


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
            font = _get_font(str(layer.get("font_weight") or "regular"), font_px)
            color = _parse_hex_color(str(layer.get("text_color_hex") or ""), default=(255, 255, 255, 255))
            align = str(layer.get("text_align") or "left").strip().lower()
            text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(text_layer)
            cursor_y = 0
            for paragraph in text_str.splitlines() or [text_str]:
                for line in _wrap_text(draw, paragraph, font, w):
                    bbox = draw.textbbox((0, 0), line, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    tx = max(0, (w - tw) // 2) if align == "center" else max(0, w - tw) if align == "right" else 0
                    draw.text((tx + 1, cursor_y + 1), line, font=font, fill=(0, 0, 0, 140))
                    draw.text((tx, cursor_y), line, font=font, fill=color)
                    cursor_y += th + max(3, int(font_px * 0.22))
                    if cursor_y > h:
                        break
                if cursor_y > h:
                    break
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
        post = db.query(models.PostLog).filter(models.PostLog.id == post_id, models.PostLog.user_id == user_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not post.ai_persona_id:
            raise HTTPException(status_code=400, detail="Post has no persona_id")
        persona = db.query(models.AIPersona).filter(models.AIPersona.id == post.ai_persona_id, models.AIPersona.user_id == user_id).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        template = _resolve_template_for_post(db, post, user_id, template_id)
        template_json = _template_payload(template)

        generation = db.query(models.PostImageGeneration).filter(models.PostImageGeneration.post_id == post.id).first()
        if generation is None:
            generation = models.PostImageGeneration(post_id=post.id, template_id=template.id, status="pending")
            db.add(generation)
            db.flush()
        generation.template_id = template.id
        generation.status = "generating_background"
        generation.error_message = None
        generation.updated_at = datetime.now(timezone.utc)
        db.commit()

        bg_prompt = _generate_background_prompt(db, post, persona, template_json)
        generation.background_generation_prompt = bg_prompt
        db.commit()

        provider_instance, model_name, api_key = get_image_provider_for_user(user_id, db)
        import asyncio

        bg_bytes = await asyncio.to_thread(
            provider_instance.generate,
            prompt=bg_prompt,
            negative_prompt="text, letters, words, logo, watermark, signature",
            aspect_ratio=template_json.get("aspect_ratio") or "1:1",
            model_name=model_name,
            api_key=api_key,
        )
        background_url = await _upload_to_supabase("generated-images", f"post-images/{post.id}/background.png", bg_bytes, "image/png")
        generation.background_image_url = background_url
        generation.status = "generating_text"
        generation.updated_at = datetime.now(timezone.utc)
        db.commit()

        generation.overlay_texts = _generate_overlay_texts(db, post, persona, template_json)
        if logo_bytes:
            generation.logo_url = await _upload_to_supabase("generated-images", f"logos/{user_id}/logo.png", logo_bytes, "image/png")
        elif not generation.logo_url:
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
                generation.logo_url = previous.logo_url
        generation.status = "assembling"
        generation.updated_at = datetime.now(timezone.utc)
        db.commit()

        logo_blob = logo_bytes or await _download_bytes(generation.logo_url)
        final_bytes = _assemble_template_image(template_json, bg_bytes, logo_blob, generation.overlay_texts, generation.layer_overrides)
        final_url = await _upload_to_supabase("generated-images", f"post-images/{post.id}/final.png", final_bytes, "image/png")
        generation.final_image_url = final_url
        generation.status = "completed"
        generation.updated_at = datetime.now(timezone.utc)
        post.image_url = final_url
        post.media_urls = [final_url]
        post.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(generation)
        return generation
    except Exception as exc:
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
        merged = {int(item.get("layer_index")): item for item in generation.layer_overrides or [] if item.get("layer_index") is not None}
        for item in incoming:
            if item.get("layer_index") is not None:
                merged[int(item["layer_index"])] = item
        generation.layer_overrides = list(merged.values())

    generation.status = "assembling"
    generation.updated_at = datetime.now(timezone.utc)
    db.commit()

    background_bytes = await _download_bytes(generation.background_image_url)
    logo_bytes = new_logo_bytes or await _download_bytes(generation.logo_url)
    final_bytes = _assemble_template_image(_template_payload(template), background_bytes, logo_bytes, generation.overlay_texts, generation.layer_overrides)
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
    return _generation_payload(generation)


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

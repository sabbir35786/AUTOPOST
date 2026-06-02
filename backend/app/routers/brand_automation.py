from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.database import get_db
from app.providers.llm_providers import generate_text_for_user, generate_text


router = APIRouter(tags=["brand-automation"])


class BrandProfileUpsert(BaseModel):
    brand_name: str | None = None
    primary_color_hex: str | None = None
    secondary_color_hex: str | None = None
    tone: str | None = None
    logo_url: str | None = None
    brand_json: dict = Field(default_factory=dict)


class ContentPlanRequest(BaseModel):
    count: int = Field(30, ge=1, le=200)
    theme: str = Field(..., min_length=2)


class ContentGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2)
    tone: str | None = None
    brand_name: str | None = None


@router.get("/api/brand/profile")
def get_brand_profile(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.query(models.BrandProfile).filter(models.BrandProfile.user_id == current_user.id).first()
    if not row:
        return {}
    return {
        "brand_name": row.brand_name,
        "primary_color_hex": row.primary_color_hex,
        "secondary_color_hex": row.secondary_color_hex,
        "tone": row.tone,
        "logo_url": row.logo_url,
        "brand_json": row.brand_json,
        "updated_at": row.updated_at,
    }


@router.post("/api/brand/profile")
def upsert_brand_profile(
    payload: BrandProfileUpsert,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.query(models.BrandProfile).filter(models.BrandProfile.user_id == current_user.id).first()
    if not row:
        row = models.BrandProfile(
            user_id=current_user.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)

    row.brand_name = payload.brand_name
    row.primary_color_hex = payload.primary_color_hex
    row.secondary_color_hex = payload.secondary_color_hex
    row.tone = payload.tone
    row.logo_url = payload.logo_url
    row.brand_json = payload.brand_json or {}
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}


@router.get("/api/brand/dna")
def get_brand_dna(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.query(models.BrandDNA).filter(models.BrandDNA.user_id == current_user.id).first()
    if not row:
        return {}
    return {"source_count": row.source_count, "dna_json": row.dna_json, "updated_at": row.updated_at}


@router.post("/api/brand/dna/analyze")
async def analyze_brand_dna(
    reference_images: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # “Creative director” analysis: extract recurring style & layout rules.
    if not reference_images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    data_uris: list[str] = []
    for f in reference_images[:20]:
        b = await f.read()
        if not b:
            continue
        ct = f.content_type or "image/png"
        data_uris.append(f"data:{ct};base64,{base64.b64encode(b).decode('utf-8')}")

    if not data_uris:
        raise HTTPException(status_code=400, detail="All provided images were empty.")

    system_prompt = (
        "You are a brand design analyst. You will be given multiple successful social posts from a single brand. "
        "Infer the brand's Creative DNA and return ONLY raw JSON (no markdown). "
        "Return keys: color_palette (array of hex), typography (object with font_families, weights, typical_sizes_px), "
        "layout_patterns (array of recurring layout rules with positions/sizes), logo_rules (object), "
        "text_length_rules (object), background_style_rules (object), do_not_do (array)."
    )
    try:
        resp = generate_text(
            prompt="Analyze the images and infer the Creative DNA.",
            system_prompt=system_prompt,
            provider_name="gemini",
            model_name="gemini-2.0-flash",
            api_key="",
            temperature=0.2,
            max_tokens=2500,
            images=data_uris,
        )
        if not resp:
            raise RuntimeError("Vision model returned empty response")
        raw = resp.strip()
        if raw.startswith("```"):
            raw = "\n".join([ln for ln in raw.splitlines() if not ln.strip().startswith("```")]).strip()
        dna_json = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to analyze Creative DNA: {str(exc)}")

    row = db.query(models.BrandDNA).filter(models.BrandDNA.user_id == current_user.id).first()
    if not row:
        row = models.BrandDNA(user_id=current_user.id, created_at=datetime.now(timezone.utc))
        db.add(row)
    row.source_count = len(data_uris)
    row.dna_json = dna_json
    row.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"source_count": row.source_count, "dna_json": row.dna_json}


@router.post("/api/content/plan")
def plan_content_topics(
    payload: ContentPlanRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    system_prompt = (
        "You are a content planner. Return ONLY raw JSON: an array of objects with key 'topic'. "
        "Topics must be distinct, actionable, and specific."
    )
    prompt = f"Generate {payload.count} post topics about: {payload.theme}"
    resp = generate_text_for_user(
        user_id=current_user.id,
        task_category="post_generation",
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        temperature=0.6,
        max_tokens=1200,
    )
    if not resp:
        raise HTTPException(status_code=500, detail="Failed to plan topics")
    raw = resp.strip()
    if raw.startswith("```"):
        raw = "\n".join([ln for ln in raw.splitlines() if not ln.strip().startswith("```")]).strip()
    try:
        topics = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse planner JSON: {str(exc)}")
    return topics


@router.post("/api/content/generate")
def generate_content_instructions(
    payload: ContentGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # “Creative director”: generate text + image prompt (instructions), not final image.
    brand = db.query(models.BrandProfile).filter(models.BrandProfile.user_id == current_user.id).first()
    tone = payload.tone or (brand.tone if brand else None) or "professional"
    brand_name = payload.brand_name or (brand.brand_name if brand else None)

    system_prompt = (
        "You are a creative director for social media. Return ONLY raw JSON with keys: "
        "headline, body, cta, image_prompt. "
        "Do NOT output any markdown."
    )
    prompt = f"Topic: {payload.topic}\nTone: {tone}\nBrand: {brand_name or 'N/A'}"
    resp = generate_text_for_user(
        user_id=current_user.id,
        task_category="post_generation",
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        temperature=0.7,
        max_tokens=900,
    )
    if not resp:
        raise HTTPException(status_code=500, detail="Failed to generate content instructions")
    raw = resp.strip()
    if raw.startswith("```"):
        raw = "\n".join([ln for ln in raw.splitlines() if not ln.strip().startswith("```")]).strip()
    try:
        out = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse generator JSON: {str(exc)}")
    return out


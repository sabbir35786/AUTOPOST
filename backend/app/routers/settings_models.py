from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.database import get_db


POST_ALLOWED: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
}

IMAGE_ALLOWED: dict[str, list[str]] = {
    "gemini": ["imagen-3.0-generate-001", "imagen-2.0"],
    "openai": ["dall-e-3", "dall-e-2"],
    "stability": ["stable-diffusion-3", "stable-diffusion-xl"],
    # Note: Mistral does not currently support image generation in this codebase.
    # We allow saving the selection so the UI can surface it, but generation will error.
    "mistral": ["mistral-not-supported"],
}

DEFAULTS = {
    "post_generation_provider": "openai",
    "post_generation_model": "gpt-4o",
    "image_generation_provider": "gemini",
    "image_generation_model": "imagen-3.0-generate-001",
}


router = APIRouter(prefix="/api/settings", tags=["settings"])


class ModelSettingsPatch(BaseModel):
    post_generation_provider: str | None = None
    post_generation_model: str | None = None
    image_generation_provider: str | None = None
    image_generation_model: str | None = None


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v.lower() if v else None


def _validate_combo(kind: str, provider: str, model: str) -> None:
    allowed = POST_ALLOWED if kind == "post" else IMAGE_ALLOWED
    if provider not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {kind} provider '{provider}'.",
        )
    if model not in allowed[provider]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {kind} model '{model}' for provider '{provider}'.",
        )


@router.get("/models")
def get_model_settings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = db.get(models.UserSettings, current_user.id)
    if not row:
        return {**DEFAULTS}
    return {
        "post_generation_provider": row.post_generation_provider,
        "post_generation_model": row.post_generation_model,
        "image_generation_provider": row.image_generation_provider,
        "image_generation_model": row.image_generation_model,
    }


@router.put("/models")
def update_model_settings(
    payload: ModelSettingsPatch,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    incoming_post_provider = _norm(payload.post_generation_provider)
    incoming_post_model = (payload.post_generation_model or "").strip() if payload.post_generation_model is not None else None
    incoming_img_provider = _norm(payload.image_generation_provider)
    incoming_img_model = (payload.image_generation_model or "").strip() if payload.image_generation_model is not None else None

    row = db.get(models.UserSettings, current_user.id)
    if not row:
        row = models.UserSettings(user_id=current_user.id, **DEFAULTS)
        db.add(row)
        db.flush()

    post_provider = incoming_post_provider or row.post_generation_provider
    post_model = incoming_post_model or row.post_generation_model
    img_provider = incoming_img_provider or row.image_generation_provider
    img_model = incoming_img_model or row.image_generation_model

    post_provider = post_provider.strip().lower()
    img_provider = img_provider.strip().lower()

    _validate_combo("post", post_provider, post_model)
    _validate_combo("image", img_provider, img_model)

    row.post_generation_provider = post_provider
    row.post_generation_model = post_model
    row.image_generation_provider = img_provider
    row.image_generation_model = img_model

    db.commit()
    return {
        "post_generation_provider": row.post_generation_provider,
        "post_generation_model": row.post_generation_model,
        "image_generation_provider": row.image_generation_provider,
        "image_generation_model": row.image_generation_model,
    }


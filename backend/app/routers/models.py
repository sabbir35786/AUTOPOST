from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.database import get_db
from app.providers.llm_providers import (
    AVAILABLE_LLM_MODELS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    TEXT_LLM_TASK_CATEGORIES,
    _resolve_gemini_model,
    generate_text,
    platform_key_configured,
)

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelPreferenceInput(BaseModel):
    provider_name: str
    model_name: str


class TestProviderRequest(BaseModel):
    provider_name: str
    model_name: str


def _normalize_provider(provider_name: str) -> str:
    provider = provider_name.strip().lower()
    if provider not in AVAILABLE_LLM_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{provider_name}'. Choose mistral or gemini.",
        )
    return provider


def _normalize_model(provider: str, model_name: str) -> str:
    model = model_name.strip()
    if provider == "gemini":
        model = _resolve_gemini_model(model)
    allowed = AVAILABLE_LLM_MODELS[provider]
    if model not in allowed:
        # Accept mapped Gemini ids even if not listed (e.g. env default).
        if provider == "gemini" and model.startswith("gemini-"):
            return model
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{model_name}' for {provider}.",
        )
    return model


def _upsert_text_settings(db: Session, user_id: int, provider: str, model: str) -> None:
    now = datetime.now(timezone.utc)
    for task_category in TEXT_LLM_TASK_CATEGORIES:
        existing = (
            db.query(models.ModelSettings)
            .filter(
                models.ModelSettings.user_id == user_id,
                models.ModelSettings.task_category == task_category,
            )
            .first()
        )
        if existing:
            existing.provider_name = provider
            existing.model_name = model
            existing.api_key_encrypted = None
            existing.updated_at = now
        else:
            db.add(
                models.ModelSettings(
                    user_id=user_id,
                    task_category=task_category,
                    provider_name=provider,
                    model_name=model,
                    api_key_encrypted=None,
                )
            )


def _read_preference(db: Session, user_id: int) -> dict:
    row = (
        db.query(models.ModelSettings)
        .filter(
            models.ModelSettings.user_id == user_id,
            models.ModelSettings.task_category == "post_generation",
        )
        .first()
    )
    if row:
        provider = (row.provider_name or DEFAULT_LLM_PROVIDER).lower()
        if provider in AVAILABLE_LLM_MODELS:
            models_for_provider = AVAILABLE_LLM_MODELS[provider]
            model = row.model_name if row.model_name in models_for_provider else models_for_provider[0]
            return {
                "provider_name": provider,
                "model_name": model,
                "configured": platform_key_configured(provider),
            }
    return {
        "provider_name": DEFAULT_LLM_PROVIDER,
        "model_name": DEFAULT_LLM_MODEL,
        "configured": platform_key_configured(DEFAULT_LLM_PROVIDER),
    }


@router.get("/options")
def list_model_options():
    return {
        "providers": [
            {
                "id": provider,
                "label": "Mistral" if provider == "mistral" else "Google Gemini",
                "models": [{"id": model, "label": model} for model in models],
                "configured": platform_key_configured(provider),
            }
            for provider, models in AVAILABLE_LLM_MODELS.items()
        ],
        "default": {
            "provider_name": DEFAULT_LLM_PROVIDER,
            "model_name": DEFAULT_LLM_MODEL,
        },
    }


@router.get("/preference")
def get_model_preference(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _read_preference(db, current_user.id)


@router.put("/preference")
def save_model_preference(
    payload: ModelPreferenceInput,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    provider = _normalize_provider(payload.provider_name)
    model = _normalize_model(provider, payload.model_name)
    if not platform_key_configured(provider):
        raise HTTPException(
            status_code=400,
            detail=f"The server does not have an API key configured for {provider}.",
        )
    _upsert_text_settings(db, current_user.id, provider, model)
    db.commit()
    return {"message": "AI model preference saved.", **_read_preference(db, current_user.id)}


@router.post("/test")
async def test_provider(req: TestProviderRequest):
    provider = _normalize_provider(req.provider_name)
    model = _normalize_model(provider, req.model_name)
    if not platform_key_configured(provider):
        return {
            "success": False,
            "error": f"No server API key is configured for {provider}.",
        }

    try:
        resp = generate_text(
            prompt="Say 'test' and nothing else.",
            system_prompt="You are a tester.",
            model_name=model,
            provider_name=provider,
            api_key="",
            temperature=0.0,
            max_tokens=10,
        )
        if resp:
            return {"success": True, "message": f"{provider.title()} is reachable with the server API key."}
        return {"success": False, "error": "Model returned an empty response."}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

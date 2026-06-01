from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from app import models
from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/models", tags=["models"])

class ModelSettingInput(BaseModel):
    task_category: str
    provider_name: str
    model_name: str
    api_key: Optional[str] = None  # Raw string to be encrypted

class TestProviderRequest(BaseModel):
    provider_name: str
    model_name: str
    api_key: Optional[str] = None
    task_category: Optional[str] = None

VALID_TASK_CATEGORIES = [
    "post_generation",
    "post_analysis",
    "image_generation",
    "style_analysis",
    "image_prompt_generation",
    "recommendations"
]

@router.post("/settings")
def save_model_settings(
    settings: list[ModelSettingInput],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    for setting in settings:
        if setting.task_category not in VALID_TASK_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid task category: {setting.task_category}")

        existing = db.query(models.ModelSettings).filter(
            models.ModelSettings.user_id == current_user.id,
            models.ModelSettings.task_category == setting.task_category
        ).first()

        encrypted_key = None
        if setting.api_key:
            from app.crypto import encrypt_token
            encrypted_key = encrypt_token(setting.api_key)
        elif not existing:
            continue

        if existing:
            existing.provider_name = setting.provider_name
            existing.model_name = setting.model_name
            if encrypted_key:
                existing.api_key_encrypted = encrypted_key
            existing.updated_at = datetime.now(timezone.utc)
        else:
            new_setting = models.ModelSettings(
                user_id=current_user.id,
                task_category=setting.task_category,
                provider_name=setting.provider_name,
                model_name=setting.model_name,
                api_key_encrypted=encrypted_key
            )
            db.add(new_setting)
            
    db.commit()
    return {"message": "Settings saved successfully"}

@router.get("/settings")
def get_model_settings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    settings = db.query(models.ModelSettings).filter(
        models.ModelSettings.user_id == current_user.id
    ).all()
    
    return [
        {
            "id": str(s.id),
            "task_category": s.task_category,
            "provider_name": s.provider_name,
            "model_name": s.model_name,
            "has_api_key": bool(s.api_key_encrypted),
            "updated_at": s.updated_at
        }
        for s in settings
    ]

@router.post("/test")
async def test_provider(
    req: TestProviderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    provider = req.provider_name.lower()
    api_key = req.api_key or ""
    if not api_key and req.task_category:
        saved = db.query(models.ModelSettings).filter(
            models.ModelSettings.user_id == current_user.id,
            models.ModelSettings.task_category == req.task_category,
        ).first()
        if saved and saved.api_key_encrypted:
            from app.crypto import decrypt_token
            api_key = decrypt_token(saved.api_key_encrypted)
    if not api_key:
        return {"success": False, "error": "No API key provided or saved for this task."}
    
    try:
        if provider in ["mistral", "openai", "anthropic", "gemini"]:
            from app.providers.llm_providers import generate_text
            resp = generate_text(
                prompt="Say 'test' and nothing else.",
                system_prompt="You are a tester.",
                model_name=req.model_name,
                provider_name=provider,
                api_key=api_key,
                temperature=0.0,
                max_tokens=10
            )
            if resp:
                return {"success": True, "message": "API key is valid for text generation."}
        elif provider in ["fal", "stability", "dall-e", "google"]:
            from app.providers.image_providers import _PROVIDER_MAP
            provider_cls = _PROVIDER_MAP.get(provider)
            if not provider_cls:
                raise ValueError("Provider not supported for testing")
            
            # Generating a very small image or fast model if possible to save costs, but we just run it.
            # We will generate a generic small image.
            inst = provider_cls()
            await import_asyncio()
            import asyncio
            
            async def _generate():
                return await asyncio.to_thread(
                    inst.generate,
                    prompt="A red circle",
                    negative_prompt="",
                    aspect_ratio="1:1",
                    model_name=req.model_name,
                    api_key=api_key
                )
            
            # Quick 15s timeout
            await asyncio.wait_for(_generate(), timeout=30)
            return {"success": True, "message": "API key is valid for image generation."}
        else:
            raise ValueError(f"Unknown provider: {req.provider_name}")
            
    except Exception as e:
        return {"success": False, "error": str(e)}

async def import_asyncio():
    pass

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field
import uuid
import httpx
import asyncio
import time
from datetime import datetime, timezone
import base64

from app import models
from app.database import get_db
from app.auth import get_current_user
from app.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from app.providers.image_providers import get_image_provider_for_user
from app.providers.llm_providers import generate_text_for_user

router = APIRouter(prefix="/api/images", tags=["images"])

# --- Schemas ---

class GenerateImageRequest(BaseModel):
    persona_id: Optional[int] = None
    custom_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    aspect_ratio: str = "1:1"
    max_wait_seconds: int = Field(120, ge=10, le=180)

class SavePromptRequest(BaseModel):
    persona_id: int
    subject_description: Optional[str] = None
    style_tags: list[str] = []
    mood_tags: list[str] = []
    color_palette: Optional[str] = None
    negative_prompt: Optional[str] = None
    aspect_ratio: str = "1:1"
    text_overlay_enabled: bool = False
    text_overlay_content: Optional[str] = None
    text_overlay_style: Optional[str] = None
    reference_image_descriptors: Optional[str] = None

class GenerateFromTextRequest(BaseModel):
    post_text: str

# --- Helper functions ---

def _upload_to_supabase(filename: str, file_bytes: bytes, content_type: str = "image/png") -> str:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("Supabase configuration missing.")

    bucket_name = "generated-images"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
    }
    storage_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket_name}/{filename}"
    
    # Upload via httpx synchronously since provider.generate might be sync, but wait, the job is async?
    # We will use httpx.post but we need an event loop. Actually, since this is called from a sync block or async block,
    # let's just make it async.
    pass

async def async_upload_to_supabase(filename: str, file_bytes: bytes, content_type: str = "image/png") -> str:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("Supabase configuration missing.")

    bucket_name = "generated-images"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
    }
    storage_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket_name}/{filename}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(storage_url, headers=headers, content=file_bytes)
        resp.raise_for_status()

    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket_name}/{filename}"

async def run_image_generation_job(job_id: str, db: Session):
    try:
        # Fetch job
        job_id_uuid = uuid.UUID(job_id)
        job = db.query(models.ImageGenerationJob).filter(models.ImageGenerationJob.id == job_id_uuid).first()
        if not job:
            print(f"Job {job_id} not found.")
            return

        job.status = "processing"
        db.commit()

        start_time = time.time()

        try:
            # Need to run synchronous generate() in a thread or wrap it to use wait_for
            provider_instance, model_name, api_key = get_image_provider_for_user(job.user_id, db)
            
            async def _generate():
                return await asyncio.to_thread(
                    provider_instance.generate,
                    prompt=job.assembled_prompt,
                    negative_prompt=job.negative_prompt,
                    aspect_ratio=job.aspect_ratio or "1:1",
                    model_name=model_name,
                    api_key=api_key,
                )

            image_bytes = await asyncio.wait_for(_generate(), timeout=job.max_wait_seconds)
            
            # Upload to Supabase
            filename = f"{job.user_id}/{job_id}.png"
            public_url = await async_upload_to_supabase(filename, image_bytes)

            # Create media library row
            media = models.MediaLibrary(
                user_id=job.user_id,
                persona_id=job.persona_id,
                image_url=public_url,
                storage_path=filename,
                generation_prompt=job.assembled_prompt,
                provider=job.provider,
                model_name=job.model_name,
            )
            db.add(media)
            db.flush()

            # Update job
            job.status = "completed"
            job.result_image_url = public_url
            job.supabase_storage_path = filename
            job.completed_at = datetime.now(timezone.utc)
            job.generation_seconds = int(time.time() - start_time)
            
            db.commit()

        except asyncio.TimeoutError:
            job.status = "timeout"
            job.generation_seconds = int(time.time() - start_time)
            db.commit()
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.generation_seconds = int(time.time() - start_time)
            db.commit()
            import traceback
            traceback.print_exc()

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()


# --- Endpoints ---

@router.post("/generate")
async def start_generation(
    req: GenerateImageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if req.custom_prompt:
        assembled_prompt = req.custom_prompt
    elif req.persona_id:
        settings = db.query(models.ImagePromptSettings).filter(
            models.ImagePromptSettings.persona_id == req.persona_id
        ).first()
        if not settings or not settings.assembled_prompt:
            raise HTTPException(status_code=400, detail="No prompt provided.")
        assembled_prompt = settings.assembled_prompt
    else:
        raise HTTPException(status_code=400, detail="No prompt provided.")

    provider_instance, model_name, _ = get_image_provider_for_user(current_user.id, db)
    provider_name = provider_instance.__class__.__name__.replace('Provider', '').lower()

    job = models.ImageGenerationJob(
        user_id=current_user.id,
        persona_id=req.persona_id,
        status="pending",
        provider=provider_name,
        model_name=model_name,
        assembled_prompt=assembled_prompt,
        negative_prompt=req.negative_prompt,
        aspect_ratio=req.aspect_ratio,
        max_wait_seconds=req.max_wait_seconds,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Need a fresh session for the background task
    from app.database import SessionLocal
    bg_db = SessionLocal()
    background_tasks.add_task(run_image_generation_job, str(job.id), bg_db)

    return {
        "job_id": str(job.id),
        "status": "pending",
        "provider": provider_name,
        "model": model_name,
        "estimated_seconds": 8,
        "message": "Image generation started",
    }

@router.get("/job/{job_id}")
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job = db.query(models.ImageGenerationJob).filter(
        models.ImageGenerationJob.id == job_uuid,
        models.ImageGenerationJob.user_id == current_user.id
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ["pending", "processing"]:
        elapsed = 0
        if job.started_at:
            elapsed = int((datetime.now(timezone.utc) - job.started_at).total_seconds())
        return {
            "job_id": str(job.id),
            "status": "processing",
            "message": "AI is generating your image...",
            "elapsed_seconds": elapsed,
        }
    elif job.status == "completed":
        # Find media library ID
        media = db.query(models.MediaLibrary).filter(
            models.MediaLibrary.image_url == job.result_image_url
        ).first()
        media_id = str(media.id) if media else None
        
        return {
            "job_id": str(job.id),
            "status": "completed",
            "image_url": job.result_image_url,
            "media_library_id": media_id,
            "generation_seconds": job.generation_seconds,
            "provider": job.provider,
            "model": job.model_name,
        }
    elif job.status == "failed":
        return {
            "job_id": str(job.id),
            "status": "failed",
            "error_message": job.error_message,
            "can_retry": True,
        }
    elif job.status == "timeout":
        return {
            "job_id": str(job.id),
            "status": "timeout",
            "message": "Generation exceeded maximum wait time. The image may still complete — check your media library in a few minutes."
        }
    return {"job_id": str(job.id), "status": job.status}

@router.post("/retry/{job_id}")
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    old_job = db.query(models.ImageGenerationJob).filter(
        models.ImageGenerationJob.id == job_uuid,
        models.ImageGenerationJob.user_id == current_user.id
    ).first()

    if not old_job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if old_job.status not in ["failed", "timeout"]:
        raise HTTPException(status_code=400, detail="Only failed or timeout jobs can be retried.")

    new_job = models.ImageGenerationJob(
        user_id=current_user.id,
        persona_id=old_job.persona_id,
        status="pending",
        provider=old_job.provider,
        model_name=old_job.model_name,
        assembled_prompt=old_job.assembled_prompt,
        negative_prompt=old_job.negative_prompt,
        aspect_ratio=old_job.aspect_ratio,
        max_wait_seconds=old_job.max_wait_seconds,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    from app.database import SessionLocal
    bg_db = SessionLocal()
    background_tasks.add_task(run_image_generation_job, str(new_job.id), bg_db)

    return {
        "job_id": str(new_job.id),
        "status": "pending",
        "provider": new_job.provider,
        "model": new_job.model_name,
        "estimated_seconds": 8,
        "message": "Retry generation started",
    }

@router.get("/library")
def get_library(
    page: int = Query(1, ge=1),
    is_used: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    per_page = 20
    query = db.query(models.MediaLibrary).filter(models.MediaLibrary.user_id == current_user.id)
    if is_used is not None:
        query = query.filter(models.MediaLibrary.is_used == is_used)
        
    total = query.count()
    items = query.order_by(models.MediaLibrary.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    
    return {
        "items": [
            {
                "id": str(item.id),
                "image_url": item.image_url,
                "generation_prompt": item.generation_prompt,
                "provider": item.provider,
                "model_name": item.model_name,
                "is_used": item.is_used,
                "created_at": item.created_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
    }

@router.delete("/library/{media_id}")
async def delete_library_item(
    media_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        media_uuid = uuid.UUID(media_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid media ID")

    item = db.query(models.MediaLibrary).filter(
        models.MediaLibrary.id == media_uuid,
        models.MediaLibrary.user_id == current_user.id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.is_used:
        raise HTTPException(status_code=400, detail="Cannot delete an image that has been published.")

    if SUPABASE_URL and SUPABASE_SERVICE_KEY and item.storage_path:
        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }
        storage_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/generated-images/{item.storage_path}"
        async with httpx.AsyncClient() as client:
            await client.delete(storage_url, headers=headers)

    db.delete(item)
    db.commit()
    return {"message": "Image deleted successfully"}


# --- Prompt Studio ---

@router.post("/prompt/save")
def save_prompt(
    req: SavePromptRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Assemble prompt
    parts = []
    if req.subject_description:
        parts.append(req.subject_description.strip())
    if req.style_tags:
        parts.append(", ".join(req.style_tags))
    if req.mood_tags:
        parts.append(", ".join(req.mood_tags))
    if req.color_palette:
        parts.append(req.color_palette.strip())
    if req.negative_prompt:
        parts.append(f"no {req.negative_prompt.strip()}")
    if req.aspect_ratio:
        parts.append(f"aspect ratio {req.aspect_ratio}")
    if req.text_overlay_enabled and req.text_overlay_content:
        style = f" in {req.text_overlay_style} style" if req.text_overlay_style else ""
        parts.append(f'Text overlay: "{req.text_overlay_content}"{style}')
    if req.reference_image_descriptors:
        parts.append(req.reference_image_descriptors)
    
    parts.append("high quality, sharp focus, detailed, 4k")
    
    assembled_prompt = ", ".join(parts)

    settings = db.query(models.ImagePromptSettings).filter(
        models.ImagePromptSettings.persona_id == req.persona_id,
        models.ImagePromptSettings.user_id == current_user.id
    ).first()

    if not settings:
        settings = models.ImagePromptSettings(
            persona_id=req.persona_id,
            user_id=current_user.id
        )
        db.add(settings)

    settings.subject_description = req.subject_description
    settings.style_tags = req.style_tags
    settings.mood_tags = req.mood_tags
    settings.color_palette = req.color_palette
    settings.negative_prompt = req.negative_prompt
    settings.aspect_ratio = req.aspect_ratio
    settings.text_overlay_enabled = req.text_overlay_enabled
    settings.text_overlay_content = req.text_overlay_content
    settings.text_overlay_style = req.text_overlay_style
    settings.reference_image_descriptors = req.reference_image_descriptors
    settings.assembled_prompt = assembled_prompt
    settings.updated_at = datetime.now(timezone.utc)

    db.commit()

    return {"assembled_prompt": assembled_prompt}

@router.get("/prompt/{persona_id}")
def get_prompt_settings(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    settings = db.query(models.ImagePromptSettings).filter(
        models.ImagePromptSettings.persona_id == persona_id,
        models.ImagePromptSettings.user_id == current_user.id
    ).first()

    if not settings:
        return {}

    return {
        "subject_description": settings.subject_description,
        "style_tags": settings.style_tags,
        "mood_tags": settings.mood_tags,
        "color_palette": settings.color_palette,
        "negative_prompt": settings.negative_prompt,
        "aspect_ratio": settings.aspect_ratio,
        "text_overlay_enabled": settings.text_overlay_enabled,
        "text_overlay_content": settings.text_overlay_content,
        "text_overlay_style": settings.text_overlay_style,
        "reference_image_descriptors": settings.reference_image_descriptors,
        "assembled_prompt": settings.assembled_prompt,
    }

@router.post("/prompt/analyze-reference")
async def analyze_reference(
    persona_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if len(files) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 images allowed.")
        
    all_descriptors = []
    system_prompt = "You are an expert visual analyst."
    user_prompt = "Analyze this image and describe its visual style in specific technical terms for an image generation AI prompt. Include: lighting style, color palette, composition, texture, mood, technique. Return only a comma-separated list of descriptive style terms. Maximum 20 terms. No explanation."
    
    # Check if Gemini/OpenAI vision models are available directly.
    # To keep it provider agnostic but robust, we'll implement a custom vision parser or use litellm style
    # if our router doesn't support images yet. Let's build a quick direct call for gemini-1.5-pro or gpt-4o.
    # We will use our generate_text_for_user with a special image kwargs.
    
    # Wait, llm_providers doesn't support images in the prompt yet. 
    # I will modify llm_providers.py to optionally accept base64 images shortly.
    # Let's assume generate_text_for_user will be updated to accept `images=...`
    
    base64_images = []
    for file in files:
        contents = await file.read()
        b64 = base64.b64encode(contents).decode('utf-8')
        mimetype = file.content_type or "image/jpeg"
        base64_images.append(f"data:{mimetype};base64,{b64}")

    try:
        from app.providers.llm_providers import generate_text_for_user
        response_text = generate_text_for_user(
            user_id=current_user.id,
            task_category="style_analysis",
            prompt=user_prompt,
            system_prompt=system_prompt,
            images=base64_images,
            db=db,
            temperature=0.3,
            max_tokens=100,
        )
    except TypeError:
        # Fallback if I haven't updated llm_providers yet or if it doesn't support it
        raise HTTPException(status_code=501, detail="Vision LLM not supported yet. Please update llm_providers.py")
        
    if response_text:
        descriptors = [d.strip() for d in response_text.split(',') if d.strip()]
        all_descriptors.extend(descriptors)

    # Deduplicate and limit
    unique_descriptors = list(dict.fromkeys(all_descriptors))
    final_descriptor_string = ", ".join(unique_descriptors)
    
    settings = db.query(models.ImagePromptSettings).filter(
        models.ImagePromptSettings.persona_id == persona_id,
        models.ImagePromptSettings.user_id == current_user.id
    ).first()
    
    if not settings:
        settings = models.ImagePromptSettings(persona_id=persona_id, user_id=current_user.id)
        db.add(settings)
        
    settings.reference_image_descriptors = final_descriptor_string
    db.commit()

    return {"descriptors": final_descriptor_string}

@router.post("/prompt/generate-from-text")
def generate_from_text(
    req: GenerateFromTextRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    system_prompt = "You are an expert at writing prompts for AI image generation. Given a social media post text, write a detailed image generation prompt that would create the perfect visual to accompany that post. The image should enhance the post's message without containing any text. Return only the image generation prompt, nothing else, maximum 150 words."
    
    response_text = generate_text_for_user(
        user_id=current_user.id,
        task_category="image_prompt_generation",
        prompt=req.post_text,
        system_prompt=system_prompt,
        db=db,
        temperature=0.7,
        max_tokens=200,
    )

    if not response_text:
        raise HTTPException(status_code=500, detail="Failed to generate image prompt")
        
    return {"generated_prompt": response_text.strip()}

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

import json
import io
from PIL import Image, ImageDraw, ImageFont

from app import models
from app.database import get_db
from app.auth import get_current_user
from app.config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from app.providers.image_providers import get_image_provider_for_user
from app.providers.llm_providers import generate_text_for_user, generate_text


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


# --- Template-Based Multi-Layer Image System ---

class GenerateLayeredRequest(BaseModel):
    template_id: str
    topic: str
    post_text: Optional[str] = None


def get_pillow_font(size: int):
    font_names = [
        "arial.ttf",
        "LiberationSans-Regular.ttf",
        "DejaVuSans.ttf",
        "Roboto-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    ]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except IOError:
            continue
    return ImageFont.load_default()


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    templates = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.user_id == current_user.id
    ).all()
    return templates


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == template_id,
        models.ImageTemplate.user_id == current_user.id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"message": "Template deleted successfully"}


@router.post("/analyze-template")
async def analyze_template(
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    file_bytes = await file.read()
    
    # 1. Upload reference image to Supabase
    filename = f"templates/{uuid.uuid4()}.png"
    try:
        public_url = await async_upload_to_supabase(filename, file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload reference image to Supabase: {str(e)}")

    # 2. Base64 encode for Vision LLM
    mimetype = file.content_type or "image/png"
    b64 = base64.b64encode(file_bytes).decode('utf-8')
    base64_image = f"data:{mimetype};base64,{b64}"

    # 3. Request analysis from Vision LLM
    system_prompt = "You are an expert visual layout analyzer."
    prompt = """Analyze the layout of the reference image and describe its structure in a strict JSON format with the following keys:
- 'background': { 'type': 'photographic' | 'solid' | 'gradient' | 'abstract', 'description': 'detailed description of the background style (e.g. vibrant blue mesh gradient, corporate white desk layout)' }
- 'text_boxes': a list of objects, each containing:
  - 'purpose': e.g., 'Main Headline', 'Call to Action', 'Subheading'
  - 'x_pct': relative X position of the text box start (0 to 100)
  - 'y_pct': relative Y position of the text box start (0 to 100)
  - 'font_size_pct': relative font size (0 to 100) where 5 is medium, 8 is large, 3 is small
  - 'color_hex': hex code for text color (e.g., '#FFFFFF')
  - 'alignment': 'left' | 'center' | 'right'
- 'logo_position': { 'x_pct': relative X, 'y_pct': relative Y, 'width_pct': relative width, 'height_pct': relative height } (or null if no logo)

Important: Return ONLY a raw JSON string. Do not wrap it in markdown code blocks like ```json. Do not include any explanations.
"""
    try:
        # Use gemini directly (we set model_name to gemini-2.0-flash by default if using gemini provider)
        # We can pass images directly to generate_text
        response_text = generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.2,
            max_tokens=1000,
            images=[base64_image]
        )
    except Exception as e:
        # Fallback to OpenAI if Gemini fails or is not configured
        try:
            response_text = generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                model_name="gpt-4o",
                provider_name="openai",
                api_key="",
                temperature=0.2,
                max_tokens=1000,
                images=[base64_image]
            )
        except Exception as oe:
            raise HTTPException(status_code=500, detail=f"LLM Vision analysis failed: {str(e)} / {str(oe)}")

    if not response_text:
        raise HTTPException(status_code=500, detail="Vision LLM returned empty response")

    # Clean code blocks
    raw_response = response_text.strip()
    if raw_response.startswith("```"):
        lines = raw_response.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_response = "\n".join(lines).strip()

    try:
        layers_json = json.loads(raw_response)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse JSON from Vision LLM: {str(e)}. Raw content: {response_text}"
        )

    # 4. Save template
    template = models.ImageTemplate(
        user_id=current_user.id,
        name=name,
        reference_image_url=public_url,
        layers_json=layers_json
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return template


@router.post("/analyze-template-reference")
async def analyze_template_reference(
    persona_id: int = Form(...),
    reference_image: UploadFile = File(...),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Analyze a reference image for template-based image generation using Vision LLM."""
    # Verify persona belongs to user
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == persona_id,
        models.AIPersona.user_id == current_user.id
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # 1. Upload reference image to Supabase
    ref_bytes = await reference_image.read()
    ref_filename = f"templates/ref_{uuid.uuid4()}.png"
    try:
        ref_public_url = await async_upload_to_supabase(ref_filename, ref_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload reference image: {str(e)}")

    # 2. Upload logo if provided
    logo_public_url = None
    if logo:
        logo_bytes = await logo.read()
        logo_filename = f"templates/logo_{uuid.uuid4()}.png"
        try:
            logo_public_url = await async_upload_to_supabase(logo_filename, logo_bytes)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload logo: {str(e)}")

    # 3. Base64 encode reference image for Vision LLM
    mimetype = reference_image.content_type or "image/png"
    b64 = base64.b64encode(ref_bytes).decode('utf-8')
    base64_image = f"data:{mimetype};base64,{b64}"

    # 4. Request analysis from Vision LLM
    system_prompt = "You are an expert visual layout analyzer."
    prompt = """Analyze the layout of the reference image and describe its structure in a strict JSON format with the following keys:
- 'background': { 'type': 'photographic' | 'solid' | 'gradient' | 'abstract', 'description': 'detailed description of the background style (e.g. vibrant blue mesh gradient, corporate white desk layout)' }
- 'text_boxes': a list of objects, each containing:
  - 'purpose': e.g., 'Main Headline', 'Call to Action', 'Subheading'
  - 'x_pct': relative X position of the text box start (0 to 100)
  - 'y_pct': relative Y position of the text box start (0 to 100)
  - 'font_size_pct': relative font size (0 to 100) where 5 is medium, 8 is large, 3 is small
  - 'color_hex': hex code for text color (e.g., '#FFFFFF')
  - 'alignment': 'left' | 'center' | 'right'
- 'logo_position': { 'x_pct': relative X, 'y_pct': relative Y, 'width_pct': relative width, 'height_pct': relative height } (or null if no logo)

Important: Return ONLY a raw JSON string. Do not wrap it in markdown code blocks like ```json. Do not include any explanations.
"""

    try:
        # Try Gemini first
        response_text = generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            model_name="gemini-2.0-flash",
            provider_name="gemini",
            api_key="",
            temperature=0.2,
            max_tokens=1000,
            images=[base64_image]
        )
    except Exception as e:
        # Fallback to OpenAI if Gemini fails
        try:
            response_text = generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                model_name="gpt-4o",
                provider_name="openai",
                api_key="",
                temperature=0.2,
                max_tokens=1000,
                images=[base64_image]
            )
        except Exception as oe:
            raise HTTPException(status_code=500, detail=f"Vision LLM analysis failed: {str(e)} / {str(oe)}")

    if not response_text:
        raise HTTPException(status_code=500, detail="Vision LLM returned empty response")

    # Clean code blocks
    raw_response = response_text.strip()
    if raw_response.startswith("```"):
        lines = raw_response.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_response = "\n".join(lines).strip()

    try:
        layers_json = json.loads(raw_response)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse JSON from Vision LLM: {str(e)}. Raw content: {response_text}"
        )

    # 5. Save to image_prompt_settings
    settings = db.query(models.ImagePromptSettings).filter(
        models.ImagePromptSettings.persona_id == persona_id
    ).first()

    if not settings:
        settings = models.ImagePromptSettings(
            persona_id=persona_id,
            user_id=current_user.id
        )
        db.add(settings)

    settings.reference_image_url = ref_public_url
    settings.template_layers_json = layers_json
    settings.template_analyzed_at = datetime.now(timezone.utc)
    if logo_public_url:
        settings.template_logo_url = logo_public_url

    # Also update persona with logo if provided
    if logo_public_url:
        persona.template_logo_url = logo_public_url

    db.commit()
    db.refresh(settings)

    return {
        "success": True,
        "reference_image_url": ref_public_url,
        "logo_url": logo_public_url,
        "layers_json": layers_json,
        "analyzed_at": settings.template_analyzed_at
    }


class TestTemplateRequest(BaseModel):
    persona_id: int
    topic_hint: str | None = None
    post_text: str | None = None


class PublishTemplateRequest(BaseModel):
    persona_id: int
    post_text: str
    include_image: bool = True


async def generate_template_layered_image(
    persona_id: int,
    post_text: str,
    topic_hint: str | None,
    db: Session,
    user_id: int,
) -> tuple[str, str]:
    """
    Generate a layered image based on persona's template settings.
    Returns (media_library_id, image_url).
    """
    # Fetch persona and template settings
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    settings = db.query(models.ImagePromptSettings).filter(
        models.ImagePromptSettings.persona_id == persona_id
    ).first()

    if not settings or not settings.template_layers_json:
        raise HTTPException(status_code=400, detail="Template not analyzed. Please analyze a reference image first.")

    layers_json = settings.template_layers_json

    # 1. Generate background prompt using LLM
    bg_style = layers_json.get("background", {}).get("description", "simple abstract background")
    system_prompt_bg = "You are an expert prompt engineer for AI image generators."
    prompt_for_bg = f"Write a high-quality prompt for generating a clean background image based on the topic: '{topic_hint or post_text}'. The background style should be: {bg_style}. IMPORTANT: This background image must contain absolutely no text, letters, logos, writing, watermarks, or signatures of any kind. It should only contain background textures, photographic elements, or abstract designs."

    bg_prompt = generate_text_for_user(
        user_id=user_id,
        task_category="image_prompt_generation",
        prompt=prompt_for_bg,
        system_prompt=system_prompt_bg,
        db=db,
        temperature=0.7,
        max_tokens=200,
    )
    if not bg_prompt:
        bg_prompt = f"abstract background related to {topic_hint or post_text}, style: {bg_style}"

    # Explicitly enforce negative prompts
    bg_prompt = f"{bg_prompt}, empty background, no people writing, no text, copy-space, clean"

    # 2. Generate background image
    provider_instance, model_name, api_key = get_image_provider_for_user(user_id, db)

    try:
        def _generate():
            return provider_instance.generate(
                prompt=bg_prompt,
                negative_prompt="text, letters, words, logo, writing, watermark, signature, symbols",
                aspect_ratio="1:1",
                model_name=model_name,
                api_key=api_key
            )
        bg_bytes = await asyncio.to_thread(_generate())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate background image: {str(e)}")

    # 3. Generate overlay text copy
    text_boxes = layers_json.get("text_boxes", [])
    copy_map = {}
    if text_boxes:
        boxes_desc = "\n".join([f"- Purpose: {b.get('purpose', 'Headline')}" for b in text_boxes])
        prompt_for_copy = f"""We are generating text copy for a social media post graphic on the topic: '{topic_hint or post_text}'.
Context/Post text: {post_text}
We need to fill the following text boxes in our template:
{boxes_desc}

For each text box, write a very short, catchy copy suitable for the purpose.
Return a raw JSON object mapping each box's exact Purpose to the written text string. Do not wrap in markdown block, just return raw JSON."""

        copy_resp = generate_text_for_user(
            user_id=user_id,
            task_category="post_generation",
            prompt=prompt_for_copy,
            system_prompt="You are a social media copywriter. Respond ONLY with a raw JSON mapping.",
            db=db,
            temperature=0.6,
            max_tokens=400,
        )
        if copy_resp:
            raw_cr = copy_resp.strip()
            if raw_cr.startswith("```"):
                lines = raw_cr.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_cr = "\n".join(lines).strip()
            try:
                copy_map = json.loads(raw_cr)
            except Exception:
                pass

    # 4. Fetch logo
    logo_img = None
    logo_pos = layers_json.get("logo_position")
    if logo_pos:
        # Try persona-specific logo first, then global logo
        logo_url = persona.template_logo_url or settings.template_logo_url
        user = db.get(models.User, user_id)
        if not logo_url and user:
            logo_url = user.brand_logo_url

        if logo_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(logo_url)
                    if resp.status_code == 200:
                        logo_img = Image.open(io.BytesIO(resp.content))
            except Exception as e:
                print(f"Error fetching logo URL: {e}")

        # Fallback to local logo.png
        if not logo_img:
            try:
                logo_img = Image.open("logo.png")
            except Exception as e:
                print(f"Error loading fallback logo.png: {e}")

    # 5. Compose with Pillow
    try:
        bg_image = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
        W, H = bg_image.size

        # Overlay Logo
        if logo_img and logo_pos:
            logo_img = logo_img.convert("RGBA")
            target_w = int(W * (float(logo_pos.get("width_pct", 15)) / 100.0))
            if target_w > 0:
                aspect = logo_img.height / logo_img.width
                target_h = int(target_w * aspect)
                logo_resized = logo_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

                logo_x = int(W * (float(logo_pos.get("x_pct", 5)) / 100.0))
                logo_y = int(H * (float(logo_pos.get("y_pct", 5)) / 100.0))

                logo_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                logo_layer.paste(logo_resized, (logo_x, logo_y))
                bg_image = Image.alpha_composite(bg_image, logo_layer)

        # Draw Text Boxes
        draw = ImageDraw.Draw(bg_image)
        for box in text_boxes:
            purpose = box.get("purpose", "")
            text_str = copy_map.get(purpose) or copy_map.get(purpose.lower()) or copy_map.get(purpose.replace(" ", ""))
            if not text_str:
                text_str = topic_hint if "headline" in purpose.lower() else "Learn More"

            x_pct = float(box.get("x_pct", 50))
            y_pct = float(box.get("y_pct", 50))
            font_size_pct = float(box.get("font_size_pct", 5))
            color_hex = box.get("color_hex", "#FFFFFF")
            alignment = box.get("alignment", "center")

            fs = max(12, int(H * (font_size_pct / 100.0)))
            font = get_pillow_font(fs)

            if not color_hex.startswith("#"):
                color_hex = f"#{color_hex}"

            try:
                bbox = draw.textbbox((0, 0), text_str, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except AttributeError:
                tw, th = draw.textsize(text_str, font=font)

            tx = int(W * (x_pct / 100.0))
            ty = int(H * (y_pct / 100.0))

            if alignment == "center":
                tx -= int(tw / 2)
            elif alignment == "right":
                tx -= tw

            draw.text((tx + 1, ty + 1), text_str, font=font, fill="#000000")
            draw.text((tx, ty), text_str, font=font, fill=color_hex)

        final_image = bg_image.convert("RGB")
        out_io = io.BytesIO()
        final_image.save(out_io, format="PNG")
        final_bytes = out_io.getvalue()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pillow Compositor failed: {str(e)}")

    # 6. Upload to Supabase
    job_id = str(uuid.uuid4())
    filename = f"{user_id}/template_{job_id}.png"
    try:
        public_url = await async_upload_to_supabase(filename, final_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload finished image: {str(e)}")

    # 7. Create Media Library Entry
    media = models.MediaLibrary(
        user_id=user_id,
        persona_id=persona_id,
        image_url=public_url,
        storage_path=filename,
        generation_prompt=bg_prompt,
        provider="compositor",
        model_name="layered"
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return str(media.id), public_url


@router.post("/test-template-generation")
async def test_template_generation(
    req: TestTemplateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Test template-based image generation without publishing."""
    # Verify persona belongs to user
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == req.persona_id,
        models.AIPersona.user_id == current_user.id
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Generate post text if not provided
    post_text = req.post_text
    if not post_text:
        from app.posts import generate_persona_post_with_user_model
        post_text = generate_persona_post_with_user_model(
            db=db,
            settings=persona,
            topic_hint=req.topic_hint
        )

    # Check if template is enabled and analyzed
    if not persona.template_image_generation_enabled:
        return {
            "success": True,
            "template_enabled": False,
            "post_text": post_text,
            "message": "Template generation is not enabled for this persona"
        }

    settings = db.query(models.ImagePromptSettings).filter(
        models.ImagePromptSettings.persona_id == req.persona_id
    ).first()

    if not settings or not settings.template_layers_json:
        return {
            "success": True,
            "template_enabled": True,
            "template_analyzed": False,
            "post_text": post_text,
            "message": "Template not analyzed. Please analyze a reference image first."
        }

    # Generate layered image
    try:
        media_id, image_url = await generate_template_layered_image(
            persona_id=req.persona_id,
            post_text=post_text,
            topic_hint=req.topic_hint,
            db=db,
            user_id=current_user.id
        )
        return {
            "success": True,
            "template_enabled": True,
            "template_analyzed": True,
            "post_text": post_text,
            "media_library_id": media_id,
            "image_url": image_url
        }
    except Exception as e:
        return {
            "success": False,
            "post_text": post_text,
            "error": str(e)
        }


@router.post("/publish-template-post")
async def publish_template_post(
    req: PublishTemplateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Publish a post with optional template-based image."""
    # Verify persona belongs to user
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == req.persona_id,
        models.AIPersona.user_id == current_user.id
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Get Facebook connection
    connection = db.query(models.FacebookConnection).filter(
        models.FacebookConnection.id == persona.page_connection_id
    ).first()
    if not connection:
        raise HTTPException(status_code=400, detail="Facebook connection not found")

    # Generate image if requested and template enabled
    media_library_id = None
    if req.include_image and persona.template_image_generation_enabled:
        settings = db.query(models.ImagePromptSettings).filter(
            models.ImagePromptSettings.persona_id == req.persona_id
        ).first()

        if settings and settings.template_layers_json:
            try:
                media_library_id, _ = await generate_template_layered_image(
                    persona_id=req.persona_id,
                    post_text=req.post_text,
                    topic_hint=None,
                    db=db,
                    user_id=current_user.id
                )
            except Exception as e:
                # Apply fallback policy
                if persona.image_fallback_policy == "skip_post":
                    raise HTTPException(status_code=400, detail=f"Image generation failed and fallback policy is skip_post: {str(e)}")
                elif persona.image_fallback_policy == "use_library":
                    any_unused = db.query(models.MediaLibrary).filter(
                        models.MediaLibrary.user_id == current_user.id,
                        models.MediaLibrary.is_used == False
                    ).order_by(models.MediaLibrary.created_at.asc()).first()
                    if any_unused:
                        media_library_id = str(any_unused.id)
                # text_only: continue without image

    # Create PostLog
    post_log = models.PostLog(
        user_id=current_user.id,
        facebook_connection_id=connection.id,
        ai_persona_id=persona.id,
        content=req.post_text,
        status="draft",
        media_library_id=media_library_id,
        ai_generated=True,
        auto_generated=False
    )
    db.add(post_log)
    db.flush()

    # Publish to Facebook
    from app.posts import publish_post_to_facebook
    success = await publish_post_to_facebook(db, post_log, connection)

    if success:
        return {
            "success": True,
            "post_log_id": post_log.id,
            "facebook_post_id": post_log.facebook_post_id,
            "media_library_id": media_library_id
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to publish to Facebook")


@router.post("/generate-layered")
async def generate_layered_image(
    req: GenerateLayeredRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # 1. Fetch template
    template = db.query(models.ImageTemplate).filter(
        models.ImageTemplate.id == req.template_id,
        models.ImageTemplate.user_id == current_user.id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # 2. Layer 1: Background Prompt & Image Generation
    bg_style = template.layers_json.get("background", {}).get("description", "simple abstract background")
    system_prompt = "You are an expert prompt engineer for AI image generators."
    prompt_for_bg = f"Write a high-quality prompt for generating a clean background image based on the topic: '{req.topic}'. The background style should be: {bg_style}. IMPORTANT: This background image must contain absolutely no text, letters, logos, writing, watermarks, or signatures of any kind. It should only contain background textures, photographic elements, or abstract designs."
    
    bg_prompt = generate_text_for_user(
        user_id=current_user.id,
        task_category="image_prompt_generation",
        prompt=prompt_for_bg,
        system_prompt=system_prompt,
        db=db,
        temperature=0.7,
        max_tokens=200,
    )
    if not bg_prompt:
        bg_prompt = f"abstract background related to {req.topic}, style: {bg_style}"

    # Explicitly enforce negative prompts or append structured instructions
    bg_prompt = f"{bg_prompt}, empty background, no people writing, no text, copy-space, clean"

    provider_instance, model_name, api_key = get_image_provider_for_user(current_user.id, db)
    
    try:
        # Generate background image
        def _generate():
            return provider_instance.generate(
                prompt=bg_prompt,
                negative_prompt="text, letters, words, logo, writing, watermark, signature, symbols",
                aspect_ratio="1:1",
                model_name=model_name,
                api_key=api_key
            )
        bg_bytes = await asyncio.to_thread(_generate())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate background image: {str(e)}")

    # 3. Layer 2: Text Copy Generation
    text_boxes = template.layers_json.get("text_boxes", [])
    copy_map = {}
    if text_boxes:
        boxes_desc = "\n".join([f"- Purpose: {b.get('purpose', 'Headline')}" for b in text_boxes])
        prompt_for_copy = f"""We are generating text copy for a social media post graphic on the topic: '{req.topic}'.
Context/Post text: {req.post_text or ''}
We need to fill the following text boxes in our template:
{boxes_desc}

For each text box, write a very short, catchy copy suitable for the purpose.
Return a raw JSON object mapping each box's exact Purpose to the written text string. Do not wrap in markdown block, just return raw JSON."""
        
        copy_resp = generate_text_for_user(
            user_id=current_user.id,
            task_category="post_generation",
            prompt=prompt_for_copy,
            system_prompt="You are a social media copywriter. Respond ONLY with a raw JSON mapping.",
            db=db,
            temperature=0.6,
            max_tokens=400,
        )
        if copy_resp:
            raw_cr = copy_resp.strip()
            if raw_cr.startswith("```"):
                lines = raw_cr.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_cr = "\n".join(lines).strip()
            try:
                copy_map = json.loads(raw_cr)
            except Exception:
                pass

    # 4. Layer 3: Logo Asset
    logo_img = None
    logo_pos = template.layers_json.get("logo_position")
    if logo_pos and (current_user.brand_logo_url or True):
        # Try user's uploaded brand logo first
        logo_url = current_user.brand_logo_url
        if logo_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(logo_url)
                    if resp.status_code == 200:
                        logo_img = Image.open(io.BytesIO(resp.content))
            except Exception as e:
                print(f"Error fetching user logo URL: {e}")
        
        # Fallback to local logo.png if user logo fails or is empty
        if not logo_img:
            try:
                logo_img = Image.open("logo.png")
            except Exception as e:
                print(f"Error loading fallback logo.png: {e}")

    # 5. Compositor (Pillow Assembly)
    try:
        bg_image = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
        W, H = bg_image.size
        
        # Overlay Logo if present and logo coordinates exist
        if logo_img and logo_pos:
            logo_img = logo_img.convert("RGBA")
            target_w = int(W * (float(logo_pos.get("width_pct", 15)) / 100.0))
            if target_w > 0:
                aspect = logo_img.height / logo_img.width
                target_h = int(target_w * aspect)
                logo_resized = logo_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                
                logo_x = int(W * (float(logo_pos.get("x_pct", 5)) / 100.0))
                logo_y = int(H * (float(logo_pos.get("y_pct", 5)) / 100.0))
                
                # Create composition layer
                logo_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                logo_layer.paste(logo_resized, (logo_x, logo_y))
                bg_image = Image.alpha_composite(bg_image, logo_layer)

        # Draw Text Boxes
        draw = ImageDraw.Draw(bg_image)
        for box in text_boxes:
            purpose = box.get("purpose", "")
            text_str = copy_map.get(purpose) or copy_map.get(purpose.lower()) or copy_map.get(purpose.replace(" ", ""))
            if not text_str:
                # Direct fallback text if LLM failed
                text_str = req.topic if "headline" in purpose.lower() else "Learn More"

            x_pct = float(box.get("x_pct", 50))
            y_pct = float(box.get("y_pct", 50))
            font_size_pct = float(box.get("font_size_pct", 5))
            color_hex = box.get("color_hex", "#FFFFFF")
            alignment = box.get("alignment", "center")

            # Determine font size relative to image height
            fs = max(12, int(H * (font_size_pct / 100.0)))
            font = get_pillow_font(fs)

            # Clean color format
            if not color_hex.startswith("#"):
                color_hex = f"#{color_hex}"

            # Calculate text size for alignment adjustment
            try:
                bbox = draw.textbbox((0, 0), text_str, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except AttributeError:
                tw, th = draw.textsize(text_str, font=font)

            tx = int(W * (x_pct / 100.0))
            ty = int(H * (y_pct / 100.0))

            if alignment == "center":
                tx -= int(tw / 2)
            elif alignment == "right":
                tx -= tw

            # Draw text shadow / stroke for legibility
            draw.text((tx + 1, ty + 1), text_str, font=font, fill="#000000")
            draw.text((tx, ty), text_str, font=font, fill=color_hex)

        # Convert back to RGB and export as bytes
        final_image = bg_image.convert("RGB")
        out_io = io.BytesIO()
        final_image.save(out_io, format="PNG")
        final_bytes = out_io.getvalue()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pillow Compositor failed: {str(e)}")

    # 6. Upload & Save
    job_id = str(uuid.uuid4())
    filename = f"{current_user.id}/template_{job_id}.png"
    try:
        public_url = await async_upload_to_supabase(filename, final_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload finished image: {str(e)}")

    # Create Media Library Entry
    media = models.MediaLibrary(
        user_id=current_user.id,
        image_url=public_url,
        storage_path=filename,
        generation_prompt=bg_prompt,
        provider=provider_name if 'provider_name' in locals() else 'compositor',
        model_name=model_name if 'model_name' in locals() else 'layered'
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return {
        "media_library_id": str(media.id),
        "image_url": public_url,
        "copy_map": copy_map,
        "bg_prompt": bg_prompt
    }


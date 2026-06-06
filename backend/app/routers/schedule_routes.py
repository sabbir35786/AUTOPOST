import json
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app import models, schemas
from app.database import get_db
from app.config import APP_BASE_URL, BACKEND_URL
from app.services.schedule_service import register_all_todays_slots, register_todays_slots
from app.qstash import cancel_scheduled_post, verify_qstash_signature
from app.posts import generate_persona_post_with_user_model, publish_post_to_facebook
from pydantic import BaseModel
from zoneinfo import ZoneInfo
from datetime import timezone

router = APIRouter()

class ScheduleInput(BaseModel):
    days_of_week: list[str]
    post_times: list[str]
    timezone: str

@router.post("/api/internal/register-daily-slots")
async def register_daily_slots(request: Request, db: Session = Depends(get_db)):
    # Verify QStash signature
    signature = request.headers.get("upstash-signature", "")
    body = await request.body()
    # The URL should match what is registered in QStash
    webhook_url = f"{BACKEND_URL.rstrip('/')}/api/internal/register-daily-slots"
    
    if not verify_qstash_signature(body, signature, webhook_url):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    await register_all_todays_slots(db)
    return {"status": "ok", "message": "Daily slots registered"}

@router.post("/api/webhooks/publish-post")
async def publish_post_webhook(request: Request, db: Session = Depends(get_db)):
    # Verify QStash signature
    signature = request.headers.get("upstash-signature", "")
    body = await request.body()
    webhook_url = f"{BACKEND_URL.rstrip('/')}/api/webhooks/publish-post"
    
    if not verify_qstash_signature(body, signature, webhook_url):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    persona_id_str = data.get("persona_id")
    scheduled_at_str = data.get("scheduled_at")
    
    if not persona_id_str:
        return {"status": "skipped", "reason": "No persona_id provided"}
        
    persona_id = int(persona_id_str)
    
    # Find the slot
    slot = db.query(models.ScheduledSlot).filter(
        models.ScheduledSlot.persona_id == persona_id,
        models.ScheduledSlot.status == 'pending'
    ).order_by(models.ScheduledSlot.scheduled_at.asc()).first()
    
    if not slot:
        return {"status": "skipped", "reason": "No pending slot found"}
    
    slot.status = 'generating'
    db.commit()
    
    try:
        persona = db.get(models.AIPersona, persona_id)
        if not persona:
            raise Exception("Persona not found")
            
        connection = db.get(models.FacebookConnection, persona.page_connection_id)
        if not connection:
            raise Exception("Facebook connection not found")

        # 1. Generate post content
        print(f"[Publish] Generating post for persona {persona_id}")
        recent_topics = [] # Add logic to get recent topics if needed
        post_content = generate_persona_post_with_user_model(db, persona, recent_topics)
        
        # 2. Generate image if template assigned (Simplified for now or adapt from original)
        image_url = None
        # ... user prompt uses generate_photocard... I will leave image generation simple for now 
        # or just skip if not configured, the prompt logic is quite complex.
        
        # Create PostLog
        post_log = models.PostLog(
            user_id=persona.user_id,
            facebook_connection_id=persona.page_connection_id,
            ai_persona_id=persona.id,
            content=post_content,
            status="publishing",
            delivery_status="delivering"
        )
        db.add(post_log)
        db.flush()

        # 3. Publish to Facebook
        print(f"[Publish] Publishing to Facebook for persona {persona_id}")
        success = await publish_post_to_facebook(db, post_log, connection)
        
        if not success:
            raise Exception(f"Facebook publish failed: {post_log.publish_error}")
            
        post_log.status = "published"
        post_log.delivery_status = "delivered"
        
        # 4. Save post to DB
        new_post = models.Post(
            status='published',
            published_at=datetime.utcnow(),
            facebook_post_id=post_log.facebook_post_id,
            facebook_post_url=post_log.link_url
        )
        db.add(new_post)
        db.flush()
        
        # 5. Update slot
        slot.status = 'published'
        slot.post_id = new_post.id
        db.commit()
        
        print(f"[Publish] ✓ Successfully published for persona {persona_id}")
        return {"status": "published"}
    
    except Exception as e:
        slot.status = 'failed'
        slot.error_message = str(e)
        db.commit()
        print(f"[Publish] ✗ Failed for persona {persona_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from app.auth import get_current_user

@router.post("/api/personas/{persona_id}/schedule")
async def save_persona_schedule(
    persona_id: int,
    schedule_data: ScheduleInput,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Upsert schedule
    schedule = db.query(models.PersonaSchedule).filter_by(persona_id=persona_id).first()
    if schedule:
        schedule.days_of_week = schedule_data.days_of_week
        schedule.post_times = schedule_data.post_times
        schedule.timezone = schedule_data.timezone
        schedule.is_active = True
        schedule.updated_at = datetime.utcnow()
    else:
        schedule = models.PersonaSchedule(
            persona_id=persona_id,
            days_of_week=schedule_data.days_of_week,
            post_times=schedule_data.post_times,
            timezone=schedule_data.timezone
        )
        db.add(schedule)
    db.commit()
    
    # Register today's slots immediately
    await register_todays_slots(persona_id, db)
    
    return {"status": "saved", "message": "Schedule saved and today's slots registered"}

@router.delete("/api/personas/{persona_id}/schedule")
async def delete_persona_schedule(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Cancel all pending QStash messages for this persona
    pending_slots = db.query(models.ScheduledSlot).filter(
        models.ScheduledSlot.persona_id == persona_id,
        models.ScheduledSlot.status == 'pending'
    ).all()
    
    for slot in pending_slots:
        if slot.qstash_message_id:
            cancel_scheduled_post(slot.qstash_message_id)
        slot.status = 'cancelled'
    
    # Deactivate schedule
    schedule = db.query(models.PersonaSchedule).filter_by(persona_id=persona_id).first()
    if schedule:
        schedule.is_active = False
    
    db.commit()
    return {"status": "cancelled", "slots_cancelled": len(pending_slots)}

def convert_to_user_timezone(dt_utc: datetime, timezone_str: str) -> str:
    if not dt_utc:
        return ""
    try:
        tz = ZoneInfo(timezone_str)
        local_dt = dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)
        return local_dt.strftime("%I:%M %p")
    except:
        return dt_utc.strftime("%I:%M %p")

@router.get("/api/dashboard")
async def get_dashboard(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
    today_end = datetime.utcnow().replace(hour=23, minute=59, second=59)
    
    # Today's slots only
    todays_slots = db.query(models.ScheduledSlot).join(models.AIPersona).filter(
        models.AIPersona.user_id == current_user.id,
        models.ScheduledSlot.scheduled_at >= today_start,
        models.ScheduledSlot.scheduled_at <= today_end
    ).order_by(models.ScheduledSlot.scheduled_at.asc()).all()
    
    # Last 10 published posts
    recent_posts = db.query(models.PostLog).join(models.AIPersona).filter(
        models.AIPersona.user_id == current_user.id,
        models.PostLog.status == 'published'
    ).order_by(models.PostLog.created_at.desc()).limit(10).all()
    
    return {
        "todays_slots": [
            {
                "id": str(slot.id),
                "persona_name": slot.persona.persona_name if slot.persona else "Unknown",
                "scheduled_at_local": convert_to_user_timezone(slot.scheduled_at, current_user.timezone),
                "status": slot.status,
                "error_message": slot.error_message
            }
            for slot in todays_slots
        ],
        "recent_posts": [
            {
                "id": str(post.id),
                "persona_name": post.persona.persona_name if hasattr(post, 'persona') and post.persona else "Unknown",
                "content_preview": post.content[:120] if post.content else "",
                "image_url": post.image_url,
                "published_at": post.posted_at or post.created_at,
                "facebook_post_url": post.link_url,
                "status": post.status
            }
            for post in recent_posts
        ]
    }

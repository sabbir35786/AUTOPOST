from datetime import datetime, date, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.schedule_service import (
    register_all_todays_slots,
    register_todays_slots,
    normalize_active_days,
    normalize_day_name,
)
from app.services.slot_publish_service import execute_slot_publish
from pydantic import BaseModel
from zoneinfo import ZoneInfo

router = APIRouter()

class ScheduleInput(BaseModel):
    timezone: str
    active_days: list[str]
    default_times: list[str]
    day_overrides: dict[str, list[str]]




from app.auth import get_current_user
from sqlalchemy.orm import joinedload


def _verify_persona_owner(db: Session, persona_id: int, user_id: int) -> models.AIPersona:
    persona = db.query(models.AIPersona).filter(
        models.AIPersona.id == persona_id,
        models.AIPersona.user_id == user_id,
    ).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


@router.get("/api/personas/{persona_id}/schedule")
async def get_persona_schedule(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _verify_persona_owner(db, persona_id, current_user.id)
    schedule = db.query(models.PersonaSchedule).filter_by(persona_id=persona_id).first()
    if not schedule:
        return {
            "timezone": current_user.timezone or "UTC",
            "active_days": [],
            "default_times": [],
            "day_overrides": {},
            "is_active": False,
        }
    return {
        "timezone": schedule.timezone,
        "active_days": schedule.active_days or [],
        "default_times": schedule.default_times or [],
        "day_overrides": schedule.day_overrides or {},
        "is_active": schedule.is_active,
    }


@router.post("/api/personas/{persona_id}/schedule")
async def save_persona_schedule(
    persona_id: int,
    schedule_data: ScheduleInput,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    persona = _verify_persona_owner(db, persona_id, current_user.id)
    # Upsert schedule
    schedule = db.query(models.PersonaSchedule).filter_by(persona_id=persona_id).first()
    
    active_days_norm = normalize_active_days(schedule_data.active_days)
    day_overrides_norm = {
        normalize_day_name(k): v for k, v in schedule_data.day_overrides.items()
    }
    
    if schedule:
        schedule.timezone = schedule_data.timezone
        schedule.is_active = persona.is_active
        schedule.active_days = active_days_norm
        schedule.default_times = schedule_data.default_times
        schedule.day_overrides = day_overrides_norm
        schedule.updated_at = datetime.now(timezone.utc)
    else:
        schedule = models.PersonaSchedule(
            persona_id=persona_id,
            timezone=schedule_data.timezone,
            is_active=persona.is_active if persona else True,
            active_days=active_days_norm,
            default_times=schedule_data.default_times,
            day_overrides=day_overrides_norm,
        )
        db.add(schedule)
    db.commit()
    
    slots_registered: list[dict] = []
    if persona.is_active:
        try:
            slots_registered = await register_todays_slots(persona_id, db)
        except Exception as exc:
            print(f"[Schedule] Persona {persona_id} saved but slot registration failed: {exc}")
            return {
                "status": "saved",
                "message": "Schedule saved; slot registration failed — will retry at midnight.",
                "warning": str(exc),
                "slots": [],
            }

    return {
        "status": "saved",
        "message": "Schedule saved and today's slots registered",
        "slots": slots_registered,
    }

@router.post("/api/scheduled-slots/{slot_id}/retry")
async def retry_scheduled_slot(
    slot_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    slot = db.query(models.ScheduledSlot).join(models.AIPersona).filter(
        models.ScheduledSlot.id == slot_id,
        models.AIPersona.user_id == current_user.id
    ).first()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
        
    if slot.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed slots can be retried")

    slot.status = "pending"
    slot.error_message = None
    slot.retry_count += 1
    db.commit()

    result = await execute_slot_publish(db, slot)
    return {
        "status": "retrying",
        "result": result,
    }

@router.delete("/api/personas/{persona_id}/schedule")
async def delete_persona_schedule(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    _verify_persona_owner(db, persona_id, current_user.id)
    # Cancel all pending slots for this persona (APScheduler will skip them)
    pending_slots = db.query(models.ScheduledSlot).filter(
        models.ScheduledSlot.persona_id == persona_id,
        models.ScheduledSlot.status == 'pending'
    ).all()
    
    for slot in pending_slots:
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
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        local_dt = dt_utc.astimezone(tz)
        return local_dt.strftime("%I:%M %p")
    except Exception:
        return dt_utc.strftime("%I:%M %p")

def _facebook_post_url(post: models.PostLog) -> str | None:
    if getattr(post, "facebook_post_url", None):
        return post.facebook_post_url
    if post.facebook_post_id:
        return f"https://www.facebook.com/{post.facebook_post_id}"
    return post.link_url


def _effective_slot_status(slot: models.ScheduledSlot, resolved_posts: dict[int, models.PostLog] | None = None) -> str:
    """Return the real status — recover from desync where FB publish succeeded but slot wasn't updated."""
    if slot.status == "published":
        return "published"
    if slot.post_id:
        post = resolved_posts.get(slot.post_id) if resolved_posts else None
        if post and post.status in ("published", "success"):
            return "published"
    if slot.status == "generating" and slot.post_id:
        post = resolved_posts.get(slot.post_id) if resolved_posts else None
        if post and post.facebook_post_id:
            return "published"
    return slot.status


@router.get("/api/dashboard")
async def get_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_tz = current_user.timezone or "Asia/Dhaka"
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)

    todays_slots = (
        db.query(models.ScheduledSlot)
        .options(joinedload(models.ScheduledSlot.persona))
        .join(models.AIPersona)
        .filter(
            models.AIPersona.user_id == current_user.id,
            models.ScheduledSlot.scheduled_at >= today_start,
            models.ScheduledSlot.scheduled_at <= today_end,
        )
        .order_by(models.ScheduledSlot.scheduled_at.asc())
        .limit(50)
        .all()
    )
    
    # Batch-load all PostLogs referenced by todays_slots for _effective_slot_status
    slot_post_ids = [slot.post_id for slot in todays_slots if slot.post_id]
    resolved_posts: dict[int, models.PostLog] = {}
    if slot_post_ids:
        for sp in db.query(models.PostLog).filter(models.PostLog.id.in_(slot_post_ids)).all():
            resolved_posts[sp.id] = sp
    
    recent_posts = (
        db.query(
            models.PostLog.id,
            models.PostLog.ai_persona_id,
            models.PostLog.content,
            models.PostLog.image_url,
            models.PostLog.published_at,
            models.PostLog.posted_at,
            models.PostLog.created_at,
            models.PostLog.facebook_post_id,
            models.PostLog.facebook_post_url,
            models.PostLog.link_url,
            models.PostLog.status,
        )
        .filter(
            models.PostLog.user_id == current_user.id,
            models.PostLog.status == "published",
        )
        .order_by(
            models.PostLog.posted_at.desc().nullslast(),
            models.PostLog.created_at.desc()
        )
        .limit(10)
        .all()
    )
    
    # Batch-load all personas referenced by recent_posts
    persona_ids = {p.ai_persona_id for p in recent_posts if p.ai_persona_id}
    persona_map: dict[int, str] = {}
    if persona_ids:
        for p in db.query(models.AIPersona.id, models.AIPersona.persona_name).filter(models.AIPersona.id.in_(persona_ids)).all():
            persona_map[p.id] = p.persona_name
    
    recent_post_items = []
    for post in recent_posts:
        persona_name = persona_map.get(post.ai_persona_id) if post.ai_persona_id else None
        published_at = post.published_at or post.posted_at or post.created_at
        if published_at and published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        elif published_at:
            published_at = published_at.astimezone(timezone.utc)
        recent_post_items.append({
            "id": str(post.id),
            "persona_name": persona_name or "Manual post",
            "content_preview": (post.content or "")[:120],
            "image_url": post.image_url,
            "published_at": published_at.isoformat() if published_at else None,
            "facebook_post_url": _facebook_post_url(post),
            "status": post.status,
        })

    return {
        "todays_slots": [
            {
                "id": str(slot.id),
                "persona_name": slot.persona.persona_name if slot.persona else "Unknown",
                "scheduled_at_local": convert_to_user_timezone(slot.scheduled_at, user_tz),
                "scheduled_at_utc": (
                    (slot.scheduled_at.replace(tzinfo=timezone.utc) if slot.scheduled_at.tzinfo is None else slot.scheduled_at.astimezone(timezone.utc)).isoformat()
                    if slot.scheduled_at
                    else None
                ),
                "status": _effective_slot_status(slot, resolved_posts),
                "error_message": slot.error_message,
                "retry_count": slot.retry_count,
            }
            for slot in todays_slots
        ],
        "recent_posts": recent_post_items
    }


@router.get("/api/scheduled-slots")
async def get_scheduled_slots(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upcoming persona auto-post slots plus manually scheduled posts."""
    now = datetime.utcnow()

    persona_slots = (
        db.query(models.ScheduledSlot)
        .options(joinedload(models.ScheduledSlot.persona))
        .join(models.AIPersona)
        .filter(
            models.AIPersona.user_id == current_user.id,
            models.ScheduledSlot.scheduled_at >= now,
            models.ScheduledSlot.status.in_(["pending", "generating"]),
        )
        .order_by(models.ScheduledSlot.scheduled_at.asc())
        .limit(50)
        .all()
    )

    manual_posts = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.user_id == current_user.id,
            models.PostLog.status.in_(["scheduled", "missed", "schedule_failed"]),
            models.PostLog.scheduled_at >= now,
        )
        .order_by(models.PostLog.scheduled_at.asc())
        .limit(50)
        .all()
    )

    # Batch-load post logs for slot status resolution
    slot_post_ids = [slot.post_id for slot in persona_slots if slot.post_id]
    resolved_posts: dict[int, models.PostLog] = {}
    if slot_post_ids:
        for sp in db.query(models.PostLog).filter(models.PostLog.id.in_(slot_post_ids)).all():
            resolved_posts[sp.id] = sp

    # Batch-load personas for manual posts
    manual_persona_ids = {p.ai_persona_id for p in manual_posts if p.ai_persona_id}
    manual_persona_map: dict[int, str] = {}
    if manual_persona_ids:
        for p in db.query(models.AIPersona.id, models.AIPersona.persona_name).filter(models.AIPersona.id.in_(manual_persona_ids)).all():
            manual_persona_map[p.id] = p.persona_name

    items = []
    for slot in persona_slots:
        persona = slot.persona
        items.append({
            "id": str(slot.id),
            "type": "persona_slot",
            "persona_name": persona.persona_name if persona else "Unknown",
            "content_preview": None,
            "scheduled_at": slot.scheduled_at,
            "scheduled_at_local": convert_to_user_timezone(slot.scheduled_at, current_user.timezone),
            "status": _effective_slot_status(slot, resolved_posts),
            "error_message": slot.error_message,
        })

    for post in manual_posts:
        persona_name = manual_persona_map.get(post.ai_persona_id) if post.ai_persona_id else None
        items.append({
            "id": str(post.id),
            "type": "manual_post",
            "persona_name": persona_name or "Manual post",
            "content_preview": (post.content or "")[:120] or None,
            "scheduled_at": post.scheduled_at,
            "scheduled_at_local": convert_to_user_timezone(post.scheduled_at, current_user.timezone) if post.scheduled_at else "",
            "status": post.status,
            "error_message": post.error_message,
        })

    items.sort(key=lambda x: x["scheduled_at"] or now)
    return {"slots": items}

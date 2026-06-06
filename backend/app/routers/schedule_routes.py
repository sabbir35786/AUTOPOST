import json
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app import models, schemas
from app.database import get_db
from app.config import APP_BASE_URL, BACKEND_URL
from app.services.schedule_service import (
    register_all_todays_slots,
    register_todays_slots,
    normalize_active_days,
    normalize_day_name,
    get_today_bounds_utc,
)
from app.services.slot_publish_service import execute_slot_publish
from app.qstash import cancel_scheduled_post, verify_qstash_signature
from pydantic import BaseModel
from zoneinfo import ZoneInfo
from datetime import timezone

router = APIRouter()

class ScheduleInput(BaseModel):
    timezone: str
    active_days: list[str]
    default_times: list[str]
    day_overrides: dict[str, list[str]]


def _normalize_scheduled_at(dt: datetime) -> datetime:
    """Normalize to UTC naive for consistent DB comparison."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _find_slot_for_webhook(db: Session, persona_id: int, scheduled_at_str: str | None):
    """Find the scheduled slot matching this webhook payload."""
    base_query = db.query(models.ScheduledSlot).filter(
        models.ScheduledSlot.persona_id == persona_id,
    )

    if scheduled_at_str:
        scheduled_at = datetime.fromisoformat(scheduled_at_str)
        scheduled_at = _normalize_scheduled_at(scheduled_at)
        window_start = scheduled_at - timedelta(seconds=60)
        window_end = scheduled_at + timedelta(seconds=60)
        return (
            base_query.filter(
                models.ScheduledSlot.scheduled_at >= window_start,
                models.ScheduledSlot.scheduled_at <= window_end,
                models.ScheduledSlot.status.in_(["pending", "generating", "published"]),
            )
            .order_by(models.ScheduledSlot.scheduled_at.asc())
            .first()
        )

    return (
        base_query.filter(models.ScheduledSlot.status.in_(["pending", "generating"]))
        .order_by(models.ScheduledSlot.scheduled_at.asc())
        .first()
    )


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
    slot = _find_slot_for_webhook(db, persona_id, scheduled_at_str)

    if not slot:
        return {"status": "skipped", "reason": "No matching slot found"}

    result = await execute_slot_publish(db, slot)
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result.get("reason", "Publish failed"))
    return result

from app.auth import get_current_user


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
            "timezone": current_user.timezone or "Asia/Dhaka",
            "active_days": [],
            "default_times": [],
            "day_overrides": {},
            "is_active": False,
        }
    data = schedule.schedule_data or {}
    return {
        "timezone": schedule.timezone,
        "active_days": data.get("active_days", []),
        "default_times": data.get("default_times", []),
        "day_overrides": data.get("day_overrides", {}),
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
    normalized_data = {
        "active_days": normalize_active_days(schedule_data.active_days),
        "default_times": schedule_data.default_times,
        "day_overrides": {
            normalize_day_name(k): v for k, v in schedule_data.day_overrides.items()
        },
    }
    if schedule:
        schedule.timezone = schedule_data.timezone
        schedule.is_active = persona.is_active
        schedule.schedule_data = normalized_data
        schedule.updated_at = datetime.utcnow()
    else:
        schedule = models.PersonaSchedule(
            persona_id=persona_id,
            timezone=schedule_data.timezone,
            is_active=persona.is_active if persona else True,
            schedule_data=normalized_data,
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

@router.delete("/api/personas/{persona_id}/schedule")
async def delete_persona_schedule(
    persona_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    _verify_persona_owner(db, persona_id, current_user.id)
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

def _facebook_post_url(post: models.PostLog) -> str | None:
    if post.facebook_post_id:
        return f"https://www.facebook.com/{post.facebook_post_id}"
    return post.link_url


def _effective_slot_status(slot: models.ScheduledSlot, db: Session) -> str:
    """Return the real status — recover from desync where FB publish succeeded but slot wasn't updated."""
    if slot.status == "published":
        return "published"
    if slot.post_id:
        post = db.get(models.PostLog, slot.post_id)
        if post and post.status in ("published", "success"):
            return "published"
    if slot.status == "generating" and slot.post_id:
        post = db.get(models.PostLog, slot.post_id)
        if post and post.facebook_post_id:
            return "published"
    return slot.status


@router.get("/api/dashboard")
async def get_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_tz = current_user.timezone or "Asia/Dhaka"
    today_start, today_end = get_today_bounds_utc(user_tz)

    todays_slots = (
        db.query(models.ScheduledSlot)
        .join(models.AIPersona)
        .filter(
            models.AIPersona.user_id == current_user.id,
            models.ScheduledSlot.scheduled_at >= today_start,
            models.ScheduledSlot.scheduled_at <= today_end,
        )
        .order_by(models.ScheduledSlot.scheduled_at.asc())
        .all()
    )
    
    recent_posts = db.query(models.PostLog).filter(
        models.PostLog.user_id == current_user.id,
        models.PostLog.status.in_(["published", "success"])
    ).order_by(
        models.PostLog.posted_at.desc().nullslast(),
        models.PostLog.created_at.desc()
    ).limit(10).all()
    
    recent_post_items = []
    for post in recent_posts:
        persona = db.get(models.AIPersona, post.ai_persona_id) if post.ai_persona_id else None
        recent_post_items.append({
            "id": str(post.id),
            "persona_name": persona.persona_name if persona else "Manual post",
            "content_preview": post.content[:120] if post.content else "",
            "image_url": post.image_url,
            "published_at": post.posted_at or post.created_at,
            "facebook_post_url": _facebook_post_url(post),
            "status": post.status,
        })

    return {
        "todays_slots": [
            {
                "id": str(slot.id),
                "persona_name": slot.persona.persona_name if slot.persona else "Unknown",
                "scheduled_at_local": convert_to_user_timezone(slot.scheduled_at, user_tz),
                "status": _effective_slot_status(slot, db),
                "error_message": slot.error_message,
                "qstash_scheduled": bool(slot.qstash_message_id),
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
        .join(models.AIPersona)
        .filter(
            models.AIPersona.user_id == current_user.id,
            models.ScheduledSlot.scheduled_at >= now,
            models.ScheduledSlot.status.in_(["pending", "generating"]),
        )
        .order_by(models.ScheduledSlot.scheduled_at.asc())
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
        .all()
    )

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
            "status": _effective_slot_status(slot, db),
            "error_message": slot.error_message,
        })

    for post in manual_posts:
        persona = db.get(models.AIPersona, post.ai_persona_id) if post.ai_persona_id else None
        items.append({
            "id": str(post.id),
            "type": "manual_post",
            "persona_name": persona.persona_name if persona else "Manual post",
            "content_preview": (post.content or "")[:120] or None,
            "scheduled_at": post.scheduled_at,
            "scheduled_at_local": convert_to_user_timezone(post.scheduled_at, current_user.timezone) if post.scheduled_at else "",
            "status": post.status,
            "error_message": post.error_message,
        })

    items.sort(key=lambda x: x["scheduled_at"] or now)
    return {"slots": items}
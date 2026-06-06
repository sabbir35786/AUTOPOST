from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.database import SessionLocal
from app.models import PersonaSchedule, ScheduledSlot

logger = logging.getLogger(__name__)

DAY_ABBREV_TO_FULL = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
    "monday": "monday",
    "tuesday": "tuesday",
    "wednesday": "wednesday",
    "thursday": "thursday",
    "friday": "friday",
    "saturday": "saturday",
    "sunday": "sunday",
}


def normalize_day_name(day: str) -> str:
    key = day.strip().lower()
    if key in DAY_ABBREV_TO_FULL:
        return DAY_ABBREV_TO_FULL[key]
    return DAY_ABBREV_TO_FULL.get(key[:3], key)


def normalize_active_days(days: list[str]) -> list[str]:
    return [normalize_day_name(d) for d in days if d.strip()]


def get_timezone(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def get_today_bounds_utc(tz_name: str) -> tuple[datetime, datetime]:
    tz = get_timezone(tz_name)
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def get_todays_slots_for_persona(schedule: PersonaSchedule) -> list[datetime]:
    tz = get_timezone(schedule.timezone)
    now = datetime.now(tz)
    today = now.strftime("%A").lower()

    active_days = normalize_active_days(schedule.active_days or [])
    default_times = schedule.default_times or []
    raw_overrides = schedule.day_overrides or {}
    day_overrides = {normalize_day_name(k): v for k, v in raw_overrides.items()}

    if today not in active_days:
        return []

    times_to_use = day_overrides.get(today, default_times)

    slots = []
    now_utc = datetime.now(timezone.utc)
    for time_str in times_to_use:
        try:
            hour, minute = map(int, time_str.split(":"))
            slot_local = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            slot_utc = slot_local.astimezone(timezone.utc)
            slots.append(slot_utc)
        except ValueError:
            continue
            
    return slots


def _serialize_registered_slot(slot: ScheduledSlot) -> dict:
    return {
        "id": str(slot.id),
        "scheduled_at": slot.scheduled_at.isoformat() if slot.scheduled_at else None,
        "status": slot.status,
        "qstash_scheduled": False,
        "error_message": slot.error_message,
    }


async def register_todays_slots(persona_id: int | str, db: Session) -> list[dict]:
    persona_id_int = int(persona_id)
    schedule = db.query(PersonaSchedule).filter_by(
        persona_id=persona_id_int, is_active=True
    ).first()

    if not schedule:
        return []

    today_start, today_end = get_today_bounds_utc(schedule.timezone)

    existing = db.query(ScheduledSlot).filter(
        ScheduledSlot.persona_id == persona_id_int,
        ScheduledSlot.status == "pending",
        ScheduledSlot.scheduled_at >= today_start,
        ScheduledSlot.scheduled_at <= today_end,
    ).all()

    existing_non_pending = db.query(ScheduledSlot).filter(
        ScheduledSlot.persona_id == persona_id_int,
        ScheduledSlot.status.in_(["published", "generating", "failed", "missed"]),
        ScheduledSlot.scheduled_at >= today_start,
        ScheduledSlot.scheduled_at <= today_end,
    ).all()
    non_pending_times = set(slot.scheduled_at for slot in existing_non_pending)

    for slot in existing:
        db.delete(slot)
    db.commit()

    slot_times = get_todays_slots_for_persona(schedule)
    registered: list[dict] = []

    for slot_utc in slot_times:
        if slot_utc in non_pending_times:
            continue

        new_slot = ScheduledSlot(
            persona_id=persona_id_int,
            scheduled_at=slot_utc,
            status="pending",
            error_message=None,
        )
        db.add(new_slot)
        db.flush()
        registered.append(_serialize_registered_slot(new_slot))

    db.commit()
    logger.info(f"[Scheduler] Registered {len(registered)} slot(s) for persona {persona_id_int}")
    return registered


async def register_all_todays_slots(db: Session = None):
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
        
    try:
        active_schedules = db.query(PersonaSchedule).filter_by(is_active=True).all()
        logger.info(f"[Scheduler] Registering daily slots for {len(active_schedules)} personas")

        for schedule in active_schedules:
            try:
                await register_todays_slots(schedule.persona_id, db)
            except Exception as e:
                logger.error(f"[Scheduler] Persona {schedule.persona_id} failed: {e}")
    finally:
        if close_db:
            db.close()

async def process_due_persona_slots(db: Session = None):
    from app.services.slot_publish_service import execute_slot_publish
    
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        now_utc = datetime.now(timezone.utc)

        due_slots = (
            db.query(ScheduledSlot)
            .filter(
                ScheduledSlot.status == "pending",
                ScheduledSlot.scheduled_at <= now_utc,
            )
            .order_by(ScheduledSlot.scheduled_at.asc())
            .all()
        )

        processed = 0
        for slot in due_slots:
            logger.info(f"[Scheduler] Processing due slot {slot.id} for persona {slot.persona_id}")
            await execute_slot_publish(db, slot)
            processed += 1
        return processed
    finally:
        if close_db:
            db.close()

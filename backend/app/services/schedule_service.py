from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models import PersonaSchedule, ScheduledSlot
from app.qstash import schedule_post_delivery, cancel_scheduled_post

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

QSTASH_MIN_DELAY_SECONDS = 30


def normalize_day_name(day: str) -> str:
    """Convert 'Mon', 'monday', etc. to full lowercase day name."""
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
    """Return start/end of 'today' in the given timezone, as UTC-aware datetimes."""
    tz = get_timezone(tz_name)
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def get_todays_slots_for_persona(schedule: PersonaSchedule) -> list[datetime]:
    """
    Returns list of UTC-aware datetimes for today's remaining posting slots.
    Only returns slots that are still in the future.
    """
    tz = get_timezone(schedule.timezone)
    now = datetime.now(tz)
    today = now.strftime("%A").lower()

    schedule_data = schedule.schedule_data or {}
    active_days = normalize_active_days(schedule_data.get("active_days", []))
    default_times = schedule_data.get("default_times", [])
    raw_overrides = schedule_data.get("day_overrides", {})
    day_overrides = {normalize_day_name(k): v for k, v in raw_overrides.items()}

    if today not in active_days:
        return []

    times_to_use = day_overrides.get(today, default_times)

    slots = []
    for time_str in times_to_use:
        hour, minute = map(int, time_str.split(":"))
        slot_local = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slots.append(slot_local.astimezone(timezone.utc))
    return slots


def _serialize_registered_slot(slot: ScheduledSlot) -> dict:
    return {
        "id": str(slot.id),
        "scheduled_at": slot.scheduled_at.isoformat() if slot.scheduled_at else None,
        "status": slot.status,
        "qstash_scheduled": bool(slot.qstash_message_id),
        "error_message": slot.error_message,
    }


async def register_todays_slots(persona_id: int | str, db: Session) -> list[dict]:
    """
    Registers today's remaining slots for one persona with QStash.
    Cancels existing pending slots for today (in persona timezone) first.
    Always saves slots to DB so the dashboard updates immediately.
    """
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
        if slot.qstash_message_id:
            cancel_scheduled_post(slot.qstash_message_id)
        db.delete(slot)
    db.commit()

    slot_times = get_todays_slots_for_persona(schedule)
    registered: list[dict] = []
    now_utc = datetime.now(timezone.utc)

    for slot_utc in slot_times:
        if slot_utc in non_pending_times:
            continue

        delay_seconds = int((slot_utc - now_utc).total_seconds())
        message_id = None
        error_message = None

        if delay_seconds >= QSTASH_MIN_DELAY_SECONDS:
            message_id = schedule_post_delivery(
                persona_id=str(persona_id_int),
                scheduled_at_utc=slot_utc,
            )
            if not message_id:
                error_message = "QStash scheduling failed — cron will retry at fire time"
        else:
            error_message = "Time too close or in past — will be processed by fallback cron immediately"

        new_slot = ScheduledSlot(
            persona_id=persona_id_int,
            scheduled_at=slot_utc,
            qstash_message_id=message_id,
            status="pending",
            error_message=error_message,
        )
        db.add(new_slot)
        db.flush()
        registered.append(_serialize_registered_slot(new_slot))

    db.commit()
    print(f"[Scheduler] Registered {len(registered)} slot(s) for persona {persona_id_int}")
    return registered


async def process_due_persona_slots(db: Session) -> int:
    """
    Cron fallback: publish any pending slots whose time has arrived.
    Covers QStash misses and slots registered without a QStash message ID.
    """
    from app.services.slot_publish_service import execute_slot_publish

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=12)

    due_slots = (
        db.query(ScheduledSlot)
        .filter(
            ScheduledSlot.status.in_(["pending", "generating"]),
            ScheduledSlot.scheduled_at <= now_utc,
            ScheduledSlot.scheduled_at >= cutoff,
        )
        .order_by(ScheduledSlot.scheduled_at.asc())
        .all()
    )

    processed = 0
    for slot in due_slots:
        if slot.status == "generating":
            continue
        print(f"[Scheduler] Processing due slot {slot.id} for persona {slot.persona_id}")
        await execute_slot_publish(db, slot)
        processed += 1
    return processed


async def register_all_todays_slots(db: Session):
    """Called every day at midnight. Registers today's slots for ALL active personas."""
    active_schedules = db.query(PersonaSchedule).filter_by(is_active=True).all()
    print(f"[Scheduler] Registering daily slots for {len(active_schedules)} personas")

    for schedule in active_schedules:
        try:
            await register_todays_slots(schedule.persona_id, db)
            print(f"[Scheduler] ✓ Persona {schedule.persona_id} slots registered")
        except Exception as e:
            print(f"[Scheduler] ✗ Persona {schedule.persona_id} failed: {e}")

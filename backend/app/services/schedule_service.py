from zoneinfo import ZoneInfo
from datetime import datetime, date, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import PersonaSchedule, ScheduledSlot
from app.qstash import schedule_post_delivery, cancel_scheduled_post

def get_todays_slots_for_persona(schedule: PersonaSchedule) -> list[datetime]:
    """
    Returns list of UTC datetimes for today's remaining posting slots.
    Only returns slots that are still in the future.
    Implements the new schedule logic with default times and day overrides.
    """
    try:
        tz = ZoneInfo(schedule.timezone)
    except Exception:
        tz = timezone.utc
    
    now = datetime.now(tz)
    today = now.strftime('%A').lower()  # full day name: monday, tuesday, etc.
    
    # Get schedule data
    schedule_data = schedule.schedule_data
    active_days = [d.lower() for d in schedule_data.get('active_days', [])]
    default_times = schedule_data.get('default_times', [])
    day_overrides = schedule_data.get('day_overrides', {})
    
    # Check if today is an active day
    if today not in active_days:
        return []
    
    # Determine which times to use
    if today in day_overrides:
        times_to_use = day_overrides[today]
    else:
        times_to_use = default_times
    
    slots = []
    for time_str in times_to_use:
        hour, minute = map(int, time_str.split(':'))
        slot_local = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot_local > now:  # only future slots
            slot_utc = slot_local.astimezone(timezone.utc).replace(tzinfo=None)
            slots.append(slot_utc)
    
    return slots

async def register_todays_slots(persona_id: str, db: Session):
    """
    Registers today's remaining slots for one persona with QStash.
    Cancels any existing pending slots for this persona first.
    """
    # Cancel existing pending slots for today
    existing = db.query(ScheduledSlot).filter(
        ScheduledSlot.persona_id == persona_id,
        ScheduledSlot.status == 'pending',
        func.date(ScheduledSlot.scheduled_at) == date.today()
    ).all()
    
    for slot in existing:
        if slot.qstash_message_id:
            cancel_scheduled_post(slot.qstash_message_id)
        db.delete(slot)
    db.commit()
    
    # Load schedule
    schedule = db.query(PersonaSchedule).filter_by(
        persona_id=persona_id, is_active=True
    ).first()
    
    if not schedule:
        return
    
    # Get today's slots
    slot_times = get_todays_slots_for_persona(schedule)
    
    for slot_utc in slot_times:
        # Register with QStash
        delay_seconds = int((slot_utc - datetime.utcnow()).total_seconds())
        if delay_seconds < 10:
            continue
        
        message_id = schedule_post_delivery(
            persona_id=persona_id,
            scheduled_at_utc=slot_utc
        )
        
        # Save to DB
        new_slot = ScheduledSlot(
            persona_id=persona_id,
            scheduled_at=slot_utc,
            qstash_message_id=message_id,
            status='pending'
        )
        db.add(new_slot)
    
    db.commit()

async def register_all_todays_slots(db: Session):
    """
    Called every day at midnight. Registers today's slots for ALL active personas.
    """
    active_schedules = db.query(PersonaSchedule).filter_by(is_active=True).all()
    
    print(f"[Scheduler] Registering daily slots for {len(active_schedules)} personas")
    
    for schedule in active_schedules:
        try:
            await register_todays_slots(str(schedule.persona_id), db)
            print(f"[Scheduler] ✓ Persona {schedule.persona_id} slots registered")
        except Exception as e:
            print(f"[Scheduler] ✗ Persona {schedule.persona_id} failed: {e}")
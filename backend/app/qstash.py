from datetime import datetime, timedelta
from typing import Any

try:
    from qstash import QStash
except ModuleNotFoundError:
    QStash = None

try:
    from qstash import Receiver as QStashReceiver
except (ModuleNotFoundError, ImportError):
    QStashReceiver = None

from app.config import (
    BACKEND_URL,
    CRON_SECRET,
    QSTASH_TOKEN,
    QSTASH_CURRENT_SIGNING_KEY,
    QSTASH_NEXT_SIGNING_KEY,
)


_client: Any | None = None


def get_qstash_client() -> Any | None:
    global _client
    if QStash is None:
        return None
    if _client is None and QSTASH_TOKEN:
        _client = QStash(token=QSTASH_TOKEN)
    return _client


def verify_qstash_signature(body: bytes, signature: str, url: str) -> bool:
    """
    Cryptographically verify the Upstash-Signature header from QStash.
    Returns True if valid (or if signing keys are not configured — dev mode).
    Returns False if the signature is invalid.
    """
    if not QSTASH_CURRENT_SIGNING_KEY or not QSTASH_NEXT_SIGNING_KEY:
        print(
            "QStash signing keys not configured (QSTASH_CURRENT_SIGNING_KEY / "
            "QSTASH_NEXT_SIGNING_KEY) — signature verification skipped in dev mode."
        )
        return True

    if QStashReceiver is None:
        print("QStash Receiver class not available — signature verification skipped.")
        return True

    try:
        receiver = QStashReceiver(
            current_signing_key=QSTASH_CURRENT_SIGNING_KEY,
            next_signing_key=QSTASH_NEXT_SIGNING_KEY,
        )
        # The SDK raises an exception if the signature is invalid.
        receiver.verify(
            signature=signature,
            body=body.decode("utf-8"),
            url=url,
        )
        return True
    except Exception as exc:
        print(f"QStash signature verification failed: {exc}")
        return False


async def schedule_scheduler_endpoint() -> bool:
    """
    Register a recurring QStash cron job that calls /api/internal/run-scheduler
    every minute. Skips creation if a schedule for this URL already exists to
    prevent duplicates on every app restart.
    """
    client = get_qstash_client()
    if client is None:
        return False

    callback_url = f"{BACKEND_URL.rstrip('/')}/api/internal/run-scheduler"

    try:
        # Prevent duplicate schedules on every restart
        try:
            existing = client.schedule.list()
            for sched in existing or []:
                dest = getattr(sched, "destination", None) or (
                    sched.get("destination", "") if hasattr(sched, "get") else ""
                )
                if callback_url in str(dest):
                    print(f"QStash schedule already exists for {callback_url} — skipping creation.")
                    return True
        except Exception as list_exc:
            print(f"Could not list QStash schedules (will attempt creation): {list_exc}")

        client.schedule.create(
            destination=callback_url,
            cron="* * * * *",
            headers={"X-Cron-Secret": CRON_SECRET},
        )
        print(f"QStash scheduler created successfully for {callback_url}")
        return True
    except Exception as exc:
        print(f"Failed to create QStash scheduler: {exc}")
        return False


def schedule_post_delivery(post_id: str, scheduled_at_utc: datetime) -> str | None:
    """
    Register a post for delivery at a specific UTC datetime via QStash.
    Returns the QStash message ID for tracking, or None on failure.
    """
    client = get_qstash_client()
    if client is None:
        print("QStash client not available — post delivery will not be scheduled.")
        return None

    delay_seconds = int((scheduled_at_utc - datetime.utcnow()).total_seconds())

    if delay_seconds < 0:
        print(f"Scheduled time is in the past ({delay_seconds}s) — cannot schedule.")
        return None

    if delay_seconds < 30:
        print(
            f"Scheduled time is too soon ({delay_seconds}s). "
            "Minimum delay is 30 seconds — not scheduling via QStash."
        )
        return None

    callback_url = f"{BACKEND_URL.rstrip('/')}/api/webhooks/publish-post"

    try:
        # Use the v2 SDK: client.message.publish_json(...)
        response = client.message.publish_json(
            url=callback_url,
            body={"post_id": post_id},
            delay=delay_seconds,
        )
        # SDK v2 returns an object with .message_id; fall back for older versions
        message_id = (
            getattr(response, "message_id", None)
            or (response.get("messageId") if hasattr(response, "get") else None)
        )
        print(f"QStash message scheduled: {message_id} for post {post_id} at {scheduled_at_utc}")
        return message_id
    except AttributeError:
        # Older SDK: client.publish_json(...)
        try:
            response = client.publish_json(
                url=callback_url,
                body={"post_id": post_id},
                delay=delay_seconds,
            )
            message_id = (
                getattr(response, "message_id", None)
                or (response.get("messageId") if hasattr(response, "get") else None)
            )
            print(f"QStash message scheduled (legacy API): {message_id} for post {post_id}")
            return message_id
        except Exception as exc2:
            print(f"Failed to schedule post delivery via QStash (legacy fallback): {exc2}")
            return None
    except Exception as exc:
        print(f"Failed to schedule post delivery via QStash: {exc}")
        return None


def cancel_scheduled_post(message_id: str) -> bool:
    """
    Cancel a scheduled post by its QStash message ID.
    """
    client = get_qstash_client()
    if client is None:
        print("QStash client not available")
        return False

    try:
        client.messages.delete(message_id)
        print(f"QStash message cancelled: {message_id}")
        return True
    except Exception as exc:
        print(f"Failed to cancel QStash message {message_id}: {exc}")
        return False


def calculate_next_scheduled_time(rule: str, from_time: datetime) -> datetime | None:
    """
    Calculate next scheduled time based on recurrence rule.

    Rules:
    - 'daily'               → same time tomorrow
    - 'weekly:monday,friday' → next matching weekday
    - 'interval:hours:6'    → every 6 hours from now
    - 'interval:days:2'     → every 2 days
    """
    rule = rule.lower().strip()

    if rule == "daily":
        return from_time + timedelta(days=1)

    if rule.startswith("interval:hours:"):
        hours = int(rule.split(":")[2])
        return from_time + timedelta(hours=hours)

    if rule.startswith("interval:days:"):
        days = int(rule.split(":")[2])
        return from_time + timedelta(days=days)

    if rule.startswith("weekly:"):
        day_names = rule.replace("weekly:", "").split(",")
        day_map = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        target_days = [day_map[d.strip()] for d in day_names if d.strip() in day_map]

        next_date = from_time + timedelta(days=1)
        for _ in range(7):
            if next_date.weekday() in target_days:
                return next_date.replace(
                    hour=from_time.hour,
                    minute=from_time.minute,
                    second=0,
                )
            next_date += timedelta(days=1)

    return None


def calculate_next_posting_datetimes(
    assigned_days: list[str],
    posting_time_slots: list[str],
    timezone_str: str,
    count: int = 7,
    from_time: datetime | None = None,
) -> list[datetime]:
    """
    Calculate the next N posting datetimes based on persona schedule.
    
    Args:
        assigned_days: List of day names (e.g., ["Mon", "Wed", "Fri"])
        posting_time_slots: List of time strings (e.g., ["09:00"])
        timezone_str: Timezone string (e.g., "Asia/Dhaka")
        count: Number of datetimes to calculate (default 7)
        from_time: Starting time (defaults to now)
    
    Returns:
        List of UTC datetimes for the next N posting slots
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from datetime import time as dt_time
    
    if from_time is None:
        from_time = datetime.utcnow()
    
    try:
        tz = ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    
    # Convert to local timezone
    local_from = from_time.replace(tzinfo=timezone.utc).astimezone(tz)
    
    # Parse time slots
    time_slots = []
    for slot in posting_time_slots:
        try:
            time_slots.append(dt_time.fromisoformat(slot))
        except ValueError:
            continue
    
    if not time_slots:
        time_slots = [dt_time(9, 0)]  # Default to 9:00 AM
    
    # Map day names to weekday numbers
    day_map = {
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    }
    target_days = [day_map[d.lower()] for d in assigned_days if d.lower() in day_map]
    
    if not target_days:
        target_days = [0, 1, 2, 3, 4, 5, 6]  # Default to all days
    
    # Calculate next N datetimes
    datetimes = []
    current = local_from + timedelta(minutes=1)  # Start from next minute
    
    while len(datetimes) < count:
        # Check if current day is a target day
        if current.weekday() in target_days:
            # Check each time slot
            for slot in time_slots:
                slot_time = current.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
                
                # Only add if slot time is in the future
                if slot_time > local_from:
                    # Convert back to UTC
                    utc_time = slot_time.astimezone(timezone.utc).replace(tzinfo=None)
                    datetimes.append(utc_time)
                    
                    if len(datetimes) >= count:
                        break
        
        # Move to next day
        current = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    return datetimes


def _print_qstash_config_status() -> None:
    print("QStash configuration:")
    token_ok = "OK" if QSTASH_TOKEN else "MISSING"
    print(f"  [{token_ok}] QSTASH_TOKEN {'loaded' if QSTASH_TOKEN else 'is missing'}")
    cur_ok = "OK" if QSTASH_CURRENT_SIGNING_KEY else "MISSING"
    print(f"  [{cur_ok}] QSTASH_CURRENT_SIGNING_KEY {'loaded' if QSTASH_CURRENT_SIGNING_KEY else 'is missing — webhook signatures will NOT be verified'}")
    nxt_ok = "OK" if QSTASH_NEXT_SIGNING_KEY else "MISSING"
    print(f"  [{nxt_ok}] QSTASH_NEXT_SIGNING_KEY {'loaded' if QSTASH_NEXT_SIGNING_KEY else 'is missing — webhook signatures will NOT be verified'}")
    if QStash is None:
        print("  [MISSING] qstash package is not installed (run: pip install upstash-qstash)")
    if QStashReceiver is None:
        print("  [MISSING] QStash Receiver not available — signature verification disabled")

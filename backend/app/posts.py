from datetime import date, datetime, time, timezone
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from app import models
from app.config import FACEBOOK_GRAPH_API_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL
from app.database import SessionLocal


posting_lock = Lock()
user_posting_locks: set[int] = set()


def build_post_prompt(niche: str) -> str:
    return (
        f"Write a short, engaging Facebook post about {niche}. "
        "Keep it under 150 words, ask a question, include 2 relevant hashtags."
    )


def generate_post_content(niche: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You write concise, friendly social media posts.",
            },
            {"role": "user", "content": build_post_prompt(niche)},
        ],
        temperature=0.8,
        max_tokens=220,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI returned empty content")
    return content.strip()


def get_user_schedule_and_connection(
    db: Session,
    user_id: int,
) -> tuple[models.Schedule, models.FacebookConnection]:
    schedule = db.query(models.Schedule).filter(models.Schedule.user_id == user_id).first()
    if schedule is None:
        raise ValueError("Schedule not found")

    connection = (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == user_id)
        .first()
    )
    if connection is None:
        raise ValueError("Facebook connection not found")

    return schedule, connection


def create_draft_post(
    db: Session,
    user_id: int,
    content: str,
    connection_id: int,
) -> models.PostLog:
    post_log = models.PostLog(
        user_id=user_id,
        facebook_connection_id=connection_id,
        content=content,
        status="draft",
    )
    db.add(post_log)
    db.commit()
    db.refresh(post_log)
    return post_log


async def publish_post_to_facebook(
    db: Session,
    post_log: models.PostLog,
    connection: models.FacebookConnection,
    post_date: date | None = None,
) -> bool:
    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        response = await client.post(
            f"{connection.page_id}/feed",
            params={
                "message": post_log.content,
                "access_token": connection.page_access_token,
            },
        )

    if response.status_code < 400:
        posted_at = datetime.now(timezone.utc)
        post_log.status = "success"
        post_log.error_message = None
        post_log.posted_at = posted_at
        post_log.post_date = post_date or posted_at.date()
        db.commit()
        return True

    post_log.status = "failed"
    post_log.error_message = response.text
    db.commit()
    return False


def already_posted_today(db: Session, user_id: int, today: date) -> bool:
    return (
        db.query(models.PostLog)
        .filter(
            models.PostLog.user_id == user_id,
            models.PostLog.status == "success",
            models.PostLog.post_date == today,
        )
        .first()
        is not None
    )


def schedule_matches_now(schedule: models.Schedule, now_utc: datetime) -> tuple[bool, date]:
    try:
        schedule_timezone = ZoneInfo(schedule.timezone)
    except ZoneInfoNotFoundError:
        schedule_timezone = ZoneInfo("UTC")

    local_now = now_utc.astimezone(schedule_timezone)
    try:
        scheduled_time = time.fromisoformat(schedule.post_time)
    except ValueError:
        return False, local_now.date()

    scheduled_now = local_now.replace(
        hour=scheduled_time.hour,
        minute=scheduled_time.minute,
        second=0,
        microsecond=0,
    )
    seconds_since_scheduled_time = (local_now - scheduled_now).total_seconds()
    return 0 <= seconds_since_scheduled_time < 600, local_now.date()


def try_claim_user_posting(user_id: int) -> bool:
    with posting_lock:
        if user_id in user_posting_locks:
            return False
        user_posting_locks.add(user_id)
        return True


def release_user_posting(user_id: int) -> None:
    with posting_lock:
        user_posting_locks.discard(user_id)


async def run_scheduled_posts() -> None:
    now_utc = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        schedules = db.query(models.Schedule).filter(models.Schedule.active.is_(True)).all()
        for schedule in schedules:
            should_post, local_today = schedule_matches_now(schedule, now_utc)
            if not should_post or not try_claim_user_posting(schedule.user_id):
                continue

            try:
                if already_posted_today(db, schedule.user_id, local_today):
                    continue

                connection = (
                    db.query(models.FacebookConnection)
                    .filter(models.FacebookConnection.user_id == schedule.user_id)
                    .first()
                )
                if connection is None:
                    continue

                content = generate_post_content(schedule.niche)
                post_log = create_draft_post(
                    db,
                    schedule.user_id,
                    content,
                    connection.id,
                )
                await publish_post_to_facebook(db, post_log, connection, local_today)
            finally:
                release_user_posting(schedule.user_id)
    finally:
        db.close()

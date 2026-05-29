from datetime import date, datetime, time, timezone
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy.orm import Session

from app import models
from app.config import (
    ANTHROPIC_API_BASE_URL,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    FACEBOOK_GRAPH_API_BASE_URL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from app.crypto import decrypt_token
from app.database import SessionLocal
from app.mistral_service import generate_ai_facebook_post, generate_ai_facebook_post_from_prompt, check_post_quality, extract_post_topic
from app.learning.service import build_learning_prompt_hint, build_strategy_prompt_hint, should_persona_post_now, user_has_learning_access


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

    from openai import OpenAI

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


async def generate_caption_with_claude(prompt: str | None = None) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    user_prompt = (
        prompt.strip()
        if prompt and prompt.strip()
        else "Write a concise, engaging Facebook caption for a small business page."
    )

    async with httpx.AsyncClient(
        base_url=ANTHROPIC_API_BASE_URL,
        timeout=45,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    ) as client:
        response = await client.post(
            "/messages",
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 260,
                "temperature": 0.8,
                "system": (
                    "You write polished Facebook captions. Return only the caption, "
                    "with no labels or commentary."
                ),
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )

    if response.status_code >= 400:
        raise RuntimeError("Claude caption request failed")

    data = response.json()
    blocks = data.get("content", [])
    caption = "".join(
        block.get("text", "")
        for block in blocks
        if block.get("type") == "text"
    ).strip()
    if not caption:
        raise RuntimeError("Claude returned empty content")
    return caption


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
    params = {
        "access_token": decrypt_token(connection.page_access_token),
    }
    endpoint = f"{connection.page_id}/feed"
    
    # Check if there is an image from the media library
    image_url = None
    if post_log.media_library_id:
        media = db.query(models.MediaLibrary).filter(models.MediaLibrary.id == post_log.media_library_id).first()
        if media and media.image_url:
            image_url = media.image_url
            # Mark image as used
            media.is_used = True
            db.commit()

    if image_url:
        params["message"] = post_log.content
        params["url"] = image_url
        endpoint = f"{connection.page_id}/photos"
    else:
        params["message"] = post_log.content
        if post_log.link_url:
            params["link"] = post_log.link_url
        elif post_log.media_urls and post_log.media_urls[0]:
            params["link"] = post_log.media_urls[0]

    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        response = await client.post(
            endpoint,
            data=params,
        )

    if response.status_code < 400:
        data = response.json()
        posted_at = datetime.now(timezone.utc)
        post_log.status = "published"
        post_log.error_message = None
        post_log.posted_at = posted_at
        post_log.post_date = post_date or posted_at.date()
        post_log.facebook_post_id = data.get("id")
        db.commit()
        return True

    error_message = _facebook_publish_error_message(response)
    if _facebook_error_code(response) == 190:
        connection.connection_status = "needs-reconnection"

    post_log.status = "failed"
    post_log.error_message = error_message
    post_log.retry_count += 1
    db.commit()
    return False


def _facebook_error_code(response: httpx.Response) -> int | None:
    try:
        import json
        return json.loads(response.text).get("error", {}).get("code")
    except Exception:
        return None


def _facebook_publish_error_message(response: httpx.Response) -> str:
    error_text = response.text
    try:
        import json
        data = json.loads(error_text)
        error_data = data.get("error", {})
        error_code = error_data.get("code")
        error_message = error_data.get("message") or error_text
    except Exception:
        error_code = None
        error_message = error_text

    if error_code == 190:
        return "Your Facebook connection has expired. Please reconnect your page."
    if error_code == 200:
        return (
            "Permission error. Reconnect your Facebook page and approve "
            "pages_read_engagement and pages_manage_posts with admin access."
        )
    return error_message


async def publish_message_to_facebook(
    db: Session,
    user_id: int,
    connection: models.FacebookConnection,
    message: str,
    media_urls: list[str] | None = None,
    link_url: str | None = None,
    link_preview_data: dict | None = None,
) -> tuple[bool, models.PostLog, str | None]:
    params = {
        "message": message,
        "access_token": decrypt_token(connection.page_access_token),
    }
    if link_url:
        params["link"] = link_url
    elif media_urls and media_urls[0]:
        params["link"] = media_urls[0]

    post_log = models.PostLog(
        user_id=user_id,
        facebook_connection_id=connection.id,
        content=message,
        status="draft",
        media_urls=media_urls or [],
        link_url=link_url,
        link_preview_data=link_preview_data,
    )
    db.add(post_log)
    db.flush()

    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        response = await client.post(f"{connection.page_id}/feed", data=params)

    if response.status_code < 400:
        data = response.json()
        facebook_post_id = data.get("id")
        posted_at = datetime.now(timezone.utc)
        post_log.status = "published"
        post_log.error_message = None
        post_log.posted_at = posted_at
        post_log.post_date = posted_at.date()
        post_log.facebook_post_id = facebook_post_id
        db.commit()
        db.refresh(post_log)
        post_url = f"https://www.facebook.com/{facebook_post_id}" if facebook_post_id else None
        return True, post_log, post_url

    error_code = _facebook_error_code(response)
    error_message = _facebook_publish_error_message(response)

    if error_code == 190:
        connection.connection_status = "needs-reconnection"

    post_log.status = "failed"
    post_log.error_message = error_message
    post_log.retry_count += 1
    db.commit()
    db.refresh(post_log)
    return False, post_log, None


def already_posted_today(db: Session, user_id: int, today: date) -> bool:
    return (
        db.query(models.PostLog)
        .filter(
            models.PostLog.user_id == user_id,
            models.PostLog.status.in_(["published", "success"]),
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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def run_scheduled_posts() -> None:
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc)
    print(f"Scheduler triggered via cron endpoint at {now_utc}")
    db = SessionLocal()
    try:
        due_posts = (
            db.query(models.PostLog)
            .filter(
                models.PostLog.status == "scheduled",
                models.PostLog.scheduled_at <= now_utc,
            )
            .all()
        )
        cutoff_time = now_utc - timedelta(hours=12)
        for post_log in due_posts:
            scheduled_at = _as_utc(post_log.scheduled_at)
            if scheduled_at is None:
                post_log.status = "failed"
                post_log.error_message = "Scheduled post is missing a scheduled time."
                db.commit()
                continue

            if scheduled_at < cutoff_time:
                post_log.status = "missed"
                post_log.error_message = "Post missed its scheduling window (older than 12 hours)."
                db.commit()
                print(f"Marked post {post_log.id} as missed (scheduled at {post_log.scheduled_at})")
                continue

            connection = db.get(models.FacebookConnection, post_log.facebook_connection_id)
            if connection is None or connection.connection_status != "connected":
                post_log.status = "failed"
                post_log.error_message = "Facebook page is not connected"
                db.commit()
                continue
            post_log.status = "publishing"
            db.commit()
            await publish_post_to_facebook(db, post_log, connection)

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

        await run_auto_ai_posts(db, now_utc)
    finally:
        db.close()


def _local_now_for_user(user: models.User, now_utc: datetime) -> datetime:
    try:
        return now_utc.astimezone(ZoneInfo(user.timezone))
    except ZoneInfoNotFoundError:
        return now_utc.astimezone(ZoneInfo("UTC"))


def _persona_matches_current_slot(persona: models.AIPersona, local_now: datetime) -> bool:
    if local_now.strftime("%a") not in persona.assigned_days.split(","):
        return False
    for slot in persona.posting_time_slots or []:
        try:
            slot_time = time.fromisoformat(slot)
        except ValueError:
            continue
        scheduled_at = local_now.replace(hour=slot_time.hour, minute=slot_time.minute, second=0, microsecond=0)
        if 0 <= (local_now - scheduled_at).total_seconds() < 300:
            return True
    return False


def _persona_priority_value(persona: models.AIPersona) -> int:
    return {"High": 3, "Normal": 2, "Low": 1}.get(persona.priority_level, 2)


async def run_auto_ai_posts(db: Session, now_utc: datetime) -> None:
    page_ids = [
        row[0]
        for row in db.query(models.AIPersona.page_connection_id)
        .filter(models.AIPersona.is_active.is_(True))
        .distinct()
        .all()
    ]
    for page_id in page_ids:
        connection = db.get(models.FacebookConnection, page_id)
        user = db.get(models.User, connection.user_id) if connection else None
        if connection is None or user is None or connection.connection_status != "connected":
            continue

        local_now = _local_now_for_user(user, now_utc)
        matching_personas = [
            persona
            for persona in db.query(models.AIPersona)
            .filter(
                models.AIPersona.page_connection_id == connection.id,
                models.AIPersona.is_active.is_(True),
            )
            .all()
            if _persona_matches_current_slot(persona, local_now)
        ]
        if user_has_learning_access(user):
            matching_personas = [persona for persona in matching_personas if should_persona_post_now(persona)]
        if not matching_personas:
            continue
        settings = sorted(
            matching_personas,
            key=lambda persona: (_persona_priority_value(persona), float(persona.performance_score or 0)),
            reverse=True,
        )[0]

        try:
            # Fix 6 — Topic rotation: fetch last 5 topics for this page
            recent_topics = [
                row[0]
                for row in db.query(models.PostLog.topic)
                .filter(
                    models.PostLog.facebook_connection_id == connection.id,
                    models.PostLog.topic.isnot(None),
                )
                .order_by(models.PostLog.created_at.desc())
                .limit(5)
                .all()
            ]

            # Fix 7 — Quality score check loop (up to 3 attempts)
            content = ""
            max_attempts = 3
            for attempt in range(max_attempts):
                hint_parts = [
                    build_learning_prompt_hint(db, settings) if user_has_learning_access(user) else None,
                    build_strategy_prompt_hint(db, settings),
                ]
                learning_hint = " ".join(part for part in hint_parts if part)
                if settings.custom_prompt and settings.custom_prompt.strip():
                    content = generate_ai_facebook_post_from_prompt(
                        settings.custom_prompt,
                        settings.creativity_level,
                        recent_topics,
                        None,
                        learning_hint,
                    )
                else:
                    content = generate_ai_facebook_post(
                        settings.niche,
                        [tag.strip() for tag in settings.tone_tags.split(",") if tag.strip()],
                        settings.custom_instructions,
                        settings.language,
                        settings.hashtags_enabled,
                        settings.hashtag_count,
                        settings.always_include_engagement_hook,
                        recent_topics,
                        learning_hint,
                    )
                score = check_post_quality(content)
                if score >= 6:
                    break
                print(f"Auto post scored {score}/10 (below 6), regenerating (attempt {attempt + 1}/{max_attempts})...")

            # Extract topic for rotation memory
            topic = extract_post_topic(content)

            post_log = models.PostLog(
                user_id=settings.user_id,
                facebook_connection_id=connection.id,
                content=content,
                status="draft",
                ai_generated=True,
                auto_generated=True,
                ai_persona_id=settings.id,
                topic=topic,
            )
            db.add(post_log)
            db.flush()

            # Optional: Image Generation Layer
            if settings.include_image:
                import time
                from app.routers.images import async_upload_to_supabase
                from app.providers.image_providers import get_image_provider_for_user
                
                # Check frequency
                total_posts = settings.total_posts_published
                should_generate = False
                freq = settings.image_frequency
                if freq == "every_post":
                    should_generate = True
                elif freq == "every_other" and total_posts % 2 == 1:
                    should_generate = True
                elif freq == "1_in_3" and total_posts % 3 == 2:
                    should_generate = True
                elif freq == "1_in_5" and total_posts % 5 == 4:
                    should_generate = True
                elif freq == "weekends_only" and local_now.weekday() >= 5:
                    should_generate = True

                if should_generate:
                    image_prompt = None
                    if settings.image_prompt_source == "persona_prompt":
                        psettings = db.query(models.ImagePromptSettings).filter(models.ImagePromptSettings.persona_id == settings.id).first()
                        if psettings and psettings.assembled_prompt:
                            image_prompt = psettings.assembled_prompt
                    elif settings.image_prompt_source == "generate_from_post":
                        from app.providers.llm_providers import generate_text_for_user
                        sys_p = "You are an expert at writing prompts for AI image generation. Given a social media post text, write a detailed image generation prompt that would create the perfect visual to accompany that post. The image should enhance the post's message without containing any text. Return only the image generation prompt, nothing else, maximum 150 words."
                        image_prompt = generate_text_for_user(
                            user_id=settings.user_id,
                            task_category="image_prompt_generation",
                            prompt=content,
                            system_prompt=sys_p,
                            db=db,
                            temperature=0.7,
                            max_tokens=200,
                        )
                        if image_prompt:
                            image_prompt = image_prompt.strip()
                    elif settings.image_prompt_source == "library_image":
                        oldest_unused = db.query(models.MediaLibrary).filter(
                            models.MediaLibrary.persona_id == settings.id,
                            models.MediaLibrary.is_used == False
                        ).order_by(models.MediaLibrary.created_at.asc()).first()
                        if oldest_unused:
                            post_log.media_library_id = str(oldest_unused.id)
                        else:
                            # Fallback to generate_from_post
                            from app.providers.llm_providers import generate_text_for_user
                            sys_p = "You are an expert at writing prompts for AI image generation. Given a social media post text, write a detailed image generation prompt that would create the perfect visual to accompany that post. The image should enhance the post's message without containing any text. Return only the image generation prompt, nothing else, maximum 150 words."
                            image_prompt = generate_text_for_user(
                                user_id=settings.user_id,
                                task_category="image_prompt_generation",
                                prompt=content,
                                system_prompt=sys_p,
                                db=db,
                                temperature=0.7,
                                max_tokens=200,
                            )
                            if image_prompt:
                                image_prompt = image_prompt.strip()

                    if image_prompt and not post_log.media_library_id:
                        provider_inst, model_name, api_key = get_image_provider_for_user(settings.user_id, db)
                        provider_name = provider_inst.__class__.__name__.replace('Provider', '').lower()
                        start_img_t = time.time()
                        try:
                            import asyncio
                            import uuid
                            async def _gen():
                                return await asyncio.to_thread(
                                    provider_inst.generate,
                                    prompt=image_prompt,
                                    negative_prompt="",
                                    aspect_ratio="1:1",
                                    model_name=model_name,
                                    api_key=api_key,
                                )
                            img_bytes = await asyncio.wait_for(_gen(), timeout=settings.image_max_wait_seconds)
                            job_id_str = str(uuid.uuid4())
                            filename = f"{settings.user_id}/{job_id_str}.png"
                            pub_url = await async_upload_to_supabase(filename, img_bytes)
                            
                            media = models.MediaLibrary(
                                user_id=settings.user_id,
                                persona_id=settings.id,
                                image_url=pub_url,
                                storage_path=filename,
                                generation_prompt=image_prompt,
                                provider=provider_name,
                                model_name=model_name,
                            )
                            db.add(media)
                            db.flush()
                            post_log.media_library_id = str(media.id)
                            elapsed = int(time.time() - start_img_t)
                            print(f"Auto image generation for persona {settings.name}: provider={provider_name} status=success seconds={elapsed}")
                        except asyncio.TimeoutError:
                            elapsed = int(time.time() - start_img_t)
                            print(f"Auto image generation for persona {settings.name}: provider={provider_name} status=timeout seconds={elapsed}")
                            if settings.image_fallback_policy == "skip_post":
                                post_log.status = "missed"
                                post_log.error_message = "image_generation_failed (timeout)"
                                db.commit()
                                continue
                            elif settings.image_fallback_policy == "use_library":
                                any_unused = db.query(models.MediaLibrary).filter(
                                    models.MediaLibrary.user_id == settings.user_id,
                                    models.MediaLibrary.is_used == False
                                ).order_by(models.MediaLibrary.created_at.asc()).first()
                                if any_unused:
                                    post_log.media_library_id = str(any_unused.id)
                        except Exception as e:
                            elapsed = int(time.time() - start_img_t)
                            print(f"Auto image generation for persona {settings.name}: provider={provider_name} status=failed seconds={elapsed}")
                            if settings.image_fallback_policy == "skip_post":
                                post_log.status = "missed"
                                post_log.error_message = "image_generation_failed (error)"
                                db.commit()
                                continue
                            elif settings.image_fallback_policy == "use_library":
                                any_unused = db.query(models.MediaLibrary).filter(
                                    models.MediaLibrary.user_id == settings.user_id,
                                    models.MediaLibrary.is_used == False
                                ).order_by(models.MediaLibrary.created_at.asc()).first()
                                if any_unused:
                                    post_log.media_library_id = str(any_unused.id)

            success = await publish_post_to_facebook(db, post_log, connection, local_now.date())
            settings.last_auto_post_at = now_utc
            settings.consecutive_failures = 0 if success else settings.consecutive_failures + 1
            if success:
                settings.total_posts_published += 1
            db.commit()
        except Exception as exc:
            settings.consecutive_failures += 1
            db.commit()
            print(f"Auto AI posting failed for page {settings.page_connection_id}: {exc}")
            if settings.consecutive_failures >= 3:
                print(
                    "Auto AI posting has failed three times for "
                    f"user {settings.user_id}, page {settings.page_connection_id}. "
                    "Email notification is not configured."
                )

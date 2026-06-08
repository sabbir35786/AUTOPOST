"""Shared persona publish flow used by tests, manual publish, and scheduler slots."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.mistral_service import extract_post_topic
from app.posts import generate_persona_post_with_user_model, publish_post_to_facebook
from app.services.publish_image_service import maybe_generate_image_for_post

logger = logging.getLogger(__name__)


async def run_full_publish_flow(
    persona_id: int,
    db: Session,
    is_test: bool = False,
    slot: models.ScheduledSlot | None = None,
    force_image: bool = False,
) -> dict:
    """Generate persona content, optionally prepare an image, and optionally publish."""
    persona = db.get(models.AIPersona, persona_id)
    if not persona:
        msg = f"Persona {persona_id} not found"
        logger.error("[Publish] %s", msg)
        _fail_slot(db, slot, msg)
        return {"status": "failed", "error_message": msg}

    logger.info(
        "[Publish] Starting full publish flow persona_id=%s persona=%s is_test=%s slot_id=%s",
        persona.id,
        persona.persona_name,
        is_test,
        getattr(slot, "id", None),
    )
    print(f"[Publish] Starting full publish flow for persona '{persona.persona_name}' (id={persona.id})")

    connection = db.get(models.FacebookConnection, persona.page_connection_id)
    if not connection or connection.connection_status != "connected":
        msg = f"Facebook page is not connected for persona '{persona.persona_name}'"
        logger.error("[Publish] %s", msg)
        _fail_slot(db, slot, msg)
        return {"status": "failed", "error_message": msg}

    try:
        post_content = generate_persona_post_with_user_model(db, persona, [])
    except Exception as exc:
        msg = f"Post text generation failed: {exc}"
        logger.exception("[Publish] Post generation failed persona_id=%s", persona.id)
        _fail_slot(db, slot, msg)
        return {"status": "failed", "error_message": msg}

    topic = extract_post_topic(post_content)
    post_log = models.PostLog(
        user_id=persona.user_id,
        facebook_connection_id=persona.page_connection_id,
        ai_persona_id=persona.id,
        content=post_content,
        status="draft" if is_test else "scheduled",
        delivery_status="pending",
        auto_generated=not is_test,
        ai_generated=True,
        topic=topic,
        scheduled_at=slot.scheduled_at if slot else None,
    )
    db.add(post_log)
    db.flush()
    logger.info("[Publish] Draft post created post_id=%s persona_id=%s", post_log.id, persona.id)

    template_name = _prepare_assigned_template_settings(db, persona)
    image_url: str | None = None
    image_error: str | None = None

    # Log image generation settings
    logger.info(
        "[Publish] Image generation check: include_image=%s, template_image_enabled=%s, template_name=%s",
        persona.include_image,
        persona.template_image_generation_enabled,
        template_name,
    )
    print(f"[Publish] Image check for persona '{persona.persona_name}': include_image={persona.include_image}, template_enabled={persona.template_image_generation_enabled}")

    template_decisions: dict = {}
    try:
        skip_reason = await maybe_generate_image_for_post(db, persona, post_log, force_image=force_image, out_decisions=template_decisions)
        if skip_reason:
            post_log.status = "missed" if not is_test else "draft"
            post_log.error_message = skip_reason
            db.commit()
            _fail_slot(db, slot, skip_reason)
            logger.error("[Publish] Image policy skipped post_id=%s reason=%s", post_log.id, skip_reason)
            return {"status": "failed", "post_id": post_log.id, "error_message": skip_reason}
        logger.info("[Publish] Image generation completed successfully for post_id=%s", post_log.id)
    except Exception as exc:
        image_error = str(getattr(exc, "detail", None) or exc)
        logger.exception("[Publish] Image generation failed post_id=%s", post_log.id)
        if persona.image_fallback_policy == "skip_post":
            post_log.status = "missed" if not is_test else "draft"
            post_log.error_message = image_error
            db.commit()
            _fail_slot(db, slot, image_error)
            return {"status": "failed", "post_id": post_log.id, "error_message": image_error}

    if post_log.media_library_id:
        media = db.get(models.MediaLibrary, post_log.media_library_id)
        image_url = media.image_url if media else None
    if not image_url and post_log.image_url:
        image_url = post_log.image_url

    db.commit()
    db.refresh(post_log)

    if is_test:
        logger.info("[Publish] Test flow complete post_id=%s persona_id=%s", post_log.id, persona.id)
        return {
            "status": "generated",
            "post_id": post_log.id,
            "content": post_content,
            "image_url": image_url,
            "image_error": image_error,
            "template_name": template_name,
            "persona_name": persona.persona_name,
            "template_decisions": template_decisions,
        }

    if slot:
        slot.status = "publishing"
        slot.post_id = post_log.id

    post_log.status = "publishing"
    post_log.delivery_status = "delivering"
    db.commit()

    try:
        logger.info(
            "[Publish] Publishing post_id=%s persona_id=%s page=%s",
            post_log.id,
            persona.id,
            connection.page_name,
        )
        success = await publish_post_to_facebook(db, post_log, connection)
        if not success:
            raise RuntimeError(post_log.error_message or "Facebook publish returned False")

        persona.total_posts_published = (persona.total_posts_published or 0) + 1
        persona.last_auto_post_at = datetime.now(timezone.utc)
        persona.consecutive_failures = 0

        if slot:
            slot.status = "published"
            slot.error_message = None

        post_log.delivery_status = "delivered"
        db.commit()
        db.refresh(post_log)

        fb_post_id = post_log.facebook_post_id or ""
        logger.info("[Publish] Published post_id=%s facebook_post_id=%s", post_log.id, fb_post_id)
        print(f"[Publish] Published successfully. Facebook post ID: {fb_post_id}")
        return {
            "status": "published",
            "post_id": post_log.id,
            "content": post_content,
            "image_url": image_url,
            "facebook_post_id": fb_post_id,
            "facebook_post_url": f"https://www.facebook.com/{fb_post_id}" if fb_post_id else None,
        }
    except Exception as exc:
        error_msg = str(exc)
        db.rollback()

        reloaded_slot = db.get(models.ScheduledSlot, slot.id) if slot and slot.id else None
        reloaded_post = db.get(models.PostLog, post_log.id) if post_log and post_log.id else None

        if reloaded_post and reloaded_post.status in ("published", "success") and reloaded_post.facebook_post_id:
            if reloaded_slot:
                reloaded_slot.status = "published"
                reloaded_slot.post_id = reloaded_post.id
                reloaded_slot.error_message = None
            db.commit()
            return {
                "status": "published",
                "post_id": reloaded_post.id,
                "content": post_content,
                "image_url": image_url,
                "facebook_post_id": reloaded_post.facebook_post_id,
                "recovered": True,
            }

        if reloaded_post:
            reloaded_post.status = "failed"
            reloaded_post.delivery_status = "failed"
            reloaded_post.error_message = error_msg
            reloaded_post.publish_error = error_msg
        if reloaded_slot:
            reloaded_slot.status = "failed"
            reloaded_slot.error_message = error_msg
        persona.consecutive_failures = (persona.consecutive_failures or 0) + 1
        db.commit()

        logger.exception("[Publish] Facebook publish failed post_id=%s", getattr(post_log, "id", None))
        print(f"[Publish] Failed at Facebook publish for persona '{persona.persona_name}': {error_msg}")
        return {
            "status": "failed",
            "error_message": error_msg,
            "post_id": reloaded_post.id if reloaded_post else None,
        }


def _prepare_assigned_template_settings(db: Session, persona: models.AIPersona) -> str | None:
    assignment = (
        db.query(models.PersonaImageTemplateAssignment)
        .filter(models.PersonaImageTemplateAssignment.persona_id == persona.id)
        .first()
    )
    if not assignment:
        return None

    template = db.get(models.ImageTemplate, assignment.image_template_id)
    if not template:
        return None

    settings = (
        db.query(models.ImagePromptSettings)
        .filter(models.ImagePromptSettings.persona_id == persona.id)
        .first()
    )
    if settings is None:
        settings = models.ImagePromptSettings(
            persona_id=persona.id,
            user_id=persona.user_id,
        )
        db.add(settings)

    if not settings.template_layers_json:
        settings.template_layers_json = template.template_json
    if persona.template_logo_url and not settings.template_logo_url:
        settings.template_logo_url = persona.template_logo_url
    db.flush()
    return template.name


def _fail_slot(db: Session, slot: models.ScheduledSlot | None, message: str) -> None:
    if slot:
        slot.status = "failed"
        slot.error_message = message
        db.commit()

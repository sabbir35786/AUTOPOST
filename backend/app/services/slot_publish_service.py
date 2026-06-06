"""Publish flow for persona scheduled slots (QStash webhook + cron fallback)."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.posts import generate_persona_post_with_user_model, publish_post_to_facebook
from app.services.publish_image_service import maybe_generate_image_for_post


async def execute_slot_publish(db: Session, slot: models.ScheduledSlot) -> dict:
    """
    Generate content, optional image, publish to Facebook, update slot + post_log.
    Idempotent if slot is already published.
    """
    if slot.status == "published":
        return {"status": "already_published", "slot_id": str(slot.id)}

    if slot.post_id:
        existing_post = db.get(models.PostLog, slot.post_id)
        if existing_post and existing_post.status in ("published", "success"):
            slot.status = "published"
            db.commit()
            return {"status": "already_published", "post_id": existing_post.id}

    persona_id = slot.persona_id
    persona = db.get(models.AIPersona, persona_id)
    if not persona:
        slot.status = "failed"
        slot.error_message = "Persona not found"
        db.commit()
        return {"status": "failed", "reason": "Persona not found"}

    connection = db.get(models.FacebookConnection, persona.page_connection_id)
    if not connection or connection.connection_status != "connected":
        slot.status = "failed"
        slot.error_message = "Facebook page is not connected"
        db.commit()
        return {"status": "failed", "reason": slot.error_message}

    slot.status = "generating"
    db.commit()

    post_log = None
    try:
        print(f"[Publish] Generating post for persona {persona_id} slot {slot.id}")
        post_content = generate_persona_post_with_user_model(db, persona, [])

        post_log = models.PostLog(
            user_id=persona.user_id,
            facebook_connection_id=persona.page_connection_id,
            ai_persona_id=persona.id,
            content=post_content,
            status="publishing",
            delivery_status="delivering",
            auto_generated=True,
            ai_generated=True,
        )
        db.add(post_log)
        db.flush()

        skip_reason = await maybe_generate_image_for_post(db, persona, post_log)
        if skip_reason:
            # Image generation failed — log it but continue publishing without an image
            print(f"[Publish] Image generation skipped for persona {persona_id}: {skip_reason} — continuing without image")

        print(f"[Publish] Publishing to Facebook for persona {persona_id}")
        success = await publish_post_to_facebook(db, post_log, connection)
        if not success:
            raise RuntimeError(f"Facebook publish failed: {post_log.error_message}")

        post_log.status = "published"
        post_log.delivery_status = "delivered"
        persona.total_posts_published = (persona.total_posts_published or 0) + 1
        persona.last_auto_post_at = datetime.now(timezone.utc)

        slot.status = "published"
        slot.post_id = post_log.id
        slot.error_message = None
        db.commit()

        print(f"[Publish] Successfully published persona {persona_id} post {post_log.id}")
        return {"status": "published", "post_id": post_log.id}

    except Exception as exc:
        db.rollback()
        slot = db.get(models.ScheduledSlot, slot.id)
        post_log = db.get(models.PostLog, post_log.id) if post_log and post_log.id else None

        if post_log and post_log.status in ("published", "success") and post_log.facebook_post_id:
            slot.status = "published"
            slot.post_id = post_log.id
            slot.error_message = None
            db.commit()
            return {"status": "published", "post_id": post_log.id, "recovered": True}

        slot.status = "failed"
        slot.error_message = str(exc)
        db.commit()
        print(f"[Publish] Failed persona {persona_id} slot {slot.id}: {exc}")
        return {"status": "failed", "reason": str(exc)}

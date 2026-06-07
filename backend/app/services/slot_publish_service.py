"""Publish flow for persona scheduled slots."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.services.publish_flow import run_full_publish_flow


async def prepare_slot_publish(db: Session, slot: models.ScheduledSlot) -> dict:
    """Generate content ahead of time using the same full-flow generator."""
    if slot.status != "pending":
        return {"status": "skipped", "reason": f"Slot is in {slot.status} status"}

    persona = db.get(models.AIPersona, slot.persona_id)
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

    try:
        result = await run_full_publish_flow(
            persona_id=persona.id,
            db=db,
            is_test=True,
            slot=slot,
        )

        if result.get("status") == "failed":
            slot = db.get(models.ScheduledSlot, slot.id)
            slot.status = "failed"
            slot.error_message = result.get("error_message", "Pre-generation failed")
            db.commit()
            return {"status": "failed", "reason": slot.error_message}

        post_id = result.get("post_id")
        slot = db.get(models.ScheduledSlot, slot.id)
        slot.status = "generated"
        slot.post_id = post_id
        slot.error_message = None
        db.commit()
        return {"status": "generated", "post_id": post_id}
    except Exception as exc:
        db.rollback()
        slot = db.get(models.ScheduledSlot, slot.id)
        slot.status = "failed"
        slot.error_message = f"Preparation failed: {exc}"
        db.commit()
        return {"status": "failed", "reason": str(exc)}


async def execute_slot_publish(db: Session, slot: models.ScheduledSlot) -> dict:
    """
    At the exact scheduled time, run the same test-full-flow generation path,
    then immediately publish that generated draft to Facebook.
    """
    if slot.status == "published":
        return {"status": "already_published", "slot_id": str(slot.id)}

    persona = db.get(models.AIPersona, slot.persona_id)
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

    slot.status = "publishing"
    db.commit()

    generation = await run_full_publish_flow(
        persona_id=persona.id,
        db=db,
        is_test=True,
        slot=slot,
    )
    if generation.get("status") == "failed":
        slot = db.get(models.ScheduledSlot, slot.id)
        slot.status = "failed"
        slot.error_message = generation.get("error_message", "Full flow generation failed")
        db.commit()
        return {"status": "failed", "reason": slot.error_message}

    post_log = db.get(models.PostLog, generation.get("post_id"))
    if not post_log:
        slot.status = "failed"
        slot.error_message = "Generated post not found"
        db.commit()
        return {"status": "failed", "reason": slot.error_message}

    from app.posts import publish_post_to_facebook

    try:
        post_log.status = "publishing"
        post_log.delivery_status = "delivering"
        db.commit()

        success = await publish_post_to_facebook(db, post_log, connection)
        if not success:
            raise RuntimeError(post_log.error_message or "Facebook publish failed")

        persona.total_posts_published = (persona.total_posts_published or 0) + 1
        persona.last_auto_post_at = datetime.now(timezone.utc)
        persona.consecutive_failures = 0

        slot.status = "published"
        slot.post_id = post_log.id
        slot.error_message = None
        db.commit()

        return {
            "status": "published",
            "post_id": post_log.id,
            "facebook_post_id": post_log.facebook_post_id,
            "facebook_post_url": (
                f"https://www.facebook.com/{post_log.facebook_post_id}"
                if post_log.facebook_post_id
                else None
            ),
        }
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
        return {"status": "failed", "reason": str(exc)}

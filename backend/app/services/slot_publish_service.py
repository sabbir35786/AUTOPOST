"""Publish flow for persona scheduled slots (QStash webhook + cron fallback)."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.services.publish_flow import run_full_publish_flow


async def prepare_slot_publish(db: Session, slot: models.ScheduledSlot) -> dict:
    """
    Generate content and optional image ahead of time.
    Sets slot status to 'generated'.
    """
    if slot.status != "pending":
        return {"status": "skipped", "reason": f"Slot is in {slot.status} status"}

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

    try:
        print(f"[Publish] Pre-generating post for persona {persona_id} slot {slot.id}")

        # Use the shared publish flow in test mode so it generates but doesn't publish
        result = await run_full_publish_flow(
            persona_id=persona_id,
            db=db,
            is_test=True,
            slot=None,
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
        print(f"[Publish] Failed preparing persona {persona_id} slot {slot.id}: {exc}")
        return {"status": "failed", "reason": str(exc)}


async def execute_slot_publish(db: Session, slot: models.ScheduledSlot) -> dict:
    """
    Publish to Facebook immediately.
    If the slot was not prepared ahead of time, it prepares it first.
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

    if slot.status == "pending":
        # Prepare first if not yet generated
        res = await prepare_slot_publish(db, slot)
        if res.get("status") == "failed":
            return res
        slot = db.get(models.ScheduledSlot, slot.id)

    if slot.status not in ("generated",) and slot.post_id is None:
        return {"status": "failed", "reason": f"Slot is in {slot.status} state without a post_id"}

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

    # If already generated (has post_id), publish the existing post directly
    if slot.post_id:
        from app.posts import publish_post_to_facebook
        post_log = db.get(models.PostLog, slot.post_id)
        if not post_log:
            slot.status = "failed"
            slot.error_message = "Prepared post not found"
            db.commit()
            return {"status": "failed", "reason": "Prepared post not found"}

        post_log.status = "publishing"
        post_log.delivery_status = "delivering"
        slot.status = "publishing"
        db.commit()

        try:
            print(f"[Publish] Publishing to Facebook for persona {persona_id} (pre-generated post {post_log.id})")
            success = await publish_post_to_facebook(db, post_log, connection)
            if not success:
                raise RuntimeError(f"Facebook publish failed: {post_log.error_message}")

            post_log.status = "published"
            post_log.delivery_status = "delivered"
            persona.total_posts_published = (persona.total_posts_published or 0) + 1
            persona.last_auto_post_at = datetime.now(timezone.utc)
            persona.consecutive_failures = 0

            slot.status = "published"
            slot.error_message = None
            db.commit()

            fb_post_id = post_log.facebook_post_id or ""
            print(f"[Publish] Successfully published persona {persona_id} post {post_log.id}. Facebook post ID: {fb_post_id}")
            return {"status": "published", "post_id": post_log.id, "facebook_post_id": fb_post_id}

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
            print(f"[Publish] Failed publishing persona {persona_id} slot {slot.id}: {exc}")
            return {"status": "failed", "reason": str(exc)}

    # Slot is pending but has no post_id — run the full flow (generate + publish)
    result = await run_full_publish_flow(
        persona_id=persona_id,
        db=db,
        is_test=False,
        slot=slot,
    )
    return result

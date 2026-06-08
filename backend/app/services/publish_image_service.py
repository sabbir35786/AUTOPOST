"""Shared image generation logic for auto-publish webhooks."""
import asyncio
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import models
from app.providers.llm_providers import generate_text_for_user


async def maybe_generate_image_for_post(
    db: Session,
    persona: models.AIPersona,
    post_log: models.PostLog,
    force_image: bool = False,
    out_decisions: dict | None = None,
) -> str | None:
    """
    Generate an image for the post when persona settings require it.
    Returns a skip reason string if publishing should be aborted, else None.
    When out_decisions is provided, populates it with LLM template decisions.
    """
    if (not force_image and not persona.include_image) or post_log.media_library_id or post_log.image_url:
        return None

    from app.routers.images import async_upload_to_supabase, generate_template_layered_image
    from app.providers.image_providers import get_image_provider_for_user

    user = db.get(models.User, persona.user_id)
    if not user:
        return None

    local_now = datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone))
    total_posts = persona.total_posts_published or 0
    should_generate = False
    freq = persona.image_frequency
    if freq == "every_post":
        should_generate = True
    elif freq == "every_other" and total_posts % 2 == 0:
        should_generate = True
    elif freq == "1_in_3" and total_posts % 3 == 2:
        should_generate = True
    elif freq == "1_in_5" and total_posts % 5 == 4:
        should_generate = True
    elif freq == "weekends_only" and local_now.weekday() >= 5:
        should_generate = True

    if not should_generate and not force_image:
        return None

    if persona.template_image_generation_enabled:
        assignment = (
            db.query(models.PersonaImageTemplateAssignment)
            .filter(models.PersonaImageTemplateAssignment.persona_id == persona.id)
            .first()
        )
        if assignment:
            try:
                from app.routers.persona_image_templates import _run_post_image_generation
                generation = await _run_post_image_generation(
                    db=db,
                    post_id=post_log.id,
                    user_id=persona.user_id,
                    raise_errors=False,
                )
                if generation and generation.status == "completed" and generation.final_image_url:
                    post_log.image_url = generation.final_image_url
                    if out_decisions is not None and generation.llm_instructions:
                        out_decisions.clear()
                        out_decisions.update({
                            "flow": "prompt_studio",
                            "chosen_background_asset_id": generation.llm_instructions.get("chosen_background_asset_id"),
                            "layers": generation.llm_instructions.get("layers", []),
                        })
                    return None
                error_msg = generation.error_message if generation else "Prompt Studio template generation failed"
                print(f"Prompt Studio image generation for persona {persona.persona_name}: {error_msg}")
                if persona.image_fallback_policy == "skip_post":
                    return f"template_image_generation_failed: {error_msg}"
                if persona.image_fallback_policy == "use_library":
                    _attach_library_image(db, persona, post_log)
                return None
            except Exception as exc:
                exc_str = str(getattr(exc, "detail", None) or exc)
                print(f"Prompt Studio image generation for persona {persona.persona_name}: failed — {exc_str}")
                if persona.image_fallback_policy == "skip_post":
                    return f"template_image_generation_failed: {exc_str}"
                if persona.image_fallback_policy == "use_library":
                    _attach_library_image(db, persona, post_log)
                return None

        # Legacy template flow (via ImagePromptSettings.template_layers_json)
        template_settings = db.query(models.ImagePromptSettings).filter(
            models.ImagePromptSettings.persona_id == persona.id
        ).first()
        if template_settings and template_settings.template_layers_json:
            try:
                media_id, _image_url, decisions = await generate_template_layered_image(
                    persona_id=persona.id,
                    post_text=post_log.content,
                    topic_hint=post_log.topic,
                    db=db,
                    user_id=persona.user_id,
                )
                post_log.media_library_id = media_id
                if out_decisions is not None:
                    out_decisions.update(decisions)
                return None
            except Exception as exc:
                print(f"Template image generation for persona {persona.persona_name}: failed — {exc}")
                if persona.image_fallback_policy == "skip_post":
                    return f"template_image_generation_failed: {exc}"
                if persona.image_fallback_policy == "use_library":
                    _attach_library_image(db, persona, post_log)
                return None

    if post_log.media_library_id:
        return None

    image_prompt = _resolve_image_prompt(db, persona, post_log)
    if not image_prompt:
        if persona.image_prompt_source == "library_image":
            oldest = (
                db.query(models.MediaLibrary)
                .filter(
                    models.MediaLibrary.persona_id == persona.id,
                    models.MediaLibrary.is_used.is_(False),
                )
                .order_by(models.MediaLibrary.created_at.asc())
                .first()
            )
            if oldest:
                post_log.media_library_id = str(oldest.id)
        return None

    provider_inst, model_name, api_key = get_image_provider_for_user(persona.user_id, db)
    provider_name = provider_inst.__class__.__name__.replace("Provider", "").lower()
    start_img_t = time.time()
    try:

        async def _gen():
            return await asyncio.to_thread(
                provider_inst.generate,
                prompt=image_prompt,
                negative_prompt="",
                aspect_ratio="1:1",
                model_name=model_name,
                api_key=api_key,
            )

        img_bytes = await asyncio.wait_for(
            _gen(),
            timeout=max(10, min(persona.image_max_wait_seconds or 120, 180)),
        )
        job_id_str = str(uuid.uuid4())
        filename = f"{persona.user_id}/{job_id_str}.png"
        pub_url = await async_upload_to_supabase(filename, img_bytes)
        media = models.MediaLibrary(
            user_id=persona.user_id,
            persona_id=persona.id,
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
        print(f"Image generation for persona {persona.persona_name}: success in {elapsed}s")
    except asyncio.TimeoutError:
        print(f"Image generation for persona {persona.persona_name}: timeout")
        if persona.image_fallback_policy == "skip_post":
            return "image_generation_failed (timeout)"
        if persona.image_fallback_policy == "use_library":
            _attach_library_image(db, persona, post_log)
    except Exception as exc:
        print(f"Image generation for persona {persona.persona_name}: failed — {exc}")
        if persona.image_fallback_policy == "skip_post":
            return f"image_generation_failed (error): {exc}"
        if persona.image_fallback_policy == "use_library":
            _attach_library_image(db, persona, post_log)

    return None


def _attach_library_image(db: Session, persona: models.AIPersona, post_log: models.PostLog) -> None:
    unused = (
        db.query(models.MediaLibrary)
        .filter(
            models.MediaLibrary.user_id == persona.user_id,
            models.MediaLibrary.is_used.is_(False),
        )
        .order_by(models.MediaLibrary.created_at.asc())
        .first()
    )
    if unused:
        post_log.media_library_id = str(unused.id)


def _resolve_image_prompt(
    db: Session,
    persona: models.AIPersona,
    post_log: models.PostLog,
) -> str | None:
    sys_p = (
        "You are an expert at writing prompts for AI image generation. Given a social media post text, "
        "write a detailed image generation prompt that would create the perfect visual to accompany that post. "
        "The image should enhance the post's message without containing any text. "
        "Return only the image generation prompt, nothing else, maximum 150 words."
    )

    if persona.image_prompt_source == "persona_prompt":
        psettings = db.query(models.ImagePromptSettings).filter(
            models.ImagePromptSettings.persona_id == persona.id
        ).first()
        return psettings.assembled_prompt if psettings and psettings.assembled_prompt else None

    if persona.image_prompt_source in ("generate_from_post", "library_image"):
        image_prompt = generate_text_for_user(
            user_id=persona.user_id,
            task_category="image_prompt_generation",
            prompt=post_log.content,
            system_prompt=sys_p,
            db=db,
            temperature=0.7,
            max_tokens=200,
        )
        return image_prompt.strip() if image_prompt else None

    return None

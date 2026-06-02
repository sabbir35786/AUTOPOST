"""
Unified LLM text-generation router.

Provides a single ``generate_text`` function that dispatches to the correct
provider library (Mistral, OpenAI, Anthropic, Google Gemini) based on
``provider_name``.

``generate_text_for_user`` reads the user's saved provider/model preference
from ``model_settings`` and uses platform API keys from the server environment.
"""

from __future__ import annotations

import httpx

from app.config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MISTRAL_API_BASE_URL,
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    OPENAI_API_KEY,
)

def _gemini_model_options() -> list[str]:
    options = [GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    seen: set[str] = set()
    unique: list[str] = []
    for name in options:
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


AVAILABLE_LLM_MODELS: dict[str, list[str]] = {
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
    "gemini": _gemini_model_options(),
}
_LEGACY_GEMINI_MODELS = {
    "gemini-1.5-pro": "gemini-2.0-flash",
    "gemini-1.5-flash": "gemini-2.0-flash",
    "gemini-pro": "gemini-2.0-flash",
}
DEFAULT_LLM_PROVIDER = "mistral"
DEFAULT_LLM_MODEL = MISTRAL_MODEL or "mistral-small-latest"
TEXT_LLM_TASK_CATEGORIES = [
    "post_generation",
    "post_analysis",
    "image_prompt_generation",
    "style_analysis",
    "recommendations",
]


class ProviderConfigurationError(RuntimeError):
    pass


def platform_key_configured(provider_name: str) -> bool:
    provider = provider_name.strip().lower()
    if provider in ("mistral", "mistralai"):
        return bool(MISTRAL_API_KEY)
    if provider in ("gemini", "google", "google_gemini"):
        return bool(GEMINI_API_KEY)
    if provider in ("openai", "open_ai"):
        return bool(OPENAI_API_KEY)
    if provider in ("anthropic", "claude"):
        return bool(ANTHROPIC_API_KEY)
    return False


def _get_first_configured_provider() -> tuple[str, str] | None:
    for provider, models in AVAILABLE_LLM_MODELS.items():
        if platform_key_configured(provider):
            model_name = models[0]
            if provider == "gemini":
                model_name = _resolve_gemini_model(model_name)
            return provider, model_name
    return None


# ---------------------------------------------------------------------------
# Core dispatcher
# ---------------------------------------------------------------------------

def generate_text(
    prompt: str,
    system_prompt: str = "",
    model_name: str = "mistral-large-latest",
    provider_name: str = "mistral",
    api_key: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    images: list[str] | None = None,
    response_format: dict | None = None,
) -> str | None:
    """Route to the correct provider and return the generated text."""
    provider = provider_name.strip().lower()
    if provider in ("mistral", "mistralai"):
        return _generate_mistral(prompt, system_prompt, model_name, api_key, temperature, max_tokens, images, response_format)
    if provider in ("openai", "open_ai"):
        return _generate_openai(prompt, system_prompt, model_name, api_key, temperature, max_tokens, images, response_format)
    if provider in ("anthropic", "claude"):
        return _generate_anthropic(prompt, system_prompt, model_name, api_key, temperature, max_tokens, images)
    if provider in ("gemini", "google", "google_gemini"):
        return _generate_gemini(prompt, system_prompt, model_name, api_key, temperature, max_tokens, images)
    raise ValueError(f"Unsupported LLM provider: {provider_name}")


# ---------------------------------------------------------------------------
# Provider: Mistral
# Available models: mistral-large-latest, mistral-small-latest, mistral-medium
# ---------------------------------------------------------------------------

def _generate_mistral(
    prompt: str,
    system_prompt: str,
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    images: list[str] | None = None,
    response_format: dict | None = None,
) -> str | None:
    effective_key = api_key or MISTRAL_API_KEY
    if not effective_key:
        raise RuntimeError("Mistral API key is not configured.")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    # Mistral Pixtral supports image_url
    if images and ("pixtral" in model_name.lower()):
        content = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({"type": "image_url", "image_url": img})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    response = httpx.post(
        f"{MISTRAL_API_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {effective_key}"},
        json=payload,
        timeout=45,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Mistral request failed ({response.status_code}): {response.text[:200]}")

    data = response.json()
    
    # Check for safety filtering in Mistral response
    choice = data.get("choices", [{}])[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason == "stop_sequence" or (finish_reason and "stop" not in finish_reason.lower()):
        # Mistral may block content with finish_reason other than "stop"
        pass  # We'll still try to return content, but log it if needed
    
    content = choice.get("message", {}).get("content")
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return content


# ---------------------------------------------------------------------------
# Provider: OpenAI
# Available models: gpt-4o, gpt-4o-mini
# ---------------------------------------------------------------------------

def _generate_openai(
    prompt: str,
    system_prompt: str,
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    images: list[str] | None = None,
    response_format: dict | None = None,
) -> str | None:
    from openai import OpenAI  # type: ignore

    effective_key = api_key or OPENAI_API_KEY
    if not effective_key:
        raise RuntimeError("OpenAI API key is not configured.")

    client = OpenAI(api_key=effective_key)

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    if images:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0] if response.choices else None
    
    # Check if OpenAI blocked the response
    if choice:
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "content_filter":
            raise RuntimeError(f"OpenAI blocked the response: Content was filtered due to safety policies.")
    
    return choice.message.content if choice else None


# ---------------------------------------------------------------------------
# Provider: Anthropic
# Available models: claude-sonnet-4-5, claude-haiku-4-5
# ---------------------------------------------------------------------------

def _generate_anthropic(
    prompt: str,
    system_prompt: str,
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    images: list[str] | None = None,
) -> str | None:
    import anthropic  # type: ignore

    effective_key = api_key or ANTHROPIC_API_KEY
    if not effective_key:
        raise RuntimeError("Anthropic API key is not configured.")

    client = anthropic.Anthropic(api_key=effective_key)

    if images:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            if img.startswith("data:"):
                # "data:image/jpeg;base64,....."
                media_type = img.split(";")[0].split(":")[1]
                data = img.split(",")[1]
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data,
                    }
                })
            else:
                pass
        msg = [{"role": "user", "content": content}]
    else:
        msg = [{"role": "user", "content": prompt}]

    kwargs: dict = {
        "model": model_name,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": msg,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    message = client.messages.create(**kwargs)
    
    # Check if Anthropic blocked the response due to safety policies
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "content_filter":
        raise RuntimeError(f"Anthropic blocked the response: Content was filtered due to safety policies.")
    
    if message.content:
        return message.content[0].text
    return None


# ---------------------------------------------------------------------------
# Provider: Google Gemini (Google AI Studio API key)
# ---------------------------------------------------------------------------

def _resolve_gemini_model(model_name: str) -> str:
    name = (model_name or GEMINI_MODEL or "gemini-2.0-flash").strip()
    return _LEGACY_GEMINI_MODELS.get(name, name)


def _extract_gemini_text(response) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        parts = getattr(candidates[0].content, "parts", None) or []
        chunks = [part.text for part in parts if getattr(part, "text", None)]
        if chunks:
            return "\n".join(chunks).strip()

    try:
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()
    except ValueError:
        pass
    return None


def _generate_gemini(
    prompt: str,
    system_prompt: str,
    model_name: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    images: list[str] | None = None,
) -> str | None:
    import google.generativeai as genai  # type: ignore

    effective_key = api_key or GEMINI_API_KEY
    if not effective_key:
        raise RuntimeError(
            "Gemini API key is not configured. Add GEMINI_API_KEY to backend/.env "
            "(from https://aistudio.google.com/apikey)."
        )

    genai.configure(api_key=effective_key)
    resolved_model = _resolve_gemini_model(model_name)

    model_kwargs: dict = {"model_name": resolved_model}
    if system_prompt:
        model_kwargs["system_instruction"] = system_prompt

    model = genai.GenerativeModel(**model_kwargs)
    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    contents: str | list = prompt
    if images:
        import io
        import base64
        from PIL import Image
        parts: list = []
        if prompt:
            parts.append(prompt)
        for image_url in images:
            if isinstance(image_url, str) and image_url.startswith("data:image/"):
                try:
                    header, base64_data = image_url.split(",", 1)
                    image_bytes = base64.b64decode(base64_data)
                    pil_img = Image.open(io.BytesIO(image_bytes))
                    parts.append(pil_img)
                except Exception as e:
                    print(f"Error parsing base64 image: {e}")
            else:
                parts.append({"file_data": {"file_uri": image_url}})
        contents = parts


    try:
        response = model.generate_content(
            contents,
            generation_config=generation_config,
        )
    except Exception as exc:
        message = str(exc)
        if "API_KEY_INVALID" in message or "API key not valid" in message:
            raise RuntimeError(
                "Gemini API key is invalid. Create a new key at https://aistudio.google.com/apikey "
                "and set GEMINI_API_KEY in backend/.env."
            ) from exc
        if "429" in message or "quota" in message.lower() or "ResourceExhausted" in type(exc).__name__:
            raise RuntimeError(
                f"Gemini rate limit or quota reached for model {resolved_model}. "
                "Wait a minute, try another model in Settings, or check usage at https://ai.dev/rate-limit."
            ) from exc
        raise RuntimeError(f"Gemini request failed: {message}") from exc

    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback else None
    if block_reason:
        raise RuntimeError(f"Gemini blocked the request: {block_reason}")

    # Check for content filtering on the response (finish_reason indicates if response was blocked)
    finish_reason = None
    if getattr(response, "candidates", None):
        finish_reason = getattr(response.candidates[0], "finish_reason", None)
    
    # finish_reason values: STOP (ok), MAX_TOKENS (ok but truncated), SAFETY (blocked), RECITATION (blocked), OTHER (unknown)
    blocked_reasons = ("SAFETY", "RECITATION")
    if finish_reason and str(finish_reason).upper() in blocked_reasons:
        raise RuntimeError(f"Gemini blocked the response: {finish_reason}. The content violated safety policies.")

    text = _extract_gemini_text(response)
    if text:
        return text

    raise RuntimeError(
        f"Gemini returned an empty response (model={resolved_model}, finish_reason={finish_reason})."
    )


# ---------------------------------------------------------------------------
# User-aware helper: look up model_settings and dispatch
# ---------------------------------------------------------------------------

def _resolve_user_llm_choice(user_id: int | None, task_category: str, db) -> tuple[str, str]:
    provider_name = DEFAULT_LLM_PROVIDER
    model_name = DEFAULT_LLM_MODEL

    if user_id is not None and db is not None:
        from sqlalchemy import text as sa_text

        for category in (task_category, "post_generation"):
            row = db.execute(
                sa_text(
                    "SELECT provider_name, model_name "
                    "FROM model_settings "
                    "WHERE user_id = :uid AND task_category = :cat "
                    "LIMIT 1"
                ),
                {"uid": user_id, "cat": category},
            ).mappings().first()
            if not row:
                continue
            candidate_provider = (row["provider_name"] or DEFAULT_LLM_PROVIDER).strip().lower()
            if candidate_provider not in AVAILABLE_LLM_MODELS:
                continue
            allowed_models = AVAILABLE_LLM_MODELS[candidate_provider]
            candidate_model = row["model_name"] or allowed_models[0]
            if candidate_provider == "gemini":
                candidate_model = _resolve_gemini_model(candidate_model)
            elif candidate_model not in allowed_models:
                candidate_model = allowed_models[0]
            if candidate_provider != "gemini" and candidate_model not in allowed_models:
                candidate_model = allowed_models[0]
            provider_name = candidate_provider
            model_name = candidate_model
            break

    if platform_key_configured(provider_name):
        return provider_name, model_name

    fallback = _get_first_configured_provider()
    if fallback is not None:
        fallback_provider, fallback_model = fallback
        return fallback_provider, fallback_model

    raise ProviderConfigurationError(
        f"The server does not have an API key configured for {provider_name}. "
        "Choose another model in Settings or ask the administrator to add keys."
    )


def generate_text_for_user(
    user_id: int | None,
    task_category: str,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    images: list[str] | None = None,
    db=None,
) -> str | None:
    """Look up the user's model preference and generate with platform API keys."""
    provider_name, model_name = _resolve_user_llm_choice(user_id, task_category, db)

    return generate_text(
        prompt=prompt,
        system_prompt=system_prompt,
        model_name=model_name,
        provider_name=provider_name,
        api_key="",
        temperature=temperature,
        max_tokens=max_tokens,
        images=images,
    )

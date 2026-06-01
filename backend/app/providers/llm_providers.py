"""
Unified LLM text-generation router.

Provides a single ``generate_text`` function that dispatches to the correct
provider library (Mistral, OpenAI, Anthropic, Google Gemini) based on
``provider_name``.

Also exposes ``generate_text_for_user`` which looks up the user's
    ``model_settings`` row for a given ``task_category`` and routes accordingly.
    User-facing generation is BYOK: if no user key exists, callers receive a
    clear configuration error instead of relying on platform environment keys.
"""

from __future__ import annotations

import httpx

from app.config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    MISTRAL_API_BASE_URL,
    MISTRAL_API_KEY,
    OPENAI_API_KEY,
)


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
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
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
    if message.content:
        return message.content[0].text
    return None


# ---------------------------------------------------------------------------
# Provider: Google Gemini
# Available models: gemini-1.5-pro, gemini-1.5-flash
# ---------------------------------------------------------------------------

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
        raise RuntimeError("Gemini API key is not configured.")

    genai.configure(api_key=effective_key)

    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt if system_prompt else None,
        generation_config=generation_config,
    )
    
    contents = [prompt]
    if images:
        import base64
        for img in images:
            if img.startswith("data:"):
                mime_type = img.split(";")[0].split(":")[1]
                data = img.split(",")[1]
                contents.append({
                    "mime_type": mime_type,
                    "data": base64.b64decode(data)
                })

    response = model.generate_content(contents)
    if response is None:
        return None

    if hasattr(response, "text") and response.text:
        return response.text

    if isinstance(response, dict):
        if response.get("text"):
            return response["text"]
        if response.get("output_text"):
            return response["output_text"]
        result = response.get("result")
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict):
                return first.get("output_text") or first.get("text")

    if hasattr(response, "result"):
        result = getattr(response, "result")
        if isinstance(result, list) and result:
            first = result[0]
            if hasattr(first, "output_text") and getattr(first, "output_text"):
                return getattr(first, "output_text")
            if hasattr(first, "text") and getattr(first, "text"):
                return getattr(first, "text")
            if isinstance(first, dict):
                return first.get("output_text") or first.get("text")

    if hasattr(response, "content"):
        content = getattr(response, "content")
        if isinstance(content, str) and content:
            return content

    return None


# ---------------------------------------------------------------------------
# User-aware helper: look up model_settings and dispatch
# ---------------------------------------------------------------------------

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
    """
    Look up the user's ``model_settings`` row for *task_category*.

    If a row exists use those settings; otherwise raise a clear BYOK setup
    error. Platform keys are still accepted by ``generate_text`` for explicit
    internal/test calls, but this user-aware path does not depend on them.
    """
    provider_name = ""
    model_name = ""
    api_key = ""

    if user_id is not None and db is not None:
        from sqlalchemy import text as sa_text

        row = db.execute(
            sa_text(
                "SELECT provider_name, model_name, api_key_encrypted "
                "FROM model_settings "
                "WHERE user_id = :uid AND task_category = :cat "
                "LIMIT 1"
            ),
            {"uid": user_id, "cat": task_category},
        ).mappings().first()

        if row:
            provider_name = row["provider_name"] or "mistral"
            model_name = row["model_name"] or "mistral-large-latest"
            if row["api_key_encrypted"]:
                from app.crypto import decrypt_token
                api_key = decrypt_token(row["api_key_encrypted"])
                if not api_key:
                    raise RuntimeError(
                        "Saved BYOK API key could not be decrypted. "
                        "Re-enter your API key in AI settings."
                    )

    if not provider_name or not model_name or not api_key:
        raise RuntimeError(
            f"No BYOK model/API key configured for task '{task_category}'. "
            "Open AI Settings and add a provider API key."
        )

    return generate_text(
        prompt=prompt,
        system_prompt=system_prompt,
        model_name=model_name,
        provider_name=provider_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        images=images,
    )

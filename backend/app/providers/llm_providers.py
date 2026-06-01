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
    MISTRAL_API_BASE_URL,
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    OPENAI_API_KEY,
)

AVAILABLE_LLM_MODELS: dict[str, list[str]] = {
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash"],
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

    prompt_text = prompt
    if system_prompt:
        prompt_text = f"{system_prompt}\n\n{prompt}"

    response = None
    if hasattr(genai, "generate_text"):
        response = genai.generate_text(
            model=model_name,
            prompt=prompt_text,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    elif hasattr(genai, "TextGenerationModel"):
        model = genai.TextGenerationModel(model_name=model_name)
        if hasattr(model, "predict"):
            response = model.predict(
                prompt_text,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        elif hasattr(model, "generate_text"):
            response = model.generate_text(
                prompt_text,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        else:
            raise RuntimeError("Installed Gemini client does not support text generation for the selected model.")
    else:
        raise RuntimeError(
            "Installed google.generativeai client does not support Gemini text generation. "
            "Please upgrade the package or use a supported Gemini driver."
        )

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
            if candidate_model not in allowed_models:
                candidate_model = allowed_models[0]
            provider_name = candidate_provider
            model_name = candidate_model
            break

    if not platform_key_configured(provider_name):
        raise RuntimeError(
            f"The server does not have an API key configured for {provider_name}. "
            "Choose another model in Settings or ask the administrator to add keys."
        )
    return provider_name, model_name


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

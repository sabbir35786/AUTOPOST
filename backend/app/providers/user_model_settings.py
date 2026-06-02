from __future__ import annotations

from dataclasses import dataclass

from app.providers.llm_providers import generate_text


POST_ALLOWED: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
}


@dataclass(frozen=True)
class UserPostModelChoice:
    provider: str
    model: str


class MissingProviderKeyError(RuntimeError):
    def __init__(self, provider: str):
        super().__init__(f"API key for {provider} is not configured. Please add it in Settings.")
        self.provider = provider


def resolve_user_post_model_choice(user_id: int | None, db) -> UserPostModelChoice | None:
    """
    If the user has a user_settings row, return their post provider/model choice.
    Otherwise return None to preserve legacy behavior.
    """
    if user_id is None or db is None:
        return None
    try:
        from app import models

        row = db.get(models.UserSettings, user_id)
    except Exception:
        row = None
    if not row:
        return None

    provider = (row.post_generation_provider or "").strip().lower()
    model = (row.post_generation_model or "").strip()
    if provider not in POST_ALLOWED:
        return None
    if model not in POST_ALLOWED[provider]:
        model = POST_ALLOWED[provider][0]
    return UserPostModelChoice(provider=provider, model=model)


def _ensure_provider_key(provider: str) -> None:
    from app.config import ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY

    if provider == "openai" and not (OPENAI_API_KEY or "").strip():
        raise MissingProviderKeyError("openai")
    if provider == "gemini" and not (GEMINI_API_KEY or "").strip():
        raise MissingProviderKeyError("gemini")
    if provider == "anthropic" and not (ANTHROPIC_API_KEY or "").strip():
        raise MissingProviderKeyError("anthropic")


def generate_post_text_for_user(
    *,
    user_id: int | None,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    images: list[str] | None = None,
    db=None,
) -> str | None:
    """
    Post-generation router that consults `user_settings` when present.
    If the row does not exist, caller should use existing legacy path.
    """
    choice = resolve_user_post_model_choice(user_id, db)
    if not choice:
        return None

    _ensure_provider_key(choice.provider)

    try:
        return generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            model_name=choice.model,
            provider_name=choice.provider,
            api_key="",
            temperature=temperature,
            max_tokens=max_tokens,
            images=images,
        )
    except MissingProviderKeyError:
        raise
    except Exception as exc:
        raise RuntimeError(f"{choice.provider} request failed: {str(exc)}") from exc


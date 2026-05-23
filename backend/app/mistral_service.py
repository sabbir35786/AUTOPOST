import httpx

from app.config import MISTRAL_API_BASE_URL, MISTRAL_API_KEY


def _complete_with_mistral(model: str, messages: list[dict], temperature: float, max_tokens: int) -> str | None:
    response = httpx.post(
        f"{MISTRAL_API_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=45,
    )
    if response.status_code >= 400:
        raise RuntimeError("Mistral post generation request failed")

    data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content")


def generate_ai_facebook_post(
    niche: str,
    tone_tags: list[str],
    custom_instructions: str | None,
    language: str,
    hashtags_enabled: bool,
    hashtag_count: int,
    topic_hint: str | None = None,
    model: str = "mistral-small-latest",
) -> str:
    if not MISTRAL_API_KEY:
        raise RuntimeError("AI post generation failed: MISTRAL_API_KEY is not configured")

    system_prompt = (
        "You are a professional social media content writer. You write engaging "
        "Facebook posts. You always stay on topic, match the requested tone exactly, "
        "follow all custom instructions strictly, write in the requested language, "
        "and never add any explanation or commentary. Return only the post text "
        "itself with no labels, no quotation marks, no preamble."
    )
    prompt_parts = [
        f"Write one Facebook post for a page about: {niche}.",
        f"Tone and style: {', '.join(tone_tags)}.",
    ]
    if custom_instructions and custom_instructions.strip():
        prompt_parts.append(f"You must follow these rules: {custom_instructions.strip()}.")
    prompt_parts.append(f"Write the post in {language}.")
    if hashtags_enabled:
        prompt_parts.append(f"Add {max(1, min(hashtag_count, 30))} relevant hashtags at the end.")
    if topic_hint and topic_hint.strip():
        prompt_parts.append(f"Focus this post on: {topic_hint.strip()}.")
    prompt_parts.append("Return only the post text. Nothing else.")

    try:
        content = _complete_with_mistral(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": " ".join(prompt_parts)},
            ],
            temperature=0.8,
            max_tokens=500,
        )
    except Exception as exc:
        raise RuntimeError(f"AI post generation failed: {exc}") from exc

    if not content or not content.strip():
        raise RuntimeError("AI post generation failed: Mistral returned empty content")
    return content.strip()


def generate_ai_recommendations(
    page_name: str,
    performance_summary: dict,
    model: str = "mistral-small-latest",
) -> list[str]:
    if not MISTRAL_API_KEY:
        return []

    prompt = (
        f"Analyze this Facebook page performance summary for {page_name}. "
        "Return 3 to 5 concise, plain-language recommendations. "
        "Each recommendation should be one sentence and practical. "
        f"Summary: {performance_summary}"
    )
    try:
        content = _complete_with_mistral(
            model=model,
            messages=[
                {"role": "system", "content": "You are a social media performance analyst. Return only recommendations."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=500,
        )
    except Exception:
        return []
    if not content:
        return []
    recommendations = []
    for line in content.splitlines():
        cleaned = line.strip().lstrip("-*0123456789. ")
        if cleaned:
            recommendations.append(cleaned)
    return recommendations[:5]

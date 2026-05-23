import httpx

from app.config import MISTRAL_API_BASE_URL, MISTRAL_API_KEY, MISTRAL_MODEL

ALLOWED_HISTORY_ROLES = {"user", "assistant"}
MAX_HISTORY_MESSAGES = 12


def _clean_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    cleaned_history = []
    for message in history[-MAX_HISTORY_MESSAGES:]:
        role = message.get("role")
        content = message.get("content", "").strip()
        if role in ALLOWED_HISTORY_ROLES and content:
            cleaned_history.append({"role": role, "content": content})
    return cleaned_history


async def create_chat_reply(
    user_message: str,
    history: list[dict[str, str]],
) -> str:
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY is not configured")

    message = user_message.strip()
    if not message:
        raise ValueError("Message cannot be empty")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant for planning and drafting social media "
                "content. Keep replies practical, concise, and easy to act on."
            ),
        },
        *_clean_history(history),
        {"role": "user", "content": message},
    ]

    async with httpx.AsyncClient(
        base_url=MISTRAL_API_BASE_URL,
        timeout=45,
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
    ) as client:
        response = await client.post(
            "/chat/completions",
            json={
                "model": MISTRAL_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 700,
            },
        )

    if response.status_code >= 400:
        raise RuntimeError("Mistral chat request failed")

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("Mistral returned empty content")
    return content.strip()

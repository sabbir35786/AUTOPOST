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
    always_include_engagement_hook: bool = False,
    recent_topics: list[str] | None = None,
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
        "itself with no labels, no quotation marks, no preamble. "
        "Every post must have a different structure from the last. Rotate between these formats — "
        "sometimes ask a question, sometimes share a short story, sometimes give a numbered tip list, "
        "sometimes make a bold statement, sometimes share a surprising fact. "
        "Never use the same opening word twice in a row. "
        "Vary the post length randomly — sometimes write 3 short punchy lines, "
        "sometimes write a longer 100 to 150 word post with a story, "
        "sometimes write just one powerful sentence. Never write the same length twice in a row."
    )
    prompt_parts = [
        f"Write one Facebook post for a page about: {niche}.",
        f"Tone and style: {', '.join(tone_tags)}.",
    ]
    if custom_instructions and custom_instructions.strip():
        prompt_parts.append(f"You must follow these rules: {custom_instructions.strip()}.")
    prompt_parts.append(f"Write the post in {language}.")
    if hashtags_enabled:
        prompt_parts.append(f"Add {max(1, min(hashtag_count, 5))} relevant hashtags at the end.")
    if always_include_engagement_hook:
        prompt_parts.append(
            "Every post must end with either a direct question to the reader, "
            "a call to action like 'tag someone who needs this', or an invitation "
            "to share their opinion in the comments. This is mandatory."
        )
    if recent_topics:
        prompt_parts.append(
            f"These topics were already covered recently, do not repeat them: {', '.join(recent_topics)}. "
            "Pick a fresh angle."
        )
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


def creativity_to_temperature(creativity_level: int | None) -> float:
    level = max(1, min(int(creativity_level or 7), 10))
    return round(0.2 + ((level - 1) / 9) * 0.8, 2)


def generate_ai_facebook_post_from_prompt(
    prompt: str,
    creativity_level: int | None = 7,
    recent_topics: list[str] | None = None,
    topic_hint: str | None = None,
    learning_hint: str | None = None,
    model: str = "mistral-small-latest",
) -> str:
    if not MISTRAL_API_KEY:
        raise RuntimeError("AI post generation failed: MISTRAL_API_KEY is not configured")

    instructions = [prompt.strip()]
    if recent_topics:
        instructions.append(
            "Avoid repeating these recently covered topics: "
            f"{', '.join(recent_topics)}. Pick a fresh angle."
        )
    if topic_hint and topic_hint.strip():
        instructions.append(f"Focus this post on: {topic_hint.strip()}.")
    if learning_hint and learning_hint.strip():
        instructions.append(learning_hint.strip())

    try:
        content = _complete_with_mistral(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write Facebook posts from the user's saved prompt. "
                        "Follow the prompt strictly. Return only the post text with no "
                        "labels, quotation marks, preamble, or commentary."
                    ),
                },
                {"role": "user", "content": "\n\n".join(instructions)},
            ],
            temperature=creativity_to_temperature(creativity_level),
            max_tokens=650,
        )
    except Exception as exc:
        raise RuntimeError(f"AI post generation failed: {exc}") from exc

    if not content or not content.strip():
        raise RuntimeError("AI post generation failed: Mistral returned empty content")
    return content.strip()


def extract_post_topic(post_content: str, model: str = "mistral-small-latest") -> str | None:
    if not MISTRAL_API_KEY:
        return None
    try:
        topic = _complete_with_mistral(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a content labeling assistant. Extract a brief 2 to 4 word "
                        "topic description of the social media post. Return ONLY the topic text "
                        "itself with no labels, no quotation marks, no punctuation, and no preamble."
                    )
                },
                {"role": "user", "content": f"Post:\n{post_content}"},
            ],
            temperature=0.3,
            max_tokens=20,
        )
        if topic:
            return topic.strip().strip('"').strip("'").strip()
    except Exception as exc:
        print(f"Error extracting topic: {exc}")
    return None


def check_post_quality(post_content: str, model: str = "mistral-small-latest") -> int:
    if not MISTRAL_API_KEY:
        return 7
    try:
        rating_str = _complete_with_mistral(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a social media quality auditor. Rate the Facebook post "
                        "from 1 to 10 for engagement potential. Return ONLY the integer number "
                        "(e.g. 7) with no explanation or extra text."
                    )
                },
                {"role": "user", "content": f"Post:\n{post_content}"},
            ],
            temperature=0.1,
            max_tokens=5,
        )
        if rating_str:
            import re
            match = re.search(r'\d+', rating_str)
            if match:
                return int(match.group())
    except Exception as exc:
        print(f"Error checking post quality: {exc}")
    return 7



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


def analyze_style_with_mistral(posts: list[str], model: str = "mistral-small-latest") -> dict:
    if not MISTRAL_API_KEY or not posts:
        return {"topics": [], "summary": "Not enough AI analysis data is available yet."}
    sample = "\n\n---\n\n".join(posts[:25])
    try:
        content = _complete_with_mistral(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analyze Facebook posts. Return compact JSON only with keys "
                        "topics (array of {name,count}) and summary (plain English paragraph)."
                    ),
                },
                {"role": "user", "content": sample},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        if content:
            import json
            import re
            match = re.search(r"\{.*\}", content, re.S)
            return json.loads(match.group(0) if match else content)
    except Exception as exc:
        print(f"Style analysis failed: {exc}")
    return {"topics": [], "summary": "AI style summary could not be generated for this sample."}


def classify_post_topic(post_content: str, model: str = "mistral-small-latest") -> str | None:
    return extract_post_topic(post_content, model)


def synthesize_learned_strategy(signals: list[dict], model: str = "mistral-small-latest") -> dict:
    if not MISTRAL_API_KEY or not signals:
        return {
            "best_post_length": "medium",
            "best_posting_times": [],
            "best_content_formats": [],
            "topics_to_increase": [],
            "topics_to_decrease": [],
            "prompt_improvements": [],
            "confidence_score": 0,
        }
    try:
        import json
        import re
        content = _complete_with_mistral(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI content strategist. Analyze the Facebook AI posting "
                        "system history and return JSON only with fields: best_post_length "
                        "(short/medium/long), best_posting_times (array of hour numbers), "
                        "best_content_formats (array), topics_to_increase (array), "
                        "topics_to_decrease (array), prompt_improvements (array), "
                        "confidence_score (0 to 1)."
                    ),
                },
                {"role": "user", "content": json.dumps(signals[:120], default=str)},
            ],
            temperature=0.2,
            max_tokens=900,
        )
        if content:
            match = re.search(r"\{.*\}", content, re.S)
            data = json.loads(match.group(0) if match else content)
            data["confidence_score"] = max(0, min(float(data.get("confidence_score", 0)), 1))
            return data
    except Exception as exc:
        print(f"Learned strategy synthesis failed: {exc}")
    return {
        "best_post_length": "medium",
        "best_posting_times": [],
        "best_content_formats": [],
        "topics_to_increase": [],
        "topics_to_decrease": [],
        "prompt_improvements": [],
        "confidence_score": 0,
    }


def suggest_prompt_improvement(current_prompt: str, strategy: dict, model: str = "mistral-small-latest") -> str | None:
    if not MISTRAL_API_KEY or not current_prompt.strip():
        return None
    try:
        import json
        return _complete_with_mistral(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Here is the current prompt used to generate social media posts. "
                        "Here is what performance data says is working. Suggest specific edits "
                        "that improve results. Return the improved prompt with changes highlighted "
                        "in [CHANGED: old text -> new text] format. Do not apply unrelated changes."
                    ),
                },
                {"role": "user", "content": f"Current prompt:\n{current_prompt}\n\nLearned strategy:\n{json.dumps(strategy, default=str)}"},
            ],
            temperature=0.25,
            max_tokens=1200,
        )
    except Exception as exc:
        print(f"Prompt improvement suggestion failed: {exc}")
    return None

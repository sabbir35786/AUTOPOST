from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from random import random

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import FACEBOOK_GRAPH_API_BASE_URL, MISTRAL_MODEL
from app.crypto import decrypt_token
from app.mistral_service import generate_ai_recommendations, suggest_prompt_improvement, synthesize_learned_strategy


SNAPSHOT_TYPES = {"1hr": timedelta(hours=1), "6hr": timedelta(hours=6), "24hr": timedelta(hours=24)}


def user_has_learning_access(user: models.User | None) -> bool:
    return bool(user and user.plan == "pro")


def engagement_score(likes: int, comments: int, shares: int, reach: int) -> float:
    return round((likes * 1) + (comments * 3) + (shares * 5) + (reach / 100), 4)


async def run_engagement_snapshot_job() -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await collect_due_engagement_snapshots(db)
    finally:
        db.close()


async def collect_due_engagement_snapshots(db: Session) -> None:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=48)
    posts = (
        db.query(models.PostLog, models.FacebookConnection, models.User)
        .join(models.FacebookConnection, models.FacebookConnection.id == models.PostLog.facebook_connection_id)
        .join(models.User, models.User.id == models.PostLog.user_id)
        .filter(
            models.PostLog.status.in_(["published", "success"]),
            models.PostLog.posted_at >= since,
            models.PostLog.facebook_post_id.isnot(None),
        )
        .all()
    )
    for post, connection, user in posts:
        if not user_has_learning_access(user):
            continue
        age = now - (post.posted_at or now)
        due_types = [name for name, delay in SNAPSHOT_TYPES.items() if age >= delay]
        for snapshot_type in due_types:
            exists = (
                db.query(models.PostEngagementSnapshot)
                .filter(
                    models.PostEngagementSnapshot.post_id == post.id,
                    models.PostEngagementSnapshot.snapshot_type == snapshot_type,
                )
                .first()
            )
            if exists:
                continue
            metrics = await fetch_facebook_engagement(post.facebook_post_id or "", connection)
            snapshot = save_snapshot(db, post, connection.id, snapshot_type, metrics)
            if post.ai_persona_id:
                recalculate_persona_performance(db, post.ai_persona_id, connection.id)
                update_persona_learning_patterns(db, post.ai_persona_id, connection.id)
            update_post_totals_from_snapshot(db, post, snapshot)
            db.commit()


async def fetch_facebook_engagement(facebook_post_id: str, connection: models.FacebookConnection) -> dict[str, int]:
    fields = "likes.summary(true),comments.summary(true),shares,insights.metric(post_impressions_unique)"
    access_token = decrypt_token(connection.page_access_token)
    if not access_token:
        return {"likes": 0, "comments": 0, "shares": 0, "reach": 0}

    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL, timeout=30) as client:
        response = await client.get(
            facebook_post_id,
            params={"fields": fields, "access_token": access_token},
        )
    if response.status_code >= 400:
        return {"likes": 0, "comments": 0, "shares": 0, "reach": 0}
    data = response.json()
    reach_values = data.get("insights", {}).get("data", [{}])[0].get("values", [{}])
    return {
        "likes": int(data.get("likes", {}).get("summary", {}).get("total_count") or 0),
        "comments": int(data.get("comments", {}).get("summary", {}).get("total_count") or 0),
        "shares": int(data.get("shares", {}).get("count") or 0),
        "reach": int((reach_values[0].get("value") if reach_values else 0) or 0),
    }


def save_snapshot(db: Session, post: models.PostLog, page_connection_id: int, snapshot_type: str, metrics: dict[str, int]) -> models.PostEngagementSnapshot:
    score = engagement_score(metrics["likes"], metrics["comments"], metrics["shares"], metrics["reach"])
    snapshot = models.PostEngagementSnapshot(
        post_id=post.id,
        persona_id=post.ai_persona_id,
        page_connection_id=page_connection_id,
        snapshot_type=snapshot_type,
        likes_count=metrics["likes"],
        comments_count=metrics["comments"],
        shares_count=metrics["shares"],
        reach_count=metrics["reach"],
        engagement_score=score,
    )
    db.add(snapshot)
    db.flush()
    db.add(models.LearningSignal(
        user_id=post.user_id,
        persona_id=post.ai_persona_id,
        signal_type="post_performance",
        signal_data={
            "post_id": post.id,
            "snapshot_type": snapshot_type,
            "content": post.content[:1000],
            "topic": post.topic,
            "posted_at": post.posted_at,
            "likes": metrics["likes"],
            "comments": metrics["comments"],
            "shares": metrics["shares"],
            "reach": metrics["reach"],
        },
        outcome_score=score,
    ))
    return snapshot


def update_post_totals_from_snapshot(db: Session, post: models.PostLog, snapshot: models.PostEngagementSnapshot) -> None:
    if not post.ai_persona_id or snapshot.snapshot_type != "24hr":
        return
    persona = db.get(models.AIPersona, post.ai_persona_id)
    if not persona:
        return
    persona.total_likes_received += snapshot.likes_count
    persona.total_comments_received += snapshot.comments_count
    persona.total_shares_received += snapshot.shares_count
    persona.total_reach_received += snapshot.reach_count


def recalculate_persona_performance(db: Session, persona_id: int, page_connection_id: int) -> None:
    rows = (
        db.query(models.PostLog.id, models.PostEngagementSnapshot.engagement_score)
        .join(models.PostEngagementSnapshot, models.PostEngagementSnapshot.post_id == models.PostLog.id)
        .filter(
            models.PostLog.ai_persona_id == persona_id,
            models.PostEngagementSnapshot.snapshot_type == "24hr",
        )
        .order_by(models.PostLog.posted_at.desc().nullslast(), models.PostLog.id.desc())
        .limit(20)
        .all()
    )
    if not rows:
        return
    weighted_sum = 0.0
    weight_sum = 0
    total = len(rows)
    for index, row in enumerate(rows):
        weight = total - index
        weighted_sum += float(row.engagement_score or 0) * weight
        weight_sum += weight
    persona_average = weighted_sum / max(weight_sum, 1)
    page_average = (
        db.query(func.avg(models.PostEngagementSnapshot.engagement_score))
        .filter(
            models.PostEngagementSnapshot.page_connection_id == page_connection_id,
            models.PostEngagementSnapshot.snapshot_type == "24hr",
        )
        .scalar()
        or persona_average
        or 1
    )
    score = min(1.0, max(0.1, persona_average / max(float(page_average), 0.01)))
    persona = db.get(models.AIPersona, persona_id)
    if persona:
        persona.performance_score = score
        persona.last_performance_update_at = datetime.now(timezone.utc)
        if persona.learning_mode_enabled and score < 0.25:
            persona.is_active = False


def update_persona_learning_patterns(db: Session, persona_id: int, page_connection_id: int) -> None:
    posts = (
        db.query(models.PostLog, models.PostEngagementSnapshot)
        .join(models.PostEngagementSnapshot, models.PostEngagementSnapshot.post_id == models.PostLog.id)
        .filter(
            models.PostLog.ai_persona_id == persona_id,
            models.PostEngagementSnapshot.snapshot_type == "24hr",
        )
        .order_by(models.PostLog.posted_at.desc().nullslast(), models.PostLog.id.desc())
        .limit(20)
        .all()
    )
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for post, snapshot in posts:
        content = post.content or ""
        score = float(snapshot.engagement_score or 0)
        length = "short" if len(content) < 120 else "medium" if len(content) < 320 else "long"
        ending = "question" if content.strip().endswith("?") else "statement"
        hashtags = "with hashtags" if "#" in content else "without hashtags"
        slot = (post.posted_at or post.created_at).strftime("%a %H:00") if (post.posted_at or post.created_at) else "unknown"
        for key in [("post length", length), ("ending type", ending), ("format", hashtags), ("time slot", slot)]:
            buckets[key].append(score)
    now = datetime.now(timezone.utc)
    db.query(models.PersonaLearningPattern).filter(models.PersonaLearningPattern.persona_id == persona_id).delete()
    best_bits = []
    for (pattern_type, pattern_value), scores in buckets.items():
        average = sum(scores) / max(len(scores), 1)
        db.add(models.PersonaLearningPattern(
            persona_id=persona_id,
            page_connection_id=page_connection_id,
            pattern_type=pattern_type,
            pattern_value=pattern_value,
            average_engagement_score=average,
            sample_size_count=len(scores),
            last_updated_at=now,
        ))
        best_bits.append((average, f"{pattern_value} {pattern_type}"))
    persona = db.get(models.AIPersona, persona_id)
    if persona:
        persona.learned_patterns_summary = ", ".join(value for _, value in sorted(best_bits, reverse=True)[:4])


def should_persona_post_now(persona: models.AIPersona) -> bool:
    if not persona.learning_mode_enabled:
        return True
    score = float(persona.performance_score or 0.5)
    if score >= 0.75:
        return True
    if score >= 0.5:
        return random() <= 0.75
    return random() <= 0.5


def build_learning_prompt_hint(db: Session, persona: models.AIPersona) -> str | None:
    if not persona.learning_mode_enabled or not persona.learned_patterns_summary:
        return None
    total_posts = (
        db.query(func.count(models.PostLog.id))
        .filter(models.PostLog.ai_persona_id == persona.id, models.PostLog.status.in_(["published", "success"]))
        .scalar()
        or 0
    )
    mode = "best patterns"
    if total_posts >= 20 and total_posts % 10 in (8, 9):
        mode = "experimental variation"
    if mode == "experimental variation":
        return "Explore a different length, format, or structure than recent posts while staying on-brand."
    return f"These content patterns have performed best for this audience recently: {persona.learned_patterns_summary}. Lean toward these while maintaining variety."


def build_strategy_prompt_hint(db: Session, persona: models.AIPersona) -> str | None:
    strategy = (
        db.query(models.LearnedStrategy)
        .filter(models.LearnedStrategy.persona_id == persona.id)
        .order_by(models.LearnedStrategy.week_start_date.desc(), models.LearnedStrategy.created_at.desc())
        .first()
    )
    if not strategy or float(strategy.confidence_score or 0) <= 0:
        return None
    data = strategy.strategy_data or {}
    bits = []
    if data.get("best_post_length"):
        bits.append(f"best length: {data['best_post_length']}")
    if data.get("best_posting_times"):
        bits.append(f"best posting hours: {', '.join(map(str, data['best_posting_times']))}")
    if data.get("best_content_formats"):
        bits.append(f"formats: {', '.join(map(str, data['best_content_formats'][:4]))}")
    if data.get("topics_to_increase"):
        bits.append(f"increase topics: {', '.join(map(str, data['topics_to_increase'][:5]))}")
    if data.get("topics_to_decrease"):
        bits.append(f"decrease topics: {', '.join(map(str, data['topics_to_decrease'][:5]))}")
    return "Based on recent performance data, prioritize these approaches: " + "; ".join(bits) + "." if bits else None


def _week_start(value: datetime) -> date:
    local_date = value.date()
    return local_date - timedelta(days=local_date.weekday())


def synthesize_weekly_strategy_for_persona(db: Session, persona: models.AIPersona) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    signals = (
        db.query(models.LearningSignal)
        .filter(models.LearningSignal.persona_id == persona.id, models.LearningSignal.created_at >= since)
        .order_by(models.LearningSignal.created_at.desc())
        .all()
    )
    if not signals:
        return
    payload = [
        {
            "type": signal.signal_type,
            "data": signal.signal_data,
            "outcome_score": float(signal.outcome_score or 0),
            "created_at": signal.created_at,
        }
        for signal in signals
    ]
    data = synthesize_learned_strategy(payload, MISTRAL_MODEL)
    current_prompt = persona.custom_prompt or persona.custom_instructions or persona.niche
    suggested = suggest_prompt_improvement(current_prompt, data, MISTRAL_MODEL)
    week = _week_start(datetime.now(timezone.utc))
    strategy = (
        db.query(models.LearnedStrategy)
        .filter(models.LearnedStrategy.persona_id == persona.id, models.LearnedStrategy.week_start_date == week)
        .first()
    )
    if strategy is None:
        strategy = models.LearnedStrategy(persona_id=persona.id, week_start_date=week)
        db.add(strategy)
    strategy.strategy_data = data
    strategy.suggested_prompt = suggested
    strategy.confidence_score = float(data.get("confidence_score") or 0)
    strategy.applied_to_prompt = False


def get_performance_insights(db: Session, page_connection_id: int, user: models.User) -> dict:
    if not user_has_learning_access(user):
        return {"enabled": False, "reason": "Performance Insights are available on the Pro plan."}
    personas = db.query(models.AIPersona).filter(models.AIPersona.page_connection_id == page_connection_id).all()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    top_posts = (
        db.query(models.PostLog, models.PostEngagementSnapshot, models.AIPersona)
        .join(models.PostEngagementSnapshot, models.PostEngagementSnapshot.post_id == models.PostLog.id)
        .outerjoin(models.AIPersona, models.AIPersona.id == models.PostLog.ai_persona_id)
        .filter(models.PostLog.facebook_connection_id == page_connection_id, models.PostLog.posted_at >= since)
        .order_by(models.PostEngagementSnapshot.engagement_score.desc())
        .limit(3)
        .all()
    )
    heat = defaultdict(list)
    snapshots = (
        db.query(models.PostLog, models.PostEngagementSnapshot)
        .join(models.PostEngagementSnapshot, models.PostEngagementSnapshot.post_id == models.PostLog.id)
        .filter(models.PostLog.facebook_connection_id == page_connection_id, models.PostLog.posted_at >= since)
        .all()
    )
    for post, snapshot in snapshots:
        if post.posted_at:
            heat[(post.posted_at.strftime("%a"), post.posted_at.hour)].append(float(snapshot.engagement_score or 0))
    recommendations = (
        db.query(models.AIRecommendation)
        .filter(models.AIRecommendation.page_connection_id == page_connection_id, models.AIRecommendation.is_dismissed.is_(False))
        .order_by(models.AIRecommendation.generated_at.desc())
        .limit(5)
        .all()
    )
    return {
        "enabled": True,
        "persona_scores": [{"id": p.id, "name": p.persona_name, "score": float(p.performance_score or 0.5)} for p in personas],
        "time_slot_heatmap": [{"day": d, "hour": h, "average_score": sum(v) / len(v)} for (d, h), v in heat.items()],
        "top_posts": [
            {
                "id": post.id,
                "content": post.content,
                "persona_name": persona.persona_name if persona else "Manual",
                "published_at": post.posted_at,
                "likes_count": snapshot.likes_count,
                "comments_count": snapshot.comments_count,
                "shares_count": snapshot.shares_count,
                "reach_count": snapshot.reach_count,
                "engagement_score": float(snapshot.engagement_score or 0),
            }
            for post, snapshot, persona in top_posts
        ],
        "recommendations": [{"id": item.id, "text": item.recommendation_text, "generated_at": item.generated_at} for item in recommendations],
    }


async def run_weekly_learning_job() -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        pages = db.query(models.FacebookConnection).filter(models.FacebookConnection.connection_status == "connected").all()
        for page in pages:
            user = db.get(models.User, page.user_id)
            if not user_has_learning_access(user):
                continue
            persona_count = db.query(func.count(models.AIPersona.id)).filter(models.AIPersona.page_connection_id == page.id).scalar() or 0
            post_count = db.query(func.count(models.PostLog.id)).filter(models.PostLog.facebook_connection_id == page.id).scalar() or 0
            if persona_count < 2 or post_count < 30:
                continue
            for persona in db.query(models.AIPersona).filter(models.AIPersona.page_connection_id == page.id).all():
                recalculate_persona_performance(db, persona.id, page.id)
                update_persona_learning_patterns(db, persona.id, page.id)
                synthesize_weekly_strategy_for_persona(db, persona)
            await regenerate_ai_recommendations(db, page)
            db.commit()
    finally:
        db.close()


async def regenerate_ai_recommendations(db: Session, page: models.FacebookConnection) -> None:
    insights = get_performance_insights(db, page.id, db.get(models.User, page.user_id))
    if not insights.get("enabled"):
        return
    texts = generate_ai_recommendations(page.page_name, insights, MISTRAL_MODEL)
    now = datetime.now(timezone.utc)
    db.query(models.AIRecommendation).filter(models.AIRecommendation.page_connection_id == page.id).update({"is_dismissed": True})
    for text in texts[:5]:
        db.add(models.AIRecommendation(page_connection_id=page.id, recommendation_text=text, generated_at=now))


def reset_persona_learning(db: Session, persona: models.AIPersona) -> None:
    persona.performance_score = 0.5
    persona.learned_patterns_summary = None
    persona.last_performance_update_at = datetime.now(timezone.utc)
    db.query(models.PersonaLearningPattern).filter(models.PersonaLearningPattern.persona_id == persona.id).delete()
    db.query(models.PostEngagementSnapshot).filter(models.PostEngagementSnapshot.persona_id == persona.id).delete()

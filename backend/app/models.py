from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String, default="UTC", nullable=False)
    plan: Mapped[str] = mapped_column(String, default="free", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class FacebookConnection(Base):
    __tablename__ = "facebook_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    page_id: Mapped[str] = mapped_column(String, nullable=False)
    page_name: Mapped[str] = mapped_column(String, nullable=False)
    page_picture_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    app_id: Mapped[str | None] = mapped_column(String, nullable=True)
    app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    instagram_business_account_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    long_lived_user_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    connection_status: Mapped[str] = mapped_column(String, default="connected", nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    niche: Mapped[str] = mapped_column(Text, nullable=False)
    post_time: Mapped[str] = mapped_column(String, nullable=False)
    timezone: Mapped[str] = mapped_column(String, default="UTC", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PostLog(Base):
    __tablename__ = "post_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    facebook_connection_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_connections.id"),
        index=True,
        nullable=False,
    )
    ai_persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", index=True, nullable=False)
    media_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_preview_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )
    facebook_post_id: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    post_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("post_logs.id"), index=True, nullable=False)
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PostEngagementSnapshot(Base):
    __tablename__ = "post_engagement_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("post_logs.id"), index=True, nullable=False)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=True)
    page_connection_id: Mapped[int] = mapped_column(ForeignKey("facebook_connections.id"), index=True, nullable=False)
    snapshot_taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    snapshot_type: Mapped[str] = mapped_column(String, nullable=False)
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reach_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_score: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)


class PersonaLearningPattern(Base):
    __tablename__ = "persona_learning_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=False)
    page_connection_id: Mapped[int] = mapped_column(ForeignKey("facebook_connections.id"), index=True, nullable=False)
    pattern_type: Mapped[str] = mapped_column(String, nullable=False)
    pattern_value: Mapped[str] = mapped_column(Text, nullable=False)
    average_engagement_score: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    sample_size_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    page_connection_id: Mapped[int] = mapped_column(ForeignKey("facebook_connections.id"), index=True, nullable=False)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    persona_id: Mapped[int] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=False)
    template_name: Mapped[str] = mapped_column(String, default="Custom", nullable=False)
    question_answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    assembled_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    creativity_level: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    style_examples: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class LearningSignal(Base):
    __tablename__ = "learning_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=True)
    signal_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    signal_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    outcome_score: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class LearnedStrategy(Base):
    __tablename__ = "learned_strategy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=False)
    strategy_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    suggested_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    week_start_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    applied_to_prompt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DashboardSuggestion(Base):
    __tablename__ = "dashboard_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    action_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class StyleAnalysis(Base):
    __tablename__ = "style_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    page_name: Mapped[str | None] = mapped_column(String, nullable=True)
    report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TrackedPage(Base):
    __tablename__ = "tracked_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    page_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    page_name: Mapped[str | None] = mapped_column(String, nullable=True)
    nickname: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TrackedPagePost(Base):
    __tablename__ = "tracked_page_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tracked_page_id: Mapped[int] = mapped_column(ForeignKey("tracked_pages.id"), index=True, nullable=False)
    facebook_post_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_score: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TrackerTrend(Base):
    __tablename__ = "tracker_trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AIPersona(Base):
    __tablename__ = "ai_personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    page_connection_id: Mapped[int] = mapped_column(
        ForeignKey("facebook_connections.id"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    persona_name: Mapped[str] = mapped_column(String, default="Default Persona", nullable=False)
    niche: Mapped[str] = mapped_column(Text, nullable=False)
    tone_tags: Mapped[str] = mapped_column(Text, nullable=False)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    creativity_level: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    language: Mapped[str] = mapped_column(String, default="English", nullable=False)
    hashtags_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hashtag_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    always_include_engagement_hook: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assigned_days: Mapped[str] = mapped_column(String, default="", nullable=False)
    posting_time_slots: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    priority_level: Mapped[str] = mapped_column(String, default="Normal", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    learning_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    minimum_engagement_threshold: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    learned_patterns_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    performance_score: Mapped[float] = mapped_column(Numeric(8, 4), default=0.5, nullable=False)
    total_posts_published: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_likes_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_comments_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_shares_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_reach_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_performance_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_auto_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

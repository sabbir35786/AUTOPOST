from datetime import date, datetime, timezone
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    brand_logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        index=True,
        nullable=False,
    )
    page_id: Mapped[str] = mapped_column(String, nullable=False)
    page_name: Mapped[str] = mapped_column(String, nullable=False)
    page_picture_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_token_refresh: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    facebook_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("facebook_connections.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    ai_persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id"), index=True, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", index=True, nullable=False)
    media_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    media_library_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("media_library.id", ondelete="SET NULL"),
        nullable=True,
    )
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_preview_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )
    qstash_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    facebook_post_id: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    include_image: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_frequency: Mapped[str] = mapped_column(String, default="every_post", nullable=False)
    image_prompt_source: Mapped[str] = mapped_column(String, default="persona_prompt", nullable=False)
    image_fallback_policy: Mapped[str] = mapped_column(String, default="text_only", nullable=False)
    image_max_wait_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    template_image_generation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    template_logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class ModelSettings(Base):
    __tablename__ = "model_settings"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    task_category: Mapped[str] = mapped_column(String, nullable=False)
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
        nullable=False,
    )
    post_generation_provider: Mapped[str] = mapped_column(String, default="openai", nullable=False)
    post_generation_model: Mapped[str] = mapped_column(String, default="gpt-4o", nullable=False)
    image_generation_provider: Mapped[str] = mapped_column(String, default="gemini", nullable=False)
    image_generation_model: Mapped[str] = mapped_column(String, default="imagen-3.0-generate-001", nullable=False)
    timezone: Mapped[str] = mapped_column(String, default="UTC", nullable=False)


class ImageGenerationJob(Base):
    __tablename__ = "image_generation_jobs"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    assembled_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String, default="1:1", nullable=False)
    result_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    supabase_storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_wait_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generation_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class MediaLibrary(Base):
    __tablename__ = "media_library"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id", ondelete="SET NULL"), nullable=True)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    generation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    used_in_post_id: Mapped[int | None] = mapped_column(ForeignKey("post_logs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ImagePromptSettings(Base):
    __tablename__ = "image_prompt_settings"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    persona_id: Mapped[int] = mapped_column(ForeignKey("ai_personas.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    mood_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    color_palette: Mapped[str | None] = mapped_column(String, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String, default="1:1", nullable=False)
    text_overlay_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    text_overlay_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_overlay_style: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_image_descriptors: Mapped[str | None] = mapped_column(Text, nullable=True)
    assembled_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_layers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    template_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    template_logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ImageTemplate(Base):
    __tablename__ = "image_templates"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    reference_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    template_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    canvas_width: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    canvas_height: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String, default="1:1", nullable=False)
    creation_method: Mapped[str] = mapped_column(String, default="extracted", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class TemplateBackgroundAsset(Base):
    __tablename__ = "template_background_assets"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TemplateFontAsset(Base):
    __tablename__ = "template_font_assets"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    font_file_url: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[str] = mapped_column(String, default="regular", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PersonaImageTemplateAssignment(Base):
    __tablename__ = "persona_image_template_assignments"

    persona_id: Mapped[int] = mapped_column(
        ForeignKey("ai_personas.id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
        index=True,
        nullable=False,
    )
    image_template_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("image_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PostImageGeneration(Base):
    __tablename__ = "post_image_generations"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id: Mapped[int] = mapped_column(ForeignKey("post_logs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    template_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("image_templates.id", ondelete="CASCADE"), nullable=False)
    background_generation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlay_texts: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    llm_instructions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    background_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    layer_overrides: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", index=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_color_hex: Mapped[str | None] = mapped_column(String, nullable=True)
    secondary_color_hex: Mapped[str | None] = mapped_column(String, nullable=True)
    tone: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class BrandDNA(Base):
    __tablename__ = "brand_dna"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dna_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class PostImageAssets(Base):
    __tablename__ = "post_image_assets"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id: Mapped[int] = mapped_column(ForeignKey("post_logs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("ai_personas.id", ondelete="SET NULL"), nullable=True)
    background_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    assets_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    facebook_post_id: Mapped[str | None] = mapped_column(String, nullable=True)
    facebook_post_url: Mapped[str | None] = mapped_column(String, nullable=True)
    publish_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    qstash_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(String, nullable=True)
    is_recurring: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PersonaImageSetting(Base):
    __tablename__ = "persona_image_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_template_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)


class BackgroundAsset(Base):
    __tablename__ = "background_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)


class FontAsset(Base):
    __tablename__ = "font_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)


class PersonaSchedule(Base):
    __tablename__ = "persona_schedules"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    persona_id: Mapped[int] = mapped_column(ForeignKey("ai_personas.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Dhaka", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_data: Mapped[dict] = mapped_column(JSON, default=lambda: {"active_days": [], "default_times": [], "day_overrides": {}}, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ScheduledSlot(Base):
    __tablename__ = "scheduled_slots"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    persona_id: Mapped[int] = mapped_column(ForeignKey("ai_personas.id", ondelete="CASCADE"), index=True, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    qstash_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("post_logs.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    persona: Mapped["AIPersona"] = relationship("AIPersona")
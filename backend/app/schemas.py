from datetime import date, datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str
    password: str
    name: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserRead(BaseModel):
    id: int
    email: str
    name: str
    email_verified: bool = True
    timezone: str = "UTC"
    plan: str = "free"
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FacebookConnectRequest(BaseModel):
    short_lived_token: str | None = None
    code: str | None = None
    redirect_uri: str | None = None
    state: str | None = None


class FacebookOAuthUrlRequest(BaseModel):
    app_id: str
    app_secret: str
    redirect_uri: str


class FacebookOAuthUrlResponse(BaseModel):
    authorization_url: str


class FacebookPage(BaseModel):
    page_id: str
    page_name: str


class FacebookConnectResponse(BaseModel):
    pages: list[FacebookPage]


class FacebookSelectPageRequest(BaseModel):
    page_id: str


class FacebookSelectPageResponse(BaseModel):
    success: bool
    page_name: str


class FacebookManualConnectRequest(BaseModel):
    page_id: str
    page_access_token: str


class FacebookStatus(BaseModel):
    connected: bool
    is_connected: bool | None = None
    page_name: str | None = None
    page_id: str | None = None
    page_picture_url: str | None = None
    connection_status: str | None = None
    instagram_business_account_id: str | None = None


class UserUpdate(BaseModel):
    email: str | None = None
    timezone: str | None = None


class PageConnectionRead(BaseModel):
    id: int
    page_id: str
    page_name: str
    page_picture_url: str | None = None
    connection_status: str
    connected_at: datetime

    model_config = {"from_attributes": True}


class ScheduleUpsert(BaseModel):
    niche: str
    post_time: str
    timezone: str = "UTC"
    active: bool = True


class ScheduleRead(ScheduleUpsert):
    id: int
    user_id: int

    model_config = {"from_attributes": True}


class PostGenerateResponse(BaseModel):
    content: str


class PostGenerateRequest(BaseModel):
    prompt: str | None = None


class PostPublishRequest(BaseModel):
    message: str
    page_connection_id: int | None = None
    image_url: str | None = None
    media_urls: list[str] = Field(default_factory=list)
    link_url: str | None = None
    link_preview_data: dict | None = None
    scheduled_at: datetime | None = None
    save_as_draft: bool = False


class PostPublishResponse(BaseModel):
    success: bool
    id: int | None = None
    status: str | None = None
    post_url: str | None = None
    error_message: str | None = None


class PostHistoryItem(BaseModel):
    id: int
    content: str
    status: str
    posted_at: datetime | None = None
    scheduled_at: datetime | None = None
    media_urls: list[str] = Field(default_factory=list)
    link_url: str | None = None
    link_preview_data: dict | None = None
    page_name: str | None = None
    page_picture_url: str | None = None
    facebook_post_id: str | None = None
    failure_reason: str | None = None
    ai_generated: bool = False
    auto_generated: bool = False
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    reach_count: int = 0
    engagement_score: float = 0
    low_engagement: bool = False

    model_config = {"from_attributes": True}


class AIPersonaBase(BaseModel):
    persona_name: str
    niche: str
    tone_tags: list[str] = Field(default_factory=list)
    custom_instructions: str | None = None
    prompt_config: dict | None = None
    custom_prompt: str | None = None
    creativity_level: int = 7
    language: str = "English"
    hashtags_enabled: bool = False
    hashtag_count: int = 3
    always_include_engagement_hook: bool = False
    assigned_days: list[str] = Field(default_factory=list)
    posting_time_slots: list[str] = Field(default_factory=lambda: ["09:00"])
    priority_level: str = "Normal"
    is_active: bool = True
    learning_mode_enabled: bool = True
    minimum_engagement_threshold: float = 0


class AIPersonaCreate(AIPersonaBase):
    pass


class AIPersonaUpdate(AIPersonaBase):
    pass


class AIPersonaRead(AIPersonaBase):
    id: int
    page_connection_id: int
    user_id: int
    performance_score: float = 0.5
    total_posts_published: int = 0
    total_likes_received: int = 0
    total_comments_received: int = 0
    total_shares_received: int = 0
    total_reach_received: int = 0
    last_performance_update_at: datetime | None = None
    last_auto_post_at: datetime | None = None
    learned_patterns_summary: str | None = None

    model_config = {"from_attributes": True}


AIPageSettingsBase = AIPersonaBase
AIPageSettingsUpsert = AIPersonaCreate
AIPageSettingsRead = AIPersonaRead


class AIGenerateRequest(BaseModel):
    page_connection_id: int
    topic_hint: str | None = None


class AIGenerateResponse(BaseModel):
    content: str


class PostUpdateRequest(BaseModel):
    message: str | None = None
    media_urls: list[str] | None = None
    scheduled_at: datetime | None = None
    link_url: str | None = None
    link_preview_data: dict | None = None
    status: str | None = None


class AnalyticsResponse(BaseModel):
    total_posts: int
    total_likes: int
    total_comments: int
    total_shares: int
    posts_per_day: list[dict]


class PerformanceInsightsResponse(BaseModel):
    enabled: bool
    reason: str | None = None
    persona_scores: list[dict] = Field(default_factory=list)
    time_slot_heatmap: list[dict] = Field(default_factory=list)
    top_posts: list[dict] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)


class DashboardIntelligenceResponse(BaseModel):
    now: datetime
    next_scheduled_post: dict | None = None
    last_published_post: dict | None = None
    facebook_connections: list[dict] = Field(default_factory=list)
    cron_health: dict
    onboarding_steps: list[dict] = Field(default_factory=list)
    learned_insights: dict
    action_items: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)


class PersonaLearningResetResponse(BaseModel):
    success: bool


class StyleAnalyzeRequest(BaseModel):
    tracked_page_id: int | None = None
    own_page_connection_id: int | None = None
    pasted_text: str | None = None


class StyleAnalyzeFromTextRequest(BaseModel):
    posts: list[str]


class PersonaFromPostsResponse(BaseModel):
    persona_name: str
    niche: str
    tone_tags: list[str]
    language: str
    custom_instructions: str | None = None
    prompt_config: dict
    hashtags_enabled: bool = False
    hashtag_count: int = 3
    always_include_engagement_hook: bool = False
    creativity_level: int = 7


class StyleAnalysisRead(BaseModel):
    id: int
    source_type: str
    source_identifier: str
    page_name: str | None = None
    report: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class StyleApplyRequest(BaseModel):
    persona_id: int
    analysis_id: int | None = None
    inspiration_post: str | None = None


class TrackedPageCreate(BaseModel):
    url: str
    name: str

class TrackedPagePostsCreate(BaseModel):
    posts: list[str]


class TrackedPageRead(BaseModel):
    id: int
    page_identifier: str
    page_name: str | None = None
    nickname: str
    is_active: bool
    last_checked_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrackerDashboardResponse(BaseModel):
    tracked_pages: list[dict] = Field(default_factory=list)
    posts: list[dict] = Field(default_factory=list)
    comparison: list[dict] = Field(default_factory=list)
    trends: list[dict] = Field(default_factory=list)


class LearnedStrategyRead(BaseModel):
    id: int
    persona_id: int
    strategy_data: dict
    suggested_prompt: str | None = None
    confidence_score: float
    week_start_date: date
    applied_to_prompt: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class StrategyDecisionRequest(BaseModel):
    action: str
    prompt: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    model: str

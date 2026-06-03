from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


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
    brand_logo_url: str | None = None
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
    brand_logo_url: str | None = None


class PageConnectionRead(BaseModel):
    id: int
    facebook_page_id: str | None = None
    page_id: str
    page_name: str
    profile_picture_url: str | None = None
    page_picture_url: str | None = None
    connection_status: str
    connected_at: datetime
    disconnected_at: datetime | None = None
    reconnect_count: int = 0
    post_count: int = 0
    scheduled_post_count: int = 0
    paused_post_count: int = 0

    model_config = {"from_attributes": True}


class PageDisconnectResponse(BaseModel):
    success: bool
    message: str
    paused_posts: int


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
    image_url: str | None = None
    image_status: str | None = None
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
    include_image: bool = False
    image_fallback_policy: str = "text_only"
    template_image_generation_enabled: bool = False
    template_logo_url: str | None = None
    template_layers_json: dict | None = None
    template_reference_image_url: str | None = None


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
    include_image: bool = False
    image_fallback_policy: str = "text_only"
    template_image_generation_enabled: bool = False
    template_logo_url: str | None = None
    template_layers_json: dict | None = None
    template_reference_image_url: str | None = None

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


# --- Manual template builder: template_json option-list structure ---

class BackgroundOption(BaseModel):
    asset_id: str
    label: str


class FontOption(BaseModel):
    font_asset_id: str
    label: str


class TextColorOption(BaseModel):
    color_hex: str
    label: str


class OverlayColorOption(BaseModel):
    color_hex: str
    opacity: float = Field(ge=0.0, le=1.0)
    label: str


class TemplateLayerBase(BaseModel):
    id: str
    z_index: int
    position_x_percent: float = Field(ge=0, le=100)
    position_y_percent: float = Field(ge=0, le=100)
    width_percent: float = Field(ge=0, le=100)
    height_percent: float = Field(ge=0, le=100)


class TextTemplateLayer(TemplateLayerBase):
    type: Literal["text"] = "text"
    role: Literal["headline", "subheadline", "body"]
    font_options: list[FontOption] = Field(min_length=1)
    color_options: list[TextColorOption] = Field(min_length=1)
    font_size_min_percent: float = Field(gt=0)
    font_size_max_percent: float = Field(gt=0)
    text_align_options: list[Literal["left", "center", "right"]] = Field(min_length=1)
    font_weight: Literal["bold", "regular"]


class OverlayTemplateLayer(TemplateLayerBase):
    type: Literal["overlay"] = "overlay"
    color_options: list[OverlayColorOption] = Field(min_length=1)


class LogoTemplateLayer(TemplateLayerBase):
    type: Literal["logo"] = "logo"


TemplateLayer = Annotated[
    Union[TextTemplateLayer, OverlayTemplateLayer, LogoTemplateLayer],
    Field(discriminator="type"),
]


class ManualTemplateJson(BaseModel):
    """template_json for manually built templates (option lists + fixed layout)."""

    canvas_width: int = Field(gt=0)
    canvas_height: int = Field(gt=0)
    aspect_ratio: str
    background_options: list[BackgroundOption] = Field(min_length=1, max_length=6)
    layers: list[TemplateLayer] = Field(default_factory=list)


class ManualImageTemplateCreate(BaseModel):
    name: str
    canvas_width: int = Field(gt=0)
    canvas_height: int = Field(gt=0)
    aspect_ratio: str
    template_json: ManualTemplateJson

    @model_validator(mode="after")
    def canvas_fields_match_template_json(self) -> "ManualImageTemplateCreate":
        tj = self.template_json
        if tj.canvas_width != self.canvas_width:
            raise ValueError("canvas_width must match template_json.canvas_width")
        if tj.canvas_height != self.canvas_height:
            raise ValueError("canvas_height must match template_json.canvas_height")
        if tj.aspect_ratio != self.aspect_ratio:
            raise ValueError("aspect_ratio must match template_json.aspect_ratio")
        return self


class ManualImageTemplateUpdate(BaseModel):
    name: str
    template_json: ManualTemplateJson


class ImageTemplatePreviewRequest(BaseModel):
    template_json: ManualTemplateJson
    persona_id: int | None = None


class ImageTemplateBase(BaseModel):
    name: str
    reference_image_url: str
    template_json: dict


class ImageTemplateCreate(ImageTemplateBase):
    pass


class ImageTemplateRead(ImageTemplateBase):
    id: str
    user_id: int
    creation_method: str = "extracted"
    canvas_width: int = 1080
    canvas_height: int = 1080
    aspect_ratio: str = "1:1"
    created_at: datetime

    model_config = {"from_attributes": True}

from datetime import datetime

from pydantic import BaseModel


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
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FacebookConnectRequest(BaseModel):
    short_lived_token: str | None = None
    code: str | None = None
    redirect_uri: str | None = None


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


class FacebookStatus(BaseModel):
    connected: bool
    is_connected: bool | None = None
    page_name: str | None = None
    page_id: str | None = None
    instagram_business_account_id: str | None = None


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
    id: int
    content: str


class PostPublishResponse(BaseModel):
    success: bool
    id: int
    status: str
    error_message: str | None = None


class PostHistoryItem(BaseModel):
    id: int
    content: str
    status: str
    posted_at: datetime | None = None

    model_config = {"from_attributes": True}

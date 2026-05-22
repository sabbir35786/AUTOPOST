from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.config import (
    FACEBOOK_APP_ID,
    FACEBOOK_APP_SECRET,
    FACEBOOK_GRAPH_API_BASE_URL,
    FRONTEND_URL,
)
from app.database import Base, engine, get_db
from app.posts import (
    create_draft_post,
    generate_post_content,
    get_user_schedule_and_connection,
    publish_post_to_facebook,
    release_user_posting,
    run_scheduled_posts,
    try_claim_user_posting,
)

pending_facebook_pages: dict[int, dict] = {}
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler.add_job(
        run_scheduled_posts,
        CronTrigger(minute="*/10"),
        id="scheduled_posts",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Auto Poster API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Auto Poster API"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/auth/register", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_user = (
        db.query(models.User).filter(models.User.email == user_data.email).first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    user = models.User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        name=user_data.name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=schemas.Token)
def login(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == credentials.email).first()
    if user is None or not verify_password(
        credentials.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me", response_model=schemas.UserRead)
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user


def _facebook_credentials_available() -> bool:
    return bool(FACEBOOK_APP_ID and FACEBOOK_APP_SECRET)


def _facebook_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=status_code, detail=message)


@app.post("/facebook/connect", response_model=schemas.FacebookConnectResponse)
async def connect_facebook(
    payload: schemas.FacebookConnectRequest,
    current_user: models.User = Depends(get_current_user),
):
    if not _facebook_credentials_available():
        _facebook_error(
            "Facebook app credentials are not configured",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        if payload.code:
            if not payload.redirect_uri:
                _facebook_error("redirect_uri is required with authorization code")
            token_response = await client.get(
                "oauth/access_token",
                params={
                    "client_id": FACEBOOK_APP_ID,
                    "client_secret": FACEBOOK_APP_SECRET,
                    "redirect_uri": payload.redirect_uri,
                    "code": payload.code,
                },
            )
        elif payload.short_lived_token:
            token_response = await client.get(
                "oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": FACEBOOK_APP_ID,
                    "client_secret": FACEBOOK_APP_SECRET,
                    "fb_exchange_token": payload.short_lived_token,
                },
            )
        else:
            _facebook_error("Provide a Facebook authorization code or token")

        if token_response.status_code >= 400:
            _facebook_error("Could not exchange Facebook token")

        token_data = token_response.json()
        long_lived_token = token_data.get("access_token")
        if not long_lived_token:
            _facebook_error("Facebook token exchange did not return an access token")

        if payload.code:
            long_lived_response = await client.get(
                "oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": FACEBOOK_APP_ID,
                    "client_secret": FACEBOOK_APP_SECRET,
                    "fb_exchange_token": long_lived_token,
                },
            )
            if long_lived_response.status_code >= 400:
                _facebook_error("Could not exchange Facebook token")
            token_data = long_lived_response.json()
            long_lived_token = token_data.get("access_token")
            if not long_lived_token:
                _facebook_error("Facebook token exchange did not return an access token")

        pages_response = await client.get(
            "me/accounts",
            params={"access_token": long_lived_token},
        )
        if pages_response.status_code >= 400:
            _facebook_error("Could not fetch Facebook pages")

    pages_data = pages_response.json().get("data", [])
    pages = [
        {
            "page_id": page.get("id"),
            "page_name": page.get("name"),
            "page_access_token": page.get("access_token"),
        }
        for page in pages_data
        if page.get("id") and page.get("name") and page.get("access_token")
    ]

    expires_in = token_data.get("expires_in")
    token_expires_at = None
    if expires_in is not None:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    pending_facebook_pages[current_user.id] = {
        "long_lived_user_token": long_lived_token,
        "token_expires_at": token_expires_at,
        "pages": pages,
    }

    return {
        "pages": [
            {"page_id": page["page_id"], "page_name": page["page_name"]}
            for page in pages
        ]
    }


@app.post("/facebook/select-page", response_model=schemas.FacebookSelectPageResponse)
async def select_facebook_page(
    payload: schemas.FacebookSelectPageRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pending_connection = pending_facebook_pages.get(current_user.id)
    if not pending_connection:
        _facebook_error("Connect Facebook before selecting a page")

    selected_page = next(
        (
            page
            for page in pending_connection["pages"]
            if page["page_id"] == payload.page_id
        ),
        None,
    )
    if selected_page is None:
        _facebook_error("Selected page was not found")

    instagram_business_account_id = None
    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        page_response = await client.get(
            payload.page_id,
            params={
                "fields": "instagram_business_account",
                "access_token": selected_page["page_access_token"],
            },
        )
        if page_response.status_code < 400:
            instagram_business_account = page_response.json().get(
                "instagram_business_account",
            )
            if instagram_business_account:
                instagram_business_account_id = instagram_business_account.get("id")

    existing_connection = (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == current_user.id)
        .first()
    )
    if existing_connection:
        db.delete(existing_connection)
        db.flush()

    connection = models.FacebookConnection(
        user_id=current_user.id,
        page_id=selected_page["page_id"],
        page_name=selected_page["page_name"],
        page_access_token=selected_page["page_access_token"],
        instagram_business_account_id=instagram_business_account_id,
        long_lived_user_token=pending_connection["long_lived_user_token"],
        token_expires_at=pending_connection["token_expires_at"],
    )
    db.add(connection)
    db.commit()
    pending_facebook_pages.pop(current_user.id, None)

    return {"success": True, "page_name": connection.page_name}


@app.get(
    "/facebook/status",
    response_model=schemas.FacebookStatus,
    response_model_exclude_none=True,
)
def facebook_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == current_user.id)
        .first()
    )
    if connection is None:
        return {"connected": False}

    return {
        "connected": True,
        "is_connected": True,
        "page_name": connection.page_name,
        "page_id": connection.page_id,
        "instagram_business_account_id": connection.instagram_business_account_id,
    }


@app.get("/schedule", response_model=schemas.ScheduleRead | None)
def get_schedule(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Schedule)
        .filter(models.Schedule.user_id == current_user.id)
        .first()
    )


@app.put("/schedule", response_model=schemas.ScheduleRead)
def upsert_schedule(
    payload: schemas.ScheduleUpsert,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(models.Schedule)
        .filter(models.Schedule.user_id == current_user.id)
        .first()
    )
    if schedule is None:
        schedule = models.Schedule(user_id=current_user.id)
        db.add(schedule)

    schedule.niche = payload.niche
    schedule.post_time = payload.post_time
    schedule.timezone = payload.timezone
    schedule.active = payload.active

    db.commit()
    db.refresh(schedule)
    return schedule


@app.post("/posts/generate", response_model=schemas.PostGenerateResponse)
def generate_post(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        schedule, connection = get_user_schedule_and_connection(db, current_user.id)
        content = generate_post_content(schedule.niche)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    post_log = create_draft_post(db, current_user.id, content, connection.id)
    return {"id": post_log.id, "content": post_log.content}


@app.post("/posts/{post_id}/publish", response_model=schemas.PostPublishResponse)
async def publish_post(
    post_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not try_claim_user_posting(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A post is already being published for this user",
        )

    try:
        post_log = (
            db.query(models.PostLog)
            .filter(
                models.PostLog.id == post_id,
                models.PostLog.user_id == current_user.id,
                models.PostLog.status == "draft",
            )
            .first()
        )
        if post_log is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft post not found",
            )

        connection = (
            db.query(models.FacebookConnection)
            .filter(
                models.FacebookConnection.id == post_log.facebook_connection_id,
                models.FacebookConnection.user_id == current_user.id,
            )
            .first()
        )
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Facebook connection not found",
            )

        success = await publish_post_to_facebook(db, post_log, connection)
        db.refresh(post_log)
        return {
            "success": success,
            "id": post_log.id,
            "status": post_log.status,
            "error_message": post_log.error_message,
        }
    finally:
        release_user_posting(current_user.id)


@app.get("/posts/history", response_model=list[schemas.PostHistoryItem])
def post_history(
    limit: int = Query(default=5, ge=1, le=50),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.PostLog)
        .filter(models.PostLog.user_id == current_user.id)
        .order_by(
            models.PostLog.posted_at.desc().nullslast(),
            models.PostLog.id.desc(),
        )
        .limit(limit)
        .all()
    )

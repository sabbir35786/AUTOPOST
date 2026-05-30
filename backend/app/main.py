from contextlib import asynccontextmanager
import asyncio
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from jose import JWTError, jwt
from sqlalchemy import func, Integer
from sqlalchemy.orm import Session, object_session

from app import models, schemas
from app import facebook_oauth
from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.chat import create_chat_reply
from app.config import (
    ALGORITHM,
    FACEBOOK_APP_ID,
    FACEBOOK_APP_SECRET,
    FACEBOOK_GRAPH_API_BASE_URL,
    FACEBOOK_OAUTH_SCOPES,
    FACEBOOK_REDIRECT_URI,
    FACEBOOK_TOKEN_ENCRYPTION_KEY,
    FAL_API_KEY,
    FRONTEND_URL,
    GEMINI_API_KEY,
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    OPENAI_API_KEY,
    SECRET_KEY,
    STABILITY_API_KEY,
    CRON_SECRET,
    SCHEDULER_INTERVAL_SECONDS,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
)
from app.crypto import decrypt_token, encrypt_token
from app.database import create_database_tables, get_db
from app.posts import (
    clear_all_user_posting_locks,
    create_draft_post,
    generate_caption_with_claude,
    generate_post_content,
    get_user_schedule_and_connection,
    publish_message_to_facebook,
    publish_post_to_facebook,
    release_user_posting,
    run_scheduled_posts,
    try_claim_user_posting,
    verify_page_connection_for_publish,
)
from app.mistral_service import (
    analyze_style_with_mistral,
    classify_post_topic,
    generate_ai_facebook_post,
    generate_ai_facebook_post_from_prompt,
    generate_ai_recommendations,
)
from app.routers import images, models as models_router
from app.mistral_service import (
    suggest_prompt_improvement,
    synthesize_learned_strategy,
)
from app.learning.service import (
    build_learning_prompt_hint,
    build_strategy_prompt_hint,
    get_performance_insights,
    reset_persona_learning,
    run_engagement_snapshot_job,
    run_weekly_learning_job,
    user_has_learning_access,
)

pending_facebook_credentials: dict[int, dict] = {}
scheduler_task: asyncio.Task | None = None
last_scheduler_run_at: datetime | None = None


async def _scheduled_post_worker() -> None:
    global last_scheduler_run_at
    while True:
        try:
            await run_scheduled_posts()
            await refresh_due_tracked_pages_all()
            last_scheduler_run_at = datetime.now(timezone.utc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Scheduled post worker failed: {exc}")
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


def _print_startup_config_status() -> None:
    required_env = {
        "DATABASE_URL": True,
        "SECRET_KEY": bool(SECRET_KEY and SECRET_KEY != "change-me"),
        "FRONTEND_URL": bool(FRONTEND_URL),
        "FACEBOOK_APP_ID": bool(FACEBOOK_APP_ID),
        "FACEBOOK_APP_SECRET": bool(FACEBOOK_APP_SECRET),
        "FACEBOOK_REDIRECT_URI": bool(FACEBOOK_REDIRECT_URI),
        "FACEBOOK_TOKEN_ENCRYPTION_KEY": bool(FACEBOOK_TOKEN_ENCRYPTION_KEY),
        "FACEBOOK_OAUTH_SCOPES": bool(FACEBOOK_OAUTH_SCOPES),
        "MISTRAL_API_KEY": bool(MISTRAL_API_KEY),
        "CRON_SECRET": bool(CRON_SECRET and CRON_SECRET != "your_cron_secret_here"),
    }
    optional_env = {
        "FAL_API_KEY": bool(FAL_API_KEY),
        "STABILITY_API_KEY": bool(STABILITY_API_KEY),
        "OPENAI_API_KEY": bool(OPENAI_API_KEY),
        "GEMINI_API_KEY": bool(GEMINI_API_KEY),
        "SUPABASE_URL": bool(SUPABASE_URL),
        "SUPABASE_SERVICE_KEY": bool(SUPABASE_SERVICE_KEY),
    }
    print("Environment configuration:")
    for name, loaded in required_env.items():
        status_icon = "OK" if loaded else "MISSING"
        status_message = "loaded" if loaded else "is missing"
        print(f"  [{status_icon}] {name} {status_message}")
    print("Optional provider keys:")
    for name, loaded in optional_env.items():
        status_icon = "OK" if loaded else "MISSING"
        print(f"  [{status_icon}] {name}")


async def _ensure_supabase_storage_bucket() -> None:
    """Create the 'generated-images' bucket in Supabase Storage if it doesn't exist.

    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY to be set in the environment.
    If either is missing the function logs a warning and returns without error.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("  [SKIP] Supabase storage setup skipped — SUPABASE_URL or SUPABASE_SERVICE_KEY not set.")
        return

    bucket_name = "generated-images"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    storage_url = SUPABASE_URL.rstrip("/") + "/storage/v1"

    async with httpx.AsyncClient(timeout=15) as client:
        # Check if bucket already exists
        list_resp = await client.get(f"{storage_url}/bucket", headers=headers)
        if list_resp.status_code == 200:
            existing = [b.get("name") for b in list_resp.json()]
            if bucket_name in existing:
                print(f"  [OK] Supabase bucket '{bucket_name}' already exists.")
                return

        # Create the bucket with public read access
        create_resp = await client.post(
            f"{storage_url}/bucket",
            headers=headers,
            json={"id": bucket_name, "name": bucket_name, "public": True},
        )
        if create_resp.status_code in (200, 201):
            print(f"  [OK] Supabase bucket '{bucket_name}' created with public read access.")
        elif create_resp.status_code == 409:
            print(f"  [OK] Supabase bucket '{bucket_name}' already exists (conflict).")
        else:
            print(
                f"  [WARN] Could not create Supabase bucket '{bucket_name}': "
                f"{create_resp.status_code} {create_resp.text[:200]}"
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler_task
    _print_startup_config_status()
    create_database_tables()
    clear_all_user_posting_locks()
    scheduler_task = asyncio.create_task(_scheduled_post_worker())
    asyncio.create_task(_ensure_supabase_storage_bucket())
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
            scheduler_task = None


app = FastAPI(title="Auto Poster API", lifespan=lifespan)
app.include_router(images.router)
app.include_router(models_router.router)

_allowed_origins = [
    FRONTEND_URL,
    "https://autopost-woad.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=False)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Auto Poster API"}


@app.get("/health")
def health_check():
    return "ok"


@app.get("/api/health")
def api_health_check():
    return "ok"


@app.get("/api/internal/run-scheduler")
async def run_internal_scheduler(request: Request):
    global last_scheduler_run_at
    try:
        cron_header = request.headers.get("X-Cron-Secret")
        auth_header = request.headers.get("Authorization")
        expected_bearer = f"Bearer {CRON_SECRET}"
        if cron_header != CRON_SECRET and auth_header != expected_bearer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
            )
        
        await run_scheduled_posts()
        await refresh_due_tracked_pages_all()
        last_scheduler_run_at = datetime.now(timezone.utc)
        
        return {
            "status": "ok",
            "message": "Scheduler run completed",
            "timestamp": str(datetime.now(timezone.utc)),
        }
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        print(f"Error running scheduler endpoint: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.get("/api/internal/init-db")
def init_db(request: Request):
    try:
        cron_header = request.headers.get("X-Cron-Secret")
        if not cron_header or cron_header != CRON_SECRET:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
            )
        
        create_database_tables()
        
        return {
            "status": "ok",
            "message": "Database tables and columns initialized successfully",
            "timestamp": str(datetime.now(timezone.utc)),
        }
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        print(f"Error running database initialization endpoint: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.post("/auth/register", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    email = user_data.email.strip().lower()
    existing_user = (
        db.query(models.User).filter(models.User.email == email).first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    user = models.User(
        email=email,
        hashed_password=get_password_hash(user_data.password),
        name=user_data.name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=schemas.Token)
def login(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    email = credentials.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email).first()
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
    return schemas.UserRead.from_orm(current_user)


@app.post("/chat", response_model=schemas.ChatResponse)
async def chat(
    payload: schemas.ChatRequest,
    current_user: models.User = Depends(get_current_user),
):
    
    try:
        reply = await create_chat_reply(
            payload.message,
            [message.model_dump() for message in payload.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return {"reply": reply, "model": MISTRAL_MODEL}


def _facebook_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=status_code, detail=message)


def _get_pending_or_global_facebook_credentials(user_id: int) -> tuple[str, str]:
    pending_credentials = pending_facebook_credentials.get(user_id)
    if pending_credentials:
        return pending_credentials["app_id"], pending_credentials["app_secret"]
    return FACEBOOK_APP_ID, FACEBOOK_APP_SECRET


@app.get("/auth/facebook/start")
def start_facebook_oauth_route(
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    user = facebook_oauth.current_user_from_popup_token(token, db)
    return facebook_oauth.start_facebook_oauth(request, user, db)


@app.get("/auth/facebook/callback", response_class=HTMLResponse)
async def facebook_oauth_callback_route(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return await facebook_oauth.handle_facebook_callback(request, db, code, state, error)


@app.post("/auth/facebook/select-page", response_class=HTMLResponse)
async def select_facebook_page_from_popup_route(
    request: Request,
    db: Session = Depends(get_db),
):
    return await facebook_oauth.handle_select_page_from_popup(request, db)


@app.post("/facebook/oauth-url", response_model=schemas.FacebookOAuthUrlResponse)
def create_facebook_oauth_url(
    payload: schemas.FacebookOAuthUrlRequest,
    current_user: models.User = Depends(get_current_user),
):
    app_id = payload.app_id.strip()
    app_secret = payload.app_secret.strip()
    redirect_uri = payload.redirect_uri.strip()
    if app_id == "server-configured":
        app_id = FACEBOOK_APP_ID
    if app_secret == "server-configured":
        app_secret = FACEBOOK_APP_SECRET
    if not app_id or not app_secret or not redirect_uri:
        _facebook_error("Facebook app id, app secret, and redirect_uri are required")

    state = secrets.token_hex(16)
    pending_facebook_credentials[current_user.id] = {
        "app_id": app_id,
        "app_secret": app_secret,
        "redirect_uri": redirect_uri,
        "state": state,
    }

    params = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": FACEBOOK_OAUTH_SCOPES,
            "state": state,
        }
    )
    return {
        "authorization_url": f"https://www.facebook.com/v18.0/dialog/oauth?{params}"
    }


@app.post("/facebook/connect", response_model=schemas.FacebookConnectResponse)
async def connect_facebook(
    payload: schemas.FacebookConnectRequest,
    current_user: models.User = Depends(get_current_user),
):
    pending_credentials = pending_facebook_credentials.get(current_user.id)
    if payload.code and pending_credentials:
        if payload.state != pending_credentials["state"]:
            _facebook_error("Facebook authorization state did not match")

    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
        _facebook_error(
            "Facebook app credentials are not configured",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    redirect_uri = payload.redirect_uri or FACEBOOK_REDIRECT_URI
    if payload.code:
        access_token, token_data = await facebook_oauth._exchange_code_for_token(payload.code)
    elif payload.short_lived_token:
        access_token = payload.short_lived_token
        token_data = None
    else:
        _facebook_error("Provide a Facebook authorization code or token")

    if not access_token:
        _facebook_error("Could not exchange Facebook token")

    pages = await facebook_oauth._fetch_managed_pages(access_token)
    if not pages:
        _facebook_error("Could not fetch Facebook pages")

    token_expires_at = None
    if token_data and token_data.get("expires_in") is not None:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))

    await facebook_oauth.store_pending_pages_for_user(current_user.id, pages, token_expires_at)
    pending_facebook_credentials.pop(current_user.id, None)

    return {
        "pages": [{"page_id": page["page_id"], "page_name": page["page_name"]} for page in pages]
    }


@app.post("/facebook/select-page", response_model=schemas.FacebookSelectPageResponse)
async def select_facebook_page(
    payload: schemas.FacebookSelectPageRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        connection = facebook_oauth.select_page_for_user(db, current_user.id, payload.page_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            _facebook_error(str(exc.detail), exc.status_code)
        raise
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
        .filter(
            models.FacebookConnection.user_id == current_user.id,
            models.FacebookConnection.connection_status == "connected",
        )
        .order_by(models.FacebookConnection.connected_at.desc())
        .first()
    )
    if connection is None:
        return {"connected": False}

    return {
        "connected": True,
        "is_connected": True,
        "page_name": connection.page_name,
        "page_id": connection.page_id,
        "page_picture_url": connection.page_picture_url,
        "connection_status": connection.connection_status,
        "instagram_business_account_id": connection.instagram_business_account_id,
    }


@app.get("/facebook/pages", response_model=list[schemas.PageConnectionRead])
def list_facebook_pages(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return facebook_oauth.list_user_page_connections(db, current_user.id)


@app.get("/api/pages", response_model=list[schemas.PageConnectionRead])
def list_api_pages(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return facebook_oauth.list_user_page_connections(db, current_user.id)


@app.delete("/api/pages/{connection_id}/disconnect", response_model=schemas.PageDisconnectResponse)
def disconnect_api_page(
    connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return facebook_oauth.disconnect_page_connection(db, current_user.id, connection_id)


@app.post("/api/admin/clear-posting-lock")
def clear_posting_lock(
    current_user: models.User = Depends(get_current_user),
):
    """Clear the posting lock for the current user. Use this if publishing is stuck."""
    release_user_posting(current_user.id)
    return {"success": True, "message": "Posting lock cleared"}


VALID_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
VALID_PRIORITIES = ["High", "Normal", "Low"]


def _serialize_ai_persona(persona: models.AIPersona) -> dict:
    return {
        "id": persona.id,
        "page_connection_id": persona.page_connection_id,
        "user_id": persona.user_id,
        "persona_name": persona.persona_name,
        "niche": persona.niche,
        "tone_tags": [tag.strip() for tag in persona.tone_tags.split(",") if tag.strip()],
        "custom_instructions": persona.custom_instructions,
        "prompt_config": persona.prompt_config,
        "custom_prompt": persona.custom_prompt,
        "creativity_level": persona.creativity_level,
        "language": persona.language,
        "hashtags_enabled": persona.hashtags_enabled,
        "hashtag_count": persona.hashtag_count,
        "always_include_engagement_hook": persona.always_include_engagement_hook,
        "assigned_days": [day.strip() for day in persona.assigned_days.split(",") if day.strip()],
        "posting_time_slots": persona.posting_time_slots or [],
        "priority_level": persona.priority_level,
        "is_active": persona.is_active,
        "learning_mode_enabled": persona.learning_mode_enabled,
        "minimum_engagement_threshold": float(persona.minimum_engagement_threshold or 0),
        "performance_score": float(persona.performance_score or 0.5),
        "total_posts_published": persona.total_posts_published,
        "total_likes_received": persona.total_likes_received,
        "total_comments_received": persona.total_comments_received,
        "total_shares_received": persona.total_shares_received,
        "total_reach_received": persona.total_reach_received,
        "last_performance_update_at": persona.last_performance_update_at,
        "last_auto_post_at": persona.last_auto_post_at,
        "learned_patterns_summary": persona.learned_patterns_summary,
    }


def _get_owned_page(db: Session, user_id: int, connection_id: int) -> models.FacebookConnection:
    connection = (
        db.query(models.FacebookConnection)
        .filter(
            models.FacebookConnection.id == connection_id,
            models.FacebookConnection.user_id == user_id,
        )
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facebook connection not found")
    return connection


def _facebook_page_identifier(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Facebook Page URL or ID is required")
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        parsed = urlparse(cleaned)
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[0]
    return cleaned.strip("/")


def _analysis_token(db: Session, current_user: models.User, own_page_connection_id: int | None = None) -> str:
    connection = None
    if own_page_connection_id is not None:
        connection = _get_owned_page(db, current_user.id, own_page_connection_id)
    else:
        connection = (
            db.query(models.FacebookConnection)
            .filter(models.FacebookConnection.user_id == current_user.id, models.FacebookConnection.connection_status == "connected")
            .first()
        )
    if connection is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect a Facebook Page before analyzing public pages")
    return decrypt_token(connection.page_access_token)





def _emoji_count(text: str) -> int:
    return sum(1 for char in text if ord(char) > 10000)


def _hashtag_count(text: str) -> int:
    import re
    return len(re.findall(r"#\w+", text))


def _style_report_from_posts(page_name: str | None, posts: list[dict]) -> dict:
    import re
    words = []
    for post in posts:
        words.extend(re.findall(r"[A-Za-z\u0980-\u09FF]{3,}", post["content"].lower()))
    stop = {"the", "and", "for", "with", "that", "this", "you", "your", "are", "from", "have", "will", "they", "but", "not"}
    counts: dict[str, int] = {}
    for word in words:
        if word not in stop:
            counts[word] = counts.get(word, 0) + 1
    post_count = max(len(posts), 1)
    word_lengths = [len(post["content"].split()) for post in posts]
    emoji_counts = [_emoji_count(post["content"]) for post in posts]
    hashtag_counts = [_hashtag_count(post["content"]) for post in posts]
    question_count = sum(1 for post in posts if post["content"].strip().endswith("?"))
    ai = analyze_style_with_mistral([post["content"] for post in posts], MISTRAL_MODEL)
    day_scores: dict[str, list[float]] = {}
    hour_scores: dict[str, list[float]] = {}
    for post in posts:
        posted_at = post.get("posted_at")
        if posted_at:
            day_scores.setdefault(posted_at.strftime("%a"), []).append(float(post["engagement_score"]))
            hour_scores.setdefault(str(posted_at.hour), []).append(float(post["engagement_score"]))
    return {
        "page_name": page_name,
        "writing_style": {
            "average_words": round(sum(word_lengths) / post_count, 1) if word_lengths else 0,
            "sentence_structure": "short punchy" if (sum(word_lengths) / post_count if word_lengths else 0) < 80 else "long narrative",
            "reading_level": "simple conversational" if (sum(word_lengths) / post_count if word_lengths else 0) < 120 else "detailed",
            "top_words": [{"text": word, "count": count} for word, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:30]],
            "question_ending_percent": round((question_count / post_count) * 100, 1),
            "emoji_post_percent": round((sum(1 for count in emoji_counts if count) / post_count) * 100, 1),
            "average_emoji_count": round(sum(emoji_counts) / post_count, 1),
            "hashtag_post_percent": round((sum(1 for count in hashtag_counts if count) / post_count) * 100, 1),
            "average_hashtag_count": round(sum(hashtag_counts) / post_count, 1),
        },
        "topics": ai.get("topics", []),
        "posting_behavior": {
            "best_days": [{"day": day, "score": sum(scores) / len(scores)} for day, scores in day_scores.items()],
            "best_hours": [{"hour": hour, "score": sum(scores) / len(scores)} for hour, scores in hour_scores.items()],
            "average_posts_per_week": round(len(posts) / 4, 1),
            "average_engagement_score": round(sum(float(post["engagement_score"]) for post in posts) / post_count, 1),
        },
        "top_posts": sorted(posts, key=lambda post: post["engagement_score"], reverse=True)[:5],
        "summary": ai.get("summary") or "No AI summary was generated.",
    }


def _save_tracked_posts(db: Session, tracked: models.TrackedPage, posts: list[str]) -> None:
    import uuid
    for post_content in posts:
        post_content = post_content.strip()
        if not post_content:
            continue
        topic = classify_post_topic(post_content, MISTRAL_MODEL)
        tracked_post = models.TrackedPagePost(
            tracked_page_id=tracked.id,
            facebook_post_id=str(uuid.uuid4()),
            content=post_content,
            posted_at=datetime.now(timezone.utc),
            likes_count=0,
            comments_count=0,
            shares_count=0,
            engagement_score=0,
            topic=topic,
        )
        db.add(tracked_post)
        if topic:
            _record_learning_signal(
                db,
                tracked.user_id,
                None,
                "competitor_trend",
                {"tracked_page_id": tracked.id, "topic": topic, "content": post_content[:500]},
                0.0,
            )


def _record_learning_signal(
    db: Session,
    user_id: int,
    persona_id: int | None,
    signal_type: str,
    signal_data: dict,
    outcome_score: float,
) -> None:
    db.add(models.LearningSignal(
        user_id=user_id,
        persona_id=persona_id,
        signal_type=signal_type,
        signal_data=signal_data,
        outcome_score=outcome_score,
    ))


def _save_prompt_template_snapshot(db: Session, persona: models.AIPersona) -> None:
    config = persona.prompt_config or {}
    template_name = str(config.get("template") or persona.persona_name or "Custom")
    existing = (
        db.query(models.PromptTemplate)
        .filter(models.PromptTemplate.persona_id == persona.id)
        .order_by(models.PromptTemplate.created_at.desc())
        .first()
    )
    target = existing or models.PromptTemplate(user_id=persona.user_id, persona_id=persona.id)
    if existing is None:
        db.add(target)
    target.template_name = template_name
    target.question_answers = config
    target.assembled_prompt = persona.custom_instructions
    target.raw_prompt = persona.custom_prompt
    target.creativity_level = persona.creativity_level
    examples = config.get("examples", "")
    target.style_examples = [examples] if isinstance(examples, str) and examples.strip() else []
    target.updated_at = datetime.now(timezone.utc)


def _latest_learned_strategy_hint(db: Session, persona: models.AIPersona) -> str | None:
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
        bits.append(f"avoid low-performing topics: {', '.join(map(str, data['topics_to_decrease'][:5]))}")
    if not bits:
        return None
    return "Based on recent performance data, prioritize these approaches: " + "; ".join(bits) + "."


def _week_start(value: datetime) -> date:
    local_date = value.date()
    return local_date - timedelta(days=local_date.weekday())


def _synthesize_persona_strategy(db: Session, persona: models.AIPersona, week_start: date | None = None) -> models.LearnedStrategy | None:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    signals = (
        db.query(models.LearningSignal)
        .filter(models.LearningSignal.persona_id == persona.id, models.LearningSignal.created_at >= since)
        .order_by(models.LearningSignal.created_at.desc())
        .all()
    )
    if not signals:
        return None
    signal_payload = [
        {
            "type": signal.signal_type,
            "data": signal.signal_data,
            "outcome_score": float(signal.outcome_score or 0),
            "created_at": signal.created_at,
        }
        for signal in signals
    ]
    strategy_data = synthesize_learned_strategy(signal_payload, MISTRAL_MODEL)
    confidence = float(strategy_data.get("confidence_score") or 0)
    current_prompt = persona.custom_prompt or persona.custom_instructions or persona.niche
    suggested_prompt = suggest_prompt_improvement(current_prompt, strategy_data, MISTRAL_MODEL)
    target_week = week_start or _week_start(datetime.now(timezone.utc))
    existing = (
        db.query(models.LearnedStrategy)
        .filter(models.LearnedStrategy.persona_id == persona.id, models.LearnedStrategy.week_start_date == target_week)
        .first()
    )
    strategy = existing or models.LearnedStrategy(persona_id=persona.id, week_start_date=target_week)
    if existing is None:
        db.add(strategy)
    strategy.strategy_data = strategy_data
    strategy.suggested_prompt = suggested_prompt
    strategy.confidence_score = confidence
    strategy.applied_to_prompt = False
    return strategy





def _detect_tracker_trends(db: Session, user_id: int) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        db.query(models.TrackedPagePost, models.TrackedPage)
        .join(models.TrackedPage, models.TrackedPage.id == models.TrackedPagePost.tracked_page_id)
        .filter(models.TrackedPage.user_id == user_id, models.TrackedPagePost.posted_at >= since, models.TrackedPagePost.topic.isnot(None))
        .all()
    )
    by_topic: dict[str, set[int]] = {}
    scores: dict[str, list[float]] = {}
    for post, page in rows:
        topic = post.topic or ""
        by_topic.setdefault(topic, set()).add(page.id)
        scores.setdefault(topic, []).append(float(post.engagement_score or 0))
    db.query(models.TrackerTrend).filter(models.TrackerTrend.user_id == user_id, models.TrackerTrend.generated_at >= since).delete()
    for topic, page_ids in by_topic.items():
        average = sum(scores.get(topic, [0])) / max(len(scores.get(topic, [])), 1)
        if len(page_ids) >= 2 and average > 0:
            db.add(models.TrackerTrend(
                user_id=user_id,
                topic=topic,
                summary=f"Trending topic detected in your niche this week: {topic}. {len(page_ids)} pages you track have posted about this with above-average engagement.",
                page_count=len(page_ids),
            ))


def _validate_posting_time_slots(slots: list[str]) -> bool:
    if len(slots) <= 1:
        return True
    minutes = []
    for s in slots:
        try:
            h, m = map(int, s.split(':'))
            minutes.append(h * 60 + m)
        except ValueError:
            return False
    minutes.sort()
    for i in range(len(minutes) - 1):
        if minutes[i+1] - minutes[i] < 240:
            return False
    if (minutes[0] + 1440) - minutes[-1] < 240:
        return False
    return True


def _validate_persona_payload(payload: schemas.AIPersonaBase) -> tuple[str, str, list[str], list[str], list[str], str]:
    name = payload.persona_name.strip()
    niche = payload.niche.strip()
    tone_tags = [tag.strip() for tag in payload.tone_tags if tag.strip()]
    assigned_days = [day for day in payload.assigned_days if day in VALID_DAYS]
    posting_time_slots = [slot for slot in payload.posting_time_slots if slot.strip()][:4]
    priority = payload.priority_level if payload.priority_level in VALID_PRIORITIES else "Normal"
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Persona name is required")
    if not niche:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Niche is required")
    if not tone_tags:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one tone is required")
    if not posting_time_slots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one posting time is required")
    if not _validate_posting_time_slots(posting_time_slots):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Posting times must be at least 4 hours apart to prevent spamming."
        )
    return name, niche, tone_tags, assigned_days, posting_time_slots, priority


def _unassign_days_from_other_personas(
    db: Session,
    user_id: int,
    connection_id: int,
    assigned_days: list[str],
    persona_id: int | None = None,
) -> None:
    if not assigned_days:
        return
    personas = (
        db.query(models.AIPersona)
        .filter(
            models.AIPersona.user_id == user_id,
            models.AIPersona.page_connection_id == connection_id,
        )
        .all()
    )
    for persona in personas:
        if persona_id is not None and persona.id == persona_id:
            continue
        remaining_days = [day for day in persona.assigned_days.split(",") if day and day not in assigned_days]
        persona.assigned_days = ",".join(remaining_days)


def _get_ai_settings(db: Session, user_id: int, connection_id: int) -> models.AIPersona:
    _get_owned_page(db, user_id, connection_id)
    persona = (
        db.query(models.AIPersona)
        .filter(
            models.AIPersona.user_id == user_id,
            models.AIPersona.page_connection_id == connection_id,
            models.AIPersona.is_active.is_(True),
        )
        .order_by(models.AIPersona.id.asc())
        .first()
    )
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI persona not configured for this page. Please set up an AI persona first.",
        )
    return persona


@app.get("/api/ai/personas/{page_connection_id}", response_model=list[schemas.AIPersonaRead])
def list_ai_personas(
    page_connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_page(db, current_user.id, page_connection_id)
    personas = (
        db.query(models.AIPersona)
        .filter(
            models.AIPersona.user_id == current_user.id,
            models.AIPersona.page_connection_id == page_connection_id,
        )
        .order_by(models.AIPersona.id.asc())
        .all()
    )
    return [_serialize_ai_persona(persona) for persona in personas]


@app.post("/api/ai/personas/{page_connection_id}", response_model=schemas.AIPersonaRead, status_code=status.HTTP_201_CREATED)
def create_ai_persona(
    page_connection_id: int,
    payload: schemas.AIPersonaCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_page(db, current_user.id, page_connection_id)
    if db.query(models.AIPersona).filter(models.AIPersona.page_connection_id == page_connection_id).count() >= 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A page can have up to 5 personas")
    name, niche, tone_tags, assigned_days, posting_time_slots, priority = _validate_persona_payload(payload)
    _unassign_days_from_other_personas(db, current_user.id, page_connection_id, assigned_days)
    persona = models.AIPersona(user_id=current_user.id, page_connection_id=page_connection_id)
    db.add(persona)
    persona.persona_name = name
    persona.niche = niche
    persona.tone_tags = ",".join(tone_tags)
    persona.custom_instructions = payload.custom_instructions
    persona.prompt_config = payload.prompt_config
    persona.custom_prompt = payload.custom_prompt
    persona.creativity_level = max(1, min(payload.creativity_level, 10))
    persona.language = payload.language
    persona.hashtags_enabled = payload.hashtags_enabled
    persona.hashtag_count = max(1, min(payload.hashtag_count, 5))
    persona.always_include_engagement_hook = payload.always_include_engagement_hook
    persona.assigned_days = ",".join(assigned_days)
    persona.posting_time_slots = posting_time_slots
    persona.priority_level = priority
    persona.is_active = payload.is_active
    persona.learning_mode_enabled = payload.learning_mode_enabled
    persona.minimum_engagement_threshold = max(0, payload.minimum_engagement_threshold)
    db.flush()
    _save_prompt_template_snapshot(db, persona)
    db.commit()
    db.refresh(persona)
    return _serialize_ai_persona(persona)


@app.put("/api/ai/personas/{persona_id}", response_model=schemas.AIPersonaRead)
def update_ai_persona(
    persona_id: int,
    payload: schemas.AIPersonaUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == persona_id, models.AIPersona.user_id == current_user.id).first()
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    name, niche, tone_tags, assigned_days, posting_time_slots, priority = _validate_persona_payload(payload)
    _unassign_days_from_other_personas(db, current_user.id, persona.page_connection_id, assigned_days, persona.id)
    persona.persona_name = name
    persona.niche = niche
    persona.tone_tags = ",".join(tone_tags)
    persona.custom_instructions = payload.custom_instructions
    persona.prompt_config = payload.prompt_config
    persona.custom_prompt = payload.custom_prompt
    persona.creativity_level = max(1, min(payload.creativity_level, 10))
    persona.language = payload.language
    persona.hashtags_enabled = payload.hashtags_enabled
    persona.hashtag_count = max(1, min(payload.hashtag_count, 5))
    persona.always_include_engagement_hook = payload.always_include_engagement_hook
    persona.assigned_days = ",".join(assigned_days)
    persona.posting_time_slots = posting_time_slots
    persona.priority_level = priority
    persona.is_active = payload.is_active
    persona.learning_mode_enabled = payload.learning_mode_enabled
    persona.minimum_engagement_threshold = max(0, payload.minimum_engagement_threshold)
    persona.updated_at = datetime.now(timezone.utc)
    _save_prompt_template_snapshot(db, persona)
    db.commit()
    db.refresh(persona)
    return _serialize_ai_persona(persona)


@app.get("/api/ai/personas/{persona_id}/strategy", response_model=schemas.LearnedStrategyRead | None)
def get_persona_strategy(
    persona_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == persona_id, models.AIPersona.user_id == current_user.id).first()
    if not persona:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    strategy = (
        db.query(models.LearnedStrategy)
        .filter(models.LearnedStrategy.persona_id == persona_id)
        .order_by(models.LearnedStrategy.created_at.desc())
        .first()
    )
    return strategy


@app.post("/api/ai/personas/{persona_id}/strategy-decision")
def apply_strategy_decision(
    persona_id: int,
    payload: schemas.StrategyDecisionRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == persona_id, models.AIPersona.user_id == current_user.id).first()
    if not persona:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    
    strategy = (
        db.query(models.LearnedStrategy)
        .filter(models.LearnedStrategy.persona_id == persona_id)
        .order_by(models.LearnedStrategy.created_at.desc())
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No strategy found to apply")

    if payload.action == "accept":
        persona.custom_prompt = strategy.suggested_prompt
        persona.custom_instructions = strategy.suggested_prompt
    elif payload.action == "partial" and payload.prompt is not None:
        persona.custom_prompt = payload.prompt
        persona.custom_instructions = payload.prompt
    
    strategy.applied_to_prompt = True
    db.commit()
    return {"success": True}


@app.get("/api/ai/settings/{page_connection_id}", response_model=schemas.AIPageSettingsRead | None)
def get_ai_page_settings(page_connection_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    personas = list_ai_personas(page_connection_id, current_user, db)
    return personas[0] if personas else None


@app.get("/api/ai/performance/{page_connection_id}", response_model=schemas.PerformanceInsightsResponse)
def ai_performance_insights(
    page_connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_page(db, current_user.id, page_connection_id)
    return get_performance_insights(db, page_connection_id, current_user)


@app.post("/api/style/analyze", response_model=schemas.StyleAnalysisRead)
async def analyze_facebook_style(
    payload: schemas.StyleAnalyzeRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # NEW: Handle pasted_text directly
    if payload.pasted_text and payload.pasted_text.strip():
        from app.mistral_service import analyze_style_with_mistral
        posts_list = [payload.pasted_text.strip()]
        ai_summary = analyze_style_with_mistral(posts_list)
        report = {
            "writing_style": {
                "average_words": len(payload.pasted_text.split()),
                "question_ending_percent": 100 if payload.pasted_text.strip().endswith("?") else 0,
                "top_words": [],
            },
            "posting_behavior": {
                "average_engagement_score": 0,
                "best_days": [],
                "best_hours": [],
            },
            "topics": ai_summary.get("topics", []),
            "top_posts": [{"content": payload.pasted_text.strip(), "likes_count": 0, "comments_count": 0, "shares_count": 0, "engagement_score": 0}],
            "summary": ai_summary.get("summary", ""),
        }
        analysis = models.StyleAnalysis(
            user_id=current_user.id,
            source_type="pasted_text",
            source_identifier="pasted",
            page_name=None,
            report=report,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis

    source_type = "own_page" if payload.own_page_connection_id else "tracked_page"
    page_name = None
    posts = []
    
    if payload.own_page_connection_id:
        connection = _get_owned_page(db, current_user.id, payload.own_page_connection_id)
        identifier = connection.page_id
        page_name = connection.page_name
        db_posts = db.query(models.PostLog).filter(models.PostLog.facebook_connection_id == connection.id, models.PostLog.status.in_(["published", "success"])).all()
        for p in db_posts:
            snapshot = _latest_snapshot_map(db, [p.id]).get(p.id)
            posts.append({
                "content": p.content,
                "posted_at": p.posted_at,
                "engagement_score": snapshot.engagement_score if snapshot else 0,
            })
    else:
        if not payload.tracked_page_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must provide own_page_connection_id or tracked_page_id")
        tracked = db.query(models.TrackedPage).filter(models.TrackedPage.id == payload.tracked_page_id, models.TrackedPage.user_id == current_user.id).first()
        if not tracked:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracked page not found")
        identifier = tracked.page_identifier
        page_name = tracked.page_name
        db_posts = db.query(models.TrackedPagePost).filter(models.TrackedPagePost.tracked_page_id == tracked.id).all()
        for p in db_posts:
            posts.append({
                "content": p.content,
                "posted_at": p.posted_at,
                "engagement_score": p.engagement_score,
            })

    if not posts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No readable posts were found for this page")
    report = _style_report_from_posts(page_name, posts)
    analysis = models.StyleAnalysis(
        user_id=current_user.id,
        source_type=source_type,
        source_identifier=identifier,
        page_name=page_name,
        report=report,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis



@app.get("/api/style/analyses", response_model=list[schemas.StyleAnalysisRead])
def list_style_analyses(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.StyleAnalysis)
        .filter(models.StyleAnalysis.user_id == current_user.id)
        .order_by(models.StyleAnalysis.created_at.desc())
        .limit(10)
        .all()
    )


@app.post("/api/style/apply")
def apply_style_to_persona(
    payload: schemas.StyleApplyRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == payload.persona_id, models.AIPersona.user_id == current_user.id).first()
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    style_text = ""
    if payload.analysis_id:
        analysis = db.query(models.StyleAnalysis).filter(models.StyleAnalysis.id == payload.analysis_id, models.StyleAnalysis.user_id == current_user.id).first()
        if analysis is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Style analysis not found")
        report = analysis.report or {}
        style_text = (
            f"Use this analyzed style as inspiration: {report.get('summary', '')} "
            f"Common topics: {', '.join(str(topic.get('name', topic)) for topic in report.get('topics', [])[:8])}. "
            "Do not copy exact wording; adapt the pattern for my own page."
        )
    elif payload.inspiration_post:
        style_text = f"Use this post as style inspiration, without copying it: {payload.inspiration_post.strip()}"
    if not style_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Analysis or inspiration post is required")
    existing = persona.custom_instructions or ""
    persona.custom_instructions = f"{existing}\n\n{style_text}".strip()
    if persona.custom_prompt:
        persona.custom_prompt = f"{persona.custom_prompt.strip()}\n\nSTYLE INSPIRATION:\n{style_text}"
    _record_learning_signal(
        db,
        current_user.id,
        persona.id,
        "style_match",
        {"style_text": style_text[:1200], "analysis_id": payload.analysis_id},
        0.5,
    )
    persona.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}


@app.post("/api/ai/generate-persona-from-posts")
async def generate_persona_from_posts_endpoint(
    payload: schemas.StyleAnalyzeFromTextRequest,
    current_user: models.User = Depends(get_current_user),
):
    """Analyze a list of pasted posts with an LLM and return a fully-populated
    AI persona configuration that the frontend can use to pre-fill the Prompt Studio form."""
    if not payload.posts or all(not p.strip() for p in payload.posts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No posts provided. Please paste at least one post.",
        )
    clean_posts = [p.strip() for p in payload.posts if p.strip()]
    from app.mistral_service import generate_persona_from_posts as _gen_persona
    result = _gen_persona(clean_posts)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate persona from posts. Make sure your AI API key is configured.",
        )
    return result



@app.get("/api/tracker", response_model=schemas.TrackerDashboardResponse)
def tracker_dashboard(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracked = db.query(models.TrackedPage).filter(models.TrackedPage.user_id == current_user.id).order_by(models.TrackedPage.created_at.desc()).all()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        db.query(models.TrackedPagePost, models.TrackedPage)
        .join(models.TrackedPage, models.TrackedPage.id == models.TrackedPagePost.tracked_page_id)
        .filter(models.TrackedPage.user_id == current_user.id, models.TrackedPagePost.posted_at >= since)
        .order_by(models.TrackedPagePost.engagement_score.desc())
        .limit(50)
        .all()
    )
    comparison = []
    for page in tracked:
        page_posts = [post for post, owner in rows if owner.id == page.id]
        if not page_posts:
            comparison.append({"id": page.id, "nickname": page.nickname, "posts": 0, "average_likes": 0, "average_comments": 0, "average_shares": 0, "most_active_day": "-", "most_used_topics": "-"})
            continue
        day_counts: dict[str, int] = {}
        topic_counts: dict[str, int] = {}
        for post in page_posts:
            if post.posted_at:
                day_counts[post.posted_at.strftime("%a")] = day_counts.get(post.posted_at.strftime("%a"), 0) + 1
            if post.topic:
                topic_counts[post.topic] = topic_counts.get(post.topic, 0) + 1
        comparison.append({
            "id": page.id,
            "nickname": page.nickname,
            "posts": len(page_posts),
            "average_likes": round(sum(post.likes_count for post in page_posts) / len(page_posts), 1),
            "average_comments": round(sum(post.comments_count for post in page_posts) / len(page_posts), 1),
            "average_shares": round(sum(post.shares_count for post in page_posts) / len(page_posts), 1),
            "most_active_day": max(day_counts.items(), key=lambda item: item[1])[0] if day_counts else "-",
            "most_used_topics": ", ".join(topic for topic, _ in sorted(topic_counts.items(), key=lambda item: item[1], reverse=True)[:3]) or "-",
        })
    trends = (
        db.query(models.TrackerTrend)
        .filter(models.TrackerTrend.user_id == current_user.id, models.TrackerTrend.is_dismissed.is_(False))
        .order_by(models.TrackerTrend.generated_at.desc())
        .limit(5)
        .all()
    )
    return {
        "tracked_pages": [{"id": page.id, "nickname": page.nickname, "page_identifier": page.page_identifier, "page_name": page.page_name, "is_active": page.is_active, "last_checked_at": page.last_checked_at} for page in tracked],
        "posts": [{"id": post.id, "page_name": page.nickname, "content": post.content, "posted_at": post.posted_at, "likes_count": post.likes_count, "comments_count": post.comments_count, "shares_count": post.shares_count, "engagement_score": float(post.engagement_score or 0), "topic": post.topic} for post, page in rows],
        "comparison": comparison,
        "trends": [{"id": trend.id, "topic": trend.topic, "summary": trend.summary, "page_count": trend.page_count, "generated_at": trend.generated_at} for trend in trends],
    }


@app.post("/api/tracker/pages", response_model=schemas.TrackedPageRead, status_code=status.HTTP_201_CREATED)
async def add_tracked_page(
    payload: schemas.TrackedPageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(models.TrackedPage).filter(models.TrackedPage.user_id == current_user.id).count() >= 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can track up to 10 pages")
    tracked = models.TrackedPage(user_id=current_user.id, page_identifier=payload.url, page_name=payload.name, nickname=payload.name)
    db.add(tracked)
    db.commit()
    db.refresh(tracked)
    return tracked

@app.post("/api/tracker/pages/{tracked_page_id}/posts")
async def add_manual_tracked_posts(
    tracked_page_id: int,
    payload: schemas.TrackedPagePostsCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracked = db.query(models.TrackedPage).filter(models.TrackedPage.id == tracked_page_id, models.TrackedPage.user_id == current_user.id).first()
    if not tracked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracked page not found")
    _save_tracked_posts(db, tracked, payload.posts)
    tracked.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}


@app.delete("/api/tracker/pages/{tracked_page_id}")
def delete_tracked_page(
    tracked_page_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracked = db.query(models.TrackedPage).filter(models.TrackedPage.id == tracked_page_id, models.TrackedPage.user_id == current_user.id).first()
    if tracked is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracked page not found")
    db.query(models.TrackedPagePost).filter(models.TrackedPagePost.tracked_page_id == tracked.id).delete()
    db.delete(tracked)
    db.commit()
    return {"success": True}


def _latest_snapshot_map(db: Session, post_ids: list[int]) -> dict[int, models.PostEngagementSnapshot]:
    if not post_ids:
        return {}
    snapshots = (
        db.query(models.PostEngagementSnapshot)
        .filter(models.PostEngagementSnapshot.post_id.in_(post_ids))
        .order_by(models.PostEngagementSnapshot.snapshot_taken_at.desc())
        .all()
    )
    latest = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.post_id, snapshot)
    return latest


def _dashboard_action_items(
    personas: list[models.AIPersona],
    posts: list[models.PostLog],
    recommendations: list[models.AIRecommendation],
) -> list[dict]:
    now = datetime.now(timezone.utc)
    actions = [
        {"id": f"ai-{item.id}", "text": item.recommendation_text, "action_label": "Review", "href": "/dashboard/analytics", "priority": "high"}
        for item in recommendations[:3]
    ]
    for persona in personas:
        if persona.last_auto_post_at is None or now - persona.last_auto_post_at > timedelta(days=4):
            actions.append({
                "id": f"persona-stale-{persona.id}",
                "text": f"{persona.persona_name} has not posted in 4 days. Consider generating a post now.",
                "action_label": "Generate Now",
                "href": "/dashboard/create",
                "priority": "high",
            })
            break
    recent = posts[:5]
    zero_comments = sum(1 for post in recent if getattr(post, "latest_comments_count", 0) == 0)
    if len(recent) >= 5 and zero_comments >= 3:
        actions.append({
            "id": "weak-comments",
            "text": "3 of your last 5 posts had zero comments. Try adding a stronger question at the end of your prompt.",
            "action_label": "Edit Prompt",
            "href": "/dashboard/ai-settings",
            "priority": "medium",
        })
    lengths = [len((post.content or "").split()) for post in posts[:10]]
    if len(lengths) >= 5 and max(lengths) - min(lengths) <= 25:
        actions.append({
            "id": "length-variety",
            "text": "Your recent posts are very similar in length. Try a short 1-3 line post for variety.",
            "action_label": "Generate Short Post",
            "href": "/dashboard/create",
            "priority": "medium",
        })
    return actions[:5]


def _refresh_daily_dashboard_recommendations(db: Session, pages: list[models.FacebookConnection], user: models.User) -> None:
    if not pages or not MISTRAL_API_KEY:
        return
    now = datetime.now(timezone.utc)
    for page in pages:
        latest = (
            db.query(models.AIRecommendation)
            .filter(models.AIRecommendation.page_connection_id == page.id)
            .order_by(models.AIRecommendation.generated_at.desc())
            .first()
        )
        if latest and latest.generated_at and now - latest.generated_at < timedelta(hours=20):
            continue
        summary = get_performance_insights(db, page.id, user)
        if not summary.get("enabled"):
            summary = {
                "page": page.page_name,
                "personas": [
                    {"name": persona.persona_name, "score": float(persona.performance_score or 0.5), "failures": persona.consecutive_failures}
                    for persona in db.query(models.AIPersona).filter(models.AIPersona.page_connection_id == page.id).all()
                ],
                "recent_posts": [
                    {"content": post.content[:240], "status": post.status, "posted_at": post.posted_at}
                    for post in db.query(models.PostLog).filter(models.PostLog.facebook_connection_id == page.id).order_by(models.PostLog.id.desc()).limit(10).all()
                ],
            }
        texts = generate_ai_recommendations(page.page_name, summary, MISTRAL_MODEL)
        if not texts:
            continue
        db.query(models.AIRecommendation).filter(models.AIRecommendation.page_connection_id == page.id).update({"is_dismissed": True})
        for text in texts[:3]:
            db.add(models.AIRecommendation(page_connection_id=page.id, recommendation_text=text, generated_at=now))
    db.commit()


@app.get("/api/dashboard/intelligence", response_model=schemas.DashboardIntelligenceResponse)
def dashboard_intelligence(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    pages = (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == current_user.id)
        .order_by(models.FacebookConnection.connected_at.desc())
        .all()
    )
    page_ids = [page.id for page in pages]
    _refresh_daily_dashboard_recommendations(db, pages, current_user)
    personas = db.query(models.AIPersona).filter(models.AIPersona.user_id == current_user.id).all()
    posts = (
        db.query(models.PostLog)
        .filter(models.PostLog.user_id == current_user.id)
        .order_by(models.PostLog.posted_at.desc().nullslast(), models.PostLog.id.desc())
        .limit(30)
        .all()
    )
    latest_snapshots = _latest_snapshot_map(db, [post.id for post in posts])
    for post in posts:
        snapshot = latest_snapshots.get(post.id)
        post.latest_comments_count = snapshot.comments_count if snapshot else 0

    next_post = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.user_id == current_user.id,
            models.PostLog.status == "scheduled",
            models.PostLog.scheduled_at >= now,
        )
        .order_by(models.PostLog.scheduled_at.asc())
        .first()
    )
    last_post = next((post for post in posts if post.status in ("published", "success")), None)
    last_snapshot = latest_snapshots.get(last_post.id) if last_post else None

    since_7 = now - timedelta(days=7)
    top_post_row = (
        db.query(models.PostLog, models.PostEngagementSnapshot)
        .join(models.PostEngagementSnapshot, models.PostEngagementSnapshot.post_id == models.PostLog.id)
        .filter(models.PostLog.user_id == current_user.id, models.PostLog.posted_at >= since_7)
        .order_by(models.PostEngagementSnapshot.engagement_score.desc())
        .first()
    )
    slot_rows = (
        db.query(models.PostLog, models.PostEngagementSnapshot)
        .join(models.PostEngagementSnapshot, models.PostEngagementSnapshot.post_id == models.PostLog.id)
        .filter(models.PostLog.user_id == current_user.id, models.PostLog.posted_at >= since_7)
        .all()
    )
    slot_scores: dict[str, list[float]] = {}
    persona_scores: dict[int, list[float]] = {}
    for post, snapshot in slot_rows:
        if post.posted_at:
            slot_scores.setdefault(post.posted_at.strftime("%a %I%p"), []).append(float(snapshot.engagement_score or 0))
        if post.ai_persona_id:
            persona_scores.setdefault(post.ai_persona_id, []).append(float(snapshot.engagement_score or 0))
    best_slot = max(slot_scores.items(), key=lambda item: sum(item[1]) / len(item[1])) if slot_scores else None
    best_persona_id = max(persona_scores.items(), key=lambda item: sum(item[1]) / len(item[1]))[0] if persona_scores else None
    best_persona = next((persona for persona in personas if persona.id == best_persona_id), None)

    recommendations = (
        db.query(models.AIRecommendation)
        .filter(models.AIRecommendation.page_connection_id.in_(page_ids), models.AIRecommendation.is_dismissed.is_(False))
        .order_by(models.AIRecommendation.generated_at.desc())
        .limit(5)
        .all()
        if page_ids else []
    )
    published_count = db.query(func.count(models.PostLog.id)).filter(models.PostLog.user_id == current_user.id, models.PostLog.status.in_(["published", "success"])).scalar() or 0
    prompt_done = any(bool(persona.custom_prompt and persona.custom_prompt.strip()) for persona in personas)
    auto_schedule_done = any(persona.assigned_days and persona.posting_time_slots for persona in personas)
    first_post_at = db.query(func.min(models.PostLog.posted_at)).filter(models.PostLog.user_id == current_user.id, models.PostLog.status.in_(["published", "success"])).scalar()
    learned_7_days = bool(first_post_at and now - first_post_at >= timedelta(days=7))
    report_ready = bool(top_post_row or recommendations)
    onboarding = [
        {"label": "Connect your Facebook Page", "done": bool(pages), "href": "/dashboard/settings"},
        {"label": "Build your first AI Persona", "done": bool(personas), "href": "/dashboard/ai-settings"},
        {"label": "Build your custom prompt", "done": prompt_done, "href": "/dashboard/ai-settings"},
        {"label": "Generate and publish your first post", "done": published_count > 0, "href": "/dashboard/create"},
        {"label": "Set up auto posting schedule", "done": auto_schedule_done, "href": "/dashboard/ai-settings"},
        {"label": "Let the system learn for 7 days", "done": learned_7_days, "href": "/dashboard/analytics"},
        {"label": "Review your first performance report", "done": report_ready, "href": "/dashboard/analytics"},
    ]
    cron_age_seconds = (now - last_scheduler_run_at).total_seconds() if last_scheduler_run_at else None
    warnings = []
    for page in pages:
        if page.connection_status != "connected":
            warnings.append({"level": "amber", "text": f"{page.page_name} needs reconnection.", "href": "/dashboard/settings"})
        elif page.token_expires_at and page.token_expires_at <= now + timedelta(days=7):
            warnings.append({"level": "amber", "text": f"{page.page_name} token expires soon. Reconnect to avoid interrupted posting.", "href": "/dashboard/settings"})
    if cron_age_seconds is None or cron_age_seconds > 600:
        warnings.append({"level": "red", "text": "Scheduler health has not checked in within 10 minutes. Auto posting may be broken.", "href": "/dashboard"})
    for persona in personas:
        if persona.consecutive_failures >= 3:
            warnings.append({"level": "amber", "text": f"{persona.persona_name} has failed to generate or publish 3 times in a row.", "href": "/dashboard/ai-settings"})
        if float(persona.performance_score or 0.5) < 0.3:
            warnings.append({"level": "amber", "text": f"{persona.persona_name} performance dropped below 0.3. Review its prompt.", "href": "/dashboard/ai-settings"})

    tracked_pages = db.query(models.TrackedPage).filter(models.TrackedPage.user_id == current_user.id).all()
    for page in tracked_pages:
        last_post = db.query(models.TrackedPagePost).filter(models.TrackedPagePost.tracked_page_id == page.id).order_by(models.TrackedPagePost.created_at.desc()).first()
        if not last_post or (now - last_post.created_at > timedelta(days=7)):
            warnings.append({"level": "amber", "text": f"You haven't added new posts for {page.nickname} in 7 days. Visit their page and add recent posts to keep your tracking data fresh.", "href": "/dashboard/page-tracker"})

    return {
        "now": now,
        "next_scheduled_post": None if not next_post else {
            "id": next_post.id,
            "content": next_post.content,
            "scheduled_at": next_post.scheduled_at,
            "minutes_until": max(0, int(((next_post.scheduled_at or now) - now).total_seconds() // 60)),
        },
        "last_published_post": None if not last_post else {
            "id": last_post.id,
            "content": last_post.content,
            "posted_at": last_post.posted_at,
            "likes_count": last_snapshot.likes_count if last_snapshot else 0,
            "comments_count": last_snapshot.comments_count if last_snapshot else 0,
            "shares_count": last_snapshot.shares_count if last_snapshot else 0,
            "reach_count": last_snapshot.reach_count if last_snapshot else 0,
            "engagement_score": float(last_snapshot.engagement_score or 0) if last_snapshot else 0,
        },
        "facebook_connections": [{"id": page.id, "page_name": page.page_name, "status": page.connection_status, "token_expires_at": page.token_expires_at} for page in pages],
        "cron_health": {"ok": bool(cron_age_seconds is not None and cron_age_seconds <= 300), "last_run_at": last_scheduler_run_at, "age_seconds": cron_age_seconds},
        "onboarding_steps": onboarding,
        "learned_insights": {
            "best_post": None if not top_post_row else {"id": top_post_row[0].id, "content": top_post_row[0].content, "score": float(top_post_row[1].engagement_score or 0), "insight": "This was your strongest post in the last 7 days. Use its angle as a reference for the next prompt test."},
            "best_time_slot": None if not best_slot else {"slot": best_slot[0], "score": sum(best_slot[1]) / len(best_slot[1]), "insight": f"{best_slot[0]} is your strongest recent slot. Consider scheduling another test post there."},
            "best_persona": None if not best_persona else {"id": best_persona.id, "name": best_persona.persona_name, "score": float(best_persona.performance_score or 0.5), "insight": f"{best_persona.persona_name} is leading this week. Let it post more often while it is working."},
        },
        "action_items": _dashboard_action_items(personas, posts, recommendations),
        "warnings": warnings[:5],
    }


@app.post("/api/ai/personas/{persona_id}/reset-learning", response_model=schemas.PersonaLearningResetResponse)
def reset_ai_persona_learning(
    persona_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user_has_learning_access(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Learning controls are available on the Pro plan")
    persona = db.query(models.AIPersona).filter(models.AIPersona.id == persona_id, models.AIPersona.user_id == current_user.id).first()
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    reset_persona_learning(db, persona)
    db.commit()
    return {"success": True}


@app.post("/api/ai/generate", response_model=schemas.AIGenerateResponse)
def generate_ai_post(
    payload: schemas.AIGenerateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = _get_ai_settings(db, current_user.id, payload.page_connection_id)
    recent_topics = [
        row[0]
        for row in db.query(models.PostLog.topic)
        .filter(
            models.PostLog.facebook_connection_id == payload.page_connection_id,
            models.PostLog.topic.isnot(None),
        )
        .order_by(models.PostLog.created_at.desc())
        .limit(5)
        .all()
    ]
    try:
        hint_parts = [
            build_learning_prompt_hint(db, settings) if user_has_learning_access(current_user) else None,
            build_strategy_prompt_hint(db, settings),
        ]
        learning_hint = " ".join(part for part in hint_parts if part)
        if settings.custom_prompt and settings.custom_prompt.strip():
            content = generate_ai_facebook_post_from_prompt(
                settings.custom_prompt,
                settings.creativity_level,
                recent_topics,
                payload.topic_hint,
                learning_hint,
                MISTRAL_MODEL,
            )
        else:
            content = generate_ai_facebook_post(
                settings.niche,
                [tag.strip() for tag in settings.tone_tags.split(",") if tag.strip()],
                settings.custom_instructions,
                settings.language,
                settings.hashtags_enabled,
                settings.hashtag_count,
                settings.always_include_engagement_hook,
                recent_topics,
                payload.topic_hint or learning_hint,
                MISTRAL_MODEL,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"content": content}


@app.post("/api/ai/generate-and-publish", response_model=schemas.PostPublishResponse)
async def generate_and_publish_ai_post(
    payload: schemas.AIGenerateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = _get_owned_page(db, current_user.id, payload.page_connection_id)
    settings = _get_ai_settings(db, current_user.id, payload.page_connection_id)
    from app.mistral_service import check_post_quality
    recent_topics = [
        row[0]
        for row in db.query(models.PostLog.topic)
        .filter(
            models.PostLog.facebook_connection_id == payload.page_connection_id,
            models.PostLog.topic.isnot(None),
        )
        .order_by(models.PostLog.created_at.desc())
        .limit(5)
        .all()
    ]
    try:
        # Quality check loop
        content = ""
        max_attempts = 3
        for attempt in range(max_attempts):
            hint_parts = [
                build_learning_prompt_hint(db, settings) if user_has_learning_access(current_user) else None,
                build_strategy_prompt_hint(db, settings),
            ]
            learning_hint = " ".join(part for part in hint_parts if part)
            if settings.custom_prompt and settings.custom_prompt.strip():
                content = generate_ai_facebook_post_from_prompt(
                    settings.custom_prompt,
                    settings.creativity_level,
                    recent_topics,
                    payload.topic_hint,
                    learning_hint,
                    MISTRAL_MODEL,
                )
            else:
                content = generate_ai_facebook_post(
                    settings.niche,
                    [tag.strip() for tag in settings.tone_tags.split(",") if tag.strip()],
                    settings.custom_instructions,
                    settings.language,
                    settings.hashtags_enabled,
                    settings.hashtag_count,
                    settings.always_include_engagement_hook,
                    recent_topics,
                    payload.topic_hint or learning_hint,
                    MISTRAL_MODEL,
                )
            score = check_post_quality(content, MISTRAL_MODEL)
            if score >= 6:
                break
            print(f"Generated post scored {score}/10 (below threshold 6), regenerating (attempt {attempt + 1}/{max_attempts})...")

        post_log = models.PostLog(
            user_id=current_user.id,
            facebook_connection_id=connection.id,
            content=content,
            status="draft",
            ai_generated=True,
            auto_generated=True,
            ai_persona_id=settings.id,
        )
        db.add(post_log)
        db.flush()
        success = await publish_post_to_facebook(db, post_log, connection)
        return {"success": success, "id": post_log.id, "status": post_log.status, "error_message": post_log.error_message}
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post("/facebook/pages/{connection_id}/refresh-token")
def refresh_facebook_token(
    connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = (
        db.query(models.FacebookConnection)
        .filter(
            models.FacebookConnection.id == connection_id,
            models.FacebookConnection.user_id == current_user.id,
        )
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    connection.connection_status = "connected"
    connection.token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    db.commit()
    return {"success": True}


@app.delete("/facebook/pages/{connection_id}")
def disconnect_facebook_page(
    connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return facebook_oauth.disconnect_page_connection(db, current_user.id, connection_id)


@app.post("/facebook/pages/recover-history/{connection_id}")
async def recover_facebook_page_history(
    connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = (
        db.query(models.FacebookConnection)
        .filter(
            models.FacebookConnection.id == connection_id,
            models.FacebookConnection.user_id == current_user.id,
        )
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not connection.page_access_token:
        raise HTTPException(status_code=400, detail="Page is disconnected or access token is missing")

    access_token = decrypt_token(connection.page_access_token)
    page_id = connection.page_id

    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        response = await client.get(
            f"{page_id}/posts",
            params={
                "fields": "id,message,created_time,likes.summary(true),comments.summary(true),shares",
                "limit": 100,
                "access_token": access_token
            }
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch history from Facebook API")

    fb_posts = response.json().get("data", [])
    synced_count = 0

    for fb_post in fb_posts:
        fb_post_id = fb_post.get("id")
        if not fb_post_id:
            continue

        # Check if already exists
        exists = db.query(models.PostLog).filter(models.PostLog.facebook_post_id == fb_post_id).first()
        if exists:
            continue

        created_time_str = fb_post.get("created_time")
        try:
            posted_at = datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
        except Exception:
            posted_at = datetime.now(timezone.utc)

        message = fb_post.get("message", "")
        # Create PostLog
        post = models.PostLog(
            user_id=current_user.id,
            facebook_connection_id=connection.id,
            content=message,
            status="published",
            facebook_post_id=fb_post_id,
            posted_at=posted_at,
            created_at=posted_at,
            updated_at=posted_at,
            ai_generated=False,
            auto_generated=False
        )
        db.add(post)
        db.flush()  # to populate post.id

        # Metrics snapshots
        likes_count = fb_post.get("likes", {}).get("summary", {}).get("total_count", 0)
        comments_count = fb_post.get("comments", {}).get("summary", {}).get("total_count", 0)
        shares_count = fb_post.get("shares", {}).get("count", 0)

        analytics_snapshot = models.AnalyticsSnapshot(
            post_id=post.id,
            likes_count=likes_count,
            comments_count=comments_count,
            shares_count=shares_count,
            snapshot_at=posted_at
        )
        db.add(analytics_snapshot)

        post_engagement = models.PostEngagementSnapshot(
            post_id=post.id,
            page_connection_id=connection.id,
            snapshot_taken_at=posted_at,
            snapshot_type="facebook",
            likes_count=likes_count,
            comments_count=comments_count,
            shares_count=shares_count,
            reach_count=likes_count * 3,  # reasonable estimation
            engagement_score=likes_count + comments_count * 2 + shares_count * 5
        )
        db.add(post_engagement)
        synced_count += 1

    db.commit()
    return {"success": True, "synced_posts_count": synced_count}


@app.post("/facebook/manual-connect", response_model=schemas.FacebookSelectPageResponse)
async def manual_connect_facebook_page(
    payload: schemas.FacebookManualConnectRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page_id = payload.page_id.strip()
    page_access_token = payload.page_access_token.strip()
    if not page_id or not page_access_token:
        _facebook_error("Page ID and Page Access Token are required")

    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        response = await client.get(
            page_id,
            params={"fields": "name", "access_token": page_access_token},
        )

    if response.status_code >= 400:
        _facebook_error("Facebook could not validate this Page ID and token")

    page_name = response.json().get("name")
    if not page_name:
        _facebook_error("Facebook validation did not return a page name")

    existing_connection = (
        db.query(models.FacebookConnection)
        .filter(
            models.FacebookConnection.user_id == current_user.id,
            models.FacebookConnection.page_id == page_id
        )
        .first()
    )
    if not existing_connection:
        existing_connection = (
            db.query(models.FacebookConnection)
            .filter(models.FacebookConnection.user_id == current_user.id)
            .first()
        )

    if existing_connection:
        connection = existing_connection
        connection.reconnect_count = (connection.reconnect_count or 0) + 1
    else:
        connection = models.FacebookConnection(user_id=current_user.id)
        connection.reconnect_count = 0
        db.add(connection)

    connection.page_id = page_id
    connection.page_name = page_name
    connection.page_picture_url = f"https://graph.facebook.com/{page_id}/picture?type=large"
    connection.page_access_token = encrypt_token(page_access_token)
    connection.long_lived_user_token = ""
    connection.token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    connection.connection_status = "connected"
    connection.disconnected_at = None
    connection.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"success": True, "page_name": page_name}


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
async def generate_post(
    payload: schemas.PostGenerateRequest | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload is not None:
        try:
            content = await generate_caption_with_claude(payload.prompt)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        return {"content": content}

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
    return {"content": post_log.content}


@app.post("/posts/publish", response_model=schemas.PostPublishResponse)
async def publish_composer_post(
    payload: schemas.PostPublishRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = payload.message.strip()
    image_url = payload.image_url.strip() if payload.image_url else None
    media_urls = payload.media_urls or ([image_url] if image_url else [])
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message is required",
        )

    filters = [models.FacebookConnection.user_id == current_user.id]
    if payload.page_connection_id is not None:
        filters.append(models.FacebookConnection.id == payload.page_connection_id)
    connection = db.query(models.FacebookConnection).filter(*filters).first()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook connection not found",
        )
    if connection.connection_status != "connected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your Facebook connection has expired. Please reconnect your page.",
        )

    if payload.save_as_draft or payload.scheduled_at:
        post_log = models.PostLog(
            user_id=current_user.id,
            facebook_connection_id=connection.id,
            content=message,
            media_urls=media_urls,
            link_url=payload.link_url,
            link_preview_data=payload.link_preview_data,
            scheduled_at=payload.scheduled_at,
            status="draft" if payload.save_as_draft else "scheduled",
        )
        db.add(post_log)
        db.commit()
        db.refresh(post_log)
        return {"success": True, "id": post_log.id, "status": post_log.status}

    await verify_page_connection_for_publish(db, connection)

    success, post_log, post_url = await publish_message_to_facebook(
        db,
        current_user.id,
        connection,
        message,
        media_urls=media_urls,
        link_url=payload.link_url,
        link_preview_data=payload.link_preview_data,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=post_log.error_message or "Facebook rejected the post. Please try again.",
        )
    return {
        "success": True,
        "id": post_log.id,
        "status": post_log.status,
        "post_url": post_url,
        "error_message": None,
    }


@app.post("/posts/{post_id}/publish", response_model=schemas.PostPublishResponse)
async def publish_post(
    post_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post_log = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.id == post_id,
            models.PostLog.user_id == current_user.id,
            models.PostLog.status.in_(["draft", "scheduled", "failed"]),
        )
        .first()
    )
    if post_log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found or already published",
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

    if connection.connection_status != "connected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your Facebook connection has expired. Please reconnect your page.",
        )

    await verify_page_connection_for_publish(db, connection)

    success = await publish_post_to_facebook(db, post_log, connection)
    if success and post_log.ai_generated:
        try:
            was_edited = db.query(models.LearningSignal).filter(
                models.LearningSignal.user_id == current_user.id,
                models.LearningSignal.signal_type == "user_edit",
                models.LearningSignal.signal_data.op("->>")("post_id").cast(Integer) == post_log.id
            ).first() is not None
            if not was_edited:
                _record_learning_signal(
                    db,
                    current_user.id,
                    post_log.ai_persona_id,
                    "user_publish_unedited",
                    {"post_id": post_log.id, "content": post_log.content[:1000]},
                    1.0,
                )
        except Exception:
            pass
    db.refresh(post_log)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=post_log.error_message or "Facebook rejected the post. Please try again.",
        )

    return {
        "success": success,
        "id": post_log.id,
        "status": post_log.status,
        "error_message": post_log.error_message,
    }


@app.get("/posts/history", response_model=list[schemas.PostHistoryItem])
def post_history(
    limit: int = Query(default=5, ge=1, le=50),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    posts = (
        db.query(models.PostLog, models.FacebookConnection)
        .join(models.FacebookConnection, models.FacebookConnection.id == models.PostLog.facebook_connection_id)
        .filter(models.PostLog.user_id == current_user.id)
        .order_by(
            models.PostLog.posted_at.desc().nullslast(),
            models.PostLog.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return [_serialize_post(post, connection) for post, connection in posts]


def _serialize_post(post: models.PostLog, connection: models.FacebookConnection | None = None):
    latest_snapshot = None
    threshold = 0
    if post.id:
        db = object_session(post)
        if db is not None:
            latest_snapshot = (
                db.query(models.PostEngagementSnapshot)
                .filter(models.PostEngagementSnapshot.post_id == post.id)
                .order_by(models.PostEngagementSnapshot.snapshot_taken_at.desc())
                .first()
            )
            if post.ai_persona_id:
                persona = db.get(models.AIPersona, post.ai_persona_id)
                threshold = float(persona.minimum_engagement_threshold or 0) if persona else 0
    score = float(latest_snapshot.engagement_score or 0) if latest_snapshot else 0
    return {
        "id": post.id,
        "content": post.content,
        "status": "published" if post.status == "success" else post.status,
        "posted_at": post.posted_at,
        "scheduled_at": post.scheduled_at,
        "media_urls": post.media_urls or [],
        "link_url": post.link_url,
        "link_preview_data": post.link_preview_data,
        "page_name": connection.page_name if connection else None,
        "page_picture_url": connection.page_picture_url if connection else None,
        "facebook_post_id": post.facebook_post_id,
        "failure_reason": post.error_message,
        "ai_generated": post.ai_generated,
        "auto_generated": post.auto_generated,
        "likes_count": latest_snapshot.likes_count if latest_snapshot else 0,
        "comments_count": latest_snapshot.comments_count if latest_snapshot else 0,
        "shares_count": latest_snapshot.shares_count if latest_snapshot else 0,
        "reach_count": latest_snapshot.reach_count if latest_snapshot else 0,
        "engagement_score": score,
        "low_engagement": bool(threshold and score < threshold),
    }


@app.get("/posts", response_model=list[schemas.PostHistoryItem])
def list_posts(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.PostLog, models.FacebookConnection)
        .join(models.FacebookConnection, models.FacebookConnection.id == models.PostLog.facebook_connection_id)
        .filter(models.PostLog.user_id == current_user.id)
    )
    if status_filter == "published":
        query = query.filter(models.PostLog.status.in_(["published", "success"]))
    elif status_filter:
        query = query.filter(models.PostLog.status == status_filter)
    order_column = models.PostLog.scheduled_at.asc() if status_filter == "scheduled" else models.PostLog.id.desc()
    return [_serialize_post(post, connection) for post, connection in query.order_by(order_column).limit(limit).all()]


@app.patch("/posts/{post_id}", response_model=schemas.PostHistoryItem)
def update_post(
    post_id: int,
    payload: schemas.PostUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(models.PostLog).filter(models.PostLog.id == post_id, models.PostLog.user_id == current_user.id).first()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if payload.message is not None and payload.message != post.content:
        if post.ai_generated:
            _record_learning_signal(
                db,
                current_user.id,
                post.ai_persona_id,
                "user_edit",
                {"post_id": post.id, "original_content": post.content[:1000], "new_content": payload.message[:1000]},
                -0.5,
            )
        post.content = payload.message
    if payload.media_urls is not None:
        post.media_urls = payload.media_urls
    if payload.scheduled_at is not None:
        post.scheduled_at = payload.scheduled_at
        post.status = "scheduled"
    if payload.link_url is not None:
        post.link_url = payload.link_url
    if payload.link_preview_data is not None:
        post.link_preview_data = payload.link_preview_data
    if payload.status is not None:
        post.status = payload.status
    db.commit()
    db.refresh(post)
    connection = db.get(models.FacebookConnection, post.facebook_connection_id)
    return _serialize_post(post, connection)


@app.delete("/posts/{post_id}")
def delete_post(
    post_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(models.PostLog).filter(models.PostLog.id == post_id, models.PostLog.user_id == current_user.id).first()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.ai_generated:
        _record_learning_signal(
            db,
            current_user.id,
            post.ai_persona_id,
            "user_delete",
            {"post_id": post.id, "content": post.content[:1000], "status": post.status},
            -1.0,
        )
    db.delete(post)
    db.commit()
    return {"success": True}


@app.get("/analytics", response_model=schemas.AnalyticsResponse)
def analytics(
    days: int = Query(default=30, ge=7, le=120),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start = datetime.now(timezone.utc) - timedelta(days=days - 1)
    published = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.user_id == current_user.id,
            models.PostLog.status.in_(["published", "success"]),
            models.PostLog.posted_at >= start,
        )
        .all()
    )
    by_day = {(start + timedelta(days=offset)).date().isoformat(): 0 for offset in range(days)}
    for post in published:
        if post.posted_at:
            key = post.posted_at.date().isoformat()
            if key in by_day:
                by_day[key] += 1
    post_ids = [post.id for post in published]
    snapshots = db.query(models.AnalyticsSnapshot).filter(models.AnalyticsSnapshot.post_id.in_(post_ids)).all() if post_ids else []
    return {
        "total_posts": len(published),
        "total_likes": sum(snapshot.likes_count for snapshot in snapshots),
        "total_comments": sum(snapshot.comments_count for snapshot in snapshots),
        "total_shares": sum(snapshot.shares_count for snapshot in snapshots),
        "posts_per_day": [{"date": day, "count": count} for day, count in by_day.items()],
    }


@app.patch("/users/me", response_model=schemas.UserRead)
def update_current_user(
    payload: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.email:
        current_user.email = payload.email
    if payload.timezone:
        current_user.timezone = payload.timezone
    db.commit()
    db.refresh(current_user)
    return current_user

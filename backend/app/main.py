from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from sqlalchemy.orm import Session, object_session

from app import models, schemas
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
    FRONTEND_URL,
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    SECRET_KEY,
)
from app.crypto import encrypt_token
from app.database import create_database_tables, get_db
from app.posts import (
    create_draft_post,
    generate_caption_with_claude,
    generate_post_content,
    get_user_schedule_and_connection,
    publish_message_to_facebook,
    publish_post_to_facebook,
    release_user_posting,
    try_claim_user_posting,
)
from app.mistral_service import generate_ai_facebook_post
from app.learning.service import (
    build_learning_prompt_hint,
    get_performance_insights,
    reset_persona_learning,
    user_has_learning_access,
)

pending_facebook_pages: dict[int, dict] = {}
pending_facebook_credentials: dict[int, dict] = {}
pending_facebook_states: dict[str, int] = {}


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
    }
    print("Environment configuration:")
    for name, loaded in required_env.items():
        status_icon = "OK" if loaded else "MISSING"
        status_message = "loaded" if loaded else "is missing"
        print(f"  [{status_icon}] {name} {status_message}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _print_startup_config_status()
    create_database_tables()
    try:
        yield
    finally:
        pass


app = FastAPI(title="Auto Poster API", lifespan=lifespan)

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


@app.get("/")
def read_root():
    return {"message": "Welcome to the Auto Poster API"}


@app.get("/health")
def health_check():
    return "ok"


@app.get("/api/health")
def api_health_check():
    return "ok"


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


def _current_user_from_popup_token(token: str, db: Session) -> models.User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError
    except (JWTError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    user = db.get(models.User, int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


@app.get("/auth/facebook/start")
def start_facebook_oauth(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    user = _current_user_from_popup_token(token, db)
    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
        _facebook_error("Facebook app credentials are not configured", status.HTTP_500_INTERNAL_SERVER_ERROR)

    state = token_urlsafe(32)
    pending_facebook_states[state] = user.id
    pending_facebook_credentials[user.id] = {
        "app_id": FACEBOOK_APP_ID,
        "app_secret": FACEBOOK_APP_SECRET,
        "redirect_uri": FACEBOOK_REDIRECT_URI,
        "state": state,
    }
    params = urlencode(
        {
            "client_id": FACEBOOK_APP_ID,
            "redirect_uri": FACEBOOK_REDIRECT_URI,
            "response_type": "code",
            "scope": FACEBOOK_OAUTH_SCOPES,
            "state": state,
        }
    )
    return RedirectResponse(f"https://www.facebook.com/v19.0/dialog/oauth?{params}")


@app.get("/auth/facebook/callback", response_class=HTMLResponse)
async def facebook_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if error:
        return _popup_html(False, f"Facebook returned an error: {error}")
    if not code or not state or state not in pending_facebook_states:
        print("Invalid Facebook OAuth callback state")
        response = _popup_html(False, "Facebook authorization state did not match")
        response.status_code = 400
        return response

    user_id = pending_facebook_states.pop(state)
    credentials = pending_facebook_credentials.get(user_id)
    if not credentials or credentials.get("state") != state:
        print("Invalid Facebook OAuth callback state")
        response = _popup_html(False, "Facebook authorization state did not match")
        response.status_code = 400
        return response

    pages, token_data, long_lived_token = await _fetch_facebook_pages(
        code,
        credentials["redirect_uri"],
        credentials["app_id"],
        credentials["app_secret"],
    )
    if not pages:
        return _popup_html(False, "No Facebook Pages were returned for this account.")

    expires_in = token_data.get("expires_in")
    token_expires_at = None
    if expires_in is not None:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    pending_facebook_pages[user_id] = {
        "app_id": credentials["app_id"],
        "app_secret": credentials["app_secret"],
        "long_lived_user_token": long_lived_token,
        "token_expires_at": token_expires_at,
        "pages": pages,
        "state": state,
    }

    if len(pages) == 1:
        connection = await _store_selected_facebook_page(db, user_id, pages[0]["page_id"])
        pending_facebook_pages.pop(user_id, None)
        pending_facebook_credentials.pop(user_id, None)
        return _popup_html(True, f"Connected {connection.page_name}.")

    return _page_picker_html(pages, state)


@app.get("/auth/facebook/select-page", response_class=HTMLResponse)
async def select_facebook_page_from_popup(
    page_id: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    credentials = next(
        ((user_id, value) for user_id, value in pending_facebook_credentials.items() if value.get("state") == state),
        None,
    )
    if credentials is None:
        response = _popup_html(False, "Facebook authorization state did not match")
        response.status_code = 400
        return response
    user_id, _ = credentials
    connection = await _store_selected_facebook_page(db, user_id, page_id)
    pending_facebook_pages.pop(user_id, None)
    pending_facebook_credentials.pop(user_id, None)
    return _popup_html(True, f"Connected {connection.page_name}.")


async def _fetch_facebook_pages(code: str, redirect_uri: str, app_id: str, app_secret: str):
    async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_API_BASE_URL) as client:
        token_response = await client.get(
            "oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_response.status_code >= 400:
            _facebook_error("Could not exchange Facebook token")
        short_lived_token = token_response.json().get("access_token")
        long_lived_response = await client.get(
            "oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_lived_token,
            },
        )
        if long_lived_response.status_code >= 400:
            _facebook_error("Could not exchange Facebook token")
        token_data = long_lived_response.json()
        long_lived_token = token_data.get("access_token")
        if not long_lived_token:
            _facebook_error("Facebook token exchange did not return an access token")
        pages_response = await client.get("me/accounts", params={"access_token": long_lived_token})
        if pages_response.status_code >= 400:
            _facebook_error("Could not fetch Facebook pages")

    pages = [
        {
            "page_id": page.get("id"),
            "page_name": page.get("name"),
            "page_access_token": page.get("access_token"),
        }
        for page in pages_response.json().get("data", [])
        if page.get("id") and page.get("name") and page.get("access_token")
    ]
    return pages, token_data, long_lived_token


async def _store_selected_facebook_page(db: Session, user_id: int, page_id: str) -> models.FacebookConnection:
    pending_connection = pending_facebook_pages.get(user_id)
    if not pending_connection:
        _facebook_error("Connect Facebook before selecting a page")
    selected_page = next((page for page in pending_connection["pages"] if page["page_id"] == page_id), None)
    if selected_page is None:
        _facebook_error("Selected page was not found")

    page_picture_url = f"https://graph.facebook.com/{selected_page['page_id']}/picture?type=large"
    existing_connection = (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == user_id)
        .first()
    )
    if existing_connection:
        connection = existing_connection
    else:
        connection = models.FacebookConnection(user_id=user_id)
        db.add(connection)
    connection.page_id = selected_page["page_id"]
    connection.page_name = selected_page["page_name"]
    connection.page_picture_url = page_picture_url
    connection.page_access_token = encrypt_token(selected_page["page_access_token"])
    connection.app_id = None
    connection.app_secret = None
    connection.long_lived_user_token = ""
    connection.token_expires_at = pending_connection["token_expires_at"]
    connection.connection_status = "connected"
    connection.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(connection)
    return connection


def _popup_html(success: bool, message: str) -> HTMLResponse:
    message_js = message.replace("\\", "\\\\").replace("'", "\\'")
    type_name = "facebook-connected" if success else "facebook-connection-failed"
    return HTMLResponse(
        f"""<!doctype html><html><body><p>{message}</p><script>
        if (window.opener) {{
          window.opener.postMessage({{ type: '{type_name}', message: '{message_js}' }}, '{FRONTEND_URL}');
          window.close();
        }}
        </script></body></html>"""
    )


def _page_picker_html(pages: list[dict], state: str) -> HTMLResponse:
    options = "".join(
        f"<label><input type='radio' name='page_id' value='{page['page_id']}' required> {page['page_name']}</label><br>"
        for page in pages
    )
    return HTMLResponse(
        f"""<!doctype html><html><body style="font-family: system-ui; padding: 24px;">
        <h1>Select Facebook Page</h1>
        <form method="get" action="/auth/facebook/select-page">
          <input type="hidden" name="state" value="{state}">
          {options}
          <button type="submit" style="margin-top: 16px;">Confirm</button>
        </form></body></html>"""
    )


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

    state = token_urlsafe(24)
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
        "authorization_url": (
            f"https://www.facebook.com/v19.0/dialog/oauth?{params}"
        )
    }


@app.post("/facebook/connect", response_model=schemas.FacebookConnectResponse)
async def connect_facebook(
    payload: schemas.FacebookConnectRequest,
    current_user: models.User = Depends(get_current_user),
):
    app_id, app_secret = _get_pending_or_global_facebook_credentials(current_user.id)
    pending_credentials = pending_facebook_credentials.get(current_user.id)
    if payload.code and pending_credentials:
        if payload.state != pending_credentials["state"]:
            _facebook_error("Facebook authorization state did not match")

    if not (app_id and app_secret):
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
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": payload.redirect_uri,
                    "code": payload.code,
                },
            )
        elif payload.short_lived_token:
            token_response = await client.get(
                "oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
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
                    "client_id": app_id,
                    "client_secret": app_secret,
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
        "app_id": app_id,
        "app_secret": app_secret,
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
        page_picture_url=f"https://graph.facebook.com/{selected_page['page_id']}/picture?type=large",
        page_access_token=encrypt_token(selected_page["page_access_token"]),
        app_id=None,
        app_secret=None,
        long_lived_user_token="",
        token_expires_at=pending_connection["token_expires_at"],
    )
    db.add(connection)
    db.commit()
    pending_facebook_pages.pop(current_user.id, None)
    pending_facebook_credentials.pop(current_user.id, None)

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
        "page_picture_url": connection.page_picture_url,
        "connection_status": connection.connection_status,
        "instagram_business_account_id": connection.instagram_business_account_id,
    }


@app.get("/facebook/pages", response_model=list[schemas.PageConnectionRead])
def list_facebook_pages(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == current_user.id)
        .order_by(models.FacebookConnection.connected_at.desc())
        .all()
    )


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
    db.commit()
    db.refresh(persona)
    return _serialize_ai_persona(persona)


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
        content = generate_ai_facebook_post(
            settings.niche,
            [tag.strip() for tag in settings.tone_tags.split(",") if tag.strip()],
            settings.custom_instructions,
            settings.language,
            settings.hashtags_enabled,
            settings.hashtag_count,
            settings.always_include_engagement_hook,
            recent_topics,
            payload.topic_hint or (build_learning_prompt_hint(db, settings) if user_has_learning_access(current_user) else None),
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
            content = generate_ai_facebook_post(
                settings.niche,
                [tag.strip() for tag in settings.tone_tags.split(",") if tag.strip()],
                settings.custom_instructions,
                settings.language,
                settings.hashtags_enabled,
                settings.hashtag_count,
                settings.always_include_engagement_hook,
                recent_topics,
                payload.topic_hint or (build_learning_prompt_hint(db, settings) if user_has_learning_access(current_user) else None),
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

    db.query(models.PostLog).filter(
        models.PostLog.facebook_connection_id == connection.id,
        models.PostLog.status == "scheduled",
    ).update({"status": "draft"})
    db.delete(connection)
    db.commit()
    return {"success": True}


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
        .filter(models.FacebookConnection.user_id == current_user.id)
        .first()
    )
    if existing_connection:
        db.delete(existing_connection)
        db.flush()

    connection = models.FacebookConnection(
        user_id=current_user.id,
        page_id=page_id,
        page_name=page_name,
        page_picture_url=f"https://graph.facebook.com/{page_id}/picture?type=large",
        page_access_token=encrypt_token(page_access_token),
        long_lived_user_token="",
        token_expires_at=datetime.now(timezone.utc) + timedelta(days=60),
    )
    db.add(connection)
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

    if not try_claim_user_posting(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A post is already being published for this user",
        )

    try:
        success, post_log, post_url = await publish_message_to_facebook(
            db,
            current_user.id,
            connection,
            message,
            media_urls=media_urls,
            link_url=payload.link_url,
            link_preview_data=payload.link_preview_data,
        )
        return {
            "success": success,
            "id": post_log.id,
            "status": post_log.status,
            "post_url": post_url,
            "error_message": post_log.error_message,
        }
    finally:
        release_user_posting(current_user.id)


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
    if payload.message is not None:
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
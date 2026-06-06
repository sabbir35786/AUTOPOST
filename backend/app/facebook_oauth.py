"""Facebook page connect and disconnect flow."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import (
    ALGORITHM,
    FACEBOOK_APP_ID,
    FACEBOOK_APP_SECRET,
    FACEBOOK_OAUTH_SCOPES,
    FACEBOOK_REDIRECT_URI,
    FRONTEND_URL,
    SECRET_KEY,
)
from app.crypto import encrypt_token

logger = logging.getLogger(__name__)

FACEBOOK_OAUTH_GRAPH_VERSION = "v18.0"
FACEBOOK_GRAPH_OAUTH_BASE = f"https://graph.facebook.com/{FACEBOOK_OAUTH_GRAPH_VERSION}"
FACEBOOK_DIALOG_OAUTH_BASE = f"https://www.facebook.com/{FACEBOOK_OAUTH_GRAPH_VERSION}/dialog/oauth"

# Bearer-authenticated JSON connect flow (legacy callback page)
pending_json_oauth_pages: dict[int, dict] = {}


def _create_oauth_state(db: Session, user_id: int) -> str:
    """Create and store OAuth state in database."""
    state = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    oauth_state = models.OAuthState(
        id=state,
        user_id=user_id,
        state=state,
        expires_at=expires_at,
    )
    db.add(oauth_state)
    db.commit()
    return state


def _verify_oauth_state(db: Session, state: str) -> int | None:
    """Verify OAuth state and return user_id if valid."""
    oauth_state = (
        db.query(models.OAuthState)
        .filter(
            models.OAuthState.state == state,
            models.OAuthState.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if oauth_state:
        user_id = oauth_state.user_id
        db.delete(oauth_state)
        db.commit()
        return user_id
    return None


def _cleanup_expired_oauth_states(db: Session) -> None:
    """Clean up expired OAuth states."""
    db.query(models.OAuthState).filter(
        models.OAuthState.expires_at <= datetime.now(timezone.utc)
    ).delete()
    db.commit()


def _facebook_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=status_code, detail=message)


def current_user_from_popup_token(token: str, db: Session) -> models.User:
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


def _clear_oauth_session(request: Request) -> None:
    for key in ("oauth_state", "oauth_user_id", "oauth_pending_pages", "oauth_token_expires_at"):
        request.session.pop(key, None)


def _popup_error_html(message: str) -> HTMLResponse:
    message_js = message.replace("\\", "\\\\").replace("'", "\\'")
    return HTMLResponse(
        f"""<!doctype html><html><body><p>{message}</p><script>
        if (window.opener) {{
          window.opener.postMessage(
            {{ type: 'FACEBOOK_CONNECT_ERROR', message: '{message_js}' }},
            '{FRONTEND_URL}'
          );
        }}
        window.close();
        </script></body></html>"""
    )


def _popup_success_html(page_id: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html><body><script>
        if (window.opener) {{
          window.opener.postMessage(
            {{ type: 'FACEBOOK_CONNECT_SUCCESS', pageId: '{page_id}' }},
            '{FRONTEND_URL}'
          );
        }}
        window.close();
        </script></body></html>"""
    )


def _page_picker_html(pages: list[dict]) -> HTMLResponse:
    cards = "".join(
        f"""
        <button type="submit" name="page_id" value="{page['page_id']}"
          style="display:block;width:100%;margin:8px 0;padding:12px;text-align:left;border:1px solid #ddd;border-radius:8px;background:#fff;cursor:pointer;">
          <strong>{page['page_name']}</strong>
        </button>
        """
        for page in pages
    )
    return HTMLResponse(
        f"""<!doctype html><html><body style="font-family:system-ui;padding:24px;">
        <h1>Select Facebook Page</h1>
        <form method="post" action="/auth/facebook/select-page">
          {cards}
        </form></body></html>"""
    )


def _page_picture_url(page: dict) -> str:
    picture = page.get("picture") or {}
    if isinstance(picture, dict):
        data = picture.get("data") or {}
        if isinstance(data, dict) and data.get("url"):
            return data["url"]
    page_id = page.get("page_id") or page.get("id")
    if page_id:
        return f"https://graph.facebook.com/{page_id}/picture?type=large"
    return ""


async def _exchange_code_for_token(code: str) -> tuple[str, dict | None]:
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            f"{FACEBOOK_GRAPH_OAUTH_BASE}/oauth/access_token",
            data={
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "redirect_uri": FACEBOOK_REDIRECT_URI,
                "code": code,
            },
        )
        if token_response.status_code >= 400:
            logger.warning("Facebook code exchange failed: %s", token_response.text[:200])
            return "", None

        short_lived_token = token_response.json().get("access_token")
        if not short_lived_token:
            return "", None

        long_lived_response = await client.get(
            f"{FACEBOOK_GRAPH_OAUTH_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "fb_exchange_token": short_lived_token,
            },
        )
        if long_lived_response.status_code >= 400:
            logger.warning(
                "Long-lived token exchange failed for user; proceeding with short-lived token"
            )
            return short_lived_token, None

        token_data = long_lived_response.json()
        long_lived_token = token_data.get("access_token") or short_lived_token
        return long_lived_token, token_data


async def _fetch_managed_pages(access_token: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        pages_response = await client.get(
            f"{FACEBOOK_GRAPH_OAUTH_BASE}/me/accounts",
            params={
                "access_token": access_token,
                "fields": "id,name,picture,access_token",
            },
        )
        if pages_response.status_code >= 400:
            logger.warning("Could not fetch Facebook pages: %s", pages_response.text[:200])
            return []

    pages: list[dict] = []
    for page in pages_response.json().get("data", []):
        page_id = page.get("id")
        page_name = page.get("name")
        page_access_token = page.get("access_token")
        if not page_id or not page_name or not page_access_token:
            continue
        pages.append(
            {
                "page_id": str(page_id),
                "page_name": str(page_name),
                "page_access_token": str(page_access_token),
                "picture": page.get("picture"),
            }
        )
    return pages


def _resume_paused_posts(db: Session, connection: models.FacebookConnection) -> int:
    now = datetime.now(timezone.utc)
    missed = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.facebook_connection_id == connection.id,
            models.PostLog.status == "paused",
            models.PostLog.scheduled_at.isnot(None),
            models.PostLog.scheduled_at <= now,
        )
        .all()
    )
    for post in missed:
        post.status = "missed"
        post.updated_at = now

    # Get posts to resume
    posts_to_resume = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.facebook_connection_id == connection.id,
            models.PostLog.status == "paused",
            models.PostLog.scheduled_at.isnot(None),
            models.PostLog.scheduled_at > now,
        )
        .all()
    )
    
    resumed_count = 0
    for post in posts_to_resume:
        post.status = "scheduled"
        post.updated_at = now
        
        # Schedule with QStash
        from app.qstash import schedule_post_delivery
        qstash_id = schedule_post_delivery(post_id=str(post.id), scheduled_at_utc=post.scheduled_at)
        if qstash_id:
            post.qstash_message_id = qstash_id
            post.delivery_status = "pending"
            resumed_count += 1
    
    if resumed_count:
        logger.info("Resumed %s paused posts for page %s", resumed_count, connection.page_name)
        db.commit()
    
    return resumed_count


def save_or_update_page_connection(
    db: Session,
    user_id: int,
    selected_page: dict,
    token_expires_at: datetime | None = None,
) -> models.FacebookConnection:
    page_id = selected_page["page_id"]
    now = datetime.now(timezone.utc)

    existing = (
        db.query(models.FacebookConnection)
        .filter(
            models.FacebookConnection.user_id == user_id,
            models.FacebookConnection.page_id == page_id,
        )
        .first()
    )

    if existing:
        existing.page_access_token = encrypt_token(selected_page["page_access_token"])
        existing.connection_status = "connected"
        existing.disconnected_at = None
        existing.last_token_refresh = now
        existing.reconnect_count = (existing.reconnect_count or 0) + 1
        existing.page_name = selected_page["page_name"]
        existing.page_picture_url = _page_picture_url(selected_page)
        existing.token_expires_at = token_expires_at
        existing.updated_at = now
        connection = existing
    else:
        conflict = (
            db.query(models.FacebookConnection)
            .filter(
                models.FacebookConnection.page_id == page_id,
                models.FacebookConnection.user_id != user_id,
                models.FacebookConnection.connection_status == "connected",
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Facebook Page is already actively connected to another account.",
            )

        connection = models.FacebookConnection(
            user_id=user_id,
            page_id=page_id,
            page_name=selected_page["page_name"],
            page_picture_url=_page_picture_url(selected_page),
            page_access_token=encrypt_token(selected_page["page_access_token"]),
            long_lived_user_token="",
            connection_status="connected",
            reconnect_count=0,
            last_token_refresh=now,
            token_expires_at=token_expires_at,
            connected_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(connection)

    db.flush()
    resumed = _resume_paused_posts(db, connection)
    db.commit()
    db.refresh(connection)
    logger.info(
        "Page %s successfully connected for user %s reconnect_count=%s resumed_posts=%s",
        connection.page_name,
        user_id,
        connection.reconnect_count,
        resumed,
    )
    return connection


async def complete_page_selection(
    request: Request,
    db: Session,
    user_id: int,
    page_id: str,
) -> models.FacebookConnection:
    pending_pages = request.session.get("oauth_pending_pages") or []
    token_expires_at_raw = request.session.get("oauth_token_expires_at")
    token_expires_at = None
    if token_expires_at_raw:
        token_expires_at = datetime.fromisoformat(token_expires_at_raw)

    selected_page = next((page for page in pending_pages if page.get("page_id") == page_id), None)
    if selected_page is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected page was not found")

    try:
        connection = save_or_update_page_connection(db, user_id, selected_page, token_expires_at)
    except HTTPException as exc:
        _clear_oauth_session(request)
        if exc.status_code == status.HTTP_409_CONFLICT:
            raise
        raise

    _clear_oauth_session(request)
    return connection


def start_facebook_oauth(request: Request, user: models.User, db: Session) -> RedirectResponse:
    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
        _facebook_error("Facebook app credentials are not configured", status.HTTP_500_INTERNAL_SERVER_ERROR)

    state = _create_oauth_state(db, user.id)
    request.session["oauth_state"] = state
    request.session["oauth_user_id"] = user.id
    logger.info("OAuth flow started for user %s", user.id)

    params = urlencode(
        {
            "client_id": FACEBOOK_APP_ID,
            "redirect_uri": FACEBOOK_REDIRECT_URI,
            "scope": FACEBOOK_OAUTH_SCOPES,
            "response_type": "code",
            "state": state,
        }
    )
    return RedirectResponse(f"{FACEBOOK_DIALOG_OAUTH_BASE}?{params}")


async def handle_facebook_callback(
    request: Request,
    db: Session,
    code: str | None,
    state: str | None,
    error: str | None,
) -> HTMLResponse:
    if error:
        return _popup_error_html(f"Facebook returned an error: {error}")

    # Verify OAuth state from database instead of session
    user_id = _verify_oauth_state(db, state) if state else None
    if not code or not state or not user_id:
        logger.warning("OAuth state mismatch for state %s", state)
        return _popup_error_html("Security check failed. Please try again.")

    request.session.pop("oauth_state", None)

    access_token, token_data = await _exchange_code_for_token(code)
    if not access_token:
        _clear_oauth_session(request)
        return _popup_error_html("Failed to connect to Facebook. Please try again.")

    pages = await _fetch_managed_pages(access_token)
    if not pages:
        _clear_oauth_session(request)
        return _popup_error_html(
            "No Facebook Pages found on this account. You need to be an admin of at least one Facebook Page."
        )

    token_expires_at = None
    if token_data and token_data.get("expires_in") is not None:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))

    request.session["oauth_pending_pages"] = pages
    if token_expires_at:
        request.session["oauth_token_expires_at"] = token_expires_at.isoformat()

    if len(pages) == 1:
        try:
            connection = await complete_page_selection(request, db, int(user_id), pages[0]["page_id"])
        except HTTPException as exc:
            return _popup_error_html(str(exc.detail))
        return _popup_success_html(connection.page_id)

    return _page_picker_html(pages)


async def handle_select_page_from_popup(
    request: Request,
    db: Session,
) -> HTMLResponse:
    form = await request.form()
    selected_page_id = form.get("page_id")
    if not selected_page_id:
        return _popup_error_html("Please select a Facebook Page.")

    user_id = request.session.get("oauth_user_id")
    if not user_id:
        return _popup_error_html("Security check failed. Please try again.")

    try:
        connection = await complete_page_selection(request, db, int(user_id), str(selected_page_id))
    except HTTPException as exc:
        return _popup_error_html(str(exc.detail))

    return _popup_success_html(connection.page_id)


def disconnect_page_connection(
    db: Session,
    user_id: int,
    connection_id: int,
) -> schemas.PageDisconnectResponse:
    connection = (
        db.query(models.FacebookConnection)
        .filter(
            models.FacebookConnection.id == connection_id,
            models.FacebookConnection.user_id == user_id,
        )
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Page connection not found")

    now = datetime.now(timezone.utc)
    connection.connection_status = "disconnected"
    connection.page_access_token = None
    connection.disconnected_at = now
    connection.updated_at = now

    paused_posts = (
        db.query(models.PostLog)
        .filter(
            models.PostLog.facebook_connection_id == connection_id,
            models.PostLog.status == "scheduled",
        )
        .update({"status": "paused", "updated_at": now}, synchronize_session=False)
    )
    db.commit()

    return schemas.PageDisconnectResponse(
        success=True,
        message="Page disconnected. Your post history is saved and will be restored when you reconnect.",
        paused_posts=paused_posts,
    )


def _post_counts_for_connection(db: Session, connection_id: int) -> tuple[int, int, int]:
    rows = (
        db.query(models.PostLog.status, func.count(models.PostLog.id))
        .filter(models.PostLog.facebook_connection_id == connection_id)
        .group_by(models.PostLog.status)
        .all()
    )
    counts = {status: count for status, count in rows}
    post_count = sum(counts.values())
    scheduled_post_count = counts.get("scheduled", 0)
    paused_post_count = counts.get("paused", 0)
    return post_count, scheduled_post_count, paused_post_count


def list_user_page_connections(db: Session, user_id: int) -> list[schemas.PageConnectionRead]:
    connections = (
        db.query(models.FacebookConnection)
        .filter(models.FacebookConnection.user_id == user_id)
        .order_by(models.FacebookConnection.connected_at.desc())
        .all()
    )
    results: list[schemas.PageConnectionRead] = []
    for connection in connections:
        post_count, scheduled_post_count, paused_post_count = _post_counts_for_connection(db, connection.id)
        picture = connection.page_picture_url
        results.append(
            schemas.PageConnectionRead(
                id=connection.id,
                facebook_page_id=connection.page_id,
                page_id=connection.page_id,
                page_name=connection.page_name,
                profile_picture_url=picture,
                page_picture_url=picture,
                connection_status=connection.connection_status,
                connected_at=connection.connected_at,
                disconnected_at=connection.disconnected_at,
                reconnect_count=connection.reconnect_count or 0,
                post_count=post_count,
                scheduled_post_count=scheduled_post_count,
                paused_post_count=paused_post_count,
            )
        )
    return results


async def store_pending_pages_for_user(
    user_id: int,
    pages: list[dict],
    token_expires_at: datetime | None = None,
) -> None:
    pending_json_oauth_pages[user_id] = {
        "pages": pages,
        "token_expires_at": token_expires_at,
    }


def select_page_for_user(db: Session, user_id: int, page_id: str) -> models.FacebookConnection:
    pending = pending_json_oauth_pages.get(user_id)
    if not pending:
        _facebook_error("Connect Facebook before selecting a page")

    selected_page = next((page for page in pending["pages"] if page["page_id"] == page_id), None)
    if selected_page is None:
        _facebook_error("Selected page was not found")

    try:
        connection = save_or_update_page_connection(
            db,
            user_id,
            selected_page,
            pending.get("token_expires_at"),
        )
    except HTTPException:
        raise

    pending_json_oauth_pages.pop(user_id, None)
    return connection

"""
AUTH INVESTIGATION - BACKEND
============================

LOGIN ROUTE: /auth/login (main.py)
- Returns: {"access_token": <JWT>, "token_type": "bearer"}
- JWT payload: {"sub": "<user_id>", "exp": <expiration_timestamp>}
- No session cookie — pure JWT only

SECRET_KEY:
- Defined in config.py — REQUIRED env var, raises ValueError if missing
- Used to sign (jwt.encode) and verify (jwt.decode) all JWT tokens
- Also used for SessionMiddleware and as fallback for Facebook encryption
- Must be a PERMANENT value in Render env vars — never changes
- Changing it invalidates ALL existing tokens and logs every user out

TOKEN EXPIRY:
- ACCESS_TOKEN_EXPIRE_MINUTES = 10080 (7 days) from config.py
- Configurable via env var ACCESS_TOKEN_EXPIRE_MINUTES
- Token refresh: middleware in main.py issues a new token via X-New-Token header
  when the current token is within 1 day of expiry

AUTH FLOW:
1. POST /auth/login with email+password → bcrypt verify → JWT returned
2. Frontend stores JWT in localStorage
3. Every API request includes Authorization: Bearer <token>
4. get_current_user() dependency:
   a. Extracts token via OAuth2PasswordBearer
   b. Decodes+verifies JWT with SECRET_KEY
   c. Fetches user from DB by user_id
   d. Returns User or raises 401

ROOT CAUSE ANALYSIS - USER FORGOTTEN:
======================================

PRIMARY: loadUser() on frontend was deleting token on ANY failure
- Frontend auth-context.tsx loadUser() catches ALL errors (network, timeout, cold start)
- Was removing token + setting user→null on any error
- Even after successful login, if GET /users/me failed, token was wiped
- FIXED: loadUser() now only sets user→null; never touches the token
- Token is only removed on explicit 401 by Axios response interceptor

SECONDARY: SECRET_KEY instability
- Was using os.getenv("SECRET_KEY", "change-me") with fallback to fixed default
- FIXED: Now raises ValueError if SECRET_KEY is not set — app won't start without it
- Must be set to a permanent value in Render env vars

PERFORMANCE - SLOW LOAD:
=========================
- social-platform.tsx load() was making 4 API calls SEQUENTIALLY
- health → pages → posts → analytics (each waits for previous)
- FIXED: Now uses Promise.allSettled() to fire all calls in parallel
- Cut initial load time from ~12s to ~3-4s (assuming ~1s per call + cold start)

TOKEN REFRESH:
===============
- main.py includes a @app.middleware("http") that runs on every response
- Decodes the JWT from Authorization header, checks if exp is within 1 day
- If so, creates a new token and adds X-New-Token response header
- Frontend Axios interceptor checks this header and updates localStorage
- Users who use the app regularly never get logged out
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import models
from app.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY
from app.database import get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.get(models.User, int(user_id))
    if user is None:
        raise credentials_exception
    return user

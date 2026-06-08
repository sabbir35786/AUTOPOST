"""
AUTH INVESTIGATION FINDINGS - BACKEND
======================================

LOGIN ROUTE: /auth/login (in main.py lines 565-580)
- Returns: {"access_token": <JWT token>, "token_type": "bearer"}
- Token type: JWT (JSON Web Token)
- Token payload contains: {"sub": "<user_id>", "exp": <expiration_timestamp>}
- No session cookie is set - only JWT token returned

SECRET_KEY USAGE:
- Location: backend/app/config.py line 21
- Value: os.getenv("SECRET_KEY", "change-me")
- Used in this file:
  - Line 37: jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM) - creates JWT tokens
  - Line 51: jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]) - verifies JWT tokens
- Also used in main.py line 424 for SessionMiddleware (but JWT auth doesn't use sessions)
- CRITICAL: If SECRET_KEY is not set in environment, defaults to "change-me"
- Startup check in main.py line 217 warns if SECRET_KEY is "change-me"

TOKEN EXPIRATION:
- Config: ACCESS_TOKEN_EXPIRE_MINUTES in config.py line 23
- Default value: 7 days (10080 minutes) - FIXED from 30 minutes
- Environment variable: ACCESS_TOKEN_EXPIRE_MINUTES (optional)
- Set in create_access_token() line 34: expires after ACCESS_TOKEN_EXPIRE_MINUTES from creation
- ROOT CAUSE #1: 30 minutes was TOO SHORT - FIXED to 7 days

AUTH FLOW:
1. User POSTs to /auth/login with email/password
2. Backend verifies credentials using bcrypt
3. Backend creates JWT token with user_id in "sub" claim
4. Backend returns token in JSON response
5. Frontend must include token in Authorization: Bearer <token> header for subsequent requests
6. get_current_user() dependency validates token and returns User object

ROOT CAUSE ANALYSIS - WHY USER IS FORGOTTEN:
==============================================

CAUSE #1: TOKEN EXPIRATION TOO SHORT (PRIMARY ISSUE) - FIXED
- Was: 30 minutes
- Now: 7 days (10080 minutes)
- Problem was: Users were logged out after 30 minutes of inactivity
- Fix applied: Increased to 7 days in backend/app/config.py line 23
- File changed: backend/app/config.py, backend/.env.example

CAUSE #2: POTENTIAL SECRET_KEY INSTABILITY (SECONDARY ISSUE)
- Current: os.getenv("SECRET_KEY", "change-me")
- Problem: If SECRET_KEY is not set in Render environment, uses default "change-me"
- Impact: If SECRET_KEY changes (e.g., redeployment with different key), all existing tokens become invalid
- MANUAL ACTION REQUIRED: Set SECRET_KEY as permanent environment variable in Render
- Check: main.py line 217 warns on startup if SECRET_KEY is "change-me"

ADDITIONAL FIXES APPLIED:
==========================
1. 401 Error Handling: Added auto-logout on token expiry in frontend/src/lib/api.ts
   - When API returns 401, clears localStorage token and redirects to login
2. API Timeout: Reduced from 90s to 30s in frontend/src/lib/api.ts
   - Improves perceived performance for failed requests
3. Database Query Limits: Added .limit(50) to queries in backend/app/routers/schedule_routes.py
   - Lines 226, 294, 306: Added limits to prevent unlimited row fetching
   - Improves database performance and response times

NOT RULED OUT:
- Token storage: Frontend uses localStorage (persists across refreshes) - OK
- Token attachment: Axios interceptor attaches Bearer header - OK

MANUAL FIXES REQUIRED:
=======================
1. PARALLEL API CALLS: Convert sequential API calls to parallel in frontend/src/components/social-platform.tsx
   - Current: Lines 223-252 make calls sequentially with await
   - Needed: Use Promise.all() to make calls in parallel
   - Impact: Could cut initial load time by 50-70%
   - Reason for manual fix: Automated edit failed due to string matching issues

2. SECRET_KEY IN RENDER: Set permanent SECRET_KEY environment variable
   - Generate: python -c "import secrets; print(secrets.token_hex(32))"
   - Add to Render dashboard → Environment Variables
   - Do not change after setting
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

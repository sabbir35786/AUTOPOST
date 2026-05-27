# AutoPoster — Full Project Documentation
### Complete conversation history, decisions, bugs, and fixes

---

## PROJECT OVERVIEW

This project is a **social media management SaaS platform** similar to Ayrshare or Buffer. It allows users to connect their Facebook Pages and manage posts from a centralized dashboard. The platform handles all OAuth tokens, Graph API calls, and token refresh logic invisibly. Users never touch the Facebook Developer Console after initial setup.

**Tech Stack:**
- Frontend: React/Next.js deployed on **Vercel**
- Backend: FastAPI (Python) deployed on **Render**
- Database: **Supabase** (PostgreSQL)
- AI: **Mistral AI** API for post generation
- Scheduling: **cron-job.org** (free) pinging a backend endpoint every minute
- Facebook: Graph API via OAuth 2.0

---

## PART 1 — CORE PLATFORM ARCHITECTURE

### How It Works
- One Facebook Developer App (owned by the platform owner) handles all user connections
- Users connect their own Facebook Pages through an OAuth popup — one click, no technical knowledge needed
- Page Access Tokens are encrypted and stored in Supabase
- The backend proxies all Facebook API calls — frontend never sees tokens

### User Flow Summary
1. User registers with email and password
2. User connects their Facebook Page via OAuth popup
3. User creates posts manually or uses AI to generate them
4. User publishes immediately or schedules for later
5. Background scheduler (via cron-job.org) publishes scheduled posts automatically

---

## PART 2 — ENVIRONMENT VARIABLES

### Backend `.env` File (all required)
```
DATABASE_URL=your_supabase_postgresql_url
SECRET_KEY=your_app_secret_key
FRONTEND_URL=https://your-app.vercel.app
FACEBOOK_APP_ID=from_facebook_developer_console
FACEBOOK_APP_SECRET=from_facebook_developer_console
FACEBOOK_REDIRECT_URI=https://your-app.onrender.com/auth/facebook/callback
FACEBOOK_TOKEN_ENCRYPTION_KEY=generated_32_char_random_string
FACEBOOK_OAUTH_SCOPES=pages_manage_posts,pages_read_engagement,pages_show_list
MISTRAL_API_KEY=from_mistral_console
CRON_SECRET=generated_32_char_random_string
```

### How to Generate Secret Keys
Run in terminal:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Or use: **generate-secret.vercel.app** in browser

### Startup Environment Check
The server prints on startup:
```
[OK] DATABASE_URL loaded
[OK] SECRET_KEY loaded
[OK] FRONTEND_URL loaded
[OK] FACEBOOK_APP_ID loaded
[OK] FACEBOOK_APP_SECRET loaded
[OK] FACEBOOK_REDIRECT_URI loaded
[OK] FACEBOOK_TOKEN_ENCRYPTION_KEY loaded
[OK] FACEBOOK_OAUTH_SCOPES loaded
[OK] MISTRAL_API_KEY loaded
[OK] CRON_SECRET loaded
```

---

## PART 3 — FACEBOOK OAUTH CONNECTION SYSTEM

### How the OAuth Flow Works

1. User clicks **Connect Facebook Page** button on dashboard
2. Frontend opens a **popup window** (600x700px) pointing to `/auth/facebook/start` on backend
3. Backend builds the Facebook OAuth URL with App ID, redirect URI, required scopes, and a random `state` string stored in session
4. Backend redirects popup to Facebook
5. User logs in and approves permissions inside popup
6. Facebook redirects popup back to `/auth/facebook/callback` with `code` and `state` parameters
7. Backend validates `state` matches session (security check)
8. Backend exchanges `code` for short-lived user token
9. Backend exchanges short-lived token for **long-lived token** (60 days)
10. Backend calls Graph API to get list of pages user manages
11. If multiple pages, user selects which one
12. Backend stores **Page Access Token** (encrypted) in database
13. Popup sends success message to parent window and closes
14. Dashboard refreshes and shows connected page

### Required Facebook Permissions
- `pages_manage_posts` — publish posts to the page
- `pages_read_engagement` — read likes, comments, shares
- `pages_show_list` — see which pages the user manages

### Token Storage Rules
- Page Access Tokens are encrypted using `FACEBOOK_TOKEN_ENCRYPTION_KEY` before storing
- Never store plain text tokens
- Never send tokens to the frontend
- Long-lived user token is discarded after extracting the page token

### Token Error Codes to Handle
- **Error 190** — Token expired/revoked → mark page as "Needs Reconnection"
- **Error 200** — Wrong permissions → ask user to reconnect and approve all permissions

---

## PART 4 — FACEBOOK APP REVIEW (Going Live)

### Development Mode vs Live Mode
```
DEVELOPMENT MODE              LIVE MODE
Only you and manually         Anyone can connect
added test users can          their Facebook Page
connect pages
```

### For Personal Testing (5 minutes)
Go to developers.facebook.com → App Roles → Testers → Add your own Facebook account

### For Public Users (requires Facebook review)
1. Fill in App Settings → Basic (icon, privacy policy URL, terms URL, category)
2. Add Facebook Login product, set Valid OAuth Redirect URI
3. Request three permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`
4. Record a screencast video showing the full flow (see video requirements below)
5. Submit for review (5-30 business days)
6. Switch app to Live Mode after approval

### Screencast Video Requirements
- Length: 2-5 minutes
- Format: MP4, 1080p
- Language: English narration or English subtitles
- Must show: real app URL in browser, full OAuth popup flow, post being published AND appearing live on the actual Facebook Page
- Must demonstrate all three permissions in action

### Access Tiers
- **Standard Access** — works for your own pages in Live Mode
- **Advanced Access** — required for other users' pages (needs business verification)

### Privacy Policy Minimum Content
Must be live at a real URL and include:
- What data is collected (email, page name, page ID, page access token)
- How it is used (only to publish posts when user instructs)
- That tokens are encrypted
- Which Facebook permissions are requested and why
- How to delete data (disconnect page, delete account)
- Contact email

---

## PART 5 — DATABASE SCHEMA

### Tables Required

**users**
- id, email, hashed_password, email_verified, timezone, created_at

**page_connections** (also called FacebookConnection)
- id, user_id, facebook_page_id, facebook_page_name, page_profile_picture_url
- encrypted_page_access_token, connection_status (connected/needs-reconnection/disconnected)
- connected_at, updated_at
- **UNIQUE constraint on facebook_page_id** — one page can only be connected to one account at a time

**post_logs**
- id, user_id, facebook_connection_id, ai_persona_id
- content, status (draft/scheduled/publishing/published/failed/missed)
- media_urls, link_url, link_preview_data
- scheduled_at, posted_at, post_date
- facebook_post_id, retry_count, error_message
- topic, ai_generated (boolean), auto_generated (boolean)
- created_at, updated_at

**ai_personas**
- id, user_id, page_connection_id, persona_name
- niche, tone_tags, custom_instructions, language
- hashtag_enabled, hashtag_count
- auto_posting_enabled, frequency_minutes
- active_hours_start, active_hours_end, active_days
- max_posts_per_day, last_auto_post_at
- priority_level, performance_score
- total_posts, total_likes, total_comments, total_shares
- created_at, updated_at

**post_engagement_snapshots**
- id, post_id, persona_id, snapshot_type (1hr/6hr/24hr)
- likes, comments, shares, reach, engagement_score, taken_at

**ai_recommendations**
- id, page_connection_id, recommendation_text, generated_at, is_dismissed

### Important Database Rule
The `facebook_page_id` column in `page_connections` must have a **UNIQUE constraint**. Before saving a new connection, check if the page ID already exists. If it belongs to a different user, reject with message: "This Facebook Page is already connected to another account."

---

## PART 6 — AI POST GENERATION (Mistral AI)

### Setup
```
pip install mistralai
MISTRAL_API_KEY=your_key_from_console.mistral.ai
```

### How the Prompt Is Built
**System prompt:** You are a professional social media content writer. Return only the post text. No labels, no quotation marks, no preamble.

**User prompt is assembled from persona settings:**
```
Write one Facebook post for a page about: [niche]
Tone and style: [tone_tags]
Follow these rules: [custom_instructions]
Write in: [language]
Add [n] relevant hashtags at the end.
Focus this post on: [topic_hint if provided]
Return only the post text. Nothing else.
```

### Mistral Settings
- Model: `mistral-large-latest` (quality) or `mistral-small-latest` (speed/cost)
- Temperature: 0.8
- Max tokens: 500

### Post Quality Rules
- Maximum 5 hashtags on Facebook (more hurts reach)
- Vary post length every time
- Always end with a question or call to action
- Maximum 1-2 posts per day for healthy organic reach
- Track last 5 post topics and avoid repeating them

---

## PART 7 — MULTI-PERSONA SYSTEM

### Concept
Each Facebook Page can have up to 5 AI Personas. Each persona has its own niche, tone, instructions, and assigned days of the week.

### Example Setup
```
Persona 1: "Motivational"    → Monday, Wednesday, Friday → 9AM, 6PM
Persona 2: "Educational"     → Tuesday, Thursday         → 10AM, 7PM  
Persona 3: "Weekend Fun"     → Saturday, Sunday          → 11AM
```

### Day Assignment Rules
- One day can only belong to one persona at a time
- If user tries to assign an already-taken day, warn them
- Unassigned days get no auto posts

### Scheduler Resolution Logic
Every 5 minutes (triggered by cron-job.org):
1. Get current day and time in user's timezone
2. Find personas where today is in their assigned days
3. Find which persona has a time slot matching current window
4. Run that persona's post generation and publish

---

## PART 8 — REINFORCEMENT LEARNING ENGAGEMENT OPTIMIZER

### Engagement Score Formula
```
score = (likes × 1) + (comments × 3) + (shares × 5) + (reach ÷ 100)
```

### Performance Score Calculation
- Each persona has a score between 0.1 and 1.0, starting at 0.5
- Uses weighted rolling average of last 20 posts
- Most recent post gets weight 20, oldest gets weight 1
- Normalized against average of all personas on the page

### How Score Affects Behavior
- Score > 0.75 → posts at all configured time slots
- Score 0.5-0.75 → one slot randomly skipped per day
- Score < 0.5 → posts at 50% of slots
- Score < 0.25 → persona auto-paused, user notified by email

### Engagement Snapshots
Fetch metrics from Facebook Graph API at:
- 1 hour after publishing
- 6 hours after publishing
- 24 hours after publishing

### A/B Testing Mode
After 20+ posts per persona:
- 8 out of every 10 posts use learned best patterns
- 2 out of every 10 use experimental different parameters
- If experimental post outperforms standard, update learned patterns

### Weekly Learning Job
Runs every Sunday midnight:
- Recalculates all persona performance scores
- Updates learned patterns
- Generates fresh AI recommendations via Mistral
- Sends user weekly performance report email

---

## PART 9 — SCHEDULING SYSTEM

### Architecture Decision
**Do NOT run APScheduler inside the FastAPI web server.** This causes missed posts when Render free tier sleeps.

**Correct Architecture:**
```
cron-job.org (free, external)
Pings every 1 minute
        │
        ▼ GET /api/internal/run-scheduler
        │ Header: X-Cron-Secret: [secret]
        ▼
Render Web Service (FastAPI)
Runs scheduling logic when pinged
        │
        ▼
Supabase PostgreSQL
        │
        ▼
Facebook Graph API
```

### The Scheduler Endpoint
- Route: `GET /api/internal/run-scheduler`
- Protected by `X-Cron-Secret` header matching `CRON_SECRET` env variable
- Returns: `{"status": "ok", "message": "Scheduler run completed", "timestamp": "..."}`
- Returns 401 if secret does not match
- Logs every trigger: "Scheduler triggered via cron endpoint at [UTC time]"

### Missed Post Recovery
- Scheduler checks for ALL posts with status "scheduled" where scheduled_at <= now
- Posts missed within last 12 hours → publish immediately
- Posts missed more than 12 hours ago → mark as "missed", do not publish late

### Retry Logic
- Failed posts retry up to 3 times with 5-minute gaps
- After 3 failures → mark "permanently failed", email user

### cron-job.org Setup
1. Create free account at cron-job.org
2. Create new cronjob
3. URL: `https://your-app.onrender.com/api/internal/run-scheduler`
4. Schedule: Every 1 minute (`* * * * *`)
5. Add header: `X-Cron-Secret` → your CRON_SECRET value
6. Save and enable

---

## PART 10 — BUGS FIXED AND HOW

### Bug 1 — "Facebook app credentials are not configured"
**Cause:** `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, and `FACEBOOK_TOKEN_ENCRYPTION_KEY` were missing from the `.env` file.
**Fix:** Added all three variables. App ID and Secret come from Facebook Developer Console → App Settings → Basic. Encryption key is self-generated using `secrets.token_hex(32)`.

### Bug 2 — "Could not load your workspace" on all pages
**Cause:** Multiple possible causes — CORS blocking API calls, missing auth token in requests, backend route not existing, or database tables not created.
**Fix:** Check browser Network tab for the failing request's HTTP status code, then fix based on the status (401=auth token missing, 404=route missing, 500=server error, check logs).

### Bug 3 — CORS error on laptop browser, works on mobile
**Cause:** Backend CORS configuration only allowed localhost, not the production Vercel URL.
**Fix:** Update `CORSMiddleware` in `main.py` — add Vercel production URL to `allow_origins`. Set `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. Also verify frontend environment variable points to Render URL not localhost.

### Bug 4 — Same Facebook Page connectable by multiple email accounts
**Cause:** No uniqueness constraint on `facebook_page_id` in the database.
**Fix:** 
1. Add UNIQUE constraint to `facebook_page_id` column in `page_connections` table
2. In OAuth callback, before saving: check if page ID already exists in database
3. If exists and belongs to different user → return error: "This Facebook Page is already connected to another account"
4. If exists and belongs to same user → update existing record (reconnect)

### Bug 5 — Auto posting not running on deployed app
**Cause:** APScheduler was running inside the FastAPI web server process. Render free tier web services sleep after 15 minutes of inactivity, killing the scheduler.
**Fix:** Removed APScheduler from web server entirely. Created protected `/api/internal/run-scheduler` endpoint. Set up cron-job.org to ping this endpoint every minute — cron-job.org runs 24/7 on their servers and keeps Render awake.

### Bug 6 — `column post_logs.topic does not exist`
**Cause:** Database migration not run after adding `topic` column to SQLAlchemy model.
**Fix:** Ran raw SQL migration against Supabase database:
```sql
ALTER TABLE post_logs ADD COLUMN IF NOT EXISTS topic VARCHAR;
```

### Bug 7 — Facebook OAuth redirect going to localhost after deployment
**Cause:** `FACEBOOK_REDIRECT_URI` environment variable on Render still had localhost URL. Also Facebook Developer Console only had localhost in Valid OAuth Redirect URIs.
**Fix:** 
1. Update `FACEBOOK_REDIRECT_URI` on Render to: `https://your-app.onrender.com/auth/facebook/callback`
2. In Facebook Developer Console → Facebook Login → Settings → Valid OAuth Redirect URIs → add the Render URL (keep localhost too for local dev)
3. Verify frontend `VITE_API_URL` / `NEXT_PUBLIC_API_URL` on Vercel points to Render not localhost

---

## PART 11 — DEPLOYMENT CONFIGURATION

### Vercel (Frontend)
- Hosts the React/Next.js frontend
- Environment variables needed:
  - `VITE_API_URL` or `NEXT_PUBLIC_API_URL` = `https://your-app.onrender.com`
- Redeploy after any environment variable change

### Render (Backend)
- Hosts the FastAPI backend
- Free tier web service (sleeps after 15 min inactivity — solved by cron-job.org pinging)
- All backend environment variables set in Render dashboard → Environment tab
- Auto-deploys on git push to main branch

### Supabase (Database)
- Hosts PostgreSQL database
- Connection string goes in `DATABASE_URL` environment variable
- Run migrations directly via Supabase SQL editor or via backend database connection
- All tables shared between Render web service and any other services

### Database Migrations
When adding new columns to existing tables, run:
```sql
ALTER TABLE table_name ADD COLUMN IF NOT EXISTS column_name COLUMN_TYPE;
```
Either through Supabase dashboard SQL editor or via the backend's database connection in terminal.

---

## PART 12 — FACEBOOK ENGAGEMENT BEST PRACTICES

### What Facebook Penalizes
- Repetitive identical post structures
- Generic filler content with no real value
- More than 5 hashtags (hurts reach on Facebook, not Instagram)
- Posting more than 2 times per day
- Posts that get zero engagement (algorithm stops showing your content)

### What Works
- Varied post formats (questions, stories, tips, bold statements)
- 2-5 hashtags maximum
- Ending every post with a question or call to action
- 1-2 posts per day maximum
- Genuine value-adding content for the niche

### Organic Reach Reality
Facebook pages reach only 2-5% of followers organically regardless of content quality. This is a platform-level decision by Facebook to push paid ads. The AI system cannot fix this but following best practices keeps you in the best possible position.

---

## PART 13 — INTERNAL UTILITY ENDPOINTS

### Health Check
- Route: `GET /health`
- No authentication required
- Returns: "ok" with 200 status
- Used by: cron-job.org to keep Render awake, general uptime monitoring

### Scheduler Trigger
- Route: `GET /api/internal/run-scheduler`
- Header required: `X-Cron-Secret: [CRON_SECRET value]`
- Returns: `{"status": "ok", "message": "Scheduler run completed", "timestamp": "..."}`
- Used by: cron-job.org every 1 minute

### Database Init (for migrations)
- Route: `GET /api/internal/init-db`
- Header required: `X-Cron-Secret: [CRON_SECRET value]`
- Calls `Base.metadata.create_all()` to create any missing tables/columns
- Used for: applying schema updates to production database

---

## PART 14 — TESTING TOOLS USED

- **Thunder Client** (VS Code extension) — testing API endpoints locally and in production
- **Hoppscotch.io** — browser-based API testing (free, no install needed)
- Both tools used to test the `/api/internal/run-scheduler` endpoint with the `X-Cron-Secret` header

---

## CURRENT STATUS SUMMARY

| Feature | Status |
|---|---|
| User registration and login | Working |
| Facebook OAuth connection | Working (after redirect URI fix) |
| Manual post creation and publishing | Working |
| AI post generation with Mistral | Working |
| Multi-persona system | Built |
| Scheduled posting via cron-job.org | Working after topic column migration |
| Auto posting with AI personas | In progress |
| Engagement analytics | Built |
| Reinforcement learning optimizer | Designed, implementation in progress |
| Facebook App Review submission | Not yet submitted |
| CORS fix for laptop browser | Fix identified, apply CORSMiddleware update |
| Duplicate page connection prevention | Fix identified, add unique constraint |

---

## WHAT STILL NEEDS TO BE DONE

1. Apply CORS fix in backend `main.py` — add Vercel URL to allow_origins
2. Add UNIQUE constraint on `facebook_page_id` in database and duplicate check in OAuth callback
3. Verify cron-job.org is running and check Render logs for scheduler trigger every minute
4. Test full scheduled post flow end to end in production
5. Submit Facebook App for review when ready for other users
6. Implement reinforcement learning engagement scoring fully
7. Build performance insights dashboard UI
8. Add weekly AI recommendation generation job

---

*This document covers the full conversation and development history of the AutoPoster project. All architecture decisions, bugs, fixes, environment setup, and remaining tasks are documented here for continuity.*

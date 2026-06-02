# AutoPoster — Codebase Reference for AI Coding Agents
> Everything built so far. Read this before making any changes.

---

## STACK

- **Frontend:** React/Next.js → deployed on Vercel
- **Backend:** FastAPI (Python) → deployed on Render (free tier)
- **Database:** Supabase (PostgreSQL)
- **AI Text:** Mistral AI (primary), with multi-provider support (OpenAI, Anthropic, Gemini)
- **AI Image:** Fal.ai FLUX (primary), Stability AI, DALL-E, Gemini Imagen
- **Scheduling:** cron-job.org pings backend every 1 minute
- **File Storage:** Supabase Storage (bucket: `generated-images`, public read)

---

## ENVIRONMENT VARIABLES (backend .env)

```
DATABASE_URL                  Supabase PostgreSQL connection string
SECRET_KEY                    App JWT/session secret
FRONTEND_URL                  Vercel frontend URL (for CORS and OAuth redirect)
FACEBOOK_APP_ID               From Facebook Developer Console
FACEBOOK_APP_SECRET           From Facebook Developer Console
FACEBOOK_REDIRECT_URI         https://your-app.onrender.com/auth/facebook/callback
FACEBOOK_TOKEN_ENCRYPTION_KEY 32-char random string, encrypts stored tokens
FACEBOOK_OAUTH_SCOPES         pages_manage_posts,pages_read_engagement,pages_show_list
MISTRAL_API_KEY               Platform-level key, all users share this
CRON_SECRET                   32-char random string, protects scheduler endpoint
SUPABASE_URL                  Supabase project URL
SUPABASE_SERVICE_KEY          Supabase service role key (for storage operations)
FAL_API_KEY                   Optional, platform-level Fal.ai key
STABILITY_API_KEY             Optional
OPENAI_API_KEY                Optional
GEMINI_API_KEY                Optional
```

Startup prints `[OK]` or `[MISSING]` for each variable. App starts regardless but features using missing keys will fail gracefully.

---

## DATABASE SCHEMA

### `users`
```
id UUID PK, email VARCHAR UNIQUE, hashed_password TEXT,
email_verified BOOL, timezone VARCHAR, created_at, updated_at
```

### `page_connections`
```
id UUID PK, user_id FK→users, facebook_page_id VARCHAR,
facebook_page_name VARCHAR, page_profile_picture_url TEXT,
access_token TEXT (nullable, encrypted), connection_status VARCHAR,
  -- values: connected | disconnected | needs_reconnection
disconnected_at TIMESTAMPTZ, reconnect_count INT DEFAULT 0,
last_token_refresh TIMESTAMPTZ, created_at, updated_at

UNIQUE INDEX on (user_id, facebook_page_id)
-- One user cannot connect same page twice
-- Different users CAN connect the same page
-- NEVER delete this row on disconnect — only update status
```

### `post_logs`
```
id UUID PK, user_id FK→users,
facebook_connection_id FK→page_connections ON DELETE SET NULL,
ai_persona_id FK→ai_personas ON DELETE SET NULL,
content TEXT, status VARCHAR,
  -- values: draft|scheduled|paused|publishing|published|failed|missed|permanently_failed
media_urls TEXT[], link_url TEXT, link_preview_data JSONB,
scheduled_at TIMESTAMPTZ, posted_at TIMESTAMPTZ,
facebook_post_id VARCHAR, retry_count INT DEFAULT 0,
error_message TEXT, topic VARCHAR,
ai_generated BOOL DEFAULT FALSE, auto_generated BOOL DEFAULT FALSE,
image_url TEXT, media_library_id FK→media_library,
post_date DATE, created_at, updated_at
```

### `ai_personas`
```
id UUID PK, user_id FK→users,
page_connection_id FK→page_connections ON DELETE SET NULL,
persona_name VARCHAR, niche TEXT, tone_tags VARCHAR,
custom_instructions TEXT, language VARCHAR DEFAULT 'English',
hashtag_enabled BOOL, hashtag_count INT DEFAULT 3,
auto_posting_enabled BOOL DEFAULT FALSE,
frequency_minutes INT, active_hours_start TIME,
active_hours_end TIME, active_days VARCHAR,
max_posts_per_day INT DEFAULT 2,
last_auto_post_at TIMESTAMPTZ,
priority_level VARCHAR DEFAULT 'normal',
performance_score DECIMAL DEFAULT 0.5,
total_posts INT DEFAULT 0,
include_image BOOL DEFAULT FALSE,
image_frequency VARCHAR DEFAULT 'every_post',
image_prompt_source VARCHAR DEFAULT 'persona_prompt',
image_fallback_policy VARCHAR DEFAULT 'text_only',
image_max_wait_seconds INT DEFAULT 120,
created_at, updated_at
```

### `image_generation_jobs`
```
id UUID PK, user_id FK→users, persona_id FK→ai_personas ON DELETE SET NULL,
status VARCHAR,
  -- values: pending|processing|completed|failed|timeout
provider VARCHAR, model_name VARCHAR,
assembled_prompt TEXT, negative_prompt TEXT,
aspect_ratio VARCHAR DEFAULT '1:1',
result_image_url TEXT, supabase_storage_path TEXT,
error_message TEXT, max_wait_seconds INT DEFAULT 120,
started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
generation_seconds INT, created_at
```

### `media_library`
```
id UUID PK, user_id FK→users,
persona_id FK→ai_personas ON DELETE SET NULL,
image_url TEXT, storage_path TEXT,
generation_prompt TEXT, provider VARCHAR, model_name VARCHAR,
is_used BOOL DEFAULT FALSE,
used_in_post_id FK→post_logs ON DELETE SET NULL,
created_at
```

### `image_prompt_settings`
```
id UUID PK, persona_id FK→ai_personas UNIQUE, user_id FK→users,
subject_description TEXT, style_tags TEXT[],
mood_tags TEXT[], color_palette VARCHAR,
negative_prompt TEXT, aspect_ratio VARCHAR DEFAULT '1:1',
text_overlay_enabled BOOL DEFAULT FALSE,
text_overlay_content TEXT, text_overlay_style VARCHAR,
reference_image_descriptors TEXT, assembled_prompt TEXT,
created_at, updated_at
```

### `model_settings`
```
id UUID PK, user_id FK→users, task_category VARCHAR, provider_name VARCHAR,
model_name VARCHAR, api_key_encrypted TEXT,
created_at, updated_at
UNIQUE on (user_id, task_category)

task_category values:
  post_generation | post_analysis | image_generation |
  style_analysis | image_prompt_generation | recommendations
```

### `post_engagement_snapshots`
```
id UUID PK, post_id FK→post_logs ON DELETE SET NULL,
persona_id FK→ai_personas ON DELETE SET NULL,
snapshot_type VARCHAR,  -- 1hr | 6hr | 24hr
likes INT, comments INT, shares INT,
reach INT, impressions INT, engagement_score DECIMAL,
taken_at TIMESTAMPTZ
```

### `learning_signals`
```
id UUID PK, user_id FK→users, persona_id FK→ai_personas,
signal_type VARCHAR,
  -- post_performance|prompt_experiment|user_edit|user_delete|competitor_trend
signal_data JSONB, outcome_score DECIMAL, created_at
```

### `learned_strategy`
```
id UUID PK, persona_id FK→ai_personas,
strategy_data JSONB, confidence_score DECIMAL,
week_start_date DATE, applied_to_prompt BOOL DEFAULT FALSE,
created_at
```

### `ai_recommendations`
```
id UUID PK, page_connection_id FK→page_connections,
recommendation_text TEXT, generated_at TIMESTAMPTZ,
is_dismissed BOOL DEFAULT FALSE
```

### `tracked_pages`
```
id UUID PK, user_id FK→users,
facebook_page_id VARCHAR, page_nickname VARCHAR,
tracking_since TIMESTAMPTZ, last_fetched_at TIMESTAMPTZ
```

### `tracked_page_posts`
```
id UUID PK, tracked_page_id FK→tracked_pages,
facebook_post_id VARCHAR, post_content TEXT,
posted_at TIMESTAMPTZ, likes INT, comments INT, shares INT,
topic_classification VARCHAR, engagement_score DECIMAL
```

### `prompt_templates`
```
id UUID PK, user_id FK→users, persona_id FK→ai_personas,
template_name VARCHAR, question_answers JSONB,
assembled_prompt TEXT, raw_prompt TEXT,
creativity_level INT DEFAULT 7, style_examples TEXT[],
created_at, updated_at
```

---

## API ROUTES

### Auth
```
POST /auth/register          Email + password registration
POST /auth/login             Returns JWT token
POST /auth/verify-email      Email verification
GET  /auth/facebook/start    Starts OAuth popup flow
GET  /auth/facebook/callback Handles Facebook redirect, saves token
POST /auth/facebook/select-page  If user manages multiple pages
```

### Pages
```
GET    /api/pages                         List user's pages (all statuses)
DELETE /api/pages/{id}/disconnect         Sets status=disconnected, nulls token
POST   /api/pages/{id}/reconnect          Restarts OAuth for existing page
POST   /api/pages/{id}/recover-history    Fetches last 100 posts from Facebook Graph API
```

### Posts
```
POST /api/posts              Create post (manual or scheduled)
GET  /api/posts              List posts (filter by status, page)
PUT  /api/posts/{id}         Edit draft or scheduled post
DELETE /api/posts/{id}       Delete post (and from Facebook if published)
POST /api/posts/{id}/publish Immediately publish a draft
```

### AI Text Generation
```
POST /api/ai/generate              Generate post text using persona settings
POST /api/ai/generate-and-publish  Generate + publish immediately (used by scheduler)
POST /api/ai/prompt/save           Save custom prompt for persona
GET  /api/ai/prompt/{persona_id}   Get saved prompt for persona
POST /api/ai/prompt/test           Test current prompt, return sample post
```

### Image Generation
```
POST /api/images/generate              Start image generation job, return job_id immediately
GET  /api/images/job/{job_id}          Poll job status and result
POST /api/images/retry/{job_id}        Retry failed/timeout job
GET  /api/images/library               User's media library (paginated, 20/page)
DELETE /api/images/library/{id}        Delete unused image from library + storage
POST /api/images/prompt/save           Save image prompt settings for persona
GET  /api/images/prompt/{persona_id}   Get image prompt settings
POST /api/images/prompt/analyze-reference  Upload reference images, get style descriptors
POST /api/images/prompt/generate-from-text Generate image prompt from post caption text
```

### Model Settings
```
GET  /api/models/settings    Get all model settings for user
POST /api/models/settings    Save model settings
POST /api/models/test        Test a provider API key
```

### Personas
```
GET    /api/personas                  List personas for user
POST   /api/personas                  Create persona
PUT    /api/personas/{id}             Update persona
DELETE /api/personas/{id}             Delete persona
POST   /api/personas/{id}/pause       Pause auto posting
POST   /api/personas/{id}/resume      Resume auto posting
```

### Analytics
```
GET /api/analytics/summary    Aggregated stats (date range param)
GET /api/analytics/posts      Per-post metrics
GET /api/analytics/personas   Performance score per persona
GET /api/analytics/heatmap    Engagement by day/hour grid
```

### Tracker
```
GET    /api/tracker                    List tracked pages
POST   /api/tracker                    Add page to track
DELETE /api/tracker/{id}              Remove tracked page
POST   /api/tracker/{id}/add-posts    Manually add posts to tracked page
GET    /api/tracker/feed              Combined feed of all tracked page posts
```

### Internal (protected by X-Cron-Secret header)
```
GET  /health                          Returns "ok", keeps Render awake
GET  /api/internal/run-scheduler      Main scheduler trigger, called by cron-job.org
POST /api/internal/init-db            Runs create_all for schema updates
```

---

## KEY BUSINESS LOGIC

### Facebook OAuth Connect Flow
1. Frontend opens popup to `/auth/facebook/start`
2. Backend generates state string, stores in session, redirects to Facebook
3. User approves in popup
4. Facebook redirects to `/auth/facebook/callback` with code + state
5. Backend validates state, exchanges code for long-lived token
6. Backend fetches user's pages via Graph API
7. If one page: auto-select. If multiple: show selection UI in popup
8. Before saving: check if `(user_id, facebook_page_id)` already exists
   - Exists (same user): UPDATE token + status, keep all history, increment reconnect_count
   - Active connection exists for different user: reject with error
   - Not found: INSERT new row
9. Popup sends `postMessage({type:'FACEBOOK_CONNECT_SUCCESS'})` to parent and closes
10. Dashboard refreshes, loads full post history

### Facebook Disconnect Flow
- ONLY update `connection_status='disconnected'`, `access_token=NULL`, `disconnected_at=NOW()`
- NEVER delete the page_connections row
- NEVER delete any post_logs or ai_personas
- Set all `scheduled` posts for this page to `paused`
- On reconnect: set paused posts back to `scheduled` (only future ones)

### Scheduler (runs every 1 minute via cron-job.org)
```
1. cron-job.org hits GET /api/internal/run-scheduler
   with header X-Cron-Secret matching CRON_SECRET env var
2. Finds all post_logs where status='scheduled' AND scheduled_at <= NOW()
3. Missed window check:
   - scheduled_at < NOW() - 12 hours → mark 'missed', skip
   - scheduled_at within last 12 hours → publish (catch-up)
4. For each due post:
   a. If persona has include_image=True and image_frequency check passes:
      - Generate image (sync, with timeout from image_max_wait_seconds)
      - On failure: apply image_fallback_policy
   b. Call Facebook Graph API to publish
   c. Update status to 'published' or 'failed'
   d. On failure: increment retry_count, retry up to 3 times (5 min gap)
   e. After 3 failures: mark 'permanently_failed', email user
5. For auto-persona posts:
   - Check day of week in persona's active_days
   - Check current time within active_hours_start and active_hours_end
   - Check posts published today < max_posts_per_day
   - Check time since last_auto_post_at >= frequency_minutes
   - If all pass: generate post via Mistral, optionally generate image, publish
```

### Image Generation (polling pattern)
```
POST /api/images/generate
→ Creates job row with status='pending', returns job_id instantly
→ Starts background task: calls provider API
→ Uploads result to Supabase Storage
→ Updates job to 'completed' with image URL
→ Creates media_library row

GET /api/images/job/{job_id}  (frontend polls every 3 seconds)
→ Returns current status + image URL when complete
→ Timeout if exceeds max_wait_seconds (10-180, user configurable)
```

### Engagement Score Formula
```
score = (likes × 1) + (comments × 3) + (shares × 5) + (reach ÷ 100)
```
Snapshots taken at 1hr, 6hr, 24hr after publish.

### Persona Performance Score
```
Rolling weighted average of last 20 posts
Most recent post weight=20, oldest weight=1
Normalized against page average
Range: 0.1 to 1.0, starts at 0.5

Effects:
> 0.75 → posts at all time slots
0.5–0.75 → skips one slot per day randomly
< 0.5 → posts at 50% of slots
< 0.25 → persona auto-paused, user emailed
```

### Multi-Provider AI Routing
All AI calls route through `app/providers/llm_providers.py`:
- Reads user's model_settings for the task_category
- Falls back to Mistral + platform key if no user setting exists
- Supports: Mistral, OpenAI, Anthropic, Google Gemini

All image calls route through `app/providers/image_providers.py`:
- Supports: Fal.ai (FLUX), Stability AI, OpenAI DALL-E, Google Imagen
- Falls back to Fal.ai + platform key if no user setting

---

## FEATURE LIST (what is built)

- User registration, login, email verification
- Facebook OAuth connect/disconnect with full data persistence
- Multi-page support per user
- Manual post creation and immediate publishing
- Post scheduling with timezone support
- Auto-posting via AI personas with day/time assignment
- Up to 5 personas per page, each with own schedule
- Custom prompt builder (gap-fill questions → assembled prompt)
- Prompt Studio with live preview and test generation
- Multi-LLM model selector per task category
- Image generation with polling (Fal.ai, Stability AI, DALL-E, Gemini)
- Image prompt studio with reference image style analysis
- Media library for generated images
- Auto image attachment on scheduled posts
- Engagement analytics (likes, comments, shares, reach, impressions)
- Engagement snapshots at 1hr/6hr/24hr per post
- Persona performance scoring with weighted rolling average
- A/B testing mode for post content (8 standard : 2 experimental)
- Weekly learning synthesis job (strategy stored in learned_strategy table)
- AI-generated prompt improvement suggestions (user approves/rejects)
- Dashboard smart suggestions (daily, from Mistral analysis)
- Style Analyzer — own page (automatic) and any page (manual paste)
- Page Tracker with manual post input and RSS auto-sync attempt
- Trending topic detection across tracked pages
- Post history recovery from Facebook Graph API (last 100 posts)
- Reconnect flow restores all history and resumes paused posts
- Missed post catch-up (up to 12 hours back)
- Retry logic (3 attempts, 5 min gaps, then permanently_failed)
- CORS configured for Vercel + localhost
- Health endpoint to keep Render awake
- Cron-job.org integration for scheduling

---

## KNOWN META API LIMITATIONS

- Cannot fetch posts from pages you do not manage via Graph API
- Style Analyzer for external pages = manual paste only
- Page Tracker auto-fetch = RSS attempt only, falls back to manual
- Competitor engagement metrics = not available via API
- `pages_read_user_content` needed for audience demographics (not yet requested in review)
- App currently in Development Mode — only test users can connect pages
- Need Facebook App Review approval to go live for all users

---

## FACEBOOK PERMISSIONS REQUESTED

- `pages_manage_posts` — publish posts
- `pages_read_engagement` — read likes, comments, shares, reach
- `pages_show_list` — list user's managed pages

Pending to add in next review submission:
- `pages_read_user_content` — richer analytics
- `pages_manage_metadata` — page category/metadata for AI context

---

## DEPLOYMENT

| Service | Platform | Notes |
|---|---|---|
| Frontend | Vercel | Auto-deploys on git push |
| Backend | Render free tier | Sleeps after 15min inactivity |
| Database | Supabase | Free tier, 500MB |
| File Storage | Supabase Storage | `generated-images` bucket, public |
| Scheduler | cron-job.org | Pings /api/internal/run-scheduler every 1 min, keeps Render awake |

**Critical:** cron-job.org must include header `X-Cron-Secret` matching the `CRON_SECRET` env var or endpoint returns 401.

---

## FILES STRUCTURE (backend)

```
backend/
├── app/
│   ├── main.py              FastAPI app, CORS, startup checks, route registration
│   ├── database.py          SQLAlchemy engine + session setup
│   ├── models.py            All SQLAlchemy ORM models
│   ├── config.py            Environment variable loading
│   ├── routers/
│   │   ├── auth.py          Registration, login, OAuth flow
│   │   ├── pages.py         Page connect/disconnect/recover
│   │   ├── posts.py         Post CRUD + scheduler job
│   │   ├── ai.py            Text generation, prompt studio
│   │   ├── images.py        Image generation, media library
│   │   ├── personas.py      Persona CRUD
│   │   ├── analytics.py     Engagement data endpoints
│   │   ├── models_settings.py  AI model selector
│   │   └── tracker.py       Page tracker
│   └── providers/
│       ├── llm_providers.py     Multi-LLM routing function
│       └── image_providers.py   Multi-image-provider classes
├── migrations/
│   └── add_image_generation_tables.sql
├── requirements.txt
└── .env
```

---

## IMPORTANT RULES — DO NOT BREAK THESE

1. Never delete a `page_connections` row — only update status
2. All foreign keys to page_connections use `ON DELETE SET NULL` not CASCADE
3. Tokens are always encrypted before database storage
4. Tokens never appear in any API response to frontend
5. Scheduler endpoint always validates X-Cron-Secret before running
6. All scheduled times stored as UTC in database, converted to user timezone only for display
7. Image URLs served from Supabase Storage must be publicly accessible for Facebook to fetch them
8. Persona performance score must stay between 0.1 and 1.0
9. Retry failed posts max 3 times with 5-minute gaps, then permanently_failed
10. Posts missed by more than 12 hours → mark missed, never publish late

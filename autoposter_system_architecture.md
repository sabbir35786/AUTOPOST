# AutoPoster System Architecture
### Comprehensive Technical Documentation
**Version:** 2.0 | **Last Updated:** June 2026

---

## Table of Contents

1. [System Overview & Tech Stack](#1-system-overview--tech-stack)
2. [Global Model Configuration](#2-global-model-configuration)
3. [Prompt Studio & Persona Logic](#3-prompt-studio--persona-logic)
4. [Photocard Generation & Asset Management System](#4-photocard-generation--asset-management-system)
5. [Scheduling System Architecture](#5-scheduling-system-architecture)
6. [API Route Reference](#6-api-route-reference)
7. [Database Schema Reference](#7-database-schema-reference)
8. [Core Technical Rules & Guardrails](#8-core-technical-rules--guardrails)
9. [Frontend Architecture](#9-frontend-architecture)
10. [Deployment & Infrastructure](#10-deployment--infrastructure)

---

## 1. System Overview & Tech Stack

### 1.1 What AutoPoster Does

AutoPoster is a social media automation platform that allows users to create AI-powered personas, each connected to a Facebook page. Each persona has its own writing style, language, tone, posting schedule, and image template. The system automatically generates post text and photocards using LLM APIs and publishes them to Facebook at scheduled times — fully autonomously.

### 1.2 Core Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FRONTEND (React)                     │
│  Prompt Studio │ Templates │ Dashboard │ Schedule        │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────────┐
│                BACKEND (Python / FastAPI)                 │
│  Routers │ Services │ APScheduler │ PIL Assembly Engine  │
└──────┬──────────────┬──────────────────┬────────────────┘
       │              │                  │
┌──────▼──────┐ ┌─────▼──────┐ ┌────────▼────────┐
│  PostgreSQL  │ │  Supabase  │ │   LLM APIs      │
│  (Supabase)  │ │  Storage   │ │  OpenAI/Gemini  │
│              │ │  (Files)   │ │  Anthropic      │
└─────────────┘ └────────────┘ └─────────────────┘
```

### 1.3 Tech Stack

#### Backend
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.11 | Core application language |
| Framework | FastAPI | Async REST API framework |
| ORM | SQLAlchemy | Database interaction |
| Scheduler | APScheduler 3.10.4 (AsyncIOScheduler) | Automated post scheduling |
| Image Assembly | PIL/Pillow | Photocard layer compositing |
| Text Rendering | PangoCairo + PyGObject < 3.52.0 | Complex script text (Bengali, Arabic) |
| Auth | JWT (python-jose) | Stateless authentication |
| Password Hashing | bcrypt | Secure password storage |
| WSGI Server | Uvicorn | ASGI production server |

#### Database & Storage
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Primary Database | PostgreSQL (via Supabase) | All persistent data |
| File Storage | Supabase Storage | Images, fonts, logos, photocards |
| Connection Pooling | SQLAlchemy pool_pre_ping=True, pool_recycle=1800 | Stale connection prevention |

#### Frontend
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | React (Vite) | UI rendering |
| State Management | React Context (global store) | Session-wide data caching |
| HTTP Client | Axios / Fetch with Bearer token | API communication |
| Auth Storage | localStorage | JWT token persistence |

#### Infrastructure
| Component | Service | Purpose |
|-----------|---------|---------|
| Hosting | Render (Free Plan) | Backend deployment |
| Keep-alive | UptimeRobot (5-min ping) | Prevent Render sleep |
| Font CDN | Google Fonts (committed to repo) | Bundled .ttf files |

### 1.4 Environment Variables

```
# Core
DATABASE_URL              PostgreSQL connection string (Supabase)
SECRET_KEY                Permanent JWT signing key (never regenerate)
FRONTEND_URL              Live frontend URL for CORS

# Facebook OAuth
FACEBOOK_APP_ID
FACEBOOK_APP_SECRET
FACEBOOK_REDIRECT_URI
FACEBOOK_TOKEN_ENCRYPTION_KEY
FACEBOOK_OAUTH_SCOPES

# LLM Providers
OPENAI_API_KEY
GEMINI_API_KEY
ANTHROPIC_API_KEY (optional)
STABILITY_API_KEY (optional)
MISTRAL_API_KEY (optional)

# Storage
SUPABASE_URL
SUPABASE_SERVICE_KEY

# Internal
CRON_SECRET               Secret header for internal cron routes
APP_BASE_URL              Full Render app URL
```

---

## 2. Global Model Configuration

### 2.1 Overview

Every LLM and image generation API call in the system is routed dynamically based on per-user model settings stored in the `user_settings` table. There are no hardcoded model strings anywhere in the generation code.

### 2.2 Database Columns (user_settings)

```sql
post_generation_provider    TEXT  DEFAULT 'openai'
post_generation_model       TEXT  DEFAULT 'gpt-4o'
image_generation_provider   TEXT  DEFAULT 'gemini'
image_generation_model      TEXT  DEFAULT 'imagen-3.0-generate-001'
timezone                    TEXT  DEFAULT 'Asia/Dhaka'
```

### 2.3 Allowed Provider/Model Combinations

#### Post Generation
| Provider | Allowed Models |
|----------|---------------|
| openai | gpt-4o, gpt-4o-mini, gpt-4-turbo |
| gemini | gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash |
| anthropic | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5 |

#### Image Generation
| Provider | Allowed Models |
|----------|---------------|
| gemini | imagen-3.0-generate-001, imagen-2.0 |
| openai | dall-e-3, dall-e-2 |
| stability | stable-diffusion-3, stable-diffusion-xl |

### 2.4 Routing Logic

```python
def get_post_generation_client(user_settings):
    provider = user_settings.post_generation_provider
    model = user_settings.post_generation_model

    if provider == "openai":
        return OpenAIClient(model=model)
    elif provider == "gemini":
        return GeminiClient(model=model)
    elif provider == "anthropic":
        return AnthropicClient(model=model)
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

All three provider branches receive the same system prompt and user message. Only the SDK client and model string differ between providers.

### 2.5 API Key Validation

If a user selects a provider whose API key is not configured, the system returns:
```
"API key for [provider] is not configured. Please add it in Settings."
```

---

## 3. Prompt Studio & Persona Logic

### 3.1 Persona Data Model

Each persona represents a social media page identity. Key fields:

```sql
personas
  id              UUID PK
  user_id         UUID FK
  name            TEXT
  niche           TEXT        -- Page topic (e.g. "AI Technology")
  language        TEXT        -- Output language (e.g. "Bengali", "English")
  tone_tags       JSONB       -- ["Professional", "Educational"]
  custom_instructions TEXT
  created_at      TIMESTAMPTZ
```

### 3.2 Style Analyzer

The Style Analyzer lets users paste a reference post to automatically extract a writing style for a persona.

**Critical Rule:** The reference post text is used only during the analysis LLM call. It is **never** saved to any database field, prompt template, or assembled_prompt. Only the extracted characteristics — tone description, writing patterns, niche — are saved.

### 3.3 Prompt Template Assembly

The `prompt_templates` table stores the assembled instruction set for each persona:

```sql
prompt_templates
  id                UUID PK
  persona_id        UUID FK UNIQUE
  question_answers  JSONB    -- Gap-fill Q&A pairs
  custom_instructions TEXT   -- Free-text user instructions
  assembled_prompt  TEXT     -- Final compiled prompt
  updated_at        TIMESTAMPTZ
```

**Assembly Logic (code-driven, not LLM-driven):**

```
assembled_prompt = ""

For each question-answer pair in question_answers:
  assembled_prompt += "Write posts that [question implies]: [answer]\n"

If custom_instructions exists:
  assembled_prompt += "\nAdditional instructions:\n" + custom_instructions
```

### 3.4 LLM System Prompt Construction

When generating a post, the final system prompt sent to the LLM is built as follows:

```
[assembled_prompt from prompt_templates]

Persona niche: [persona.niche]
Tone: [persona.tone_tags joined as comma list]
The tone of every post must be [tone]. Stay consistent. Do not drift toward a neutral style.
This page is about [niche]. Every post must be relevant to this niche.

You must write this post entirely in [language].
The post content, hashtags, and any call to action must all be in [language].
Do not use any other language.
```

**The language instruction is always the last line of the system prompt** to give it highest priority with the LLM.

### 3.5 Debug Endpoint

`GET /api/internal/debug-prompt/{persona_id}` (protected by X-Cron-Secret header)

Returns the full assembled system prompt that would be sent to the LLM for that persona, without calling the LLM. Used for verification and debugging.

---

## 4. Photocard Generation & Asset Management System

### 4.1 System Overview

The photocard system is a **local assembly engine**. No external image generation API is used. All visual elements come from an internal asset library. Only text content is generated by LLM. PIL/Pillow assembles everything locally.

```
Post Content (LLM-generated)
        │
        ▼
LLM picks styling from template options
  (background, fonts, colors, overlay texts)
        │
        ▼
PIL Assembly (zero network calls):
  Background layer (from asset library)
  → Overlay layer (semi-transparent)
  → Text layers (PangoCairo renders Bengali/Arabic)
  → Logo layer (from persona settings)
        │
        ▼
Final PNG uploaded to Supabase Storage
```

### 4.2 Asset Tables

#### background_assets
```sql
id          UUID PK
user_id     UUID nullable  -- null = built-in asset
name        TEXT
type        TEXT           -- solid_color | gradient | pattern | custom_upload
config      JSONB          -- visual definition (see below)
preview_url TEXT           -- 200x200 preview in Supabase Storage
is_builtin  BOOLEAN
```

**Config formats:**
```json
// solid_color
{ "color_hex": "#1a1a2e" }

// gradient
{ "color1": "#1a1a2e", "color2": "#e94560", "direction": "vertical" }
// direction: vertical | horizontal | diagonal

// pattern
{ "pattern_name": "dots", "color_hex": "#1a1a2e", "accent_hex": "#ffffff" }
// pattern_name: dots | lines | grid | noise

// custom_upload
{ "file_url": "https://supabase.storage.url/..." }
```

#### font_assets
```sql
id            UUID PK
user_id       UUID nullable  -- null = bundled font
name          TEXT           -- "Poppins Bold"
font_file_url TEXT           -- Supabase Storage URL or local path
is_bundled    BOOLEAN
```

**Bundled Fonts (committed to assets/fonts/):**
- Poppins-Regular.ttf, Poppins-Bold.ttf, Poppins-SemiBold.ttf
- Roboto-Regular.ttf, Roboto-Bold.ttf
- Montserrat-Regular.ttf, Montserrat-Bold.ttf
- PlayfairDisplay-Regular.ttf, PlayfairDisplay-Bold.ttf
- NotoSansBengali-Regular.ttf, NotoSansBengali-Bold.ttf
- NotoSans-Regular.ttf, NotoSans-Bold.ttf
- NotoSansArabic-Regular.ttf, NotoSansArabic-Bold.ttf

#### image_templates
```sql
id               UUID PK
user_id          UUID FK
name             TEXT
reference_image_url TEXT nullable
canvas_width     INT
canvas_height    INT
aspect_ratio     TEXT    -- "1:1" | "4:5" | "9:16" | "16:9"
template_json    JSONB   -- full layout definition
creation_method  TEXT    -- "manual" | "extracted"
created_at       TIMESTAMPTZ
```

#### persona_image_settings
```sql
persona_id          UUID PK FK
logo_url            TEXT nullable
image_template_id   UUID FK nullable
updated_at          TIMESTAMPTZ
```

#### post_image_generations
```sql
id              UUID PK
post_id         UUID FK UNIQUE
template_id     UUID FK
overlay_texts   JSONB    -- [{"role": "headline", "text": "..."}]
llm_instructions JSONB   -- full LLM decision set
background_image_url TEXT nullable
logo_url        TEXT nullable
final_image_url TEXT
status          TEXT     -- pending|generating_text|assembling|completed|failed
error_message   TEXT nullable
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
```

### 4.3 Template JSON Structure

```json
{
  "canvas_width": 1080,
  "canvas_height": 1080,
  "aspect_ratio": "1:1",
  "background_options": [
    { "asset_id": "uuid", "label": "Dark Navy" },
    { "asset_id": "uuid", "label": "Deep Purple" }
  ],
  "layers": [
    {
      "id": "layer_1",
      "type": "overlay",
      "z_index": 0,
      "position_x_percent": 0,
      "position_y_percent": 0,
      "width_percent": 100,
      "height_percent": 100,
      "color_options": [
        { "color_hex": "#000000", "opacity": 0.4, "label": "Dark" }
      ]
    },
    {
      "id": "layer_2",
      "type": "text",
      "role": "headline",
      "z_index": 1,
      "position_x_percent": 10.0,
      "position_y_percent": 38.0,
      "width_percent": 80.0,
      "height_percent": 20.0,
      "font_options": [
        { "font_asset_id": "uuid", "label": "Poppins Bold" }
      ],
      "color_options": [
        { "color_hex": "#ffffff", "label": "White" },
        { "color_hex": "#FFD700", "label": "Gold" }
      ],
      "font_size_min_percent": 4.0,
      "font_size_max_percent": 7.0,
      "text_align_options": ["center", "left"],
      "font_weight": "bold"
    },
    {
      "id": "layer_3",
      "type": "logo",
      "z_index": 2,
      "position_x_percent": 78.0,
      "position_y_percent": 4.0,
      "width_percent": 18.0,
      "height_percent": 12.0
    }
  ]
}
```

**Layer types:** `background_image` | `text` | `logo` | `overlay`
**Text roles:** `headline` | `subheadline` | `body`

### 4.4 Template Creation Workflows

#### Workflow A — AI Style Extraction

1. User uploads a reference image with a name
2. Image uploaded to Supabase Storage at `image-templates/{user_id}/{uuid}.png`
3. Image sent to Gemini Vision (`gemini-1.5-pro`) with structured analysis prompt
4. Gemini returns raw JSON describing canvas size, background, and all layers
5. **JSON Cleaning (mandatory):** Strip markdown fences, extract between ``` markers, call `json.loads()`. If parsing fails, send back to Gemini asking for corrected JSON. If still fails, return HTTP 422.
6. Background is matched to nearest built-in asset by hex color distance calculation
7. Text layers auto-assigned Poppins fonts as default
8. Template saved with `creation_method: "extracted"`

#### Workflow B — Manual Template Builder (Four Modes)

All four modes produce the same template JSON. They are tabs on the same page sharing a single `templateState` object.

**Tab 1 — Visual Builder (Drag and Drop)**
- React component using native mouse/touch events (no external DnD library)
- `<div>` based canvas (not HTML5 canvas) for DOM-level layer control
- Interactions: drag to reposition, resize via 8 handles, rotate via rotation handle, snap to grid (5% increments), multi-select with Shift+click
- Left panel: layer list with z_index reordering
- Right panel: live property editor synced with canvas
- Background selector: horizontal scroll row, Ctrl+click for multi-select

**Tab 2 — Option Builder (Form Selection)**
- Single-page scrollable form
- Live 200x200 mini-preview with 500ms debounce calling the preview endpoint
- Same fields as Visual Builder right panel

**Tab 3 — JSON Editor**
- Sub-options: Paste JSON or Upload .json file
- Monospace editor with syntax highlighting
- Validate button: checks schema, verifies all asset_id references exist, checks percent ranges
- Auto-validation on paste with 300ms debounce
- Download JSON button

**Tab 4 — Describe It (LLM Generation)**
- User writes plain text description of desired template
- Optional: select background assets to constrain LLM choices
- Backend route `POST /api/image-templates/generate-from-description` sends description + available asset IDs + all font asset IDs to LLM
- LLM returns raw template JSON
- Result shown in JSON Editor tab for review before saving

**Tab Sync Rule:** All tabs read from and write to `templateState`. Switching tabs never loses unsaved work. Invalid JSON in JSON Editor triggers warning before tab switch.

### 4.5 LLM Image Instruction Generation

When generating a photocard, the post content is sent to the LLM with the full template option list. The LLM picks one choice from each option. The prompt is built dynamically by reading the actual template JSON:

```
System: You are a creative director for social media photocards.
Return ONLY raw JSON. No explanation. No markdown.

POST CONTENT: [post_content]
TONE: [tone_tags]
NICHE: [niche]
LANGUAGE: [language]

AVAILABLE BACKGROUNDS:
- asset_id: X | label: Dark Navy
- asset_id: Y | label: Deep Purple

TEXT LAYER layer_2 — role: headline
  Choose font from: [font_options list]
  Choose color from: [color_options list]
  Choose font_size_percent between 4.0 and 7.0
  Choose text_align from: center, left
  Generate text (max 6 words) in [language]

OVERLAY LAYER layer_1
  Choose from: [color_options with opacity]

Return JSON:
{
  "chosen_background_asset_id": "...",
  "layers": [
    {"layer_id": "layer_2", "text": "...", "font_asset_id": "...",
     "color_hex": "...", "font_size_percent": 5.5, "text_align": "center"},
    {"layer_id": "layer_1", "color_hex": "#000000", "opacity": 0.4}
  ]
}
```

**Validation after parsing:** Every returned value is validated against the template's allowed options. Any value outside the allowed list is silently replaced with the first allowed option. Every fallback is logged.

**Critical separation:**
- LLM decides: background choice, text content, font, color, font size, text align, overlay opacity
- Template always decides: position, size, z_index, layer structure

### 4.6 PIL Assembly Pipeline

Assembly runs entirely locally with zero network calls.

```python
# Step 1: Create canvas
canvas = PIL.Image.new("RGBA", (canvas_width, canvas_height))

# Step 2: Sort layers by z_index

# Step 3: For each layer:

# BACKGROUND (solid_color)
canvas = PIL.Image filled with hex_to_rgb(color_hex)

# BACKGROUND (gradient)
# Draw linear gradient using numpy or PIL pixel manipulation

# BACKGROUND (pattern)
# Draw dots/lines/grid/noise using PIL ImageDraw

# BACKGROUND (custom_upload)
# Download from Supabase, resize to canvas, paste

# OVERLAY
overlay_img = PIL.Image.new("RGBA", layer_pixel_size, hex_to_rgb(color_hex))
overlay_img.putalpha(int(opacity * 255))
canvas.paste(overlay_img, (x_px, y_px), mask=overlay_img)

# TEXT (uses PangoCairo for complex scripts)
text_img = render_text_layer_pango(
    text, font_path, font_size_px, color_hex,
    layer_width_px, layer_height_px, text_align, font_weight
)
canvas.paste(text_img, (x_px, y_px), mask=text_img)

# LOGO
logo = PIL.Image.open(logo_bytes).convert("RGBA")
logo = resize_maintain_aspect(logo, layer_width_px, layer_height_px)
canvas.paste(logo, (x_px, y_px), mask=logo)

# Step 4: Convert to RGB, save to BytesIO, upload to Supabase
```

### 4.7 Bengali / Complex Script Text Rendering

PIL cannot shape complex scripts. All text rendering uses PangoCairo:

```python
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo
import cairo

def render_text_layer_pango(text, font_path, font_size_px, ...):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(surface)
    layout = PangoCairo.create_layout(ctx)
    layout.set_width(w * Pango.SCALE)
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    # ... font, color, alignment setup
    PangoCairo.show_layout(ctx, layout)
    # Convert Cairo surface → PIL RGBA Image
```

**Script detection:** Unicode codepoint ranges identify Bengali (0x0980–0x09FF), Arabic (0x0600–0x06FF), Devanagari (0x0900–0x097F). Correct font is automatically selected based on detected script.

**Fallback:** If PangoCairo is unavailable, PIL basic text rendering is used with a warning log. `PANGO_AVAILABLE` flag controls which renderer is used.

**PyGObject version pinning:** Must use `PyGObject<3.52.0` to ensure compatibility with `girepository-1.0` (not girepository-2.0 which is unavailable on Debian 12).

### 4.8 Supabase Storage Buckets

| Bucket | Path Pattern | Contents |
|--------|-------------|----------|
| generated-images | `post-images/{post_id}/final.png` | Final photocards |
| image-templates | `image-templates/{user_id}/{uuid}.png` | Reference images |
| image-templates | `template-tests/{template_id}/preview.png` | Test previews (overwritten) |
| assets | `assets/backgrounds/custom/{user_id}/{uuid}.png` | Custom backgrounds |
| assets | `assets/backgrounds/previews/{asset_id}.png` | 200x200 previews |
| assets | `assets/fonts/custom/{user_id}/{uuid}.ttf` | Custom fonts |
| persona-logos | `persona-logos/{persona_id}/logo.png` | Persona logos |

---

## 5. Scheduling System Architecture

### 5.1 Overview

Scheduling uses APScheduler (AsyncIOScheduler) running inside FastAPI. UptimeRobot keeps Render awake. No external job queue is needed.

```
UptimeRobot → pings /health every 5 min → Render stays awake
APScheduler → Job 1: every 1 min → checks scheduled_slots
             → Job 2: every midnight UTC → registers today's slots
```

### 5.2 Schedule Data Model

#### persona_schedules
```sql
id              UUID PK
persona_id      UUID FK UNIQUE
timezone        TEXT DEFAULT 'Asia/Dhaka'
active_days     JSONB   -- ["monday", "wednesday", "friday"]
default_times   JSONB   -- ["09:00", "18:00"]
day_overrides   JSONB   -- {"monday": ["08:00", "12:00"], "saturday": ["10:00"]}
is_active       BOOLEAN DEFAULT true
```

#### scheduled_slots
```sql
id              UUID PK
persona_id      UUID FK (ON DELETE CASCADE)
scheduled_at    TIMESTAMPTZ   -- UTC
status          TEXT          -- pending|generating|published|failed|cancelled
post_id         UUID FK nullable
error_message   TEXT nullable
retry_count     INT DEFAULT 0
```

**Indexes:**
```sql
CREATE INDEX idx_scheduled_slots_status_time ON scheduled_slots(status, scheduled_at);
CREATE INDEX idx_posts_status_published ON posts(status, published_at);
```

### 5.3 Time Resolution Logic

For any given day, the system resolves posting times as follows:

```
1. Is today in active_days? → No: skip entirely
2. Does today have a day_override? → Yes: use override times
3. No override? → Use default_times
4. Filter to only future times (slot_local > now)
5. Convert all times from persona timezone to UTC
6. Save one scheduled_slot row per resolved time
```

### 5.4 APScheduler Jobs

**Job 1 — Minute Checker** (every 1 minute, max_instances=1)
```python
async def job_check_due_slots():
    due_slots = db.query(ScheduledSlot).filter(
        ScheduledSlot.scheduled_at <= datetime.utcnow(),
        ScheduledSlot.status == 'pending'
    ).order_by(ScheduledSlot.scheduled_at.asc()).all()

    for slot in due_slots:
        await run_full_publish_flow(slot.persona_id, slot, db)
```

**Job 2 — Midnight Registration** (daily at 00:00 UTC, max_instances=1)
```python
async def job_midnight_registration():
    # Registers today's slots for all active personas
    await register_all_todays_slots(db)
```

**Startup Registration:** On every app startup, `register_all_todays_slots()` is called in a background task to recover any slots that were not registered due to downtime.

### 5.5 The Single Shared Publish Flow

There is **one** function `run_full_publish_flow(persona_id, slot, db)` used by all three entry points:

| Entry Point | Calls |
|-------------|-------|
| APScheduler minute job | `run_full_publish_flow()` |
| Test Full Flow button | `run_full_publish_flow()` |
| Publish to Facebook button in popup | `publish_to_facebook_direct()` (skips generation, uses existing result) |

```
run_full_publish_flow():
  1. Generate post text (LLM via user's configured provider)
  2. Load persona image settings
  3. If image template assigned → generate photocard
     a. Call LLM for overlay text decisions
     b. Run PIL assembly locally
     c. Upload to Supabase Storage
  4. If image generation fails → continue with text only (non-blocking)
  5. Publish to Facebook (text + image if available)
  6. Save post to DB with status: published
  7. Update slot status to published
  8. Log every step
```

### 5.6 Schedule Management Rules

- When schedule is saved → immediately register today's remaining slots
- When schedule is deleted → delete all pending slots (or via CASCADE on persona delete)
- When persona is deleted → all slots auto-deleted via ON DELETE CASCADE
- Multiple personas posting at same time → fully independent, no conflict
- Multiple slots per persona per day → fully supported, each is a separate slot row
- Retry failed slot → reset status to pending, minute checker picks up within 60 seconds

---

## 6. API Route Reference

### Authentication
| Method | Route | Description |
|--------|-------|-------------|
| POST | /auth/login | Login, returns JWT token |
| POST | /auth/register | Register new user |
| GET | /users/me | Get current user profile |

### Health
| Method | Route | Description |
|--------|-------|-------------|
| GET/HEAD | /health | Health check (UptimeRobot target) |
| GET/HEAD | / | Root endpoint |

### Settings
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/settings/models | Get current model preferences |
| PUT | /api/settings/models | Update model preferences |

### Facebook
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/pages | List connected Facebook pages |
| GET | /api/auth/facebook | Start Facebook OAuth flow |
| GET | /api/auth/facebook/callback | OAuth callback |

### Personas
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/personas | List all personas |
| POST | /api/personas | Create persona |
| GET | /api/personas/{id} | Get persona detail |
| PUT | /api/personas/{id} | Update persona |
| DELETE | /api/personas/{id} | Delete persona (cascades slots) |
| POST | /api/personas/{id}/schedule | Save/update schedule |
| GET | /api/personas/{id}/schedule | Get schedule |
| DELETE | /api/personas/{id}/schedule | Delete schedule |
| GET | /api/personas/{id}/image-settings | Get image settings |
| PUT | /api/personas/{id}/image-settings | Update logo / assign template |
| GET | /api/personas/{id}/image-template | Get assigned template |
| POST | /api/personas/{id}/assign-image-template | Assign template |
| DELETE | /api/personas/{id}/assign-image-template | Remove assignment |

### Prompt Studio
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/personas/{id}/prompt-template | Get assembled prompt |
| POST | /api/personas/{id}/prompt-template | Save prompt template |
| POST | /api/personas/{id}/generate-post | Generate post text |
| POST | /api/personas/{id}/test-full-flow | Run Test Full Flow |
| POST | /api/personas/{id}/publish-now | Publish generated result to Facebook |
| POST | /api/personas/{id}/style-analyze | Analyze reference post style |

### Posts
| Method | Route | Description |
|--------|-------|-------------|
| GET | /posts | List posts (limit 50) |
| GET | /posts/{id} | Get post detail |
| GET | /posts/{id}/image-status | Poll image generation status |
| POST | /posts/{id}/generate-image | Trigger image generation |
| PATCH | /posts/{id}/image | Light edit (text overrides, re-assemble) |
| DELETE | /posts/{id} | Delete post |

### Asset Library
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/assets/backgrounds | List all backgrounds (built-in + user) |
| POST | /api/assets/backgrounds/upload | Upload custom background |
| DELETE | /api/assets/backgrounds/{id} | Delete custom background |
| GET | /api/assets/fonts | List all fonts (bundled + user) |
| POST | /api/assets/fonts/upload | Upload custom font |
| DELETE | /api/assets/fonts/{id} | Delete custom font |

### Image Templates
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/image-templates | List all templates |
| GET | /api/image-templates/{id} | Get full template with JSON |
| POST | /api/image-templates/manual | Create template manually |
| POST | /api/image-templates/analyze | Create from reference image (AI extraction) |
| POST | /api/image-templates/generate-from-description | Create from plain text description |
| POST | /api/image-templates/preview | Render preview PNG (not saved) |
| PUT | /api/image-templates/{id} | Update template |
| DELETE | /api/image-templates/{id} | Delete template |
| POST | /api/image-templates/{id}/test | Test template with sample text |

### Dashboard
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/dashboard | Today's slots + last 10 published posts |

### Scheduled Slots
| Method | Route | Description |
|--------|-------|-------------|
| POST | /api/scheduled-slots/{id}/retry | Retry failed slot |

### Internal (protected by X-Cron-Secret header)
| Method | Route | Description |
|--------|-------|-------------|
| GET | /api/internal/debug-prompt/{persona_id} | View assembled prompt |
| GET | /api/internal/debug-template/{template_id} | View template JSON |

---

## 7. Database Schema Reference

### Complete Table List

```sql
-- User management
users
user_settings

-- Facebook
facebook_connections        -- OAuth tokens (encrypted)
facebook_pages             -- Connected pages per user

-- Personas & prompts
personas
prompt_templates
persona_schedules

-- Scheduling
scheduled_slots

-- Posts
posts

-- Asset library
background_assets
font_assets

-- Image templates & generation
image_templates
persona_image_settings
post_image_generations
```

### posts (key columns)
```sql
id                  UUID PK
persona_id          UUID FK
content             TEXT
image_url           TEXT
status              TEXT    -- draft|scheduled|published|failed
published_at        TIMESTAMPTZ
facebook_post_id    TEXT
facebook_post_url   TEXT
publish_error       TEXT
created_at          TIMESTAMPTZ
```

---

## 8. Core Technical Rules & Guardrails

### 8.1 PIL Assembly Rules

- **Zero network calls during assembly.** All assets (fonts, backgrounds, logos) must be downloaded before the PIL draw loop begins. The draw loop is pure in-memory Python.
- **Script detection is mandatory.** Always detect the script of overlay text before selecting a font. Never use a Latin font for Bengali or Arabic text.
- **PangoCairo for text, PIL for everything else.** PangoCairo handles all text rendering. PIL handles background, overlay, logo compositing.
- **Hex color conversion.** Never pass hex strings directly to PIL. Always convert with `hex_to_rgb()` first.
- **Rotation support.** If a layer has `rotation_degrees`, apply `PIL.Image.rotate()` before pasting.

### 8.2 LLM Usage Rules

- **assembled_prompt is mandatory.** The assembled_prompt from prompt_templates must always be included in the LLM system prompt. If missing, fall back to persona niche + tone + language fields and log a warning.
- **Language instruction is always last.** The language enforcement instruction is the last line of every system prompt.
- **LLM never decides layout.** Layer positions, sizes, and z_index come from the template JSON only. LLM decides only content and styling choices within defined options.
- **Validate LLM JSON responses.** All LLM responses expected to be JSON must be cleaned (strip markdown fences) and validated. Never trust raw LLM JSON output without cleaning.
- **Reference posts never saved.** Style analyzer reference posts are used only for the analysis LLM call. They are never persisted.

### 8.3 Storage Rules

- **All files go to Supabase Storage.** Never write to local disk in production. Render's filesystem is ephemeral and wiped on every restart.
- **Paths follow defined patterns.** All Supabase paths follow the bucket/pattern table in Section 4.8.
- **Template test previews overwrite.** The test preview path `template-tests/{template_id}/preview.png` is overwritten each test run. Only one test preview per template is kept.

### 8.4 Authentication Rules

- **SECRET_KEY must be permanent.** Never generate a random SECRET_KEY at startup. If SECRET_KEY is not set as an environment variable, throw a ValueError and refuse to start.
- **Token stored in localStorage.** JWT tokens must be stored in browser localStorage to survive page refreshes and tab switches.
- **Token expiry: 7 days minimum.** Short-lived tokens cause unnecessary logouts.
- **Bearer token on every request.** The frontend API client must attach `Authorization: Bearer {token}` on every API request.
- **API base URL from environment.** Never hardcode `localhost:8000` in frontend production builds. Use `VITE_API_URL` environment variable.

### 8.5 Scheduling Rules

- **Generate at publish time only.** Post content is never pre-generated. It is always created fresh at the moment of publishing.
- **QStash holds today only.** Only today's slots are ever registered. The midnight job rolls the schedule forward each day.
- **Image failure never blocks publishing.** If photocard generation fails, publish text-only to Facebook and log the image error.
- **ON DELETE CASCADE on slots.** Deleting a persona automatically deletes all its scheduled slots.
- **UTC everywhere.** All datetimes stored in the database are UTC. Timezone conversion happens only at display time on the frontend.
- **max_instances=1 on all scheduler jobs.** Never run two instances of the same job simultaneously.
- **Re-register on startup.** App startup always re-registers today's remaining slots to recover from restarts.

### 8.6 Database Rules

- **pool_pre_ping=True.** Always test connections before use to automatically replace stale connections.
- **pool_recycle=1800.** Recycle connections every 30 minutes to prevent overnight stale connections.
- **No DROP TABLE in migrations.** Migrations only add columns or tables. Never drop existing data.
- **Migrations run once.** Each migration is guarded so it only runs if it has not already been applied.
- **All list queries have limits.** Never fetch unlimited rows. Dashboard queries are limited to 10. Post list queries are limited to 50.

### 8.7 Error Handling Rules

- **Silent failures are forbidden.** Every exception must be caught, logged with context, and saved to the relevant database field (e.g., `publish_error`, `error_message`).
- **Slot status always updated.** Even on failure, the slot status must be updated so the dashboard reflects accurate information.
- **Frontend shows user-friendly errors.** Never show technical error messages (port numbers, stack traces) to users. Show actionable messages with retry options.

---

## 9. Frontend Architecture

### 9.1 Global State Store

All fetched data lives in a single global store initialized after login:

```javascript
store = {
  user: null,
  personas: [],
  pages: [],
  dashboard: { todays_slots: [], recent_posts: [] },
  posts: [],
  settings: null,
  templates: []
}
```

**Initial load (parallel):**
```javascript
const [user, personas, pages, dashboard, posts] = await Promise.all([
  api.get('/users/me'),
  api.get('/api/personas'),
  api.get('/api/pages'),
  api.get('/api/dashboard'),
  api.get('/posts?limit=50')
])
```

**Selective refresh:** Only the affected slice is refreshed after user actions. Dashboard auto-refreshes every 30 seconds silently.

### 9.2 Tab Navigation Rules

- Tab switches read from the global store — no API calls
- Loading spinners only appear on first app load after login
- Returning to a previously visited tab shows cached content instantly
- Background silent refresh updates content without blocking UI

### 9.3 Frontend Routing

The backend serves `index.html` for all non-API, non-auth routes. This enables frontend routing to work correctly on browser refresh.

```python
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("auth/"):
        raise HTTPException(status_code=404)
    return FileResponse("static/index.html")
```

### 9.4 API Client Configuration

```javascript
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "https://autopost-1-ax2p.onrender.com",
  timeout: 10000
})

api.interceptors.request.use(config => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-retry once on network error
api.interceptors.response.use(null, async error => {
  if (!error.response && !error.config._retry) {
    error.config._retry = true
    await new Promise(r => setTimeout(r, 2000))
    return api(error.config)
  }
  return Promise.reject(error)
})
```

---

## 10. Deployment & Infrastructure

### 10.1 Render Configuration

- **Plan:** Free (with UptimeRobot keep-alive)
- **WEB_CONCURRENCY:** 1 (auto-set by Render based on available CPUs)
- **Port:** 10000
- **Build:** Docker-based via Dockerfile

### 10.2 Dockerfile Key Requirements

```dockerfile
# System packages (must come before pip installs)
RUN apt-get update && apt-get install -y \
    python3-gi python3-gi-cairo python3-cairo \
    gir1.2-pango-1.0 libpango1.0-dev libcairo2-dev \
    libgirepository1.0-dev gobject-introspection \
    pkg-config fonts-noto fonts-noto-core \
    libmagickwand-dev imagemagick \
    && rm -rf /var/lib/apt/lists/*

# PyGObject MUST be pinned below 3.52.0
RUN pip install --no-cache-dir "PyGObject<3.52.0" pycairo

# Verify Pango works at build time
RUN python3 -c "import gi; gi.require_version('Pango', '1.0'); \
    from gi.repository import Pango; print('Pango OK')"
```

### 10.3 UptimeRobot Configuration

- **Monitor Type:** HTTP(s)
- **URL:** `https://autopost-1-ax2p.onrender.com/health`
- **Interval:** 5 minutes
- **Purpose:** Prevent Render free plan sleep only — not for scheduling

### 10.4 Startup Sequence

```
1. FastAPI app created, routers registered
2. Database connection verified (ping only)
3. Server starts accepting requests immediately
4. Background task begins:
   a. Font registration with fontconfig
   b. Pango Bengali rendering verification
   c. Supabase bucket verification
   d. APScheduler started (2 jobs registered)
   e. Today's slots registered for all active personas
5. Background Init Complete logged
```

**Target:** Server ready to accept requests within 3 seconds of process start. Full background initialization completes within 90 seconds.

### 10.5 Monitoring Checklist

On every deploy, confirm these log lines appear:
```
✓ Database connected
✓ Routers registered
✓ Server ready at port 10000
[OK] Fonts registered with fontconfig
[OK] Pango Bengali text rendering working correctly
[SCHEDULER] APScheduler started with 3 jobs
[Scheduler] Today's slots registered for N personas
=== Background Init Complete ===
```

Every minute in running logs:
```
[Scheduler] Scheduler minute check running at [timestamp]
```

---

*This document reflects the complete AutoPoster system as designed and built through the full development session. All architectural decisions, guardrails, and implementation details documented here are authoritative and should be treated as the single source of truth for this project.*

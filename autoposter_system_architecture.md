# AutoPoster — System Architecture

> Production-ready technical blueprint for the AutoPoster AI social media content automation platform.

---

## 1. System Overview & Tech Stack

AutoPoster is a social media content automation platform that uses AI to generate, style, schedule, and publish Facebook posts with companion images. The system follows a **frontend-backend monorepo** architecture with a Python async backend and a Next.js SPA frontend.

### Backend

| Layer | Technology | Role |
|---|---|---|
| **Runtime** | Python 3.11+ | Async-first runtime |
| **Web Framework** | FastAPI | REST API, CORS, background tasks, lifespan events |
| **ORM** | SQLAlchemy 2.0 (declarative) | 32 model tables, migration sequencing |
| **Database** | PostgreSQL (Supabase) via `psycopg[binary]` | Transaction pooler at `pooler.supabase.com:6543` |
| **Auth** | JWT (`python-jose`) + bcrypt | OAuth2 password bearer, `get_current_user` dependency |
| **Task Scheduling** | APScheduler 3.10 (AsyncIOScheduler) + Upstash QStash | In-process slot preparation/processing + external webhook triggers |
| **Encryption** | Fernet (cryptography) | Facebook page access tokens at rest |
| **Image Processing** | Pillow (PIL) + PangoCairo / PyCairo | Local compositing with zero network calls |
| **Font Engine** | fontTools | Font family name extraction, script detection |
| **LLM Clients** | `openai`, `anthropic`, `google-generativeai`, `mistralai`, `httpx` (OpenRouter) | Unified text generation dispatcher |
| **Image Gen Clients** | `fal-client`, `stability-sdk`, `openai`, `google-generativeai` | AI image generation dispatcher |
| **Validation** | Pydantic v2 | Request/response schemas |
| **HTTP Client** | httpx (async) | Supabase storage, external API calls |
| **Deployment** | Docker + Render (free tier, Singapore) | Containerized via `backend/Dockerfile` (Python 3.11-slim-bookworm + PangoCairo) |

### Frontend

| Layer | Technology | Role |
|---|---|---|
| **Runtime** | Node.js / TypeScript 5 | Type-safe development |
| **Framework** | Next.js 14 (React 18) | SPA routing, rewrites to backend |
| **Styling** | Tailwind CSS 4 + CSS variables | Utility-first responsive design |
| **UI Library** | shadcn/ui (base-nova) + lucide-react | Pre-built accessible components |
| **State** | React Context (AuthContext, AppContext) | Token management, parallel dashboard loads |
| **HTTP** | Axios + interceptors | JWT injection, error handling, base URL resolution |
| **Fonts** | Geist (Vercel) | System font stack |
| **Notifications** | Sonner | Toast alerts |
| **Deployment** | Vercel | Static + serverless hosting |

### Infrastructure

| Service | Purpose |
|---|---|
| **Render** | Backend Docker host (free tier, Singapore) |
| **Vercel** | Frontend hosting, rewrite proxy `/backend/*` → Render |
| **Supabase PostgreSQL** | Primary database (transaction pooler port 6543) |
| **Supabase Storage** | Asset buckets: `generated-images`, `image-templates` |
| **Upstash QStash** | HTTP-triggered scheduled post delivery |
| **UptimeRobot** | Health check every 5 min at `/health` |

### Key Architectural Decisions

1. **Monolithic backend routes** — ~60+ endpoints defined inline in `app/main.py` (3303 lines); router modules handle specialized domains (images, templates, brand, schedule).
2. **Monolithic frontend SPA** — All dashboard views rendered by a single `social-platform.tsx` (3257 lines) switched via a `view` prop.
3. **Zero network calls during PIL assembly** — All text rendering, layer compositing, and image assembly happens locally using Pillow/PangoCairo. The only outbound calls during generation are fetching background images and logos from Supabase URLs, then uploading the final result.
4. **Non-blocking image generation** — AI image provider calls (Fal.ai, Stability, DALL-E, Gemini) run in background threads via `asyncio.to_thread()` with configurable timeouts.
5. **UTC-only timestamps** — All database timestamps use `DateTime(timezone=True)` with `datetime.now(timezone.utc)`. Timezone conversion happens at the application layer for scheduling and display.

---

## 2. Global Model Configuration

### 2.1 Provider & Model Routing

The system supports **five LLM providers** for text generation and **four image generation providers**, configurable per user at both the global and task-category level.

#### LLM Providers (`backend/app/providers/llm_providers.py`)

| Provider | Module Name | Default Model | API Key Env Var |
|---|---|---|---|
| Mistral | `mistral` | `mistral-small-latest` | `MISTRAL_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini` | `gemini-2.0-flash` | `GEMINI_API_KEY` |
| OpenRouter | `openrouter` | `openrouter/auto` | `OPENROUTER_API_KEY` |

The core dispatcher is `generate_text()` which routes by `provider_name`:
- **Mistral/OpenRouter**: Raw `httpx.post` to their respective `/chat/completions` endpoints.
- **OpenAI**: SDK client with `response_format` support for structured JSON.
- **Anthropic**: SDK client with system prompt as top-level `system` parameter, base64 image support.
- **Gemini**: SDK client with `system_instruction`, PIL image ingestion for vision, and content safety checks (`SAFETY`, `RECITATION` finish reasons).

#### Image Generation Providers (`backend/app/providers/image_providers.py`)

| Provider | Class | Models | Aspect Ratio Support |
|---|---|---|---|
| Fal.ai | `FalProvider` | `FLUX.1-schnell`, `FLUX.1-dev`, `FLUX-pro` | 1:1, 16:9, 4:5 |
| Stability AI | `StabilityProvider` | `stable-diffusion-xl-1024-v1-0`, `sd3-medium` | 1:1, 16:9, 4:5 |
| OpenAI DALL-E | `OpenAIProvider` | `dall-e-3`, `dall-e-2` | 1:1, 16:9, 4:5 |
| Google Gemini | `GeminiProvider` | `imagen-3.0-generate-002` | 1:1, 16:9, 4:5, 3:4, 9:16 |

Each provider implements a standard `generate(prompt, negative_prompt, aspect_ratio, model_name, api_key) -> bytes` interface. Aspect ratio is mapped internally (e.g., Fal.ai uses named sizes like `square_hd`, Stability uses pixel dimensions, DALL-E 3 uses `WxH` strings).

### 2.2 User Preference Resolution

Two parallel systems manage user model preferences:

#### A. `user_settings` table (legacy + new global settings)

Single-row per user with these columns:
- `post_generation_provider` / `post_generation_model` — Controls which provider/model handles post text generation.
- `image_generation_provider` / `image_generation_model` — Controls which provider/model handles image generation.

The resolver `get_image_provider_for_user(user_id, db)` reads this row and instantiates the correct provider class. If no row exists, it defaults to `FalProvider() + FLUX.1-schnell`.

The resolver `resolve_user_post_model_choice(user_id, db)` (in `user_model_settings.py`) validates against a strict whitelist (`POST_ALLOWED` dict). If the selected provider key is missing in the environment, it raises `MissingProviderKeyError`.

#### B. `model_settings` table (task-category level)

Supports per-task-category configuration:
```python
TEXT_LLM_TASK_CATEGORIES = [
    "post_generation",      # Facebook post generation
    "post_analysis",        # Engagement analysis
    "image_prompt_generation", # Image prompt crafting
    "style_analysis",       # Competitor style analysis
    "recommendations",      # Dashboard recommendations
]
```

The function `generate_text_for_user(user_id, task_category, ...)` consults `model_settings` first, then falls back to environment-configured defaults, then to the first configured provider.

### 2.3 API Key Resolution Order

1. Check `model_settings.api_key_encrypted` for user-specific keys.
2. If empty, use the platform-level environment variable (e.g., `OPENAI_API_KEY`).
3. If neither is configured, raise `MissingProviderKeyError` with a user-facing message directing them to Settings.

### 2.4 Global Defaults

```python
DEFAULT_LLM_PROVIDER = "mistral"
DEFAULT_LLM_MODEL = MISTRAL_MODEL or "mistral-small-latest"
```

If no provider key is configured for the user's choice, the system falls back to the **first configured provider** found via `_get_first_configured_provider()`.

---

## 3. Prompt Studio & Persona Logic

### 3.1 Persona Model (`ai_personas` table — the central entity)

Each persona represents a distinct content voice belonging to a Facebook page connection. Key fields:

| Field | Type | Purpose |
|---|---|---|
| `persona_name` | String | Display name |
| `niche` | Text | The page's topic/industry |
| `tone_tags` | Text | Comma-separated tone descriptors (e.g., "professional, witty, inspiring") |
| `custom_instructions` | Text | Freeform user instructions appended to the prompt |
| `prompt_config` | JSON | Structured config including `length` (short/medium/long), additional flags |
| `custom_prompt` | Text | Full override prompt (if set, bypasses template assembly) |
| `creativity_level` | Integer (0–10) | Mapped to LLM temperature (creativity / 10, clamped to [0.1, 1.0]) |
| `language` | String | Output language (e.g., "English", "Bengali", "Arabic") |
| `hashtags_enabled` / `hashtag_count` | Bool + Int | Auto-hashtag generation (1–5) |
| `always_include_engagement_hook` | Bool | Append a question or CTA |
| `learning_mode_enabled` | Bool | Enable weekly strategy learning from engagement data |
| `template_image_generation_enabled` | Bool | Route to Prompt Studio (manual template) image generation |
| `image_frequency` | Enum | `every_post`, `every_other`, `1_in_3`, `1_in_5`, `weekends_only` |
| `image_fallback_policy` | Enum | `text_only`, `skip_post`, `use_library` |

### 3.2 Prompt Assembly Pipeline

The function `_persona_post_prompt()` in `backend/app/posts.py` builds the system prompt and user prompt:

**Step 1 — System prompt construction:**
```
You are an expert social media writer. Create polished, platform-ready Facebook posts...
→ [niche instruction] "This page is about {niche}. Every post must be relevant to this niche."
→ [tone instruction]  "The tone of every post must be {tone_tags}. Stay consistent..."
→ [prompt template]   Load the latest PromptTemplate.assembled_prompt for this persona
                      (or fallback to niche + tone_tags + custom_instructions joined text)
→ [language lock]     "You must write this post entirely in {language}."
```

**Step 2 — User prompt construction:**
```
→ creativity_level → temperature mapping
→ length preference from prompt_config.length
→ hashtag count instruction (if enabled)
→ engagement hook instruction (if enabled)
→ recent topic avoidance list
→ topic hint (if provided)
→ learning hint from engagement analysis
→ "Return only the Facebook post text. No labels, no explanation."
```

**Step 3 — Provider routing:**
`generate_persona_post_with_user_model()` calls `generate_post_text_for_user()` which resolves the user's model preference and dispatches to the appropriate LLM provider.

### 3.3 Prompt Template System (`prompt_templates` table)

The Prompt Studio UI lets users save structured prompt configurations:

| Field | Purpose |
|---|---|
| `question_answers` | JSON — raw form data from the prompt builder wizard |
| `assembled_prompt` | Text — the compiled prompt string injected into the LLM system prompt |
| `raw_prompt` | Text — raw user-entered prompt text |
| `creativity_level` | Integer |
| `style_examples` | JSON array — example posts for style reference |

The template is loaded at generation time via:
```python
template = db.query(PromptTemplate)
    .filter(PromptTemplate.persona_id == persona_id)
    .order_by(PromptTemplate.created_at.desc())
    .first()
```

If a `prompt_template_override` parameter is passed (used by the learning system's applied strategy), it takes precedence over the database-stored template.

### 3.4 Language & Script Handling

The language field on the persona is enforced at the **end of the system prompt** to ensure it acts as an overriding instruction:
```python
f"You must write this post entirely in {language.strip()}. "
f"The post content, hashtags, and any call to action must all be in {language.strip()}. "
f"Do not use any other language."
```

For image text overlays, the `_detect_script()` function in `persona_image_templates.py` classifies text into `bengali`, `arabic`, `devanagari`, `cyrillic`, or `latin` by Unicode code point ranges, then selects the appropriate system fonts for Pango rendering.

### 3.5 Content Generation Flow

```
User clicks "Generate Post"
  ↓
generate_persona_post_with_user_model(db, persona, recent_topics, topic_hint, learning_hint)
  ↓
_persona_post_prompt() → builds (system_prompt, user_prompt)
  ↓
generate_post_text_for_user() → resolve model → generate_text() → dispatch to provider
  ↓
Post content string returned
  ↓
extract_post_topic(content) → topic stored in post_log
  ↓
PostLog row created (status = "draft")
```

---

## 4. Photocard Generation & Asset Management System

### 4.1 Asset Tables

#### `template_background_assets`

Per-user reusable background definitions:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `asset_type` | String | `solid_color`, `gradient`, `photo`, `illustration` |
| `label` | String | Human-readable name (e.g., "Dark Navy") |
| `preview_url` | Text | Optional preview image URL |
| `value_json` | JSON | Asset payload: `{"color_hex": "#1a1a2e"}` for solids, `{"stops": ["#0f2027", "#203a43"]}` for gradients, `{"image_url": "..."}` for images |

Default assets are seeded via `_ensure_default_template_assets()`:
- 6 built-in presets (Dark Navy, Deep Purple, Charcoal Black, Warm Cream, Ocean Blue gradient, Sunset Glow gradient)
- 3 default fonts (Roboto Bold, Roboto Regular, Nirmala UI Regular)

#### `template_font_assets`

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `display_name` | String | Human-readable name |
| `font_file_url` | Text | Local filesystem path or URL |
| `weight` | String | `regular`, `bold`, etc. |

#### `image_templates`

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `name` | String | Template name |
| `reference_image_url` | Text | Original reference image (AI-extracted only) |
| `template_json` | JSON | Full template definition (layers, backgrounds, canvas) |
| `canvas_width` / `canvas_height` | Integer | Output dimensions |
| `aspect_ratio` | String | `1:1`, `4:5`, `9:16`, `16:9` |
| `creation_method` | String | `extracted` (AI vision) or `manual` (step-by-step builder) |

#### `persona_image_template_assignments`

Links a persona to exactly one image template (1:1 relationship keyed on persona_id).

#### `post_image_generations`

Tracks per-post image generation state:

| Field | Type | Description |
|---|---|---|
| `post_id` | FK → post_logs | 1:1 unique |
| `template_id` | FK → image_templates | Which template was used |
| `status` | String | `pending` → `generating_styling` / `generating_background` → `generating_text` → `assembling` → `completed` / `failed` |
| `background_generation_prompt` | Text | LLM-generated prompt for background image |
| `overlay_texts` | JSON | Array of `{layer_index, text}` for extracted templates |
| `llm_instructions` | JSON | Full LLM decisions for manual templates: `{chosen_background_asset_id, layers: [{layer_id, text, font_asset_id, color_hex, font_size_percent, text_align}]}` |
| `background_image_url` | Text | Uploaded background image URL |
| `logo_url` | Text | Uploaded logo URL |
| `final_image_url` | Text | Completed composite image URL |
| `layer_overrides` | JSON | User edits on specific layers |

#### `image_prompt_settings`

Per-persona image prompt configuration (legacy + reference image extraction):

| Field | Purpose |
|---|---|
| `assembled_prompt` | Compiled prompt for pure AI image generation |
| `reference_image_url` | Reference image for style extraction |
| `template_layers_json` | Extracted layout layers from Gemini Vision |
| `template_logo_url` | Logo overlay URL |
| `text_overlay_enabled` | Enable text overlay on generated images |

### 4.2 Template Creation Workflows

#### Workflow A: Manual Template Builder (Step-by-Step Form)

The frontend `manual-template-builder.tsx` implements a multi-step wizard:

1. **Canvas Setup** — Choose aspect ratio (1:1, 4:5, 9:16, 16:9) which sets `canvas_width` / `canvas_height`.
2. **Background Selection** — Pick one or more background assets from the user's `template_background_assets`. Each becomes an option in `background_options`.
3. **Layer Configuration** — Add/reorder layers with these properties:
   - **Type**: `text`, `overlay`, `logo`
   - **Position**: `position_x_percent`, `position_y_percent`, `width_percent`, `height_percent` (all 0–100)
   - **Z-Index**: Draw order
   - **Text-specific**: `role` (headline/subheadline/body), `font_options` (one or more `{font_asset_id, label}` choices), `color_options` (one or more `{color_hex, label}` choices), `font_size_min_percent` / `font_size_max_percent`, `text_align_options`
   - **Overlay-specific**: `color_options` with `opacity` per option
4. **Validation** — Enforces: at least one background option, unique layer IDs, `font_size_min_percent <= font_size_max_percent`, all referenced asset IDs exist.
5. **Save** — Calls `POST /api/image-templates/manual` which stores the template with `creation_method = "manual"`.

The template JSON schema for manual templates:
```json
{
  "canvas_width": 1080,
  "canvas_height": 1080,
  "aspect_ratio": "1:1",
  "background_options": [
    {"asset_id": "uuid", "label": "Dark Navy"}
  ],
  "layers": [
    {
      "id": "headline_1",
      "type": "text",
      "role": "headline",
      "z_index": 2,
      "position_x_percent": 10,
      "position_y_percent": 38,
      "width_percent": 80,
      "height_percent": 20,
      "font_options": [{"font_asset_id": "uuid", "label": "Roboto Bold"}],
      "color_options": [{"color_hex": "#ffffff", "label": "White"}],
      "font_size_min_percent": 4,
      "font_size_max_percent": 8,
      "text_align_options": ["center"]
    }
  ]
}
```

#### Workflow B: AI Style Extraction (Gemini Vision)

The endpoint `POST /api/image-templates/analyze` accepts a reference image upload and runs it through Gemini's vision model:

1. **Upload** — Image is stored in Supabase Storage (`image-templates` bucket).
2. **Base64 encode** — Converted to `data:image/{type};base64,...` URI.
3. **Gemini Vision call** — Sent with `_VISION_SYSTEM_INSTRUCTION` which instructs the model to return a JSON layout analysis with exact canvas dimensions, aspect ratio, background type, and a layers array.
4. **JSON parsing with recovery** — `_parse_json_with_fallback()`:
   - Strips markdown code fences.
   - Tries `json.loads()`.
   - On failure, sends the malformed text back to Gemini with a "fix this JSON" instruction.
   - On second failure, returns HTTP 422.
5. **Storage** — Result stored as an `image_templates` row with `creation_method = "extracted"`.

#### Workflow C: AI Generation from Description

The endpoint `POST /api/image-templates/generate-from-description` takes a natural language description (e.g., "A motivational quote card with a dark gradient background and bold white text") and produces a complete `ManualTemplateJson` structure:

1. Aspect ratio is inferred from description or uses the requested value.
2. Available background assets and font assets are fetched and listed in the LLM prompt.
3. The LLM receives the `_MANUAL_TEMPLATE_JSON_REFERENCE` schema and the user's description.
4. The response is parsed, validated through Pydantic (`ManualTemplateJson.model_validate()`), and returned with a suggested name.

### 4.3 Multi-Step Generation Pipeline

When a post needs a photocard image, `_run_post_image_generation()` orchestrates the pipeline:

#### Pipeline for Manual (Asset-Based) Templates:

```
[1] _generate_llm_instructions(db, post, persona, template_json)
    → build_image_instruction_prompt() creates a structured prompt enumerating
      every background option, text layer with font/color/alignment choices.
    → LLM returns JSON: {chosen_background_asset_id, layers: [{layer_id, text, font_asset_id, color_hex, font_size_percent, text_align}]}
    → _validate_and_clamp_llm_instructions() ensures every value is from the
      allowed options; logs and replaces with first-option fallback if invalid.

[2] Background Loading
    → Load background from template_background_assets (solid color, gradient, or image URL).
    → Upload to Supabase: generated-images/post-images/{post.id}/background.png

[3] Logo Resolution (priority order):
    a) Uploaded logo file from the request.
    b) Persona's saved template_logo_url from ImagePromptSettings.
    c) Previous generation's logo for the same persona.
    d) None → skip logo layers.

[4] Assembly via _assemble_from_llm_instructions():
    → Merge any layer_overrides (user edits from the photocard editor).
    → Build layer canvas (RGBA composite) by sorted z_index.
    → For text layers: run render_text_layer_pango() for script-aware rendering.
    → For overlay layers: draw semi-transparent colored rectangles.
    → For logo layers: fit image within bounds and composite.
    → Upload final PNG to Supabase.
    → Update generation.status = "completed".
```

#### Pipeline for Extracted (AI Background) Templates:

```
[1] _generate_background_prompt(db, post, persona, template_json)
    → LLM writes an image generation prompt based on post content + persona niche +
      template's background_style_description.

[2] Background Image Generation
    → Dispatch to user's configured image provider (Fal.ai / Stability / DALL-E / Gemini Imagen).
    → Upload result to Supabase.
    → status = "generating_text"

[3] _generate_overlay_texts(db, post, persona, template_json)
    → LLM generates N text strings (headline + supporting lines) as a JSON array.
    → Each mapped to a text layer by layer_index.

[4] Assembly via _assemble_template_image():
    → Similar composite pipeline but uses overlay_texts array instead of llm_instructions.
    → Legacy compatibility: reads layer fields like font_size_percent, text_color_hex directly.
```

### 4.4 Pango/Cairo Text Rendering

The system supports **complex text layout** (Bengali conjuncts, Arabic cursive, Devanagari matras) through a conditional rendering engine:

- **Primary**: PangoCairo via `gi.repository` (PyGObject) — supports script-aware font fallback, bidirectional text, and proper glyph shaping.
- **Fallback**: PIL `ImageDraw.text()` — used when Pango dependencies are unavailable (e.g., Windows without GTK3 runtime).

The font fallback chain is:
1. Custom font from `font_asset.font_file_url`.
2. Script-specific Noto fonts (Bengali, Arabic, Devanagari, Cyrillic, Latin).
3. System fonts (Nirmala UI on Windows, Noto Sans on Linux, Segoe UI fallback).
4. Generic `sans-serif`.

Font family resolution uses `fontTools` to extract the `nameID 1` record from TrueType fonts, then registers all fonts with Fontconfig via an XML config file at `~/.config/fontconfig/fonts.conf`.

### 4.5 Key Guardrails

- **Zero network calls during PIL assembly**: After background image and logo bytes are fetched, all compositing (text rendering, layer compositing, PNG encoding) happens in-process with zero external dependencies.
- **Non-blocking generation**: AI image provider calls (`generate()`) are wrapped in `asyncio.to_thread()`.
- **Configurable timeout**: `image_max_wait_seconds` per persona controls how long to wait for image generation before fallback.
- **Layer validation**: LLM responses are strictly validated against the template's allowed options using `_validate_and_clamp_llm_instructions()` which logs every fallback.
- **All timestamps in UTC**: `DateTime(timezone=True)` with `datetime.now(timezone.utc)` throughout.

---

## 5. API Route Reference

### 5.1 Auth & User Management

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | — | Register new user (email, password, name) |
| POST | `/auth/login` | — | Login, returns JWT + user object |
| GET | `/users/me` | JWT | Current user profile |
| PATCH | `/users/me` | JWT | Update profile (name, timezone, plan) |
| GET | `/auth/facebook/start` | Query token | Start Facebook OAuth flow |
| GET | `/auth/facebook/callback` | — | OAuth callback handler |
| POST | `/auth/facebook/select-page` | Session token | Select Facebook page after OAuth |

### 5.2 Facebook Integration

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/facebook/oauth-url` | JWT | Generate Facebook OAuth login URL |
| POST | `/facebook/connect` | JWT | Connect Facebook (code exchange or short-lived token) |
| POST | `/facebook/select-page` | JWT | Select connected page from pending OAuth |
| GET | `/facebook/status` | JWT | Connection status + page list |
| POST | `/facebook/manual-connect` | JWT | Manual connect with page ID + token |
| POST | `/facebook/pages/{id}/refresh-token` | JWT | Refresh long-lived page token |
| DELETE | `/facebook/pages/{id}` | JWT | Disconnect page |
| POST | `/facebook/pages/{id}/recover-history` | JWT | Import historical Facebook posts |
| GET | `/api/pages` | JWT | List connected pages |
| DELETE | `/api/pages/{id}/disconnect` | JWT | Remove page connection |

### 5.3 Post Management

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/posts` | JWT | List posts (filterable by status: draft, scheduled, published, failed) |
| GET | `/posts/history` | JWT | Post history with engagement stats |
| POST | `/posts/generate` | JWT | Generate post content from persona |
| POST | `/posts/publish` | JWT | Publish a post |
| PATCH | `/posts/{id}` | JWT | Update post content/status |
| DELETE | `/posts/{id}` | JWT | Delete post |
| POST | `/posts/{id}/publish` | JWT | Publish specific post by ID |
| POST | `/posts/{id}/publish-test-to-facebook` | JWT | Publish test draft to Facebook (bypasses quality checks) |

### 5.4 AI Personas

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/ai/personas/{page_connection_id}` | JWT | List personas for a Facebook page |
| POST | `/api/ai/personas/{page_connection_id}` | JWT | Create persona |
| PUT | `/api/ai/personas/{persona_id}` | JWT | Update persona fields |
| DELETE | `/api/ai/personas/{persona_id}` | JWT | Delete persona |
| POST | `/api/ai/generate` | JWT | Generate single post from persona |
| POST | `/api/ai/generate-and-publish` | JWT | Full generate + image + publish flow |
| POST | `/api/ai/test-full-flow` | JWT | Test flow (generates but does not publish) |
| POST | `/api/ai/prompt/test` | JWT | Test a custom prompt |
| POST | `/api/ai/generate-persona-from-posts` | JWT | Generate persona config from example posts |
| GET | `/api/ai/performance/{page_connection_id}` | JWT | Performance insights |
| GET | `/api/ai/personas/{id}/strategy` | JWT | Get learned strategy |
| POST | `/api/ai/personas/{id}/strategy-decision` | JWT | Accept/partial/reject learned strategy |
| POST | `/api/ai/personas/{id}/reset-learning` | JWT | Reset learning data |
| POST | `/api/ai/personas/{id}/publish-now` | JWT | Immediate publish from persona |

### 5.5 Prompt Templates

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/ai/prompt-templates` | JWT | List prompt templates |
| POST | `/api/ai/prompt-templates` | JWT | Create prompt template |
| PUT | `/api/ai/prompt-templates/{id}` | JWT | Update prompt template |
| DELETE | `/api/ai/prompt-templates/{id}` | JWT | Delete prompt template |

### 5.6 Schedule & Automation

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/personas/{id}/schedule` | JWT | Get persona schedule |
| POST | `/api/personas/{id}/schedule` | JWT | Save persona schedule (days, times, timezone) |
| GET | `/schedule` | JWT | Legacy schedule |
| PUT | `/schedule` | JWT | Legacy schedule upsert |
| POST | `/api/internal/run-scheduler` | CRON secret | Trigger slot processing (QStash webhook) |

### 5.7 Image Generation

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/images/generate` | JWT | Start async image generation job |
| GET | `/api/images/job/{job_id}` | JWT | Poll job status (pending/processing/completed/failed/timeout) |
| POST | `/api/images/retry/{job_id}` | JWT | Retry failed/timeout job |
| POST | `/api/images/save-prompt` | JWT | Save assembled image prompt for persona |
| POST | `/api/images/generate-from-text` | JWT | Generate image from post text content |
| POST | `/api/images/upload` | JWT | Upload image to Supabase media library |
| GET | `/api/images/generations` | JWT | List all image generations |
| GET | `/api/images/generations/{id}` | JWT | Get generation details |
| DELETE | `/api/images/generations/{id}` | JWT | Delete generation + storage asset |
| GET | `/api/images/media-library` | JWT | List media library |
| POST | `/api/images/media-library/{id}/use` | JWT | Mark media as used |

### 5.8 Image Templates & Photocard System

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/image-templates` | JWT | List all templates |
| POST | `/api/image-templates/manual` | JWT | Create manual template |
| PUT | `/api/image-templates/{template_id}` | JWT | Update manual template |
| POST | `/api/image-templates/analyze` | JWT | AI style extraction from uploaded image |
| POST | `/api/image-templates/generate-from-description` | JWT | Generate template JSON from description |
| POST | `/api/image-templates/preview` | JWT | Render preview PNG from template JSON |
| GET | `/api/image-templates/{template_id}` | JWT | Get single template |
| DELETE | `/api/image-templates/{template_id}` | JWT | Delete template + Supabase asset |
| GET | `/api/template-assets/backgrounds` | JWT | List background assets |
| POST | `/api/template-assets/backgrounds` | JWT | Create background asset |
| DELETE | `/api/template-assets/backgrounds/{id}` | JWT | Delete background asset |
| GET | `/api/template-assets/fonts` | JWT | List font assets |
| POST | `/api/template-assets/fonts` | JWT | Create font asset |

### 5.9 Template-to-Persona Assignment

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/personas/{persona_id}/assign-image-template` | JWT | Assign template to persona |
| DELETE | `/api/personas/{persona_id}/assign-image-template` | JWT | Unassign template |
| GET | `/api/personas/{persona_id}/assign-image-template` | JWT | Get assigned template ID |
| GET | `/api/personas/{persona_id}/image-template` | JWT | Get full assigned template |

### 5.10 Post Image Generation & Editing

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/posts/{post_id}/generate-image` | JWT | Trigger full photocard generation for a post |
| PATCH | `/api/posts/{post_id}/image` | JWT | Edit photocard (text overrides, background swap, new logo) |
| GET | `/api/image-templates/post-generation/{post_id}` | JWT | Get post image generation status |
| POST | `/api/image-templates/post-generation/{post_id}/override` | JWT | Override photocard selections |

### 5.11 Brand Automation

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/brand/profile` | JWT | Get brand profile |
| POST | `/api/brand/profile` | JWT | Upsert brand profile |
| POST | `/api/brand/analyze-dna` | JWT | Analyze brand DNA from source content |
| GET | `/api/brand/dna` | JWT | Get brand DNA analysis |
| POST | `/api/brand/content-plan` | JWT | Generate content plan from brand |
| POST | `/api/brand/generate` | JWT | Generate brand-aligned content |

### 5.12 Model & Provider Settings

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/models` | JWT | List available providers/models |
| GET | `/api/models/preference` | JWT | Get user model preference |
| POST | `/api/models/preference` | JWT | Set user model preference |
| POST | `/api/models/test` | JWT | Test provider connection |
| GET | `/api/settings/models` | JWT | Get user model settings |
| PATCH | `/api/settings/models` | JWT | Update user model settings |

### 5.13 Style Analyzer & Page Tracker

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/style/analyze` | JWT | Analyze page/social style |
| GET | `/api/style/analyses` | JWT | List analyses |
| POST | `/api/style/apply` | JWT | Apply analysis to persona |
| GET | `/api/tracker` | JWT | Get tracker dashboard |
| POST | `/api/tracker/pages` | JWT | Add tracked page |
| POST | `/api/tracker/pages/{id}/posts` | JWT | Add tracked posts |
| DELETE | `/api/tracker/pages/{id}` | JWT | Remove tracked page |
| DELETE | `/api/tracker/posts/{id}` | JWT | Remove tracked post |

### 5.14 Dashboard, Analytics & Internal

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/dashboard/intelligence` | JWT | Full dashboard intelligence data |
| GET | `/analytics` | JWT | Get analytics (engagements, performance) |
| POST | `/chat` | JWT | AI chat assistant |
| POST | `/api/admin/clear-posting-lock` | JWT | Clear user's posting lock |
| GET | `/health` | — | Health check |
| GET | `/api/health` | — | Health check |
| POST | `/api/internal/init-db` | CRON secret | Initialize database tables |
| GET | `/api/internal/debug-prompt/{persona_id}` | JWT/CRON | Debug persona's assembled prompt |
| POST | `/api/internal/run-scheduler` | CRON secret | Trigger scheduler slot processing |
| GET, HEAD | `/{path}` | — | SPA catch-all |

---

## 6. Core Technical Rules

### 6.1 PIL Assembly — Zero Network Calls

During the final image composition phase, all rendering is purely local:
- **Text rendering**: PangoCairo (primary) or PIL `ImageDraw` (fallback).
- **Layer compositing**: RGBA alpha compositing via `Image.alpha_composite()`.
- **Gradient generation**: Per-pixel lerp in pure Python.
- **Image resizing/cropping**: PIL `Image.Resampling.LANCZOS`.

The only explicit HTTP requests during a photocard generation flow are:
1. `async_upload_to_supabase()` — uploading the final image after assembly.
2. `_download_bytes()` — downloading background image and logo from Supabase URLs.
3. **AI provider API calls** — LLM for instruction generation, image provider for background generation (extracted template path only).

### 6.2 Non-Blocking Background Generation

All long-running operations use FastAPI's `BackgroundTasks` or explicit `asyncio` patterns:

```python
# Image generation job (backend/app/routers/images.py)
bg_db = SessionLocal()
background_tasks.add_task(run_image_generation_job, str(job.id), bg_db)

# AI provider generation (backend/app/routers/persona_image_templates.py)
image_bytes = await asyncio.to_thread(
    provider_instance.generate,
    prompt=bg_prompt,
    ...
)

# AI provider within a background job (backend/app/routers/images.py)
async def _generate():
    return await asyncio.to_thread(provider_instance.generate, ...)
image_bytes = await asyncio.wait_for(_generate(), timeout=job.max_wait_seconds)
```

- Each background task opens its **own database session** (`SessionLocal()`) to avoid thread-safety issues.
- Timeout is configurable per persona via `image_max_wait_seconds` (default 120, range [10, 180]).

### 6.3 Supabase Storage Rules

- **Buckets**: `generated-images` (AI-generated images, photocards), `image-templates` (reference uploads).
- **Upload**: `POST /storage/v1/object/{bucket}/{path}` using service key authorization.
- **Public URL**: `{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}`.
- **Deletion**: `DELETE /storage/v1/object/{bucket}/{path}` — called when templates or generations are deleted.
- **Paths**: Organized as `{user_id}/{uuid}.png` or `post-images/{post_id}/{type}.png` or `logos/{user_id}/logo.png`.
- **No Supabase client SDK**: All storage operations use raw `httpx` calls to the REST API.

### 6.4 UTC Timestamps

All database models use:
```python
DateTime(timezone=True)
default=lambda: datetime.now(timezone.utc)
onupdate=lambda: datetime.now(timezone.utc)
```

Timezone conversion happens at the application layer:
- User's `timezone` field (stored as IANA timezone name, default `"UTC"`).
- Scheduling uses `zoneinfo.ZoneInfo(user.timezone)` for local-time-aware slot creation.
- Dashboard display converts UTC to user's timezone.

### 6.5 APScheduler Architecture

Four scheduled jobs run in-process on the backend:

| Job | Trigger | Purpose |
|---|---|---|
| `prepare_upcoming_persona_slots` | Every 5 min | Checks persona schedules and creates/updates `scheduled_slots` for the next 24 hours |
| `process_due_persona_slots` | Every 1 min | Fires `run_full_publish_flow` for any `scheduled_slot` whose `scheduled_at` has passed and status is `pending` |
| `register_daily_slots` | Midnight UTC | Bulk-creates slots for all active personas with schedules |
| `keep_db_alive` | Every 10 min | `SELECT 1` to prevent connection pool staleness |

Additionally, QStash webhooks at `POST /api/internal/run-scheduler` can trigger `process_due_persona_slots` externally as a reliability layer.

### 6.6 Facebook Token Security

- Page access tokens are encrypted at rest using **Fernet symmetric encryption** (`backend/app/crypto.py`).
- The encryption key is `FACEBOOK_TOKEN_ENCRYPTION_KEY` from environment variables.
- Tokens are decrypted only at the moment of API call to the Facebook Graph API.
- Long-lived user tokens are stored alongside page tokens; token refresh is attempted before publishing when a token is nearing expiry.

### 6.7 Posting Lock

A thread-level and database-level posting lock prevents concurrent publishes for the same user:
```python
posting_lock = Lock()  # Thread lock
user_posting_locks: set[int] = set()  # In-memory set of locked user IDs
```

The lock is acquired before the publish flow and released on completion or failure. An admin endpoint `POST /api/admin/clear-posting-lock` allows manual clearing.

### 6.8 Image Fallback Policies

When image generation fails, the persona's `image_fallback_policy` determines behavior:

| Policy | Behavior |
|---|---|
| `text_only` | Continue publishing without an image |
| `skip_post` | Abort the post entirely, mark as "missed" |
| `use_library` | Attach the oldest unused image from the media library |

### 6.9 Learning System

The `learning/service.py` module captures engagement signals and generates weekly strategy insights:

1. **Snapshot Collection**: `collect_engagement_snapshots()` runs periodically to fetch likes, comments, shares, and reach from Facebook for published posts.
2. **Weekly Learning**: `run_weekly_learning()` aggregates snapshots into `persona_learning_patterns` by pattern type (tone, topic, length, time, day).
3. **Strategy Synthesis**: Generates `learned_strategy` rows with a `suggested_prompt` that can be accepted or rejected by the user via `POST /api/ai/personas/{id}/strategy-decision`.
4. **Signal Tracking**: `learning_signals` capture explicit feedback (user edits, deletes, manual publishes) with outcome scores.
5. **Access Control**: Learning features are gated behind `user_has_learning_access()` (Pro plan only).

---

*Document version: 1.0 — Generated from codebase analysis of all backend, frontend, database, and infrastructure layers.*

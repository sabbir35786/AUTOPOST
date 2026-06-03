-- Table 1 — model_settings
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS model_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id Integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_category VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    model_name VARCHAR NOT NULL,
    api_key_encrypted TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, task_category)
);

-- Table 2 — image_generation_jobs
CREATE TABLE IF NOT EXISTS image_generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id Integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    persona_id Integer REFERENCES ai_personas(id) ON DELETE SET NULL,
    status VARCHAR NOT NULL DEFAULT 'pending',
    provider VARCHAR NOT NULL,
    model_name VARCHAR NOT NULL,
    assembled_prompt TEXT NOT NULL,
    negative_prompt TEXT,
    aspect_ratio VARCHAR DEFAULT '1:1',
    result_image_url TEXT,
    supabase_storage_path TEXT,
    error_message TEXT,
    max_wait_seconds INTEGER NOT NULL DEFAULT 120,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    generation_seconds INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table 3 — media_library
CREATE TABLE IF NOT EXISTS media_library (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id Integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    persona_id Integer REFERENCES ai_personas(id) ON DELETE SET NULL,
    image_url TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    generation_prompt TEXT,
    provider VARCHAR,
    model_name VARCHAR,
    is_used BOOLEAN DEFAULT FALSE,
    used_in_post_id Integer REFERENCES post_logs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table 4 — image_prompt_settings
CREATE TABLE IF NOT EXISTS image_prompt_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id Integer NOT NULL REFERENCES ai_personas(id) ON DELETE CASCADE,
    user_id Integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_description TEXT,
    style_tags JSONB,
    mood_tags JSONB,
    color_palette VARCHAR,
    negative_prompt TEXT,
    aspect_ratio VARCHAR DEFAULT '1:1',
    text_overlay_enabled BOOLEAN DEFAULT FALSE,
    text_overlay_content TEXT,
    text_overlay_style VARCHAR,
    reference_image_descriptors TEXT,
    assembled_prompt TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(persona_id)
);

-- Step 2 — Add new columns to the existing ai_personas table
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS include_image BOOLEAN DEFAULT FALSE;
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS image_frequency VARCHAR DEFAULT 'every_post';
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS image_prompt_source VARCHAR DEFAULT 'persona_prompt';
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS image_fallback_policy VARCHAR DEFAULT 'text_only';
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS image_max_wait_seconds INTEGER DEFAULT 120;

-- Step 3 — Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_image_jobs_user_id ON image_generation_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_image_jobs_status ON image_generation_jobs(status);
CREATE INDEX IF NOT EXISTS idx_media_library_user_id ON media_library(user_id);
CREATE INDEX IF NOT EXISTS idx_media_library_is_used ON media_library(is_used);
CREATE INDEX IF NOT EXISTS idx_model_settings_user_id ON model_settings(user_id);

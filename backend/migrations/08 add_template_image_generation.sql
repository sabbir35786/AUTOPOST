-- Add template image generation columns to ai_personas table
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS template_image_generation_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS template_logo_url TEXT;

-- Add template image generation columns to image_prompt_settings table
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS reference_image_url TEXT;
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS template_layers_json JSONB;
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS template_analyzed_at TIMESTAMPTZ;
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS template_logo_url TEXT;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS image_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    reference_image_url TEXT NOT NULL,
    template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    canvas_width INTEGER NOT NULL DEFAULT 1024,
    canvas_height INTEGER NOT NULL DEFAULT 1024,
    aspect_ratio TEXT NOT NULL DEFAULT '1:1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE image_templates ADD COLUMN IF NOT EXISTS canvas_width INTEGER NOT NULL DEFAULT 1024;
ALTER TABLE image_templates ADD COLUMN IF NOT EXISTS canvas_height INTEGER NOT NULL DEFAULT 1024;
ALTER TABLE image_templates ADD COLUMN IF NOT EXISTS aspect_ratio TEXT NOT NULL DEFAULT '1:1';

CREATE TABLE IF NOT EXISTS persona_image_template_assignments (
    persona_id INTEGER PRIMARY KEY REFERENCES ai_personas(id) ON DELETE CASCADE,
    image_template_id UUID NOT NULL REFERENCES image_templates(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_image_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id INTEGER NOT NULL UNIQUE REFERENCES post_logs(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES image_templates(id) ON DELETE CASCADE,
    background_generation_prompt TEXT,
    overlay_texts JSONB NOT NULL DEFAULT '[]'::jsonb,
    background_image_url TEXT,
    logo_url TEXT,
    final_image_url TEXT,
    layer_overrides JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_ai_personas_template_enabled ON ai_personas(template_image_generation_enabled) WHERE template_image_generation_enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_image_templates_user_id ON image_templates(user_id);
CREATE INDEX IF NOT EXISTS idx_post_image_generations_post_id ON post_image_generations(post_id);
CREATE INDEX IF NOT EXISTS idx_post_image_generations_status ON post_image_generations(status);

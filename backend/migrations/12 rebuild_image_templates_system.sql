CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS image_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    reference_image_url TEXT NOT NULL,
    template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE image_templates
    ADD COLUMN IF NOT EXISTS template_json JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE image_templates SET template_json = '{}'::jsonb WHERE template_json IS NULL;

CREATE TABLE IF NOT EXISTS persona_image_template_assignments (
    persona_id INTEGER PRIMARY KEY REFERENCES ai_personas(id) ON DELETE CASCADE,
    image_template_id UUID NOT NULL REFERENCES image_templates(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TABLE IF EXISTS persona_image_templates;

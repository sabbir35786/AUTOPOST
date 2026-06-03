-- Step 2: Asset tables referenced by manual template option lists

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS template_background_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_type VARCHAR NOT NULL,
    label VARCHAR,
    preview_url TEXT,
    value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_background_assets_user_id
    ON template_background_assets(user_id);

CREATE TABLE IF NOT EXISTS template_font_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR NOT NULL,
    font_file_url TEXT NOT NULL,
    weight VARCHAR NOT NULL DEFAULT 'regular',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_font_assets_user_id
    ON template_font_assets(user_id);

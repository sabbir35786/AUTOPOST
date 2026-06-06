-- Migration 16_health_check_fixes
-- Adds missing tables and columns requested in the health check

-- 1. Create posts table
CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    status TEXT,
    published_at TIMESTAMPTZ,
    facebook_post_id TEXT,
    facebook_post_url TEXT,
    publish_error TEXT
);

-- 2. Create scheduled_posts table
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id SERIAL PRIMARY KEY,
    qstash_message_id TEXT,
    delivery_status TEXT,
    is_recurring BOOLEAN,
    recurrence_rule TEXT,
    retry_count INTEGER
);

-- 3. Update user_settings
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'UTC';

-- 4. Create persona_image_settings
CREATE TABLE IF NOT EXISTS persona_image_settings (
    id SERIAL PRIMARY KEY,
    logo_url TEXT,
    image_template_id UUID
);

-- 5. Update image_templates
ALTER TABLE image_templates 
    ADD COLUMN IF NOT EXISTS creation_method TEXT DEFAULT 'extracted',
    ADD COLUMN IF NOT EXISTS canvas_width INTEGER DEFAULT 1024,
    ADD COLUMN IF NOT EXISTS canvas_height INTEGER DEFAULT 1024;

-- 6. Create background_assets
CREATE TABLE IF NOT EXISTS background_assets (
    id SERIAL PRIMARY KEY,
    name TEXT,
    url TEXT
);

INSERT INTO background_assets (name, url) 
SELECT 'default', 'default.png'
WHERE NOT EXISTS (SELECT 1 FROM background_assets);

-- 7. Create font_assets
CREATE TABLE IF NOT EXISTS font_assets (
    id SERIAL PRIMARY KEY,
    name TEXT,
    url TEXT
);

INSERT INTO font_assets (name, url) 
SELECT 'Roboto', 'backend/assets/fonts/Roboto-Regular.ttf'
WHERE NOT EXISTS (SELECT 1 FROM font_assets);

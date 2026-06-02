-- Adds per-user provider/model selection for post and image generation.
-- Safe to run multiple times (best-effort / idempotent where possible).

-- 1) Create table if missing
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY,
  post_generation_provider TEXT DEFAULT 'openai' NOT NULL,
  post_generation_model TEXT DEFAULT 'gpt-4o' NOT NULL,
  image_generation_provider TEXT DEFAULT 'gemini' NOT NULL,
  image_generation_model TEXT DEFAULT 'imagen-3.0-generate-001' NOT NULL
);

-- 2) Add missing columns (Postgres syntax; ignore failures on SQLite)
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS post_generation_provider TEXT DEFAULT 'openai' NOT NULL;
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS post_generation_model TEXT DEFAULT 'gpt-4o' NOT NULL;
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS image_generation_provider TEXT DEFAULT 'gemini' NOT NULL;
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS image_generation_model TEXT DEFAULT 'imagen-3.0-generate-001' NOT NULL;


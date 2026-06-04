-- Add updated_at column to image_templates if it doesn't exist
ALTER TABLE image_templates
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

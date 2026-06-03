-- Add missing columns to image_templates table
ALTER TABLE image_templates
    ADD COLUMN IF NOT EXISTS template_json JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS canvas_width INTEGER DEFAULT 1024,
    ADD COLUMN IF NOT EXISTS canvas_height INTEGER DEFAULT 1024,
    ADD COLUMN IF NOT EXISTS aspect_ratio VARCHAR(10) DEFAULT '1:1';

-- Ensure columns are NOT NULL where required
ALTER TABLE image_templates
    ALTER COLUMN template_json SET NOT NULL,
    ALTER COLUMN canvas_width SET NOT NULL,
    ALTER COLUMN canvas_height SET NOT NULL,
    ALTER COLUMN aspect_ratio SET NOT NULL;

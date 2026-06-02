-- Add template image generation columns to ai_personas table
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS template_image_generation_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE ai_personas ADD COLUMN IF NOT EXISTS template_logo_url TEXT;

-- Add template image generation columns to image_prompt_settings table
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS reference_image_url TEXT;
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS template_layers_json JSONB;
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS template_analyzed_at TIMESTAMPTZ;
ALTER TABLE image_prompt_settings ADD COLUMN IF NOT EXISTS template_logo_url TEXT;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_ai_personas_template_enabled ON ai_personas(template_image_generation_enabled) WHERE template_image_generation_enabled = TRUE;

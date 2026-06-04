-- Drop the orphaned layers_json column if it exists
ALTER TABLE image_templates
    DROP COLUMN IF EXISTS layers_json;

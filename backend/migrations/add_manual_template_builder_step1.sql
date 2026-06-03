-- Step 1: Manual Template Builder — image_templates.creation_method
-- template_json option lists use the existing JSONB column (no column change).

ALTER TABLE image_templates
    ADD COLUMN IF NOT EXISTS creation_method TEXT NOT NULL DEFAULT 'extracted';

UPDATE image_templates
SET creation_method = 'extracted'
WHERE creation_method IS NULL OR creation_method = '';

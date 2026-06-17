-- Safely rename columns if they exist
DO $$
BEGIN
    -- Rename asset_type to type if it exists
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'template_background_assets' 
        AND column_name = 'asset_type'
    ) THEN
        ALTER TABLE template_background_assets RENAME COLUMN asset_type TO type;
    END IF;
    
    -- Rename value_json to config if it exists
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'template_background_assets' 
        AND column_name = 'value_json'
    ) THEN
        ALTER TABLE template_background_assets RENAME COLUMN value_json TO config;
    END IF;
END $$;

-- Update type values
UPDATE template_background_assets SET type = 'solid' WHERE type = 'solid_color';
UPDATE template_background_assets SET type = 'gradient_linear' WHERE type = 'gradient';

-- Update config structures
UPDATE template_background_assets 
SET config = jsonb_build_object('hex', config->>'color_hex') 
WHERE type = 'solid' AND config ? 'color_hex';

UPDATE template_background_assets 
SET config = jsonb_build_object(
    'from_hex', config->'stops'->>0, 
    'to_hex', config->'stops'->>1, 
    'angle_deg', 135
) 
WHERE type = 'gradient_linear' AND config ? 'stops';

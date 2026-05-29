ALTER TABLE post_logs ADD COLUMN IF NOT EXISTS media_library_id UUID REFERENCES media_library(id) ON DELETE SET NULL;

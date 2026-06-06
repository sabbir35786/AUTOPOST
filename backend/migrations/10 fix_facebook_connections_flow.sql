-- Facebook connect/disconnect flow schema fixes
-- Table name in this project: facebook_connections (maps to spec's page_connections)

ALTER TABLE facebook_connections
    ADD COLUMN IF NOT EXISTS connection_status VARCHAR DEFAULT 'connected',
    ADD COLUMN IF NOT EXISTS disconnected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reconnect_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_token_refresh TIMESTAMPTZ;

ALTER TABLE facebook_connections
    ALTER COLUMN page_access_token DROP NOT NULL;

-- Allow multiple pages per user - unique per (user_id, page_id)
ALTER TABLE facebook_connections
    DROP CONSTRAINT IF EXISTS facebook_connections_user_id_key;

ALTER TABLE facebook_connections
    DROP CONSTRAINT IF EXISTS page_connections_facebook_page_id_key;

ALTER TABLE facebook_connections
    DROP CONSTRAINT IF EXISTS facebook_connections_page_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_connections_user_page
    ON facebook_connections(user_id, page_id);

-- Never delete posts when a page disconnects
ALTER TABLE post_logs
    DROP CONSTRAINT IF EXISTS post_logs_facebook_connection_id_fkey;

ALTER TABLE post_logs
    ADD CONSTRAINT post_logs_facebook_connection_id_fkey
    FOREIGN KEY (facebook_connection_id)
    REFERENCES facebook_connections(id)
    ON DELETE SET NULL;

ALTER TABLE ai_personas
    DROP CONSTRAINT IF EXISTS ai_personas_page_connection_id_fkey;

ALTER TABLE ai_personas
    ADD CONSTRAINT ai_personas_page_connection_id_fkey
    FOREIGN KEY (page_connection_id)
    REFERENCES facebook_connections(id)
    ON DELETE SET NULL;

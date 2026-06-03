-- Add oauth_states table for database-backed OAuth state storage
-- This fixes OAuth state mismatch issues in distributed environments

CREATE TABLE IF NOT EXISTS oauth_states (
    id VARCHAR PRIMARY KEY,
    user_id INTEGER NOT NULL,
    state VARCHAR NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

-- Create index on expires_at for cleanup
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON oauth_states(expires_at);
-- Create index on user_id for lookups
CREATE INDEX IF NOT EXISTS idx_oauth_states_user_id ON oauth_states(user_id);
                                                                                                                                                            
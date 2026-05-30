-- Add sessions table for database-backed session storage
-- This fixes OAuth state mismatch issues in distributed environments

CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR PRIMARY KEY,
    data TEXT NOT NULL,
    expiry TIMESTAMPTZ NOT NULL
);

-- Create index on expiry for cleanup
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expiry);

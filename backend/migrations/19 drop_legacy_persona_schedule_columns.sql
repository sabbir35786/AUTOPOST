-- Drop legacy persona_schedules columns that block inserts on the new schedule_data schema.
-- Safe to run multiple times on Postgres/Supabase.

ALTER TABLE persona_schedules DROP COLUMN IF EXISTS days_of_week;
ALTER TABLE persona_schedules DROP COLUMN IF EXISTS post_times;

ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS schedule_data JSONB DEFAULT '{"active_days": [], "default_times": [], "day_overrides": {}}'::jsonb NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS timezone VARCHAR DEFAULT 'Asia/Dhaka' NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL;

CREATE TABLE IF NOT EXISTS persona_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id INTEGER NOT NULL UNIQUE REFERENCES ai_personas(id) ON DELETE CASCADE,
    timezone VARCHAR NOT NULL DEFAULT 'Asia/Dhaka',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    schedule_data JSONB NOT NULL DEFAULT '{"active_days": [], "default_times": [], "day_overrides": {}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scheduled_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id INTEGER NOT NULL REFERENCES ai_personas(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMPTZ NOT NULL,
    qstash_message_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'pending',
    post_id INTEGER REFERENCES post_logs(id) ON DELETE SET NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

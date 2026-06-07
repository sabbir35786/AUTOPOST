-- Repair persona_schedules to match the current app model.
-- Safe to run multiple times on Postgres/Supabase.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS persona_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id INTEGER NOT NULL UNIQUE REFERENCES ai_personas(id) ON DELETE CASCADE,
    timezone VARCHAR NOT NULL DEFAULT 'Asia/Dhaka',
    active_days JSONB NOT NULL DEFAULT '[]'::jsonb,
    default_times JSONB NOT NULL DEFAULT '[]'::jsonb,
    day_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS timezone VARCHAR DEFAULT 'Asia/Dhaka' NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS active_days JSONB DEFAULT '[]'::jsonb NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS default_times JSONB DEFAULT '[]'::jsonb NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS day_overrides JSONB DEFAULT '{}'::jsonb NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE NOT NULL;
ALTER TABLE persona_schedules ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL;
ALTER TABLE persona_schedules ALTER COLUMN active_days TYPE JSONB USING active_days::jsonb;
ALTER TABLE persona_schedules ALTER COLUMN default_times TYPE JSONB USING default_times::jsonb;
ALTER TABLE persona_schedules ALTER COLUMN day_overrides TYPE JSONB USING day_overrides::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona_schedules' AND column_name = 'days_of_week'
    ) THEN
        UPDATE persona_schedules
        SET active_days = to_jsonb(days_of_week)
        WHERE (active_days IS NULL OR active_days = '[]'::jsonb)
          AND days_of_week IS NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona_schedules' AND column_name = 'post_times'
    ) THEN
        UPDATE persona_schedules
        SET default_times = to_jsonb(post_times)
        WHERE (default_times IS NULL OR default_times = '[]'::jsonb)
          AND post_times IS NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona_schedules' AND column_name = 'schedule_data'
    ) THEN
        UPDATE persona_schedules
        SET
            active_days = COALESCE((schedule_data::jsonb)->'active_days', active_days::jsonb, '[]'::jsonb),
            default_times = COALESCE((schedule_data::jsonb)->'default_times', default_times::jsonb, '[]'::jsonb),
            day_overrides = COALESCE((schedule_data::jsonb)->'day_overrides', day_overrides::jsonb, '{}'::jsonb)
        WHERE schedule_data IS NOT NULL;
    END IF;
END $$;

ALTER TABLE persona_schedules DROP COLUMN IF EXISTS days_of_week;
ALTER TABLE persona_schedules DROP COLUMN IF EXISTS post_times;
ALTER TABLE persona_schedules DROP COLUMN IF EXISTS schedule_data;

CREATE INDEX IF NOT EXISTS idx_persona_schedules_persona_id ON persona_schedules(persona_id);

CREATE TABLE IF NOT EXISTS scheduled_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id INTEGER NOT NULL REFERENCES ai_personas(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMPTZ NOT NULL,
    qstash_message_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'pending',
    post_id INTEGER REFERENCES post_logs(id) ON DELETE SET NULL,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE scheduled_slots ADD COLUMN IF NOT EXISTS qstash_message_id VARCHAR;
ALTER TABLE scheduled_slots ADD COLUMN IF NOT EXISTS post_id INTEGER;
ALTER TABLE scheduled_slots ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE scheduled_slots ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE scheduled_slots ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scheduled_slots_persona_id ON scheduled_slots(persona_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_slots_scheduled_at ON scheduled_slots(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_slots_status ON scheduled_slots(status);
CREATE INDEX IF NOT EXISTS ix_scheduled_slots_status_time ON scheduled_slots(status, scheduled_at);

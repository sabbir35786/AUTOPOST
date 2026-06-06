-- Point scheduled_slots.post_id at post_logs (where published posts actually live).
-- Safe to run multiple times on Postgres/Supabase.

ALTER TABLE scheduled_slots DROP CONSTRAINT IF EXISTS scheduled_slots_post_id_fkey;

ALTER TABLE scheduled_slots
    ADD CONSTRAINT scheduled_slots_post_id_fkey
    FOREIGN KEY (post_id) REFERENCES post_logs(id) ON DELETE SET NULL;

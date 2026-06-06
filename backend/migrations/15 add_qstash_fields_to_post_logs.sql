-- Add QStash tracking fields to post_logs table
ALTER TABLE post_logs ADD COLUMN IF NOT EXISTS qstash_message_id VARCHAR(255);
ALTER TABLE post_logs ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(50) DEFAULT 'pending';

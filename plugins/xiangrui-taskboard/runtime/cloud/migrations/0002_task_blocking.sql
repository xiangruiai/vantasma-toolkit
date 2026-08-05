ALTER TABLE tasks ADD COLUMN blocked_reason TEXT;
ALTER TABLE tasks ADD COLUMN unblock_action TEXT;
ALTER TABLE tasks ADD COLUMN blocked_at TEXT;
ALTER TABLE tasks ADD COLUMN blocked_by_type TEXT CHECK (blocked_by_type IS NULL OR blocked_by_type IN ('user', 'agent'));
ALTER TABLE tasks ADD COLUMN blocked_by_id TEXT;
ALTER TABLE tasks ADD COLUMN blocked_by_name TEXT;
ALTER TABLE tasks ADD COLUMN blocked_by_avatar_url TEXT;

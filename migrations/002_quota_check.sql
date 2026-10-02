ALTER TABLE user_show_quota ADD CONSTRAINT active_count_non_negative CHECK (active_count >= 0);

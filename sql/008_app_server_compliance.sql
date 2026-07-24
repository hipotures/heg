ALTER TABLE app_server_turns
    ADD COLUMN cache_write_input_tokens INTEGER;
ALTER TABLE app_server_turns
    ADD COLUMN final_agent_item_id TEXT;
PRAGMA user_version=8;

ALTER TABLE app_server_turns
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'requested';
ALTER TABLE app_server_turns
    ADD COLUMN request_id TEXT;
ALTER TABLE app_server_turns
    ADD COLUMN item_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE app_server_turns
    ADD COLUMN item_types_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE app_server_turns
    ADD COLUMN reasoning_item_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE app_server_turns
    ADD COLUMN latest_event_sequence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app_server_turns
    ADD COLUMN latest_event_at TEXT;
ALTER TABLE app_server_turns
    ADD COLUMN turn_started_at TEXT;
ALTER TABLE app_server_turns
    ADD COLUMN terminal_reason TEXT;
ALTER TABLE app_server_turns
    ADD COLUMN evidence_registry_artifact_ref TEXT;
ALTER TABLE app_server_turns
    ADD COLUMN evidence_registry_sha256 TEXT;

UPDATE app_server_turns
SET lifecycle_status=CASE
    WHEN status IN ('completed', 'completed_valid', 'completed_invalid')
        THEN 'completed'
    WHEN status='failed_interrupted' THEN 'aborted'
    WHEN status='failed' THEN 'failed'
    WHEN status='in_progress' THEN 'in_progress'
    ELSE lifecycle_status
END,
turn_started_at=CASE
    WHEN turn_id IS NOT NULL AND turn_started_at IS NULL THEN started_at
    ELSE turn_started_at
END;

PRAGMA user_version=9;

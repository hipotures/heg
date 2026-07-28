-- Additive campaign/attempt mode and passive scheduler persistence.
-- Apply through sglab.db.migrate(), after an SQLite Online Backup snapshot.

PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

ALTER TABLE research_campaigns
    ADD COLUMN director_mode TEXT NOT NULL DEFAULT 'llm';
ALTER TABLE campaign_execution_attempts
    ADD COLUMN director_mode TEXT NOT NULL DEFAULT 'llm';
ALTER TABLE campaign_execution_attempts
    ADD COLUMN previous_director_mode TEXT;
ALTER TABLE campaign_execution_attempts
    ADD COLUMN mode_transition_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE campaign_execution_attempts
    ADD COLUMN contract_fingerprint TEXT;

CREATE TABLE passive_scheduler_states (
    campaign_id TEXT PRIMARY KEY REFERENCES research_campaigns(campaign_id),
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    scheduler_state_version INTEGER NOT NULL,
    state_version INTEGER NOT NULL,
    rng_seed INTEGER NOT NULL,
    rng_counter INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(policy_version >= 1),
    CHECK(scheduler_state_version >= 1),
    CHECK(state_version >= 0),
    CHECK(rng_seed >= 0),
    CHECK(rng_counter >= 0)
);

CREATE TABLE passive_scheduler_decisions (
    scheduler_decision_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    execution_attempt_id TEXT REFERENCES campaign_execution_attempts(attempt_id),
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    scheduler_state_version INTEGER NOT NULL,
    state_version_before INTEGER NOT NULL,
    state_version_after INTEGER,
    input_snapshot_id TEXT NOT NULL REFERENCES director_snapshots(snapshot_id),
    input_snapshot_version INTEGER NOT NULL,
    input_metrics_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    generated_action_ids_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validation_detail TEXT,
    resulting_changes_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK(policy_version >= 1),
    CHECK(scheduler_state_version >= 1),
    CHECK(state_version_before >= 0),
    CHECK(state_version_after IS NULL OR state_version_after > state_version_before)
);

CREATE INDEX idx_passive_scheduler_decisions_campaign
    ON passive_scheduler_decisions(campaign_id, created_at);

CREATE TABLE director_action_batches_v17 (
    decision_batch_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    snapshot_id TEXT NOT NULL REFERENCES director_snapshots(snapshot_id),
    trigger_id TEXT NOT NULL REFERENCES director_triggers(trigger_id),
    turn_record_id TEXT REFERENCES app_server_turns(turn_record_id),
    scheduler_decision_id TEXT
        REFERENCES passive_scheduler_decisions(scheduler_decision_id),
    campaign_assessment TEXT NOT NULL,
    next_review_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    response_artifact_ref TEXT,
    response_sha256 TEXT,
    created_at TEXT NOT NULL,
    CHECK(
        (turn_record_id IS NOT NULL AND scheduler_decision_id IS NULL)
        OR
        (turn_record_id IS NULL AND scheduler_decision_id IS NOT NULL)
    )
);

INSERT INTO director_action_batches_v17
    (decision_batch_id, campaign_id, snapshot_id, trigger_id,
     turn_record_id, scheduler_decision_id, campaign_assessment,
     next_review_json, validation_status, response_artifact_ref,
     response_sha256, created_at)
SELECT decision_batch_id, campaign_id, snapshot_id, trigger_id,
       turn_record_id, NULL, campaign_assessment, next_review_json,
       validation_status, response_artifact_ref, response_sha256, created_at
FROM director_action_batches;

DROP TABLE director_action_batches;
ALTER TABLE director_action_batches_v17
    RENAME TO director_action_batches;

PRAGMA user_version=17;
COMMIT;
PRAGMA foreign_keys=ON;

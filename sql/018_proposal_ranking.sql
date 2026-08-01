-- Additive reviewed proposal-ranking identity ledger.
-- Apply through sglab.db.migrate() after an SQLite Online Backup snapshot.

CREATE TABLE IF NOT EXISTS research_lane_policy_identities (
    lane_id TEXT PRIMARY KEY REFERENCES research_lanes(lane_id),
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    catalog_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    normalized_ast_sha256 TEXT NOT NULL,
    behavior_signature_sha256 TEXT NOT NULL,
    validator_version TEXT NOT NULL,
    runtime_protocol_version TEXT NOT NULL,
    feature_contract_version TEXT NOT NULL,
    proposal_pool_contract_version TEXT NOT NULL,
    tie_breaking_rule TEXT NOT NULL,
    failure_policy TEXT NOT NULL,
    worker_identity TEXT,
    identity_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lane_policy_identity_campaign
    ON research_lane_policy_identities(campaign_id, lane_id);

PRAGMA user_version=18;

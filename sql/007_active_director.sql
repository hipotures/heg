-- Additive migration for the authoritative Structural Graph Lab schema v1.
-- The executable source of this migration is ACTIVE_DIRECTOR_SCHEMA_SQL in
-- src/sglab/db.py. This reviewed copy documents the schema-v7 transition.
--
-- Apply only through sglab.db.migrate(). Before experiments against existing
-- data, create a consistent SQLite Online Backup API snapshot and run
-- PRAGMA integrity_check on the migrated snapshot.

-- New durable entity groups:
--   research_campaigns
--   director_snapshots
--   app_server_sessions / app_server_turns
--   director_triggers
--   research_lanes / lane_revisions / lane_metric_windows
--   director_action_batches / director_actions / director_action_outcomes
--   research_hypotheses_v2
--   campaign_verification_jobs / campaign_terminal_events
--
-- Existing schema-v1 tables and their semantics are unchanged. See the
-- constant in src/sglab/db.py for the complete idempotent CREATE TABLE and
-- CREATE INDEX statements used by the application.

PRAGMA user_version=7;

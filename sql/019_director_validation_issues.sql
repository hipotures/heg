-- Additive bounded Director validation diagnostics for invalid turns.
-- Apply through sglab.db.migrate() after an SQLite Online Backup snapshot.

ALTER TABLE app_server_turns
    ADD COLUMN validation_issues_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE app_server_turns
    ADD COLUMN validation_issue_count INTEGER NOT NULL DEFAULT 0;

PRAGMA user_version=19;

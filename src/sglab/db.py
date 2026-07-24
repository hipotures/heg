from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json
import sqlite3

SCHEMA_VERSION = 7
MAX_METRIC_ROWS = 100_000

BASE_SCHEMA_SQL = """
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    environment_json TEXT NOT NULL
);
CREATE TABLE run_metrics (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    recorded_at TEXT NOT NULL,
    candidates INTEGER NOT NULL,
    improvements INTEGER NOT NULL,
    candidates_per_second REAL NOT NULL,
    rss_bytes INTEGER NOT NULL
);
CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    graph6 TEXT NOT NULL,
    order_n INTEGER NOT NULL,
    size_m INTEGER NOT NULL,
    score_json TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX candidates_run_score ON candidates(run_id, created_at);
CREATE TABLE candidate_scores (
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    component TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY(candidate_id, component)
);
CREATE TABLE artifacts (
    artifact_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    candidate_id TEXT,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TABLE verifications (
    verification_id INTEGER PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    verifier TEXT NOT NULL,
    status TEXT NOT NULL,
    complete INTEGER NOT NULL,
    elapsed_seconds REAL NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TABLE benchmarks (
    benchmark_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TABLE tool_versions (
    name TEXT PRIMARY KEY,
    version TEXT,
    path TEXT
);
PRAGMA user_version=1;
"""

ACTIVE_DIRECTOR_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_campaigns (
    campaign_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    target TEXT NOT NULL,
    target_definition_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    stop_mode TEXT NOT NULL,
    deadline_at TEXT,
    certified_candidate_id TEXT,
    certification_artifact_ref TEXT,
    fault_kind TEXT,
    fault_detail TEXT,
    CHECK(state_version >= 0),
    CHECK(stop_mode IN ('time_limit', 'until_success'))
);

CREATE TABLE IF NOT EXISTS director_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    campaign_state_version INTEGER NOT NULL,
    high_water_json TEXT NOT NULL,
    artifact_ref TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    payload_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(payload_bytes >= 0)
);

CREATE INDEX IF NOT EXISTS idx_director_snapshots_campaign
    ON director_snapshots(campaign_id, created_at);

CREATE TABLE IF NOT EXISTS app_server_sessions (
    session_record_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    thread_id TEXT NOT NULL,
    app_server_session_id TEXT,
    thread_path TEXT,
    parent_thread_id TEXT,
    model_requested TEXT,
    effort_requested TEXT,
    codex_version TEXT NOT NULL,
    codex_executable_sha256 TEXT NOT NULL,
    protocol_schema_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_resumed_at TEXT,
    closed_at TEXT,
    UNIQUE(campaign_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_app_server_sessions_campaign
    ON app_server_sessions(campaign_id, started_at);

CREATE TABLE IF NOT EXISTS director_triggers (
    trigger_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    campaign_state_version INTEGER NOT NULL,
    reason_set_json TEXT NOT NULL,
    first_event_at TEXT NOT NULL,
    coalesced_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES director_snapshots(snapshot_id),
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_server_turns (
    turn_record_id TEXT PRIMARY KEY,
    session_record_id TEXT NOT NULL
        REFERENCES app_server_sessions(session_record_id),
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    thread_id TEXT NOT NULL,
    turn_id TEXT,
    snapshot_id TEXT NOT NULL REFERENCES director_snapshots(snapshot_id),
    trigger_id TEXT NOT NULL REFERENCES director_triggers(trigger_id),
    status TEXT NOT NULL,
    request_artifact_ref TEXT,
    request_sha256 TEXT,
    response_artifact_ref TEXT,
    response_sha256 TEXT,
    wire_log_artifact_ref TEXT,
    wire_log_sha256 TEXT,
    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_output_tokens INTEGER,
    total_tokens INTEGER,
    raw_usage_json TEXT,
    wall_seconds REAL,
    error_kind TEXT,
    error_detail TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_server_turns_campaign_time
    ON app_server_turns(campaign_id, started_at);

CREATE TABLE IF NOT EXISTS research_lanes (
    lane_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    target TEXT NOT NULL,
    parent_lane_id TEXT REFERENCES research_lanes(lane_id),
    parent_checkpoint_ref TEXT,
    created_by_action_id TEXT,
    state TEXT NOT NULL,
    lane_version INTEGER NOT NULL,
    algorithm TEXT NOT NULL,
    graph_family TEXT NOT NULL,
    current_parameters_json TEXT NOT NULL,
    seed_lineage_json TEXT NOT NULL,
    checkpoint_ref TEXT,
    checkpoint_sha256 TEXT,
    telemetry_high_water INTEGER NOT NULL DEFAULT 0,
    resource_share REAL NOT NULL,
    lease_expires_at TEXT,
    process_generation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stopped_at TEXT,
    CHECK(lane_version >= 0),
    CHECK(telemetry_high_water >= 0),
    CHECK(resource_share >= 0.0 AND resource_share <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_research_lanes_campaign_state
    ON research_lanes(campaign_id, state, updated_at);

CREATE TABLE IF NOT EXISTS lane_revisions (
    lane_revision_id TEXT PRIMARY KEY,
    lane_id TEXT NOT NULL REFERENCES research_lanes(lane_id),
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    action_id TEXT,
    old_lane_version INTEGER NOT NULL,
    new_lane_version INTEGER NOT NULL,
    old_parameters_json TEXT NOT NULL,
    new_parameters_json TEXT NOT NULL,
    applied_checkpoint_ref TEXT NOT NULL,
    applied_checkpoint_sha256 TEXT,
    applied_at TEXT NOT NULL,
    UNIQUE(lane_id, new_lane_version)
);

CREATE TABLE IF NOT EXISTS lane_metric_windows (
    metric_window_id TEXT PRIMARY KEY,
    lane_id TEXT NOT NULL REFERENCES research_lanes(lane_id),
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    lane_version INTEGER NOT NULL,
    start_high_water INTEGER NOT NULL,
    end_high_water INTEGER NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    artifact_ref TEXT,
    artifact_sha256 TEXT,
    UNIQUE(lane_id, lane_version, end_high_water),
    CHECK(start_high_water >= 0),
    CHECK(end_high_water >= start_high_water)
);

CREATE INDEX IF NOT EXISTS idx_lane_metric_windows_recent
    ON lane_metric_windows(campaign_id, end_at);

CREATE TABLE IF NOT EXISTS director_action_batches (
    decision_batch_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    snapshot_id TEXT NOT NULL REFERENCES director_snapshots(snapshot_id),
    trigger_id TEXT NOT NULL REFERENCES director_triggers(trigger_id),
    turn_record_id TEXT NOT NULL REFERENCES app_server_turns(turn_record_id),
    campaign_assessment TEXT NOT NULL,
    next_review_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    response_artifact_ref TEXT,
    response_sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS director_actions (
    action_id TEXT PRIMARY KEY,
    decision_batch_id TEXT NOT NULL
        REFERENCES director_action_batches(decision_batch_id),
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    action_type TEXT NOT NULL,
    priority INTEGER NOT NULL,
    target_lane_id TEXT,
    expected_lane_version INTEGER,
    hypothesis_ids_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    expected_effect TEXT NOT NULL,
    evaluation_window_json TEXT NOT NULL,
    fallback_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    lease_expires_at TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validation_detail TEXT,
    created_at TEXT NOT NULL,
    CHECK(priority >= 0 AND priority <= 100)
);

CREATE INDEX IF NOT EXISTS idx_director_actions_campaign_status
    ON director_actions(campaign_id, validation_status, created_at);

CREATE TABLE IF NOT EXISTS director_action_outcomes (
    action_outcome_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES director_actions(action_id),
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    application_status TEXT NOT NULL,
    resulting_lane_id TEXT REFERENCES research_lanes(lane_id),
    resulting_lane_version INTEGER,
    pre_window_id TEXT REFERENCES lane_metric_windows(metric_window_id),
    post_window_id TEXT REFERENCES lane_metric_windows(metric_window_id),
    observed_effect_json TEXT,
    expectation_met INTEGER,
    failure_kind TEXT,
    failure_detail TEXT,
    applied_at TEXT,
    evaluated_at TEXT
);

CREATE TABLE IF NOT EXISTS research_hypotheses_v2 (
    hypothesis_revision_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    parent_revision_id TEXT REFERENCES research_hypotheses_v2(
        hypothesis_revision_id
    ),
    statement TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    evidence_for_json TEXT NOT NULL,
    evidence_against_json TEXT NOT NULL,
    creating_decision_batch_id TEXT NOT NULL
        REFERENCES director_action_batches(decision_batch_id),
    created_at TEXT NOT NULL,
    CHECK(confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_research_hypotheses_current
    ON research_hypotheses_v2(campaign_id, hypothesis_id, created_at);

CREATE TABLE IF NOT EXISTS campaign_verification_jobs (
    verification_job_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    candidate_id TEXT NOT NULL,
    requested_by_action_id TEXT REFERENCES director_actions(action_id),
    priority INTEGER NOT NULL,
    state TEXT NOT NULL,
    certification_artifact_ref TEXT,
    certification_status TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(campaign_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS campaign_terminal_events (
    terminal_event_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    terminal_kind TEXT NOT NULL,
    certified_candidate_id TEXT,
    verification_job_id TEXT REFERENCES campaign_verification_jobs(
        verification_job_id
    ),
    deadline_at TEXT,
    artifact_ref TEXT,
    created_at TEXT NOT NULL,
    CHECK(terminal_kind IN (
        'succeeded_certified_counterexample',
        'completed_deadline_reached',
        'stopped_by_operator'
    ))
);

PRAGMA user_version=7;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        migrate(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema {version} is newer than supported {SCHEMA_VERSION}"
        )
    if version == 0:
        connection.executescript(BASE_SCHEMA_SQL)
        connection.commit()
        version = 1
    if version < 7:
        connection.executescript(ACTIVE_DIRECTOR_SCHEMA_SQL)
        connection.commit()
    _ensure_m6_lane_columns(connection)


def _ensure_m6_lane_columns(connection: sqlite3.Connection) -> None:
    """Complete the schema-v7 lane shape from pre-lane M6.2 checkouts."""

    exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='research_lanes'
        """
    ).fetchone()
    if exists is None:
        return
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(research_lanes)")
    }
    changed = False
    if "target" not in columns:
        connection.execute(
            """
            ALTER TABLE research_lanes
            ADD COLUMN target TEXT NOT NULL DEFAULT 'erdos_gyarfas'
            """
        )
        connection.execute(
            """
            UPDATE research_lanes
            SET target=(
                SELECT target FROM research_campaigns
                WHERE research_campaigns.campaign_id=research_lanes.campaign_id
            )
            """
        )
        changed = True
    if "parent_checkpoint_ref" not in columns:
        connection.execute(
            "ALTER TABLE research_lanes ADD COLUMN parent_checkpoint_ref TEXT"
        )
        changed = True
    if changed:
        connection.commit()


def insert_run(
    connection: sqlite3.Connection,
    run_id: str,
    created_at: str,
    target: str,
    parameters: dict[str, Any],
    environment: dict[str, Any],
) -> None:
    connection.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
        (
            run_id,
            created_at,
            target,
            "RUNNING",
            json.dumps(parameters, sort_keys=True),
            json.dumps(environment, sort_keys=True),
        ),
    )
    connection.commit()


def set_run_status(connection: sqlite3.Connection, run_id: str, status: str) -> None:
    connection.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
    connection.commit()


def insert_metrics(
    connection: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]
) -> None:
    connection.executemany("INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.commit()


def prune_metrics(
    connection: sqlite3.Connection, max_rows: int = MAX_METRIC_ROWS
) -> None:
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    latest = int(
        connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM run_metrics"
        ).fetchone()[0]
    )
    threshold = latest - max_rows
    if threshold > 0:
        connection.execute("DELETE FROM run_metrics WHERE rowid <= ?", (threshold,))
        connection.commit()


def checkpoint(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

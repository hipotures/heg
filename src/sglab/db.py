from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json
import sqlite3

SCHEMA_VERSION = 10
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

CREATE TABLE IF NOT EXISTS campaign_candidates (
    candidate_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
    lane_id TEXT NOT NULL REFERENCES research_lanes(lane_id),
    lane_version INTEGER NOT NULL,
    checkpoint_ref TEXT,
    graph6 TEXT NOT NULL,
    graph_sha256 TEXT NOT NULL,
    score_json TEXT NOT NULL,
    state TEXT NOT NULL,
    artifact_ref TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    promoted_at TEXT,
    certification_status TEXT,
    certification_artifact_ref TEXT,
    UNIQUE(campaign_id, graph_sha256)
);

CREATE INDEX IF NOT EXISTS idx_campaign_candidates_score
    ON campaign_candidates(campaign_id, state, created_at);

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

APP_SERVER_COMPLIANCE_SCHEMA_SQL = """
ALTER TABLE app_server_turns
    ADD COLUMN cache_write_input_tokens INTEGER;
ALTER TABLE app_server_turns
    ADD COLUMN final_agent_item_id TEXT;
PRAGMA user_version=8;
"""

APP_SERVER_TURN_LIFECYCLE_COLUMNS = {
    "lifecycle_status": "TEXT NOT NULL DEFAULT 'requested'",
    "request_id": "TEXT",
    "item_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "item_types_json": "TEXT NOT NULL DEFAULT '{}'",
    "reasoning_item_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "latest_event_sequence": "INTEGER NOT NULL DEFAULT 0",
    "latest_event_at": "TEXT",
    "turn_started_at": "TEXT",
    "terminal_reason": "TEXT",
    "evidence_registry_artifact_ref": "TEXT",
    "evidence_registry_sha256": "TEXT",
}

APP_SERVER_TURN_LIFECYCLE_SCHEMA_SQL = """
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
"""

COMPARISON_SCHEMA_SQL = """
CREATE TABLE comparison_fixtures (
    fixture_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    fixture_type TEXT NOT NULL,
    source_artifact_reference TEXT NOT NULL,
    fixture_sha256 TEXT NOT NULL,
    director_state_schema_version TEXT NOT NULL,
    target_statement_id TEXT NOT NULL,
    status_timestamp TEXT NOT NULL,
    serialized_bytes INTEGER NOT NULL,
    estimated_client_owned_tokens INTEGER NOT NULL,
    director_state_json TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    output_schema_sha256 TEXT NOT NULL,
    applicable_action_space_sha256 TEXT NOT NULL,
    evidence_registry_sha256 TEXT NOT NULL,
    advisory_registry_sha256 TEXT NOT NULL,
    executable_registry_sha256 TEXT NOT NULL,
    base_instructions_sha256 TEXT NOT NULL,
    developer_instructions_sha256 TEXT NOT NULL,
    personality TEXT,
    campaign_budget_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(fixture_type IN (
        'preserved_director_state',
        'campaign_snapshot',
        'custom_director_state_json'
    )),
    CHECK(serialized_bytes >= 0),
    CHECK(estimated_client_owned_tokens >= 0)
);

CREATE TABLE comparison_suites (
    suite_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    fixture_type TEXT NOT NULL,
    fixture_reference TEXT NOT NULL REFERENCES comparison_fixtures(fixture_id),
    fixture_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    status TEXT NOT NULL,
    measurement_only INTEGER NOT NULL DEFAULT 1,
    execute_decisions INTEGER NOT NULL DEFAULT 0,
    randomized_arm_order INTEGER NOT NULL DEFAULT 0,
    ordering_seed INTEGER,
    planned_inference_count INTEGER NOT NULL,
    maximum_inference_starts INTEGER NOT NULL,
    maximum_total_server_tokens INTEGER,
    maximum_client_owned_tokens_per_turn INTEGER NOT NULL DEFAULT 12000,
    timeout_seconds INTEGER NOT NULL,
    fail_closed INTEGER NOT NULL DEFAULT 1,
    plan_fingerprint TEXT,
    authorization_status TEXT NOT NULL DEFAULT 'unauthorized',
    consumed_inference_starts INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    read_only INTEGER NOT NULL DEFAULT 0,
    runtime_executed_elsewhere INTEGER NOT NULL DEFAULT 0,
    recommendation_status TEXT,
    recommendation_basis TEXT,
    started_at TEXT,
    completed_at TEXT,
    failure_reason TEXT,
    CHECK(status IN (
        'draft', 'prepared', 'authorized', 'running',
        'completed', 'failed', 'stopped'
    )),
    CHECK(measurement_only IN (0, 1)),
    CHECK(execute_decisions IN (0, 1)),
    CHECK(randomized_arm_order IN (0, 1)),
    CHECK(fail_closed IN (0, 1)),
    CHECK(read_only IN (0, 1)),
    CHECK(runtime_executed_elsewhere IN (0, 1)),
    CHECK(planned_inference_count >= 0),
    CHECK(maximum_inference_starts >= 0),
    CHECK(consumed_inference_starts >= 0),
    CHECK(timeout_seconds BETWEEN 1 AND 900)
);

CREATE TABLE model_cost_profiles (
    profile_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    display_name TEXT NOT NULL,
    relative_cost_multiplier REAL NOT NULL,
    api_input_per_million REAL,
    api_cached_input_per_million REAL,
    api_output_per_million REAL,
    currency TEXT,
    source_label TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    CHECK(relative_cost_multiplier >= 0),
    CHECK(enabled IN (0, 1))
);

CREATE INDEX idx_model_cost_profiles_lookup
    ON model_cost_profiles(model, reasoning_effort, enabled, effective_from);

CREATE TABLE comparison_arms (
    arm_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES comparison_suites(suite_id),
    display_name TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    context_mode TEXT NOT NULL,
    repetition_index INTEGER NOT NULL,
    planned_order INTEGER NOT NULL,
    effective_order INTEGER,
    expected_model TEXT NOT NULL,
    expected_reasoning_effort TEXT NOT NULL,
    effective_model TEXT,
    effective_reasoning_effort TEXT,
    effective_context_mode TEXT,
    model_contract_matched INTEGER,
    prompt_sha256 TEXT NOT NULL,
    director_state_sha256 TEXT NOT NULL,
    output_schema_sha256 TEXT NOT NULL,
    evidence_registry_sha256 TEXT NOT NULL,
    advisory_registry_sha256 TEXT NOT NULL,
    executable_registry_sha256 TEXT NOT NULL,
    applicable_action_space_sha256 TEXT NOT NULL,
    base_instructions_sha256 TEXT NOT NULL,
    developer_instructions_sha256 TEXT NOT NULL,
    campaign_budget_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    cost_profile_id TEXT REFERENCES model_cost_profiles(profile_id),
    relative_cost_multiplier_snapshot REAL,
    api_input_per_million_snapshot REAL,
    api_cached_input_per_million_snapshot REAL,
    api_output_per_million_snapshot REAL,
    currency_snapshot TEXT,
    CHECK(context_mode IN (
        'persistent_thread', 'compacted_thread', 'stateless_turns'
    )),
    CHECK(status IN (
        'planned', 'preflight', 'inference_started', 'completed',
        'schema_invalid', 'semantic_invalid', 'timed_out', 'aborted', 'failed'
    )),
    CHECK(repetition_index >= 0),
    CHECK(planned_order >= 0),
    UNIQUE(suite_id, planned_order)
);

CREATE INDEX idx_comparison_arms_suite
    ON comparison_arms(suite_id, effective_order, planned_order);

CREATE TABLE comparison_turns (
    comparison_turn_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES comparison_suites(suite_id),
    arm_id TEXT NOT NULL REFERENCES comparison_arms(arm_id),
    app_server_turn_record_id TEXT REFERENCES app_server_turns(turn_record_id),
    lifecycle_status TEXT NOT NULL,
    thread_lifecycle TEXT,
    schema_valid INTEGER,
    semantic_valid INTEGER,
    evidence_references_valid INTEGER,
    action_inside_applicable_space INTEGER,
    executable_targets_valid INTEGER,
    implemented_parameters_only INTEGER,
    budgets_respected INTEGER,
    no_false_counterexample_claim INTEGER,
    no_tool_request INTEGER,
    no_code_request INTEGER,
    no_shell_request INTEGER,
    no_measurement_execution_request INTEGER,
    selected_action TEXT,
    selected_algorithm TEXT,
    selected_parameters_json TEXT,
    raw_decision_json TEXT,
    normalized_decision_json TEXT,
    validation_issues_json TEXT NOT NULL DEFAULT '[]',
    applicable_action_space_json TEXT,
    active_executable_lane_count INTEGER NOT NULL DEFAULT 0,
    active_candidate_target_count INTEGER NOT NULL DEFAULT 0,
    historical_evidence_target_count INTEGER NOT NULL DEFAULT 0,
    measurement_only INTEGER NOT NULL,
    executed INTEGER NOT NULL,
    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    cache_write_input_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_output_tokens INTEGER,
    server_reported_total_tokens INTEGER,
    first_item_latency_seconds REAL,
    final_answer_latency_seconds REAL,
    total_wall_seconds REAL,
    retry_count_reaching_inference INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    validation_issue_count INTEGER NOT NULL DEFAULT 0,
    decision_batch_id TEXT,
    resulting_metric_window_id TEXT,
    best_score_before REAL,
    best_score_after REAL,
    time_to_improvement REAL,
    candidate_evaluations INTEGER,
    cpu_seconds REAL,
    exact_verifier_result TEXT,
    cost_profile_id TEXT REFERENCES model_cost_profiles(profile_id),
    relative_cost_multiplier_snapshot REAL,
    api_input_per_million_snapshot REAL,
    api_cached_input_per_million_snapshot REAL,
    api_output_per_million_snapshot REAL,
    currency_snapshot TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK(measurement_only IN (0, 1)),
    CHECK(executed IN (0, 1)),
    CHECK(retry_count_reaching_inference >= 0),
    CHECK(tool_call_count >= 0),
    UNIQUE(arm_id)
);

CREATE INDEX idx_comparison_turns_suite
    ON comparison_turns(suite_id, created_at);

CREATE TABLE manual_ratings (
    rating_id TEXT PRIMARY KEY,
    comparison_turn_id TEXT NOT NULL
        REFERENCES comparison_turns(comparison_turn_id),
    scientific_usefulness INTEGER NOT NULL,
    clarity INTEGER NOT NULL,
    novelty INTEGER NOT NULL,
    would_execute TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(scientific_usefulness BETWEEN 1 AND 5),
    CHECK(clarity BETWEEN 1 AND 5),
    CHECK(novelty BETWEEN 1 AND 5),
    CHECK(would_execute IN ('yes', 'no', 'uncertain'))
);

CREATE INDEX idx_manual_ratings_turn
    ON manual_ratings(comparison_turn_id, created_at);

CREATE TABLE pairwise_ratings (
    rating_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES comparison_suites(suite_id),
    left_turn_id TEXT NOT NULL REFERENCES comparison_turns(comparison_turn_id),
    right_turn_id TEXT NOT NULL REFERENCES comparison_turns(comparison_turn_id),
    preferred TEXT NOT NULL,
    comment TEXT NOT NULL,
    blind_order_seed INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(preferred IN ('left', 'equal', 'right', 'skip')),
    CHECK(left_turn_id <> right_turn_id)
);

CREATE INDEX idx_pairwise_ratings_suite
    ON pairwise_ratings(suite_id, created_at);

CREATE TABLE comparison_authorizations (
    authorization_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES comparison_suites(suite_id),
    plan_fingerprint TEXT NOT NULL,
    maximum_inference_starts INTEGER NOT NULL,
    authorized_models TEXT NOT NULL,
    authorized_efforts TEXT NOT NULL,
    authorized_context_modes TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    consumed_inference_starts INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT,
    completed_at TEXT,
    CHECK(maximum_inference_starts >= 0),
    CHECK(consumed_inference_starts >= 0)
);

CREATE INDEX idx_comparison_authorizations_suite
    ON comparison_authorizations(suite_id, authorized_at);

PRAGMA user_version=10;
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
        version = 7
    _ensure_m6_lane_columns(connection)
    _ensure_m6_candidate_table(connection)
    _ensure_app_server_compliance_columns(connection)
    _ensure_app_server_turn_lifecycle_columns(connection)
    _ensure_comparison_schema(connection)


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
def _ensure_m6_candidate_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS campaign_candidates (
            candidate_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES research_campaigns(campaign_id),
            lane_id TEXT NOT NULL REFERENCES research_lanes(lane_id),
            lane_version INTEGER NOT NULL,
            checkpoint_ref TEXT,
            graph6 TEXT NOT NULL,
            graph_sha256 TEXT NOT NULL,
            score_json TEXT NOT NULL,
            state TEXT NOT NULL,
            artifact_ref TEXT NOT NULL,
            artifact_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            promoted_at TEXT,
            certification_status TEXT,
            certification_artifact_ref TEXT,
            UNIQUE(campaign_id, graph_sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_candidates_score
            ON campaign_candidates(campaign_id, state, created_at);
        """
    )
    connection.commit()


def _ensure_app_server_compliance_columns(
    connection: sqlite3.Connection,
) -> None:
    exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='app_server_turns'
        """
    ).fetchone()
    if exists is not None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(app_server_turns)")
        }
        missing = {
            "cache_write_input_tokens",
            "final_agent_item_id",
        } - columns
        if missing == {"cache_write_input_tokens", "final_agent_item_id"}:
            connection.executescript(APP_SERVER_COMPLIANCE_SCHEMA_SQL)
        elif "cache_write_input_tokens" in missing:
            connection.execute(
                "ALTER TABLE app_server_turns "
                "ADD COLUMN cache_write_input_tokens INTEGER"
            )
        elif "final_agent_item_id" in missing:
            connection.execute(
                "ALTER TABLE app_server_turns ADD COLUMN final_agent_item_id TEXT"
            )
    connection.commit()


def _ensure_app_server_turn_lifecycle_columns(
    connection: sqlite3.Connection,
) -> None:
    exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='app_server_turns'
        """
    ).fetchone()
    if exists is not None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(app_server_turns)")
        }
        lifecycle_added = "lifecycle_status" not in columns
        for name, definition in APP_SERVER_TURN_LIFECYCLE_COLUMNS.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE app_server_turns "
                    f"ADD COLUMN {name} {definition}"
                )
        if lifecycle_added:
            connection.execute(
                """
                UPDATE app_server_turns
                SET lifecycle_status=CASE
                    WHEN status IN ('completed', 'completed_valid',
                                    'completed_invalid') THEN 'completed'
                    WHEN status='failed_interrupted' THEN 'aborted'
                    WHEN status='failed' THEN 'failed'
                    WHEN status='in_progress' THEN 'in_progress'
                    ELSE lifecycle_status
                END,
                turn_started_at=CASE
                    WHEN turn_id IS NOT NULL AND turn_started_at IS NULL
                    THEN started_at
                    ELSE turn_started_at
                END
                """
            )
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) < 9:
        connection.execute("PRAGMA user_version=9")
    connection.commit()


def _ensure_comparison_schema(connection: sqlite3.Connection) -> None:
    additions = {
        "research_campaigns": {
            "effective_context_mode": "TEXT",
            "context_recommendation_basis": "TEXT",
        },
        "app_server_sessions": {"context_mode": "TEXT"},
        "app_server_turns": {"thread_lifecycle": "TEXT"},
    }
    for table, columns in additions.items():
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists is None:
            continue
        present = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for name, definition in columns.items():
            if name not in present:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                )
    exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='comparison_suites'
        """
    ).fetchone()
    if exists is None:
        connection.executescript(COMPARISON_SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
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

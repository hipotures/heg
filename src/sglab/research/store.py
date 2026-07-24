from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
import json
import sqlite3
import threading
import uuid

from ..db import connect
from ..state import utc_now


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class ResearchStore:
    """Authoritative single-writer facade for Active Director state."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.connection = connect(self.path)
        self._writer_thread = threading.get_ident()

    def _require_writer(self) -> None:
        if threading.get_ident() != self._writer_thread:
            raise RuntimeError("ResearchStore writes must use the owning thread")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._require_writer()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def create_campaign(
        self,
        *,
        campaign_id: str,
        target: str,
        target_definition_sha256: str,
        stop_mode: str,
        deadline_at: str | None,
    ) -> None:
        if stop_mode not in {"time_limit", "until_success"}:
            raise ValueError("invalid campaign stop mode")
        if (stop_mode == "time_limit") != (deadline_at is not None):
            raise ValueError("time_limit requires and until_success forbids deadline_at")
        now = utc_now()
        with self.transaction() as database:
            database.execute(
                """
                INSERT INTO research_campaigns
                (campaign_id, created_at, updated_at, target,
                 target_definition_sha256, state, state_version, stop_mode,
                 deadline_at)
                VALUES (?, ?, ?, ?, ?, 'running', 0, ?, ?)
                """,
                (
                    campaign_id,
                    now,
                    now,
                    target,
                    target_definition_sha256,
                    stop_mode,
                    deadline_at,
                ),
            )

    def campaign(self, campaign_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM research_campaigns WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            raise KeyError(campaign_id)
        return dict(row)

    def transition_campaign(
        self,
        campaign_id: str,
        *,
        expected_version: int,
        state: str,
        fault_kind: str | None = None,
        fault_detail: str | None = None,
    ) -> int:
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE research_campaigns
                SET state=?, state_version=state_version+1, updated_at=?,
                    fault_kind=?, fault_detail=?
                WHERE campaign_id=? AND state_version=?
                """,
                (
                    state,
                    utc_now(),
                    fault_kind,
                    fault_detail,
                    campaign_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("stale campaign state")
            return expected_version + 1

    def record_snapshot(
        self,
        *,
        snapshot_id: str,
        campaign_id: str,
        campaign_state_version: int,
        high_water: dict[str, Any],
        artifact_ref: str,
        artifact_sha256: str,
        payload_bytes: int,
    ) -> None:
        with self.transaction() as database:
            current = database.execute(
                "SELECT state_version FROM research_campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            if current is None or int(current[0]) != campaign_state_version:
                raise RuntimeError("cannot commit snapshot from stale campaign state")
            database.execute(
                """
                INSERT INTO director_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    campaign_id,
                    campaign_state_version,
                    json.dumps(high_water, sort_keys=True),
                    artifact_ref,
                    artifact_sha256,
                    payload_bytes,
                    utc_now(),
                ),
            )

    def record_trigger(
        self,
        *,
        trigger_id: str,
        campaign_id: str,
        campaign_state_version: int,
        reasons: list[str],
        first_event_at: str,
        snapshot_id: str,
        status: str = "committed",
    ) -> None:
        with self.transaction() as database:
            database.execute(
                """
                INSERT INTO director_triggers VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trigger_id,
                    campaign_id,
                    campaign_state_version,
                    json.dumps(sorted(set(reasons))),
                    first_event_at,
                    utc_now(),
                    snapshot_id,
                    status,
                ),
            )

    def mark_trigger_status(self, trigger_id: str, status: str) -> None:
        with self.transaction() as database:
            cursor = database.execute(
                "UPDATE director_triggers SET status=? WHERE trigger_id=?",
                (status, trigger_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(trigger_id)

    def record_session(
        self,
        *,
        record_id: str,
        campaign_id: str,
        thread_id: str,
        session_id: str | None,
        thread_path: str | None,
        parent_thread_id: str | None,
        model: str | None,
        effort: str,
        codex_version: str,
        executable_sha256: str,
        protocol_schema_sha256: str,
        resumed: bool = False,
    ) -> str:
        now = utc_now()
        with self.transaction() as database:
            existing = database.execute(
                """
                SELECT session_record_id FROM app_server_sessions
                WHERE campaign_id=? AND thread_id=?
                """,
                (campaign_id, thread_id),
            ).fetchone()
            if existing is not None:
                if not resumed:
                    raise RuntimeError("app-server thread is already recorded")
                existing_id = str(existing[0])
                database.execute(
                    """
                    UPDATE app_server_sessions
                    SET app_server_session_id=?, thread_path=?, state='active',
                        last_resumed_at=?, closed_at=NULL
                    WHERE session_record_id=?
                    """,
                    (session_id, thread_path, now, existing_id),
                )
                return existing_id
            database.execute(
                """
                INSERT INTO app_server_sessions
                (session_record_id, campaign_id, thread_id,
                 app_server_session_id, thread_path, parent_thread_id,
                 model_requested, effort_requested, codex_version,
                 codex_executable_sha256, protocol_schema_sha256, state,
                 started_at, last_resumed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    record_id,
                    campaign_id,
                    thread_id,
                    session_id,
                    thread_path,
                    parent_thread_id,
                    model,
                    effort,
                    codex_version,
                    executable_sha256,
                    protocol_schema_sha256,
                    now,
                    now if resumed else None,
                ),
            )
            return record_id

    def begin_turn(
        self,
        *,
        turn_record_id: str,
        session_record_id: str,
        campaign_id: str,
        thread_id: str,
        snapshot_id: str,
        trigger_id: str,
        request_artifact_ref: str,
        request_sha256: str,
        wire_artifact_ref: str,
    ) -> None:
        with self.transaction() as database:
            database.execute(
                """
                INSERT INTO app_server_turns
                (turn_record_id, session_record_id, campaign_id, thread_id,
                 snapshot_id, trigger_id, status, request_artifact_ref,
                 request_sha256, wire_log_artifact_ref, started_at)
                VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?)
                """,
                (
                    turn_record_id,
                    session_record_id,
                    campaign_id,
                    thread_id,
                    snapshot_id,
                    trigger_id,
                    request_artifact_ref,
                    request_sha256,
                    wire_artifact_ref,
                    utc_now(),
                ),
            )

    def complete_turn(
        self,
        turn_record_id: str,
        *,
        turn_id: str | None,
        status: str,
        response_artifact_ref: str | None = None,
        response_sha256: str | None = None,
        wire_sha256: str | None = None,
        usage: dict[str, Any] | None = None,
        wall_seconds: float | None = None,
        error_kind: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        normalized = usage or {}
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE app_server_turns
                SET turn_id=?, status=?, response_artifact_ref=?,
                    response_sha256=?, wire_log_sha256=?,
                    input_tokens=?, cached_input_tokens=?, output_tokens=?,
                    reasoning_output_tokens=?, total_tokens=?,
                    raw_usage_json=?, wall_seconds=?, error_kind=?,
                    error_detail=?, completed_at=?
                WHERE turn_record_id=? AND status='in_progress'
                """,
                (
                    turn_id,
                    status,
                    response_artifact_ref,
                    response_sha256,
                    wire_sha256,
                    normalized.get("input_tokens"),
                    normalized.get("cached_input_tokens"),
                    normalized.get("output_tokens"),
                    normalized.get("reasoning_output_tokens"),
                    normalized.get("total_tokens"),
                    json.dumps(normalized.get("raw"), sort_keys=True)
                    if normalized.get("raw") is not None
                    else None,
                    wall_seconds,
                    error_kind,
                    error_detail,
                    utc_now(),
                    turn_record_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("turn completion is stale or duplicated")

    def commit_decision_batch(
        self,
        *,
        decision_batch_id: str,
        campaign_id: str,
        snapshot_id: str,
        trigger_id: str,
        turn_record_id: str,
        decision: dict[str, Any],
    ) -> dict[str, str]:
        """Commit validated actions, rejecting races without silent rebasing."""

        now = utc_now()
        statuses: dict[str, str] = {}
        with self.transaction() as database:
            turn = database.execute(
                """
                SELECT status FROM app_server_turns
                WHERE turn_record_id=? AND campaign_id=? AND snapshot_id=?
                """,
                (turn_record_id, campaign_id, snapshot_id),
            ).fetchone()
            if turn is None or turn["status"] != "completed_valid":
                raise RuntimeError("decision source turn is not completed_valid")
            snapshot = database.execute(
                """
                SELECT campaign_state_version FROM director_snapshots
                WHERE snapshot_id=? AND campaign_id=?
                """,
                (snapshot_id, campaign_id),
            ).fetchone()
            campaign = database.execute(
                """
                SELECT state_version FROM research_campaigns
                WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()
            if snapshot is None or campaign is None:
                raise RuntimeError("decision references missing durable state")
            campaign_is_fresh = int(snapshot[0]) == int(campaign[0])
            database.execute(
                """
                INSERT INTO director_action_batches
                (decision_batch_id, campaign_id, snapshot_id, trigger_id,
                 turn_record_id, campaign_assessment, next_review_json,
                 validation_status, response_artifact_ref, response_sha256,
                 created_at)
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, response_artifact_ref,
                       response_sha256, ?
                FROM app_server_turns WHERE turn_record_id=?
                """,
                (
                    decision_batch_id,
                    campaign_id,
                    snapshot_id,
                    trigger_id,
                    turn_record_id,
                    decision["campaign_assessment"],
                    json.dumps(decision["next_review"], sort_keys=True),
                    "accepted" if campaign_is_fresh else "rejected_stale_campaign",
                    now,
                    turn_record_id,
                ),
            )
            for action in decision["actions"]:
                action_id = str(action["action_id"])
                duplicate = database.execute(
                    """
                    SELECT action_id FROM director_actions
                    WHERE idempotency_key=?
                    """,
                    (action["idempotency_key"],),
                ).fetchone()
                if duplicate is not None:
                    statuses[action_id] = "rejected_duplicate_idempotency"
                    continue
                status = (
                    "accepted"
                    if campaign_is_fresh
                    else "rejected_stale_campaign"
                )
                stale_detail = None
                targets = _action_lane_targets(action)
                for lane_id, expected_version in targets:
                    lane = database.execute(
                        """
                        SELECT lane_version, state FROM research_lanes
                        WHERE lane_id=? AND campaign_id=?
                        """,
                        (lane_id, campaign_id),
                    ).fetchone()
                    if (
                        lane is None
                        or lane["state"] not in {"starting", "running", "paused"}
                        or int(lane["lane_version"]) != expected_version
                    ):
                        status = "rejected_stale_state"
                        stale_detail = (
                            f"lane {lane_id} no longer has version "
                            f"{expected_version}"
                        )
                        break
                expires = (
                    datetime.now(UTC)
                    + timedelta(seconds=int(action["lease_seconds"]))
                ).isoformat(timespec="seconds").replace("+00:00", "Z")
                target_lane_id = (
                    str(action.get("lane_id"))
                    if action.get("lane_id") is not None
                    else None
                )
                expected_lane_version = (
                    int(action["expected_lane_version"])
                    if action.get("expected_lane_version") is not None
                    else None
                )
                parameters = {
                    key: value
                    for key, value in action.items()
                    if key
                    not in {
                        "action_id",
                        "type",
                        "priority",
                        "hypothesis_ids",
                        "evidence_ids",
                        "rationale",
                        "expected_effect",
                        "evaluation_window",
                        "idempotency_key",
                        "lease_seconds",
                        "fallback",
                        "lane_id",
                        "expected_lane_version",
                    }
                }
                database.execute(
                    """
                    INSERT INTO director_actions
                    (action_id, decision_batch_id, campaign_id, action_type,
                     priority, target_lane_id, expected_lane_version,
                     hypothesis_ids_json, evidence_ids_json, parameters_json,
                     rationale, expected_effect, evaluation_window_json,
                     fallback_json, idempotency_key, lease_expires_at,
                     validation_status, validation_detail, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?)
                    """,
                    (
                        action_id,
                        decision_batch_id,
                        campaign_id,
                        action["type"],
                        action["priority"],
                        target_lane_id,
                        expected_lane_version,
                        json.dumps(action["hypothesis_ids"], sort_keys=True),
                        json.dumps(action["evidence_ids"], sort_keys=True),
                        json.dumps(parameters, sort_keys=True),
                        action["rationale"],
                        action["expected_effect"],
                        json.dumps(action["evaluation_window"], sort_keys=True),
                        json.dumps(action["fallback"], sort_keys=True),
                        action["idempotency_key"],
                        expires,
                        status,
                        stale_detail,
                        now,
                    ),
                )
                statuses[action_id] = status
            for update in decision["hypothesis_updates"]:
                previous = database.execute(
                    """
                    SELECT hypothesis_revision_id
                    FROM research_hypotheses_v2
                    WHERE campaign_id=? AND hypothesis_id=?
                    ORDER BY created_at DESC, rowid DESC LIMIT 1
                    """,
                    (campaign_id, update["hypothesis_id"]),
                ).fetchone()
                database.execute(
                    """
                    INSERT INTO research_hypotheses_v2
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("hyp-revision"),
                        update["hypothesis_id"],
                        campaign_id,
                        str(previous[0]) if previous is not None else None,
                        update["statement"],
                        update["confidence"],
                        update["operation"],
                        json.dumps(update["evidence_for"], sort_keys=True),
                        json.dumps(update["evidence_against"], sort_keys=True),
                        decision_batch_id,
                        now,
                    ),
                )
            if any(status != "accepted" for status in statuses.values()):
                database.execute(
                    """
                    UPDATE director_action_batches
                    SET validation_status=?
                    WHERE decision_batch_id=?
                    """,
                    (
                        "partial_rejected"
                        if any(status == "accepted" for status in statuses.values())
                        else "rejected",
                        decision_batch_id,
                    ),
                )
            if campaign_is_fresh:
                database.execute(
                    """
                    UPDATE research_campaigns
                    SET state_version=state_version+1, updated_at=?
                    WHERE campaign_id=?
                    """,
                    (now, campaign_id),
                )
            database.execute(
                "UPDATE director_triggers SET status='decided' WHERE trigger_id=?",
                (trigger_id,),
            )
        return statuses

    def create_lane(
        self,
        *,
        lane_id: str,
        campaign_id: str,
        target: str,
        parent_lane_id: str | None,
        parent_checkpoint_ref: str | None,
        action_id: str,
        algorithm: str,
        graph_family: str,
        parameters: dict[str, Any],
        seed_lineage: list[int],
        resource_share: float,
        lease_expires_at: str | None,
    ) -> None:
        now = utc_now()
        with self.transaction() as database:
            database.execute(
                """
                INSERT INTO research_lanes
                (lane_id, campaign_id, target, parent_lane_id,
                 parent_checkpoint_ref, created_by_action_id, state,
                 lane_version, algorithm, graph_family,
                 current_parameters_json, seed_lineage_json, checkpoint_ref,
                 checkpoint_sha256, telemetry_high_water, resource_share,
                 lease_expires_at, process_generation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'starting', 0, ?, ?, ?, ?, NULL,
                        NULL, 0, ?, ?, 0, ?, ?)
                """,
                (
                    lane_id,
                    campaign_id,
                    target,
                    parent_lane_id,
                    parent_checkpoint_ref,
                    action_id,
                    algorithm,
                    graph_family,
                    json.dumps(parameters, sort_keys=True),
                    json.dumps(seed_lineage),
                    resource_share,
                    lease_expires_at,
                    now,
                    now,
                ),
            )

    def mark_lane_running(self, lane_id: str) -> None:
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE research_lanes SET state='running', updated_at=?
                WHERE lane_id=? AND state='starting'
                """,
                (utc_now(), lane_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("lane start completion is stale")

    def record_lane_checkpoint(
        self,
        *,
        lane_id: str,
        lane_version: int,
        checkpoint_ref: str,
        checkpoint_sha256: str,
        high_water: int,
    ) -> bool:
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE research_lanes
                SET checkpoint_ref=?, checkpoint_sha256=?,
                    telemetry_high_water=MAX(telemetry_high_water, ?),
                    updated_at=?
                WHERE lane_id=? AND lane_version=?
                """,
                (
                    checkpoint_ref,
                    checkpoint_sha256,
                    high_water,
                    utc_now(),
                    lane_id,
                    lane_version,
                ),
            )
            return cursor.rowcount == 1

    def mark_lane_birth_failed(self, action_id: str, detail: str) -> int:
        with self.transaction() as database:
            rows = database.execute(
                """
                SELECT campaign_id FROM research_lanes
                WHERE created_by_action_id=? AND state='starting'
                """,
                (action_id,),
            ).fetchall()
            cursor = database.execute(
                """
                UPDATE research_lanes
                SET state='failed', updated_at=?, stopped_at=?
                WHERE created_by_action_id=? AND state='starting'
                """,
                (utc_now(), utc_now(), action_id),
            )
            if rows:
                database.execute(
                    """
                    UPDATE research_campaigns
                    SET state_version=state_version+1, updated_at=?,
                        fault_kind='lane_start_failure', fault_detail=?
                    WHERE campaign_id=?
                    """,
                    (utc_now(), detail[:2000], rows[0]["campaign_id"]),
                )
            return cursor.rowcount

    def record_lane_exit(
        self,
        *,
        lane_id: str,
        lane_version: int,
        failed: bool,
        detail: str | None,
    ) -> bool:
        state = "failed" if failed else "stopped"
        with self.transaction() as database:
            lane = database.execute(
                "SELECT campaign_id, state FROM research_lanes WHERE lane_id=?",
                (lane_id,),
            ).fetchone()
            if lane is None:
                return False
            cursor = database.execute(
                """
                UPDATE research_lanes
                SET state=?, updated_at=?, stopped_at=?
                WHERE lane_id=? AND lane_version=?
                  AND state NOT IN ('failed', 'stopped')
                """,
                (state, utc_now(), utc_now(), lane_id, lane_version),
            )
            if cursor.rowcount and failed:
                database.execute(
                    """
                    UPDATE research_campaigns
                    SET state_version=state_version+1, updated_at=?,
                        fault_kind='lane_failure', fault_detail=?
                    WHERE campaign_id=?
                    """,
                    (utc_now(), (detail or "lane failed")[:2000], lane["campaign_id"]),
                )
            return cursor.rowcount == 1

    def record_lane_metric_window(
        self,
        *,
        metric_window_id: str,
        lane_id: str,
        campaign_id: str,
        lane_version: int,
        start_high_water: int,
        end_high_water: int,
        started_at: str,
        ended_at: str,
        metrics: dict[str, Any],
        retention: int = 120,
    ) -> bool:
        if retention < 2:
            raise ValueError("metric retention must be at least 2")
        with self.transaction() as database:
            lane = database.execute(
                """
                SELECT lane_version, telemetry_high_water FROM research_lanes
                WHERE lane_id=? AND campaign_id=?
                """,
                (lane_id, campaign_id),
            ).fetchone()
            if lane is None or int(lane["lane_version"]) != lane_version:
                return False
            database.execute(
                """
                INSERT OR IGNORE INTO lane_metric_windows
                (metric_window_id, lane_id, campaign_id, lane_version,
                 start_high_water, end_high_water, start_at, end_at,
                 metrics_json, artifact_ref, artifact_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    metric_window_id,
                    lane_id,
                    campaign_id,
                    lane_version,
                    start_high_water,
                    end_high_water,
                    started_at,
                    ended_at,
                    json.dumps(metrics, sort_keys=True),
                ),
            )
            database.execute(
                """
                UPDATE research_lanes
                SET telemetry_high_water=MAX(telemetry_high_water, ?),
                    updated_at=?
                WHERE lane_id=?
                """,
                (end_high_water, utc_now(), lane_id),
            )
            database.execute(
                """
                DELETE FROM lane_metric_windows
                WHERE lane_id=?
                  AND metric_window_id NOT IN (
                    SELECT metric_window_id FROM lane_metric_windows
                    WHERE lane_id=? ORDER BY end_high_water DESC LIMIT ?
                  )
                  AND metric_window_id NOT IN (
                    SELECT pre_window_id FROM director_action_outcomes
                    WHERE pre_window_id IS NOT NULL
                    UNION
                    SELECT post_window_id FROM director_action_outcomes
                    WHERE post_window_id IS NOT NULL
                  )
                """,
                (lane_id, lane_id, retention),
            )
            return True

    def complete_lane_births(
        self,
        *,
        action_id: str,
        lane_ids: list[str],
        observed_effect: dict[str, Any],
    ) -> bool:
        """Atomically mark all children ready and complete start/fork."""

        with self.transaction() as database:
            if database.execute(
                "SELECT 1 FROM director_action_outcomes WHERE action_id=?",
                (action_id,),
            ).fetchone():
                return False
            action = database.execute(
                "SELECT campaign_id FROM director_actions WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if action is None:
                raise KeyError(action_id)
            if not lane_ids:
                raise ValueError("lane birth outcome requires a lane")
            placeholders = ",".join("?" for _ in lane_ids)
            rows = database.execute(
                f"""
                SELECT lane_id, state FROM research_lanes
                WHERE campaign_id=? AND lane_id IN ({placeholders})
                """,
                (action["campaign_id"], *lane_ids),
            ).fetchall()
            if len(rows) != len(lane_ids) or any(
                row["state"] != "starting" for row in rows
            ):
                raise RuntimeError("lane birth completion is stale")
            database.execute(
                f"""
                UPDATE research_lanes SET state='running', updated_at=?
                WHERE lane_id IN ({placeholders})
                """,
                (utc_now(), *lane_ids),
            )
            now = utc_now()
            database.execute(
                """
                INSERT INTO director_action_outcomes
                (action_outcome_id, action_id, campaign_id,
                 application_status, resulting_lane_id,
                 resulting_lane_version, pre_window_id, post_window_id,
                 observed_effect_json, expectation_met, failure_kind,
                 failure_detail, applied_at, evaluated_at)
                VALUES (?, ?, ?, 'applied', ?, 0, NULL, NULL, ?, NULL,
                        NULL, NULL, ?, NULL)
                """,
                (
                    new_id("action-outcome"),
                    action_id,
                    action["campaign_id"],
                    lane_ids[0],
                    json.dumps(observed_effect, sort_keys=True),
                    now,
                ),
            )
            database.execute(
                """
                UPDATE research_campaigns
                SET state_version=state_version+1, updated_at=?
                WHERE campaign_id=?
                """,
                (now, action["campaign_id"]),
            )
            return True

    def record_action_outcome(
        self,
        *,
        action_id: str,
        status: str,
        resulting_lane_id: str | None = None,
        resulting_lane_version: int | None = None,
        failure_kind: str | None = None,
        failure_detail: str | None = None,
        observed_effect: dict[str, Any] | None = None,
    ) -> bool:
        """Record an idempotent outcome for an action without a lane revision."""

        with self.transaction() as database:
            if database.execute(
                "SELECT 1 FROM director_action_outcomes WHERE action_id=?",
                (action_id,),
            ).fetchone():
                return False
            action = database.execute(
                "SELECT campaign_id FROM director_actions WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if action is None:
                raise KeyError(action_id)
            applied = status == "applied"
            now = utc_now()
            database.execute(
                """
                INSERT INTO director_action_outcomes
                (action_outcome_id, action_id, campaign_id,
                 application_status, resulting_lane_id,
                 resulting_lane_version, pre_window_id, post_window_id,
                 observed_effect_json, expectation_met, failure_kind,
                 failure_detail, applied_at, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?, ?, NULL)
                """,
                (
                    new_id("action-outcome"),
                    action_id,
                    action["campaign_id"],
                    status,
                    resulting_lane_id,
                    resulting_lane_version,
                    json.dumps(observed_effect, sort_keys=True)
                    if observed_effect is not None
                    else None,
                    failure_kind,
                    failure_detail,
                    now if applied else None,
                ),
            )
            if applied:
                database.execute(
                    """
                    UPDATE research_campaigns
                    SET state_version=state_version+1, updated_at=?
                    WHERE campaign_id=?
                    """,
                    (now, action["campaign_id"]),
                )
            return True

    def apply_lane_action_outcome(
        self,
        *,
        action_id: str,
        status: str,
        resulting_lane_id: str | None,
        resulting_lane_version: int | None,
        checkpoint_ref: str | None,
        checkpoint_sha256: str | None,
        parameters: dict[str, Any] | None,
        resource_share: float | None,
        failure_kind: str | None = None,
        failure_detail: str | None = None,
        observed_effect: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically record one idempotent action result and lane revision."""

        with self.transaction() as database:
            if database.execute(
                "SELECT 1 FROM director_action_outcomes WHERE action_id=?",
                (action_id,),
            ).fetchone():
                return False
            action = database.execute(
                """
                SELECT campaign_id, target_lane_id, expected_lane_version,
                       action_type
                FROM director_actions WHERE action_id=?
                """,
                (action_id,),
            ).fetchone()
            if action is None:
                raise KeyError(action_id)
            applied = status == "applied"
            if applied and action["target_lane_id"] is not None:
                lane = database.execute(
                    "SELECT * FROM research_lanes WHERE lane_id=?",
                    (action["target_lane_id"],),
                ).fetchone()
                if (
                    lane is None
                    or int(lane["lane_version"])
                    != int(action["expected_lane_version"])
                    or resulting_lane_version is None
                    or resulting_lane_version != int(lane["lane_version"]) + 1
                ):
                    status = "rejected_late_completion"
                    applied = False
                    failure_kind = "stale_lane_completion"
                    failure_detail = "lane version changed before outcome commit"
                else:
                    new_parameters = (
                        parameters
                        if parameters is not None
                        else json.loads(lane["current_parameters_json"])
                    )
                    new_share = (
                        resource_share
                        if resource_share is not None
                        else float(lane["resource_share"])
                    )
                    database.execute(
                        """
                        UPDATE research_lanes
                        SET lane_version=?, current_parameters_json=?,
                            resource_share=?, checkpoint_ref=?,
                            checkpoint_sha256=?, state=?, updated_at=?,
                            stopped_at=?
                        WHERE lane_id=? AND lane_version=?
                        """,
                        (
                            resulting_lane_version,
                            json.dumps(new_parameters, sort_keys=True),
                            new_share,
                            checkpoint_ref or lane["checkpoint_ref"],
                            checkpoint_sha256 or lane["checkpoint_sha256"],
                            (
                                "stopped"
                                if action["action_type"] == "stop_lane"
                                else "running"
                            ),
                            utc_now(),
                            utc_now()
                            if action["action_type"] == "stop_lane"
                            else None,
                            lane["lane_id"],
                            lane["lane_version"],
                        ),
                    )
                    database.execute(
                        """
                        INSERT INTO lane_revisions VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("lane-revision"),
                            lane["lane_id"],
                            action["campaign_id"],
                            action_id,
                            lane["lane_version"],
                            resulting_lane_version,
                            lane["current_parameters_json"],
                            json.dumps(new_parameters, sort_keys=True),
                            checkpoint_ref or lane["checkpoint_ref"] or "none",
                            checkpoint_sha256,
                            utc_now(),
                        ),
                    )
                    database.execute(
                        """
                        UPDATE research_campaigns
                        SET state_version=state_version+1, updated_at=?
                        WHERE campaign_id=?
                        """,
                        (utc_now(), action["campaign_id"]),
                    )
            database.execute(
                """
                INSERT INTO director_action_outcomes
                (action_outcome_id, action_id, campaign_id,
                 application_status, resulting_lane_id,
                 resulting_lane_version, pre_window_id, post_window_id,
                 observed_effect_json, expectation_met, failure_kind,
                 failure_detail, applied_at, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?, ?, NULL)
                """,
                (
                    new_id("action-outcome"),
                    action_id,
                    action["campaign_id"],
                    status,
                    resulting_lane_id,
                    resulting_lane_version,
                    json.dumps(observed_effect, sort_keys=True)
                    if observed_effect is not None
                    else None,
                    failure_kind,
                    failure_detail,
                    utc_now() if applied else None,
                ),
            )
            return True

    def apply_multi_lane_action_outcome(
        self,
        *,
        action_id: str,
        revisions: list[dict[str, Any]],
    ) -> bool:
        """Commit one successful multi-lane allocation as one transaction."""

        if not revisions:
            raise ValueError("multi-lane action requires revisions")
        with self.transaction() as database:
            if database.execute(
                "SELECT 1 FROM director_action_outcomes WHERE action_id=?",
                (action_id,),
            ).fetchone():
                return False
            action = database.execute(
                """
                SELECT campaign_id, action_type FROM director_actions
                WHERE action_id=?
                """,
                (action_id,),
            ).fetchone()
            if action is None:
                raise KeyError(action_id)
            if action["action_type"] != "reallocate_resources":
                raise ValueError("multi-lane completion is only for allocation")
            lane_rows: list[sqlite3.Row] = []
            for revision in revisions:
                lane = database.execute(
                    """
                    SELECT * FROM research_lanes
                    WHERE lane_id=? AND campaign_id=?
                    """,
                    (revision["lane_id"], action["campaign_id"]),
                ).fetchone()
                if (
                    lane is None
                    or int(lane["lane_version"])
                    != int(revision["expected_lane_version"])
                    or int(revision["resulting_lane_version"])
                    != int(lane["lane_version"]) + 1
                ):
                    raise RuntimeError("multi-lane completion is stale")
                lane_rows.append(lane)
            now = utc_now()
            for revision, lane in zip(revisions, lane_rows, strict=True):
                checkpoint_ref = (
                    revision.get("checkpoint_ref") or lane["checkpoint_ref"]
                )
                checkpoint_sha256 = (
                    revision.get("checkpoint_sha256")
                    or lane["checkpoint_sha256"]
                )
                database.execute(
                    """
                    UPDATE research_lanes
                    SET lane_version=?, resource_share=?, checkpoint_ref=?,
                        checkpoint_sha256=?, updated_at=?
                    WHERE lane_id=? AND lane_version=?
                    """,
                    (
                        revision["resulting_lane_version"],
                        revision["resource_share"],
                        checkpoint_ref,
                        checkpoint_sha256,
                        now,
                        lane["lane_id"],
                        lane["lane_version"],
                    ),
                )
                database.execute(
                    """
                    INSERT INTO lane_revisions VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("lane-revision"),
                        lane["lane_id"],
                        action["campaign_id"],
                        action_id,
                        lane["lane_version"],
                        revision["resulting_lane_version"],
                        lane["current_parameters_json"],
                        lane["current_parameters_json"],
                        checkpoint_ref or "none",
                        checkpoint_sha256,
                        now,
                    ),
                )
            database.execute(
                """
                INSERT INTO director_action_outcomes
                (action_outcome_id, action_id, campaign_id,
                 application_status, resulting_lane_id,
                 resulting_lane_version, pre_window_id, post_window_id,
                 observed_effect_json, expectation_met, failure_kind,
                 failure_detail, applied_at, evaluated_at)
                VALUES (?, ?, ?, 'applied', NULL, NULL, NULL, NULL, ?,
                        NULL, NULL, NULL, ?, NULL)
                """,
                (
                    new_id("action-outcome"),
                    action_id,
                    action["campaign_id"],
                    json.dumps(
                        {
                            "allocations": [
                                {
                                    "lane_id": revision["lane_id"],
                                    "resource_share": revision["resource_share"],
                                    "lane_version": revision[
                                        "resulting_lane_version"
                                    ],
                                }
                                for revision in revisions
                            ]
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            database.execute(
                """
                UPDATE research_campaigns
                SET state_version=state_version+1, updated_at=?
                WHERE campaign_id=?
                """,
                (now, action["campaign_id"]),
            )
            return True

    def complete_action_evaluation(
        self,
        *,
        action_id: str,
        pre_window_id: str,
        post_window_id: str,
        observed_effect: dict[str, Any],
        expectation_met: bool | None,
    ) -> bool:
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE director_action_outcomes
                SET pre_window_id=?, post_window_id=?,
                    observed_effect_json=?, expectation_met=?, evaluated_at=?
                WHERE action_id=? AND application_status='applied'
                  AND evaluated_at IS NULL
                """,
                (
                    pre_window_id,
                    post_window_id,
                    json.dumps(observed_effect, sort_keys=True),
                    (
                        int(expectation_met)
                        if expectation_met is not None
                        else None
                    ),
                    utc_now(),
                    action_id,
                ),
            )
            return cursor.rowcount == 1

    def retain_campaign_candidate(
        self,
        *,
        candidate_id: str,
        campaign_id: str,
        lane_id: str,
        lane_version: int,
        checkpoint_ref: str | None,
        graph6: str,
        graph_sha256: str,
        score: dict[str, Any],
        artifact_ref: str,
        artifact_sha256: str,
    ) -> bool:
        with self.transaction() as database:
            cursor = database.execute(
                """
                INSERT OR IGNORE INTO campaign_candidates
                (candidate_id, campaign_id, lane_id, lane_version,
                 checkpoint_ref, graph6, graph_sha256, score_json, state,
                 artifact_ref, artifact_sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'retained', ?, ?, ?)
                """,
                (
                    candidate_id,
                    campaign_id,
                    lane_id,
                    lane_version,
                    checkpoint_ref,
                    graph6,
                    graph_sha256,
                    json.dumps(score, sort_keys=True),
                    artifact_ref,
                    artifact_sha256,
                    utc_now(),
                ),
            )
            return cursor.rowcount == 1

    def prune_campaign_candidates(
        self, campaign_id: str, maximum: int
    ) -> list[str]:
        if maximum < 1:
            raise ValueError("candidate maximum must be positive")
        with self.transaction() as database:
            rows = database.execute(
                """
                SELECT candidate_id, artifact_ref FROM campaign_candidates
                WHERE campaign_id=? AND state='retained'
                  AND candidate_id NOT IN (
                    SELECT candidate_id FROM campaign_verification_jobs
                    WHERE campaign_id=?
                  )
                ORDER BY created_at DESC, rowid DESC
                LIMIT -1 OFFSET ?
                """,
                (campaign_id, campaign_id, maximum),
            ).fetchall()
            if rows:
                database.executemany(
                    "DELETE FROM campaign_candidates WHERE candidate_id=?",
                    ((row["candidate_id"],) for row in rows),
                )
            return [str(row["artifact_ref"]) for row in rows]

    def campaign_candidate(self, candidate_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM campaign_candidates WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return dict(row)

    def queue_verification_action(
        self,
        *,
        action_id: str,
        candidate_ids: list[str],
        priority: int,
        job_ids: list[str],
    ) -> bool:
        if len(candidate_ids) != len(job_ids) or not candidate_ids:
            raise ValueError("verification action candidate/job mismatch")
        with self.transaction() as database:
            if database.execute(
                "SELECT 1 FROM director_action_outcomes WHERE action_id=?",
                (action_id,),
            ).fetchone():
                return False
            action = database.execute(
                """
                SELECT campaign_id FROM director_actions
                WHERE action_id=? AND validation_status='accepted'
                """,
                (action_id,),
            ).fetchone()
            if action is None:
                raise KeyError(action_id)
            placeholders = ",".join("?" for _ in candidate_ids)
            candidates = database.execute(
                f"""
                SELECT candidate_id, state FROM campaign_candidates
                WHERE campaign_id=? AND candidate_id IN ({placeholders})
                """,
                (action["campaign_id"], *candidate_ids),
            ).fetchall()
            if len(candidates) != len(candidate_ids):
                raise RuntimeError("verification action references missing candidate")
            forbidden = {
                str(row["candidate_id"])
                for row in candidates
                if row["state"] in {"rejected", "certified"}
            }
            if forbidden:
                raise RuntimeError(
                    f"candidate is not eligible for verification: {sorted(forbidden)}"
                )
            now = utc_now()
            for candidate_id, job_id in zip(
                candidate_ids, job_ids, strict=True
            ):
                existing = database.execute(
                    """
                    SELECT state, certification_status
                    FROM campaign_verification_jobs
                    WHERE campaign_id=? AND candidate_id=?
                    """,
                    (action["campaign_id"], candidate_id),
                ).fetchone()
                if existing is None:
                    database.execute(
                        """
                        INSERT INTO campaign_verification_jobs
                        (verification_job_id, campaign_id, candidate_id,
                         requested_by_action_id, priority, state, created_at)
                        VALUES (?, ?, ?, ?, ?, 'queued', ?)
                        """,
                        (
                            job_id,
                            action["campaign_id"],
                            candidate_id,
                            action_id,
                            priority,
                            now,
                        ),
                    )
                elif existing["state"] in {"unknown", "failed"}:
                    database.execute(
                        """
                        UPDATE campaign_verification_jobs
                        SET requested_by_action_id=?, priority=?, state='queued',
                            certification_status=NULL,
                            certification_artifact_ref=NULL, started_at=NULL,
                            completed_at=NULL
                        WHERE campaign_id=? AND candidate_id=?
                        """,
                        (
                            action_id,
                            priority,
                            action["campaign_id"],
                            candidate_id,
                        ),
                    )
                database.execute(
                    """
                    UPDATE campaign_candidates
                    SET state='promoted', promoted_at=COALESCE(promoted_at, ?)
                    WHERE candidate_id=?
                    """,
                    (now, candidate_id),
                )
            database.execute(
                """
                INSERT INTO director_action_outcomes
                (action_outcome_id, action_id, campaign_id,
                 application_status, observed_effect_json, applied_at)
                VALUES (?, ?, ?, 'applied', ?, ?)
                """,
                (
                    new_id("action-outcome"),
                    action_id,
                    action["campaign_id"],
                    json.dumps(
                        {
                            "candidate_ids": candidate_ids,
                            "verification_job_ids": job_ids,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            database.execute(
                """
                UPDATE research_campaigns
                SET state_version=state_version+1, updated_at=?
                WHERE campaign_id=?
                """,
                (now, action["campaign_id"]),
            )
            return True

    def pending_candidate_actions(
        self, campaign_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT a.* FROM director_actions a
            LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE a.campaign_id=? AND a.validation_status='accepted'
              AND a.action_type IN ('promote_candidate',
                                    'schedule_verification')
              AND o.action_id IS NULL
            ORDER BY a.priority DESC, a.created_at, a.action_id
            """,
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def pending_auxiliary_actions(
        self, campaign_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT a.* FROM director_actions a
            LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE a.campaign_id=? AND a.validation_status='accepted'
              AND a.action_type IN ('request_diagnostic',
                                    'set_review_trigger')
              AND o.action_id IS NULL
            ORDER BY a.priority DESC, a.created_at, a.action_id
            """,
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def queued_verification_jobs(
        self, campaign_id: str, limit: int
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM campaign_verification_jobs
            WHERE campaign_id=? AND state='queued'
            ORDER BY priority DESC, created_at, verification_job_id LIMIT ?
            """,
            (campaign_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_verification_started(self, job_id: str) -> bool:
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE campaign_verification_jobs
                SET state='running', started_at=?
                WHERE verification_job_id=? AND state='queued'
                """,
                (utc_now(), job_id),
            )
            return cursor.rowcount == 1

    def prepare_lane_recovery(
        self, lane_id: str, expected_version: int
    ) -> bool:
        with self.transaction() as database:
            cursor = database.execute(
                """
                UPDATE research_lanes
                SET process_generation=process_generation+1, updated_at=?
                WHERE lane_id=? AND lane_version=?
                  AND state IN ('starting', 'running', 'paused')
                """,
                (utc_now(), lane_id, expected_version),
            )
            return cursor.rowcount == 1

    def recover_interrupted_records(self, campaign_id: str) -> dict[str, int]:
        with self.transaction() as database:
            turns = database.execute(
                """
                UPDATE app_server_turns
                SET status='failed_interrupted',
                    error_kind='application_restart',
                    error_detail='turn interrupted before durable completion',
                    completed_at=?
                WHERE campaign_id=? AND status='in_progress'
                """,
                (utc_now(), campaign_id),
            ).rowcount
            jobs = database.execute(
                """
                UPDATE campaign_verification_jobs
                SET state='queued', started_at=NULL
                WHERE campaign_id=? AND state='running'
                """,
                (campaign_id,),
            ).rowcount
            sessions = database.execute(
                """
                UPDATE app_server_sessions
                SET state='interrupted'
                WHERE campaign_id=? AND state='active'
                """,
                (campaign_id,),
            ).rowcount
            return {
                "interrupted_turns": turns,
                "requeued_verifications": jobs,
                "interrupted_sessions": sessions,
            }

    def latest_app_server_thread(self, campaign_id: str) -> str | None:
        row = self.connection.execute(
            """
            SELECT thread_id FROM app_server_sessions
            WHERE campaign_id=?
            ORDER BY COALESCE(last_resumed_at, started_at) DESC, rowid DESC
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def complete_verification_job(
        self,
        *,
        job_id: str,
        status: str,
        artifact_ref: str,
    ) -> bool:
        """Commit M4 result; return true only for the first certified success."""

        with self.transaction() as database:
            job = database.execute(
                """
                SELECT * FROM campaign_verification_jobs
                WHERE verification_job_id=? AND state='running'
                """,
                (job_id,),
            ).fetchone()
            if job is None:
                return False
            if status == "COUNTEREXAMPLE_VERIFIED":
                job_state = "completed"
                candidate_state = "certified"
            elif status == "INVALID_CANDIDATE":
                job_state = "completed"
                candidate_state = "rejected"
            elif status in {
                "UNKNOWN_TIMEOUT",
                "UNKNOWN_MEMORY_LIMIT",
                "TOOL_FAILURE",
            }:
                job_state = "unknown"
                candidate_state = "retained"
            else:
                job_state = "failed"
                candidate_state = "retained"
            now = utc_now()
            database.execute(
                """
                UPDATE campaign_verification_jobs
                SET state=?, certification_artifact_ref=?,
                    certification_status=?, completed_at=?
                WHERE verification_job_id=?
                """,
                (job_state, artifact_ref, status, now, job_id),
            )
            database.execute(
                """
                UPDATE campaign_candidates
                SET state=?, certification_status=?,
                    certification_artifact_ref=?
                WHERE candidate_id=?
                """,
                (
                    candidate_state,
                    status,
                    artifact_ref,
                    job["candidate_id"],
                ),
            )
            terminal = False
            if status == "COUNTEREXAMPLE_VERIFIED":
                campaign = database.execute(
                    """
                    SELECT state FROM research_campaigns WHERE campaign_id=?
                    """,
                    (job["campaign_id"],),
                ).fetchone()
                if campaign is not None and campaign["state"] not in {
                    "succeeded_certified_counterexample",
                    "completed_deadline_reached",
                    "stopped_by_operator",
                }:
                    database.execute(
                        """
                        UPDATE research_campaigns
                        SET state='succeeded_certified_counterexample',
                            state_version=state_version+1,
                            certified_candidate_id=?,
                            certification_artifact_ref=?, updated_at=?
                        WHERE campaign_id=?
                        """,
                        (
                            job["candidate_id"],
                            artifact_ref,
                            now,
                            job["campaign_id"],
                        ),
                    )
                    database.execute(
                        """
                        INSERT INTO campaign_terminal_events
                        (terminal_event_id, campaign_id, terminal_kind,
                         certified_candidate_id, verification_job_id,
                         artifact_ref, created_at)
                        VALUES (?, ?, 'succeeded_certified_counterexample',
                                ?, ?, ?, ?)
                        """,
                        (
                            new_id("terminal"),
                            job["campaign_id"],
                            job["candidate_id"],
                            job_id,
                            artifact_ref,
                            now,
                        ),
                    )
                    terminal = True
            return terminal

    def pending_accepted_actions(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT a.* FROM director_actions a
            LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE a.campaign_id=? AND a.validation_status='accepted'
              AND o.action_id IS NULL
            ORDER BY a.priority DESC, a.created_at, a.action_id
            """,
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ResearchStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _action_lane_targets(action: dict[str, Any]) -> list[tuple[str, int]]:
    if action["type"] == "reallocate_resources":
        return [
            (str(item["lane_id"]), int(item["expected_lane_version"]))
            for item in action["allocations"]
        ]
    if "lane_id" in action:
        return [(str(action["lane_id"]), int(action["expected_lane_version"]))]
    return []

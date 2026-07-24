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

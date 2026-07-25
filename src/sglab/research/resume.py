from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import os
import sqlite3

from ..artifacts import hash_file
from .continuity import (
    CampaignResources,
    NON_RESUMABLE_CAMPAIGN_STATES,
    RESUMABLE_CAMPAIGN_STATES,
    ScientificMemoryPolicy,
    CampaignResumeError,
)
from .context import prepare_director_state_v2
from .protocol import canonical_json
from .recovery import CampaignRecovery


def campaign_plan(workspace: Path, campaign_id: str) -> dict[str, Any]:
    path = (
        workspace.resolve()
        / "research-campaigns"
        / campaign_id
        / "campaign-plan.json"
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignResumeError("campaign plan is unavailable") from error
    if value.get("campaign_id") != campaign_id:
        raise CampaignResumeError("campaign plan ID mismatch")
    return value


def proposed_attempt_id(
    *,
    campaign_id: str,
    attempt_index: int,
    state_version: int,
    code_commit: str,
    additional_wall_seconds: float,
    resources: dict[str, Any],
) -> str:
    payload = canonical_json(
        {
            "campaign_id": campaign_id,
            "attempt_index": attempt_index,
            "state_version": state_version,
            "code_commit": code_commit,
            "additional_wall_seconds": additional_wall_seconds,
            "resources": resources,
        },
        max_bytes=128 * 1024,
    )
    return f"execution-attempt-{hashlib.sha256(payload).hexdigest()[:24]}"


def build_resume_preview(
    workspace: Path,
    campaign_id: str,
    *,
    additional_wall_seconds: float,
    resource_overrides: dict[str, Any] | None = None,
    repair_acknowledgement: str | None = None,
    code_commit: str,
) -> dict[str, Any]:
    if additional_wall_seconds <= 0:
        raise CampaignResumeError("additional wall time must be positive")
    root = workspace.resolve()
    plan = campaign_plan(root, campaign_id)
    requested = CampaignResources.from_plan(
        plan, overrides=resource_overrides
    )
    effective = requested.as_dict()
    requested_values = dict(effective)
    for key, value in (resource_overrides or {}).items():
        if value is not None:
            requested_values[key] = value
    db = root / "results.sqlite3"
    connection = sqlite3.connect(
        f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=2
    )
    connection.row_factory = sqlite3.Row
    try:
        campaign = connection.execute(
            "SELECT * FROM research_campaigns WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            raise CampaignResumeError("campaign not found")
        state = str(campaign["state"])
        active_process = active_campaign_process(root, campaign_id)
        host_restart = state == "running" and not active_process
        if state in NON_RESUMABLE_CAMPAIGN_STATES and not host_restart:
            raise CampaignResumeError(
                f"campaign state is not resumable: {state}"
            )
        if state not in RESUMABLE_CAMPAIGN_STATES and not host_restart:
            raise CampaignResumeError(
                f"campaign state is not resumable: {state}"
            )
        if state == "paused_fault" and not (
            repair_acknowledgement
            and repair_acknowledgement.strip()
        ):
            raise CampaignResumeError(
                "paused_fault resume requires a repair acknowledgement"
            )
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        attempts = (
            [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM campaign_execution_attempts
                    WHERE campaign_id=? ORDER BY attempt_index
                    """,
                    (campaign_id,),
                )
            ]
            if "campaign_execution_attempts" in table_names
            else []
        )
        has_legacy_activity = _count(
            connection, "app_server_turns", campaign_id
        ) > 0 or _count(connection, "research_lanes", campaign_id) > 0
        attempt_index = (
            int(attempts[-1]["attempt_index"]) + 1
            if attempts
            else (2 if has_legacy_activity else 1)
        )
        memory = _latest_memory(
            connection, root, campaign_id, table_names
        )
        checkpoints = _checkpoint_previews(
            connection,
            root / "research-campaigns" / campaign_id,
            campaign_id,
        )
        valid_candidates = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT candidate_id FROM campaign_candidates
                WHERE campaign_id=? AND state IN ('retained','promoted')
                ORDER BY created_at DESC, candidate_id
                """,
                (campaign_id,),
            )
        ]
        stale_actions = _stale_pending_actions(
            connection, campaign_id, set(valid_candidates)
        )
        counters = _counters(connection, campaign_id)
        reason = _resume_reason(state, host_restart)
        attempt_id = proposed_attempt_id(
            campaign_id=campaign_id,
            attempt_index=attempt_index,
            state_version=int(campaign["state_version"]),
            code_commit=code_commit,
            additional_wall_seconds=additional_wall_seconds,
            resources=effective,
        )
        previous_resources = (
            json.loads(str(attempts[-1]["effective_resource_json"]))
            if attempts
            else CampaignResources.from_plan(plan).as_dict()
        )
        policy = _memory_policy(plan, campaign)
        return {
            "schema_version": "1.0",
            "campaign_id": campaign_id,
            "campaign_state": state,
            "campaign_state_version": int(campaign["state_version"]),
            "resumable": True,
            "proposed_attempt_id": attempt_id,
            "proposed_attempt_index": attempt_index,
            "attempt_reason": reason,
            "code_commit": code_commit,
            "additional_wall_seconds": additional_wall_seconds,
            "requested_resources": requested_values,
            "effective_resources": effective,
            "previous_effective_resources": previous_resources,
            "resource_changes": {
                key: {
                    "previous": previous_resources.get(key),
                    "requested": effective.get(key),
                }
                for key in effective
                if effective.get(key) != previous_resources.get(key)
            },
            "application_level_cpu_concurrency": True,
            "os_cpu_isolation_claimed": False,
            "previous_fault": {
                "kind": campaign["fault_kind"],
                "detail": campaign["fault_detail"],
                "acknowledgement": repair_acknowledgement,
            },
            "scientific_contract": {
                "target": campaign["target"],
                "target_definition_sha256": campaign[
                    "target_definition_sha256"
                ],
                "director": plan.get("director", {}),
                "unchanged": True,
            },
            "scientific_memory": {
                **memory,
                "policy": {
                    "soft_limit_bytes": policy.soft_limit_bytes,
                    "hard_limit_bytes": policy.hard_limit_bytes,
                    "snapshot_interval_cycles": (
                        policy.snapshot_interval_cycles
                    ),
                },
            },
            "checkpoints": checkpoints,
            "reusable_checkpoint_count": sum(
                item["valid"] for item in checkpoints
            ),
            "current_executable_candidate_ids": valid_candidates,
            "historical_stale_actions_excluded": stale_actions,
            "cumulative_counters": counters,
            "side_effects": {
                "database_writes": 0,
                "model_inferences": 0,
                "auth_accesses": 0,
                "search_batches": 0,
            },
        }
    finally:
        connection.close()


def _memory_policy(
    plan: dict[str, Any], campaign: sqlite3.Row
) -> ScientificMemoryPolicy:
    scientific = plan.get("scientific_memory") or {}
    keys = set(campaign.keys())
    return ScientificMemoryPolicy(
        soft_limit_bytes=int(
            scientific.get(
                "scientific_state_soft_limit_bytes",
                campaign["scientific_state_soft_limit_bytes"]
                if "scientific_state_soft_limit_bytes" in keys
                else 24_576,
            )
        ),
        hard_limit_bytes=int(
            scientific.get(
                "scientific_state_hard_limit_bytes",
                campaign["scientific_state_hard_limit_bytes"]
                if "scientific_state_hard_limit_bytes" in keys
                else 32_768,
            )
        ),
        snapshot_interval_cycles=int(
            scientific.get(
                "scientific_snapshot_interval_cycles",
                campaign["scientific_snapshot_interval_cycles"]
                if "scientific_snapshot_interval_cycles" in keys
                else 5,
            )
        ),
    )


def _resume_reason(state: str, host_restart: bool) -> str:
    if host_restart:
        return "host_restart_recovery"
    if state in {"completed_deadline_reached", "deadline_reached",
                 "budget_exhausted"}:
        return "additional_budget"
    if state in {"paused_fault", "infrastructure_failure"}:
        return "infrastructure_recovery"
    return "operator_resume"


def active_campaign_process(root: Path, campaign_id: str) -> bool:
    """Return true only for a live PID that still owns this campaign command."""

    try:
        pointer = json.loads(
            (root / "active-research-campaign.json").read_text(
                encoding="utf-8"
            )
        )
        pid = int(pointer.get("pid", 0))
        if pointer.get("campaign_id") != campaign_id or pid <= 1:
            return False
        os.kill(pid, 0)
        stat_fields = Path(f"/proc/{pid}/stat").read_text(
            encoding="utf-8"
        ).split()
        if len(stat_fields) >= 3 and stat_fields[2] == "Z":
            return False
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
        return (
            b"sglab" in command
            and b"research-campaign" in command
            and campaign_id.encode("utf-8") in command
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _latest_memory(
    connection: sqlite3.Connection,
    root: Path,
    campaign_id: str,
    tables: set[str],
) -> dict[str, Any]:
    if "campaign_memory_snapshots" in tables:
        row = connection.execute(
            """
            SELECT memory_snapshot_id, version, sha256, byte_size,
                   estimated_token_count, creation_trigger
            FROM campaign_memory_snapshots
            WHERE campaign_id=? ORDER BY version DESC LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        if row is not None:
            return {
                "memory_snapshot_id": row["memory_snapshot_id"],
                "version": int(row["version"]),
                "sha256": row["sha256"],
                "byte_size": int(row["byte_size"]),
                "estimated_token_count": int(
                    row["estimated_token_count"]
                ),
                "creation_trigger": row["creation_trigger"],
                "reusable": True,
                "legacy_reconstruction_required": False,
            }
    row = connection.execute(
        """
        SELECT snapshot_id, artifact_ref, artifact_sha256, payload_bytes
        FROM director_snapshots
        WHERE campaign_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (campaign_id,),
    ).fetchone()
    if row is None:
        return {
            "memory_snapshot_id": None,
            "version": 0,
            "sha256": None,
            "byte_size": 0,
            "estimated_token_count": 0,
            "reusable": False,
            "legacy_reconstruction_required": False,
        }
    path = (
        root
        / "research-campaigns"
        / campaign_id
        / str(row["artifact_ref"])
    ).resolve()
    valid = path.is_file() and hash_file(path) == str(row["artifact_sha256"])
    projected_payload = None
    if valid:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            projected_payload = canonical_json(
                prepare_director_state_v2(raw).state,
                max_bytes=32_768,
            )
        except (OSError, ValueError, json.JSONDecodeError):
            valid = False
    return {
        "memory_snapshot_id": f"legacy:{row['snapshot_id']}",
        "version": 0,
        "sha256": (
            hashlib.sha256(projected_payload).hexdigest()
            if projected_payload is not None
            else row["artifact_sha256"]
        ),
        "byte_size": (
            len(projected_payload)
            if projected_payload is not None
            else int(row["payload_bytes"])
        ),
        "estimated_token_count": (
            (len(projected_payload) + 3) // 4
            if projected_payload is not None
            else (int(row["payload_bytes"]) + 3) // 4
        ),
        "creation_trigger": "legacy_director_snapshot",
        "reusable": valid,
        "legacy_reconstruction_required": True,
    }


def _checkpoint_previews(
    connection: sqlite3.Connection,
    campaign_dir: Path,
    campaign_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM research_lanes WHERE campaign_id=?
          AND checkpoint_ref IS NOT NULL
        ORDER BY created_at, lane_id
        """,
        (campaign_id,),
    ).fetchall()
    values: list[dict[str, Any]] = []
    for row in rows:
        valid = False
        failure = None
        try:
            payload = CampaignRecovery._checkpoint(  # type: ignore[misc]
                _PreviewRecovery(campaign_dir), row
            )
            valid = isinstance(payload, dict)
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"[:500]
        values.append(
            {
                "lane_id": row["lane_id"],
                "lane_state": row["state"],
                "checkpoint_ref": row["checkpoint_ref"],
                "checkpoint_sha256": row["checkpoint_sha256"],
                "valid": valid,
                "restore_process": (
                    valid
                    and row["state"] in {"starting", "running", "paused"}
                ),
                "failure": failure,
            }
        )
    return values


class _PreviewRecovery:
    def __init__(self, campaign_dir: Path):
        self.campaign_dir = campaign_dir.resolve()


def _stale_pending_actions(
    connection: sqlite3.Connection,
    campaign_id: str,
    valid_candidates: set[str],
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT a.action_id, a.action_type, a.parameters_json
        FROM director_actions a
        LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
        WHERE a.campaign_id=? AND a.validation_status='accepted'
          AND a.action_type IN ('promote_candidate','schedule_verification')
          AND o.action_id IS NULL
        ORDER BY a.created_at, a.action_id
        """,
        (campaign_id,),
    ).fetchall()
    values = []
    for row in rows:
        parameters = json.loads(str(row["parameters_json"]))
        targets = (
            [str(parameters["candidate_id"])]
            if row["action_type"] == "promote_candidate"
            else [str(value) for value in parameters["candidate_ids"]]
        )
        stale = [value for value in targets if value not in valid_candidates]
        if stale:
            values.append(
                {
                    "action_id": row["action_id"],
                    "stale_candidate_ids": stale,
                    "will_be_terminalized_as": "stale_target",
                    "will_not_be_reexecuted": True,
                }
            )
    return values


def _count(
    connection: sqlite3.Connection, table: str, campaign_id: str
) -> int:
    return int(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()[0]
    )


def _counters(
    connection: sqlite3.Connection, campaign_id: str
) -> dict[str, int | float]:
    turns = connection.execute(
        """
        SELECT count(*), coalesce(sum(total_tokens),0),
               coalesce(sum(wall_seconds),0)
        FROM app_server_turns WHERE campaign_id=?
        """,
        (campaign_id,),
    ).fetchone()
    return {
        "director_turns": int(turns[0]),
        "server_tokens": int(turns[1]),
        "director_wall_seconds": float(turns[2]),
        "actions": _count(connection, "director_actions", campaign_id),
        "terminal_actions": _count(
            connection, "director_action_outcomes", campaign_id
        ),
        "lanes": _count(connection, "research_lanes", campaign_id),
        "evaluations": int(
            connection.execute(
                """
                SELECT coalesce(sum(telemetry_high_water),0)
                FROM research_lanes WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()[0]
        ),
        "retained_candidates": _count(
            connection, "campaign_candidates", campaign_id
        ),
        "terminal_verifications": int(
            connection.execute(
                """
                SELECT count(*) FROM campaign_verification_jobs
                WHERE campaign_id=? AND state IN ('completed','unknown','failed')
                """,
                (campaign_id,),
            ).fetchone()[0]
        ),
    }

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Iterator
import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
import warnings

from ..artifacts import hash_file
from ..locations import asset_path, score_worker_path
from ..model import BitGraph
from ..resources import (
    current_rss_bytes,
    disk_free_bytes,
    recommended_workers,
    sqlite_size_bytes,
)
from ..resource_accounting import (
    LOGS,
    RUNTIME_SCRATCH,
    account_execution_root,
    discover_trusted_codex_roots,
)
from ..state import atomic_write_json, read_json, utc_now
from ..score_worker import PROTOCOL_VERSION
from ..targets import TARGETS
from .actions import LaneActionDispatcher
from .app_server_client import AppServerClient, AppServerConfig
from .app_server_protocol import generate_protocol_preflight
from .auth import (
    auth_is_imported,
    director_home,
    import_authorized_auth,
)
from .candidates import CandidateArchive
from .catalog import normalize_proposal_ranking_catalog_id
from .context import (
    CONTEXT_RECOMMENDATION_BASIS,
    DEFAULT_DIRECTOR_CONTEXT_MODE,
    DirectorContextMode,
)
from .continuity import (
    CampaignResources,
    ScientificMemoryPolicy,
    DEFAULT_SCIENTIFIC_SNAPSHOT_INTERVAL,
    DEFAULT_SCIENTIFIC_STATE_HARD_BYTES,
    DEFAULT_SCIENTIFIC_STATE_SOFT_BYTES,
    repository_commit,
)
from .diagnostics import ScientificActionDispatcher
from .director import ActiveDirector
from .export import export_campaign
from .lanes import LaneManager
from .orchestrator import ActiveResearchOrchestrator
from .passive import (
    PASSIVE_POLICY_ID,
    PASSIVE_POLICY_VERSION,
    PASSIVE_REVIEW_CANDIDATE_DELTA,
    PASSIVE_SCHEDULER_STATE_VERSION,
    PASSIVE_STAGNATION_WINDOWS,
    DeterministicReviewTrigger,
    PassiveScheduler,
)
from .providers import (
    AppServerDecisionProvider,
    SerialAppServerDecisionProvider,
    SyntheticControlProvider,
)
from .protocol import canonical_json
from .recovery import CampaignRecovery
from .resume import (
    active_campaign_process,
    campaign_plan,
    proposed_attempt_id,
)
from .snapshot import SnapshotBuilder
from .store import ResearchStore, new_id
from .telemetry import TelemetrySeries
from .triggers import TriggerEngine
from .verification_broker import M4VerificationBroker


TERMINAL_STATES = {
    "succeeded_certified_counterexample",
    "completed_deadline_reached",
    "stopped_by_operator",
    "budget_exhausted",
    "director_replan_exhausted",
    "scientifically_invalidated",
}
ATTEMPT_STOP_STATES = TERMINAL_STATES | {"paused_by_operator", "paused_fault"}
CONTROL_ACTIONS = {"PAUSE", "STOP"}
CONTROLLER_MODES = {
    "active_ai",
    "serial_ai",
    "static",
    "random",
    "continuity_demo",
}
DIRECTOR_MODES = {"llm", "passive"}


def _score_runtime_provenance() -> dict[str, Any]:
    binary = score_worker_path().resolve()
    return {
        "implementation": "cpp",
        "early_exit_enabled": True,
        "duplicate_key_scheme": "delta_local_v2",
        "score_worker": {
            "path": str(binary),
            "available": binary.is_file(),
            "sha256": hash_file(binary) if binary.is_file() else None,
            "protocol_version": PROTOCOL_VERSION,
        },
    }


CAMPAIGN_PLAN_SCHEMA_VERSION = "1.3"
PRODUCTION_DIRECTOR_MODEL = "gpt-5.6-luna"
PRODUCTION_DIRECTOR_EFFORT = "high"
PRODUCTION_CONTEXT_MODE = DirectorContextMode.STATELESS_TURNS
PRODUCTION_MAXIMUM_DIRECTOR_CYCLES = 12
PRODUCTION_MAXIMUM_DIRECTOR_TURNS = 24
PRODUCTION_TURN_TIMEOUT_SECONDS = 300
PRODUCTION_MAX_ACTIVE_LANES = 8
PRODUCTION_LANE_MEMORY_BYTES = 512 * 1024 * 1024
PRODUCTION_VERIFICATION_QUEUE = 32
PRODUCTION_VERIFICATION_TIMEOUT_SECONDS = 60
PRODUCTION_VERIFIER_MEMORY_BYTES = 512 * 1024 * 1024
PRODUCTION_VERIFICATION_BROKER_MEMORY_BYTES = 1024 * 1024 * 1024
PRODUCTION_MAX_RUNTIME_SCRATCH_BYTES = 512 * 1024 * 1024
PRODUCTION_MAX_SINGLE_RUNTIME_FILE_BYTES = 256 * 1024 * 1024
PRODUCTION_MAX_WIRE_BYTES = 8 * 1024 * 1024
PRODUCTION_MAX_STDERR_BYTES = 256 * 1024
PRODUCTION_MAX_STDOUT_BYTES = 2 * 1024 * 1024
PREPARED_CAMPAIGN_POINTER = "prepared-research-campaign.json"


class CampaignPlanError(RuntimeError):
    pass


class CampaignResourceError(RuntimeError):
    pass


def parse_duration(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        suffix = value[-1].lower()
        seconds = float(value[:-1]) * units[suffix] if suffix in units else float(value)
    except (ValueError, IndexError) as error:
        raise ValueError(f"invalid duration: {value}") from error
    if not 1 <= seconds <= 365 * 86400:
        raise ValueError("campaign duration must be between 1 second and 365 days")
    return seconds


def target_definition_sha256(target: str = "erdos_gyarfas") -> str:
    if target not in TARGETS:
        raise ValueError(f"unsupported target: {target}")
    digest = hashlib.sha256()
    target_module = {
        "erdos_gyarfas": "erdos_gyarfas.py",
        "m6_hidden_witness_control_v1": "hidden_witness_control.py",
    }[target]
    sources = [Path(__file__).resolve().parents[1] / "targets" / target_module]
    if target == "erdos_gyarfas":
        sources.append(asset_path("configs", "targets", "erdos_gyarfas.toml"))
    digest.update(TARGETS[target].statement.encode("utf-8"))
    for path in sources:
        payload = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _campaign_plan_fingerprint(plan: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in plan.items()
        if key != "plan_fingerprint"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def validate_campaign_plan_fingerprint(
    plan: dict[str, Any], *, expected: str | None = None
) -> str:
    stored = plan.get("plan_fingerprint")
    recomputed = _campaign_plan_fingerprint(plan)
    if not isinstance(stored, str) or stored != recomputed:
        raise CampaignPlanError("campaign plan fingerprint mismatch")
    if expected is not None and stored != expected:
        raise CampaignPlanError(
            "campaign plan does not match the authorized fingerprint"
        )
    return stored


def _attempt_contract_fingerprint(
    plan: dict[str, Any], director_mode: str
) -> str:
    payload = canonical_json(
        {
            "campaign_plan_fingerprint": (
                plan.get("plan_fingerprint")
                or _campaign_plan_fingerprint(plan)
            ),
            "director_mode": director_mode,
            "director_contract": plan.get("director", {}),
            "passive_scheduler_contract": plan.get(
                "passive_scheduler", {}
            ),
        },
        max_bytes=128 * 1024,
    )
    return hashlib.sha256(payload).hexdigest()


def _campaign_private_root(workspace: Path, campaign_id: str) -> Path:
    return (
        workspace.resolve()
        / ".sglab"
        / "research-campaigns"
        / campaign_id
    )


def campaign_application_data(
    workspace: Path, campaign_id: str
) -> Path:
    return _campaign_private_root(workspace, campaign_id) / "runtime-groups" / "director"


def campaign_attempt_application_data(
    workspace: Path, campaign_id: str, attempt_id: str
) -> Path:
    return (
        _campaign_private_root(workspace, campaign_id)
        / "attempts"
        / attempt_id
        / "application-data"
    )


def _prepared_plan_path(workspace: Path, campaign_id: str) -> Path:
    return (
        workspace.resolve()
        / "research-campaigns"
        / campaign_id
        / "campaign-plan.json"
    )


def prepare_campaign_plan(
    workspace: Path,
    *,
    duration_seconds: float,
    director_mode: str = "llm",
    passive_seed: int = 0,
    proposal_ranking: str | None = None,
) -> dict[str, Any]:
    if director_mode not in DIRECTOR_MODES:
        raise CampaignPlanError("unsupported director mode")
    if not 0 <= passive_seed < 2**63:
        raise CampaignPlanError(
            "passive scheduler seed must be in [0, 2**63)"
        )
    try:
        proposal_ranking = normalize_proposal_ranking_catalog_id(
            proposal_ranking
        )
    except ValueError as error:
        raise CampaignPlanError(str(error)) from error
    if proposal_ranking is not None and director_mode != "llm":
        raise CampaignPlanError(
            "proposal-ranking activation requires LLM Director mode"
        )
    root = workspace.resolve()
    marker = read_json(root / "workspace.json", default={})
    if (
        marker.get("synthetic_data") is not False
        or marker.get("workspace_kind") != "first_real_graph_campaign"
    ):
        raise CampaignPlanError(
            "campaign preparation requires a non-synthetic "
            "first_real_graph_campaign workspace marker"
        )
    if duration_seconds != 3600:
        raise CampaignPlanError(
            "the first real graph campaign contract is fixed at one hour"
        )
    pointer_path = root / PREPARED_CAMPAIGN_POINTER
    if pointer_path.exists():
        raise CampaignPlanError("a prepared campaign already exists")
    database = root / "results.sqlite3"
    with ResearchStore(database) as store:
        existing = store.connection.execute(
            "SELECT count(*) FROM research_campaigns"
        ).fetchone()[0]
        if int(existing) != 0:
            raise CampaignPlanError(
                "fresh campaign workspace already contains campaign records"
            )
        campaign_id = new_id("campaign")
        maximum_lanes = max(
            2,
            min(
                PRODUCTION_MAX_ACTIVE_LANES,
                recommended_workers(512),
            ),
        )
        plan = {
            "schema_version": CAMPAIGN_PLAN_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "director_mode": director_mode,
            "proposal_ranking": proposal_ranking,
            "target": "erdos_gyarfas",
            "target_definition_sha256": target_definition_sha256(),
            "stop_contract": {
                "certified_counterexample": (
                    "stop immediately after exact M4 certification"
                ),
                "campaign_wall_seconds": 3600,
            },
            "director": {
                "model": PRODUCTION_DIRECTOR_MODEL,
                "reasoning_effort": PRODUCTION_DIRECTOR_EFFORT,
                "context_mode": PRODUCTION_CONTEXT_MODE.value,
                "maximum_cycles": PRODUCTION_MAXIMUM_DIRECTOR_CYCLES,
                "maximum_turns_including_replans": (
                    PRODUCTION_MAXIMUM_DIRECTOR_TURNS
                ),
                "turn_timeout_seconds": PRODUCTION_TURN_TIMEOUT_SECONDS,
                "maximum_replans_per_state": 1,
                "replan_context": "fresh_stateless_thread",
                "automatic_compaction": True,
                "model_tools": False,
                "shell_or_code_requests": False,
                "provider_recovery_attempts": 0,
            },
            "passive_scheduler": {
                "policy_id": PASSIVE_POLICY_ID,
                "policy_version": PASSIVE_POLICY_VERSION,
                "scheduler_state_version": (
                    PASSIVE_SCHEDULER_STATE_VERSION
                ),
                "seed": passive_seed,
                "review_candidate_delta": (
                    PASSIVE_REVIEW_CANDIDATE_DELTA
                ),
                "stagnation_windows": PASSIVE_STAGNATION_WINDOWS,
                "decision_clock": "persisted_evaluation_boundaries",
                "wall_clock_scientific_input": False,
            },
            "decision_policy": {
                "valid_actions": "execute",
                "invalid_actions": "never_execute",
                "first_invalid_response": (
                    "persist and allow one fresh stateless replan "
                    "for the identical scientific state"
                ),
                "second_invalid_response": "stop cleanly without execution",
                "infrastructure_protocol_resource_auth": "fail_closed",
            },
            "search_limits": {
                "cpu_workers": maximum_lanes,
                "maximum_active_lanes": maximum_lanes,
                "maximum_resource_share_per_lane": 1.0,
                "maximum_aggregate_resource_share": float(maximum_lanes),
                "lane_memory_limit_bytes": PRODUCTION_LANE_MEMORY_BYTES,
                "event_queue_capacity": 512,
                "command_queue_capacity_per_lane": 32,
                "telemetry_windows_per_lane": 120,
                "checkpoints_per_lane": 8,
                "pinned_checkpoints": 128,
                "score_profiling_enabled": True,
            },
            "scientific_memory": {
                "scientific_state_soft_limit_bytes": (
                    DEFAULT_SCIENTIFIC_STATE_SOFT_BYTES
                ),
                "scientific_state_hard_limit_bytes": (
                    DEFAULT_SCIENTIFIC_STATE_HARD_BYTES
                ),
                "scientific_snapshot_interval_cycles": (
                    DEFAULT_SCIENTIFIC_SNAPSHOT_INTERVAL
                ),
                "compactor": "deterministic_projection_v1",
            },
            "verification_limits": {
                "maximum_queue_depth": PRODUCTION_VERIFICATION_QUEUE,
                "maximum_concurrent_jobs": 1,
                "timeout_seconds_per_exact_path": (
                    PRODUCTION_VERIFICATION_TIMEOUT_SECONDS
                ),
                "verifier_memory_limit_bytes": (
                    PRODUCTION_VERIFIER_MEMORY_BYTES
                ),
                "broker_memory_limit_bytes": (
                    PRODUCTION_VERIFICATION_BROKER_MEMORY_BYTES
                ),
                "success_authority": "M4_independent_verifier",
            },
            "runtime_limits": {
                "resource_accounting_version": 2,
                "max_runtime_scratch_bytes": (
                    PRODUCTION_MAX_RUNTIME_SCRATCH_BYTES
                ),
                "max_single_runtime_file_bytes": (
                    PRODUCTION_MAX_SINGLE_RUNTIME_FILE_BYTES
                ),
                "max_wire_log_bytes": PRODUCTION_MAX_WIRE_BYTES,
                "max_stderr_bytes": PRODUCTION_MAX_STDERR_BYTES,
                "max_stdout_bytes": PRODUCTION_MAX_STDOUT_BYTES,
                "symlink_policy": "expected_app_server_wrappers_v1",
            },
            "scientific_contract": {
                "heuristic_score_is_certification": False,
                "capped_witness_counts": "approximate_or_truncated",
                "verifier_disagreement": (
                    "stop affected candidate path and trigger review"
                ),
                "announce_success_without_certificate": False,
                "fixed_experiment_sequence": False,
            },
        }
        plan["plan_fingerprint"] = _campaign_plan_fingerprint(plan)
        campaign_dir = root / "research-campaigns" / campaign_id
        campaign_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        campaign_dir.chmod(0o700)
        atomic_write_json(campaign_dir / "campaign-plan.json", plan)
        now = utc_now()
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO research_campaigns
                (campaign_id, created_at, updated_at, target,
                 target_definition_sha256, state, state_version, stop_mode,
                 deadline_at, effective_context_mode,
                 context_recommendation_basis, initial_state_sha256,
                 initial_resource_plan_json, director_mode)
                VALUES (?, ?, ?, 'erdos_gyarfas', ?, 'prepared', 0,
                        'time_limit', NULL, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    now,
                    now,
                    plan["target_definition_sha256"],
                    (
                        PRODUCTION_CONTEXT_MODE.value
                        if director_mode == "llm"
                        else None
                    ),
                    (
                        CONTEXT_RECOMMENDATION_BASIS
                        if director_mode == "llm"
                        else None
                    ),
                    hashlib.sha256(
                        canonical_json(
                            {
                                "target": "erdos_gyarfas",
                                "hypotheses": [],
                                "lanes": [],
                                "candidates": [],
                            },
                            max_bytes=4096,
                        )
                    ).hexdigest(),
                    json.dumps(plan["search_limits"], sort_keys=True),
                    director_mode,
                ),
            )
        atomic_write_json(
            pointer_path,
            {
                "campaign_id": campaign_id,
                "plan_fingerprint": plan["plan_fingerprint"],
                "plan_artifact": str(
                    Path("research-campaigns")
                    / campaign_id
                    / "campaign-plan.json"
                ),
                "prepared_at": now,
            },
        )
    private_root = _campaign_private_root(root, campaign_id)
    private_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    private_root.chmod(0o700)
    return plan


def load_prepared_campaign_plan(
    workspace: Path,
    *,
    campaign_id: str | None = None,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    root = workspace.resolve()
    pointer = read_json(
        root / PREPARED_CAMPAIGN_POINTER,
        default={},
    )
    selected = campaign_id or pointer.get("campaign_id")
    if not isinstance(selected, str) or not selected:
        raise CampaignPlanError("prepared campaign is unavailable")
    plan = read_json(_prepared_plan_path(root, selected), default={})
    if plan.get("campaign_id") != selected:
        raise CampaignPlanError("prepared campaign ID mismatch")
    director_mode = str(plan.get("director_mode", "llm"))
    if director_mode not in DIRECTOR_MODES:
        raise CampaignPlanError("prepared campaign director mode is invalid")
    try:
        normalized_ranking = normalize_proposal_ranking_catalog_id(
            plan.get("proposal_ranking")
        )
    except ValueError as error:
        raise CampaignPlanError(str(error)) from error
    if plan.get("proposal_ranking") != normalized_ranking:
        raise CampaignPlanError("prepared campaign proposal-ranking field is invalid")
    if normalized_ranking is not None and director_mode != "llm":
        raise CampaignPlanError(
            "proposal-ranking activation requires LLM Director mode"
        )
    try:
        validate_campaign_plan_fingerprint(
            plan, expected=expected_fingerprint
        )
    except CampaignPlanError as error:
        raise CampaignPlanError(
            str(error).replace("campaign plan", "prepared campaign", 1)
        ) from error
    with ResearchStore(root / "results.sqlite3") as store:
        campaign = store.campaign(selected)
        if campaign["state"] != "prepared":
            raise CampaignPlanError("prepared campaign is no longer prepared")
        if campaign["target_definition_sha256"] != plan[
            "target_definition_sha256"
        ]:
            raise CampaignPlanError("prepared target hash mismatch")
        if str(campaign.get("director_mode", "llm")) != director_mode:
            raise CampaignPlanError("prepared director mode mismatch")
        if store.connection.execute(
            "SELECT count(*) FROM app_server_turns WHERE campaign_id=?",
            (selected,),
        ).fetchone()[0]:
            raise CampaignPlanError("prepared campaign already has Director turns")
        if store.connection.execute(
            "SELECT count(*) FROM research_lanes WHERE campaign_id=?",
            (selected,),
        ).fetchone()[0]:
            raise CampaignPlanError("prepared campaign already has search lanes")
    return plan


def request_campaign_control(workspace: Path, action: str) -> dict[str, Any]:
    if action not in CONTROL_ACTIONS:
        raise ValueError("unsupported campaign control action")
    root = workspace.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".research-campaign-control.lock"
    with lock_path.open("a", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = root / "research-campaign-control.json"
        current = read_json(path, default={"version": 0})
        request = {
            "version": int(current.get("version", 0)) + 1,
            "requested_at": utc_now(),
            "action": action,
        }
        atomic_write_json(path, request)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return request


def campaign_status(workspace: Path, campaign_id: str | None = None) -> dict[str, Any]:
    root = workspace.resolve()
    pointer = read_json(root / "active-research-campaign.json", default={})
    if not pointer:
        pointer = read_json(root / PREPARED_CAMPAIGN_POINTER, default={})
    selected = campaign_id or pointer.get("campaign_id")
    process = (
        pointer
        if pointer.get("campaign_id") == selected
        else {
            "campaign_id": selected,
            "campaign_dir": str(root / "research-campaigns" / str(selected)),
        }
    )
    database_path = root / "results.sqlite3"
    if not selected or not database_path.is_file():
        return {
            "campaign_id": None,
            "state": "IDLE",
            "target": "erdos_gyarfas",
            "auth_imported": auth_is_imported(root / ".sglab"),
            "proposal_ranking": None,
            "proposal_ranking_enabled": False,
        }
    auth_data = (
        campaign_application_data(root, str(selected))
        if _prepared_plan_path(root, str(selected)).is_file()
        else root / ".sglab"
    )
    uri = f"{database_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        campaign = connection.execute(
            "SELECT * FROM research_campaigns WHERE campaign_id=?", (selected,)
        ).fetchone()
        if campaign is None:
            return {
                "campaign_id": selected,
                "state": "NOT_FOUND",
                "proposal_ranking": None,
                "proposal_ranking_enabled": False,
            }
        campaign_state = str(campaign["state"])
        campaign_columns = set(campaign.keys())
        director_mode = str(
            campaign["director_mode"]
            if "director_mode" in campaign_columns
            else "llm"
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        active_attempt_started_at = None
        if "campaign_execution_attempts" in tables:
            active_attempt_row = connection.execute(
                """
                SELECT started_at FROM campaign_execution_attempts
                WHERE campaign_id=? AND terminal_at IS NULL
                ORDER BY attempt_index DESC LIMIT 1
                """,
                (selected,),
            ).fetchone()
            if active_attempt_row is not None:
                active_attempt_started_at = str(
                    active_attempt_row["started_at"]
                )
        lanes = []
        for row in connection.execute(
            """
            SELECT * FROM research_lanes WHERE campaign_id=?
            ORDER BY updated_at DESC LIMIT 32
            """,
            (selected,),
        ):
            metric_rows = connection.execute(
                """
                SELECT metrics_json, end_at FROM lane_metric_windows
                WHERE lane_id=? ORDER BY end_at DESC, rowid DESC LIMIT 8
                """,
                (row["lane_id"],),
            ).fetchall()
            metric_payloads = [
                json.loads(metric["metrics_json"]) for metric in metric_rows
            ]
            series = TelemetrySeries(maximum=8)
            for metrics in reversed(metric_payloads):
                series.append(metrics)
            lanes.append(
                {
                    **dict(row),
                    "parameters": json.loads(row["current_parameters_json"]),
                    "seed_lineage": json.loads(row["seed_lineage_json"]),
                    "metrics": series.recent(),
                    "latest_throughput": (
                        metric_payloads[0].get("candidates_per_second")
                        if campaign_state == "running"
                        and metric_payloads
                        and active_attempt_started_at is not None
                        and _timestamp_at_or_after(
                            metric_rows[0]["end_at"],
                            active_attempt_started_at,
                        )
                        else 0.0
                    ),
                }
            )
        assessment = connection.execute(
            """
            SELECT campaign_assessment, next_review_json, validation_status,
                   created_at, decision_batch_id
            FROM director_action_batches WHERE campaign_id=?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (selected,),
        ).fetchone()
        turn_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(app_server_turns)")
        }
        attempt_turn_fields = (
            ", t.execution_attempt_id, t.memory_snapshot_id"
            if {"execution_attempt_id", "memory_snapshot_id"}.issubset(
                turn_columns
            )
            else ""
        )
        validation_turn_fields = (
            ", t.error_detail, t.validation_issues_json, "
            "t.validation_issue_count"
            if {
                "validation_issues_json",
                "validation_issue_count",
            }.issubset(turn_columns)
            else ", t.error_detail"
        )
        turns = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT t.turn_record_id, t.thread_id, t.turn_id, t.status,
                       t.wall_seconds, t.input_tokens, t.cached_input_tokens,
                       t.cache_write_input_tokens, t.output_tokens,
                       t.reasoning_output_tokens, t.total_tokens, t.started_at,
                       t.completed_at, t.error_kind, t.final_agent_item_id,
                       t.thread_lifecycle, s.model_requested AS model,
                       s.effort_requested AS reasoning_effort
                       {validation_turn_fields}
                       {attempt_turn_fields}
                FROM app_server_turns AS t
                JOIN app_server_sessions AS s
                  ON s.session_record_id=t.session_record_id
                WHERE t.campaign_id=?
                ORDER BY t.started_at DESC, t.rowid DESC LIMIT 10
                """,
                (selected,),
            )
        ]
        for turn in turns:
            raw_issues = turn.get("validation_issues_json")
            if isinstance(raw_issues, str):
                try:
                    turn["validation_issues"] = json.loads(raw_issues)
                except json.JSONDecodeError:
                    turn["validation_issues"] = []
                turn.pop("validation_issues_json", None)
            else:
                turn["validation_issues"] = []
            turn["validation_issue_count"] = int(
                turn.get("validation_issue_count")
                or len(turn["validation_issues"])
            )
        actions = [
            {
                **dict(row),
                "parameters": json.loads(row["parameters_json"]),
                "observed_effect": (
                    json.loads(row["observed_effect_json"])
                    if row["observed_effect_json"]
                    else None
                ),
            }
            for row in connection.execute(
                """
                SELECT a.action_id, a.action_type, a.target_lane_id,
                       a.parameters_json, a.expected_effect,
                       a.validation_status, a.created_at,
                       o.application_status, o.observed_effect_json,
                       o.expectation_met, o.failure_kind
                FROM director_actions a
                LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
                WHERE a.campaign_id=?
                ORDER BY a.created_at DESC, a.rowid DESC LIMIT 32
                """,
                (selected,),
            )
        ]
        hypotheses = [
            dict(row)
            for row in connection.execute(
                """
                SELECT hypothesis_id, statement, confidence, status, created_at
                FROM research_hypotheses_v2 WHERE campaign_id=?
                ORDER BY created_at DESC, rowid DESC LIMIT 32
                """,
                (selected,),
            )
        ]
        verification = dict(
            connection.execute(
                """
                SELECT
                  SUM(CASE WHEN state='queued' THEN 1 ELSE 0 END) AS queued,
                  SUM(CASE WHEN state='running' THEN 1 ELSE 0 END) AS running,
                  SUM(CASE WHEN certification_status='COUNTEREXAMPLE_VERIFIED'
                           THEN 1 ELSE 0 END) AS certified
                FROM campaign_verification_jobs WHERE campaign_id=?
                """,
                (selected,),
            ).fetchone()
        )
        candidates = []
        for row in connection.execute(
            """
            SELECT candidate_id, lane_id, lane_version, graph6, score_json,
                   state, artifact_sha256, created_at, promoted_at,
                   certification_status
            FROM campaign_candidates WHERE campaign_id=?
            ORDER BY created_at DESC, rowid DESC LIMIT 24
            """,
            (selected,),
        ):
            degree_histogram: dict[str, int] = {}
            try:
                graph = BitGraph.from_graph6(str(row["graph6"]))
                order = graph.n
                size = graph.size()
                for degree in graph.degree_sequence():
                    key = str(degree)
                    degree_histogram[key] = degree_histogram.get(key, 0) + 1
            except (UnicodeError, ValueError):
                order = None
                size = None
            candidates.append(
                {
                    "candidate_id": row["candidate_id"],
                    "lane_id": row["lane_id"],
                    "lane_version": row["lane_version"],
                    "state": row["state"],
                    "verification_status": (
                        row["certification_status"] or row["state"]
                    ),
                    "order": order,
                    "size": size,
                    "degree_histogram": degree_histogram,
                    "score": json.loads(row["score_json"]),
                    "artifact_sha256": row["artifact_sha256"],
                    "created_at": row["created_at"],
                    "promoted_at": row["promoted_at"],
                }
            )
        revisions = [
            {
                **dict(row),
                "old_parameters": json.loads(row["old_parameters_json"]),
                "new_parameters": json.loads(row["new_parameters_json"]),
            }
            for row in connection.execute(
                """
                SELECT lane_revision_id, lane_id, action_id, old_lane_version,
                       new_lane_version, old_parameters_json,
                       new_parameters_json, applied_at
                FROM lane_revisions WHERE campaign_id=?
                ORDER BY applied_at DESC, rowid DESC LIMIT 64
                """,
                (selected,),
            )
        ]
        session = connection.execute(
            """
            SELECT thread_id, app_server_session_id, thread_path, state,
                   model_requested, effort_requested, codex_version,
                   started_at, last_resumed_at, context_mode
            FROM app_server_sessions WHERE campaign_id=?
            ORDER BY COALESCE(last_resumed_at, started_at) DESC, rowid DESC
            LIMIT 1
            """,
            (selected,),
        ).fetchone()
        attempts = []
        if "campaign_execution_attempts" in tables:
            for row in connection.execute(
                """
                SELECT * FROM campaign_execution_attempts
                WHERE campaign_id=? ORDER BY attempt_index DESC LIMIT 32
                """,
                (selected,),
            ):
                value = dict(row)
                for key in (
                    "requested_resource_json",
                    "effective_resource_json",
                    "starting_checkpoint_refs_json",
                    "inherited_counters_json",
                    "attempt_counters_json",
                    "authorization_provenance_json",
                    "runtime_provenance_json",
                    "mode_transition_json",
                ):
                    if key in value:
                        value[key.removesuffix("_json")] = json.loads(
                            str(value.pop(key))
                        )
                attempts.append(value)
        passive_scheduler = None
        if "passive_scheduler_decisions" in tables:
            row = connection.execute(
                """
                SELECT d.scheduler_decision_id, d.policy_id,
                       d.policy_version, d.scheduler_state_version,
                       d.state_version_before, d.state_version_after,
                       d.input_snapshot_id, d.input_snapshot_version,
                       d.reason_codes_json, d.validation_status,
                       d.validation_detail, d.resulting_changes_json,
                       d.created_at, s.rng_seed, s.rng_counter,
                       s.state_json
                FROM passive_scheduler_decisions AS d
                LEFT JOIN passive_scheduler_states AS s
                  ON s.campaign_id=d.campaign_id
                WHERE d.campaign_id=?
                ORDER BY d.created_at DESC, d.rowid DESC LIMIT 1
                """,
                (selected,),
            ).fetchone()
            if row is not None:
                passive_scheduler = {
                    **dict(row),
                    "reason_codes": json.loads(
                        str(row["reason_codes_json"])
                    ),
                    "resulting_changes": json.loads(
                        str(row["resulting_changes_json"])
                    ),
                    "state": (
                        json.loads(str(row["state_json"]))
                        if row["state_json"]
                        else None
                    ),
                }
                for key in (
                    "reason_codes_json",
                    "resulting_changes_json",
                    "state_json",
                ):
                    passive_scheduler.pop(key)
        memory = None
        if "campaign_memory_snapshots" in tables:
            row = connection.execute(
                """
                SELECT memory_snapshot_id, version, parent_snapshot_id,
                       byte_size, estimated_token_count, sha256,
                       creation_trigger, source_high_water_json,
                       source_record_counts_json, created_at
                FROM campaign_memory_snapshots
                WHERE campaign_id=? ORDER BY version DESC LIMIT 1
                """,
                (selected,),
            ).fetchone()
            if row is not None:
                memory = {
                    **dict(row),
                    "source_high_water": json.loads(
                        str(row["source_high_water_json"])
                    ),
                    "source_record_counts": json.loads(
                        str(row["source_record_counts_json"])
                    ),
                }
                memory.pop("source_high_water_json")
                memory.pop("source_record_counts_json")
        cumulative = {
            "director_turns": int(
                connection.execute(
                    """
                    SELECT count(*) FROM app_server_turns
                    WHERE campaign_id=?
                    """,
                    (selected,),
                ).fetchone()[0]
            ),
            "server_tokens": int(
                connection.execute(
                    """
                    SELECT coalesce(sum(total_tokens),0)
                    FROM app_server_turns WHERE campaign_id=?
                    """,
                    (selected,),
                ).fetchone()[0]
            ),
            "scheduler_decisions": int(
                connection.execute(
                    """
                    SELECT count(*) FROM passive_scheduler_decisions
                    WHERE campaign_id=?
                    """,
                    (selected,),
                ).fetchone()[0]
                if "passive_scheduler_decisions" in tables
                else 0
            ),
            "actions": int(
                connection.execute(
                    """
                    SELECT count(*) FROM director_actions
                    WHERE campaign_id=?
                    """,
                    (selected,),
                ).fetchone()[0]
            ),
            "evaluations": sum(
                int(lane["telemetry_high_water"] or 0) for lane in lanes
            ),
        }
        active_attempt = next(
            (
                attempt
                for attempt in attempts
                if attempt["terminal_at"] is None
            ),
            None,
        )
        if active_attempt is not None:
            inherited = active_attempt["inherited_counters"]
            active_attempt["live_attempt_counters"] = {
                key: cumulative.get(key, 0) - inherited.get(key, 0)
                for key in cumulative
            }
        plan_summary = read_json(
            _prepared_plan_path(root, str(selected)), default={}
        )
        proposal_ranking_error = None
        try:
            projected_proposal_ranking = normalize_proposal_ranking_catalog_id(
                plan_summary.get("proposal_ranking")
            )
        except ValueError as error:
            projected_proposal_ranking = None
            proposal_ranking_error = str(error)
        try:
            pid = int(process.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        host_restart_resume = (
            campaign_state == "running"
            and not active_campaign_process(root, str(selected))
        )
        return {
            **dict(campaign),
            "director_mode": director_mode,
            "director_mode_label": (
                "No-LLM passive search"
                if director_mode == "passive"
                else "AI Director"
            ),
            "auth_applicable": director_mode == "llm",
            "auth_imported": (
                auth_is_imported(auth_data)
                if director_mode == "llm"
                else False
            ),
            "model_usage_applicable": director_mode == "llm",
            "process": process,
            "lanes": lanes,
            "active_lane_count": sum(
                lane["state"] in {"starting", "running", "paused", "stopping"}
                for lane in lanes
            ),
            "assessment": dict(assessment) if assessment else None,
            "director_session": dict(session) if session else None,
            "turns": turns,
            "actions": actions,
            "hypotheses": hypotheses,
            "revisions": revisions,
            "candidates": candidates,
            "verification": {
                key: int(value or 0) for key, value in verification.items()
            },
            "execution_attempts": attempts,
            "current_attempt": (
                active_attempt
            ),
            "cumulative_counters": cumulative,
            "scientific_memory": memory,
            "passive_scheduler": passive_scheduler,
            "maximum_director_turns": (
                plan_summary.get("director", {}).get("maximum_cycles")
                or plan_summary.get("director", {}).get(
                    "maximum_turns_including_replans"
                )
            ),
            "proposal_ranking": projected_proposal_ranking,
            "proposal_ranking_enabled": projected_proposal_ranking is not None,
            "proposal_ranking_error": proposal_ranking_error,
            "resume_supported": (
                campaign_state
                in {
                    "paused_by_operator",
                    "stopped_by_operator",
                    "completed_deadline_reached",
                    "deadline_reached",
                    "budget_exhausted",
                    "paused_fault",
                    "interrupted",
                    "infrastructure_failure",
                }
                or host_restart_resume
            ),
            "host_restart_resume": host_restart_resume,
            "resources": {
                "coordinator_rss_bytes": current_rss_bytes(pid) if pid > 0 else 0,
                "database_bytes": sqlite_size_bytes(database_path),
                "disk_free_bytes": disk_free_bytes(root),
            },
        }
    except sqlite3.OperationalError:
        return {
            "campaign_id": selected,
            "state": "SCHEMA_UNAVAILABLE",
            "target": "erdos_gyarfas",
            "auth_imported": auth_is_imported(auth_data),
            "proposal_ranking": None,
            "proposal_ranking_enabled": False,
        }
    finally:
        connection.close()


@contextmanager
def campaign_lock(workspace: Path) -> Iterator[None]:
    path = workspace.resolve() / ".research-campaign.lock"
    with path.open("a", encoding="ascii") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another research campaign coordinator is active") from error
        yield


class ResearchCampaignRunner:
    """Production foreground supervisor for one active AI-directed campaign."""

    def __init__(
        self,
        *,
        workspace: Path,
        stop_mode: str,
        duration_seconds: float | None = None,
        campaign_id: str | None = None,
        target: str = "erdos_gyarfas",
        codex: str = "codex",
        poll_seconds: float = 0.05,
        controller_mode: str = "active_ai",
        controller_seed: int = 0,
        maximum_director_turns: int | None = None,
        context_mode: DirectorContextMode | str = DEFAULT_DIRECTOR_CONTEXT_MODE,
        prepared_plan: dict[str, Any] | None = None,
        resume_resource_overrides: dict[str, Any] | None = None,
        repair_acknowledgement: str | None = None,
        attempt_reason: str | None = None,
        code_commit: str | None = None,
        director_mode: str | None = None,
        passive_seed: int = 0,
        proposal_ranking: str | None = None,
    ):
        if stop_mode not in {"time_limit", "until_success"}:
            raise ValueError("invalid stop mode")
        if target not in TARGETS:
            raise ValueError(f"unsupported target: {target}")
        if controller_mode not in CONTROLLER_MODES:
            raise ValueError("unsupported campaign controller mode")
        if director_mode not in DIRECTOR_MODES | {None}:
            raise ValueError("unsupported director mode")
        if not 0 <= passive_seed < 2**63:
            raise ValueError(
                "passive scheduler seed must be in [0, 2**63)"
            )
        try:
            proposal_ranking = normalize_proposal_ranking_catalog_id(
                proposal_ranking
            )
        except ValueError as error:
            raise ValueError(str(error)) from error
        if maximum_director_turns is not None and not (
            1 <= maximum_director_turns <= 1000
        ):
            raise ValueError("Director turn budget must be between 1 and 1000")
        if (
            campaign_id is None
            and (stop_mode == "time_limit") != (duration_seconds is not None)
        ):
            raise ValueError("time-limit mode requires exactly one duration")
        self.workspace = workspace.resolve()
        self.stop_mode = stop_mode
        self.duration_seconds = duration_seconds
        self.campaign_id = campaign_id
        self.target = target
        self.codex = codex
        self.poll_seconds = poll_seconds
        self.controller_mode = controller_mode
        self.controller_seed = controller_seed
        self.director_mode = director_mode
        self.passive_seed = passive_seed
        self.proposal_ranking = proposal_ranking
        self.maximum_director_turns = maximum_director_turns
        self.context_mode = DirectorContextMode(context_mode)
        self.prepared_plan = prepared_plan
        self.resume_resource_overrides = resume_resource_overrides or {}
        self.repair_acknowledgement = repair_acknowledgement
        self.attempt_reason = attempt_reason
        self.code_commit = code_commit or repository_commit(
            Path(__file__).resolve().parents[3]
        )
        self._effective_campaign_plan = prepared_plan
        self._last_resource_sample = 0.0
        self._resource_peaks: dict[str, int] = {
            RUNTIME_SCRATCH: 0,
            LOGS: 0,
        }
        if prepared_plan is not None:
            if campaign_id != prepared_plan.get("campaign_id"):
                raise ValueError("prepared campaign ID mismatch")
            if stop_mode != "time_limit" or duration_seconds != 3600:
                raise ValueError("prepared campaign stop contract mismatch")
            director_plan = prepared_plan["director"]
            if (
                director_plan["model"] != PRODUCTION_DIRECTOR_MODEL
                or director_plan["reasoning_effort"]
                != PRODUCTION_DIRECTOR_EFFORT
                or director_plan["context_mode"]
                != PRODUCTION_CONTEXT_MODE.value
            ):
                raise ValueError("prepared Director contract mismatch")
            if maximum_director_turns != int(
                director_plan["maximum_cycles"]
            ):
                raise ValueError("prepared Director cycle limit mismatch")
            try:
                planned_ranking = normalize_proposal_ranking_catalog_id(
                    prepared_plan.get("proposal_ranking")
                )
            except ValueError as error:
                raise ValueError(str(error)) from error
            if (
                self.proposal_ranking is not None
                and self.proposal_ranking != planned_ranking
            ):
                raise ValueError(
                    "start proposal-ranking does not match the prepared campaign"
                )
            if planned_ranking is not None and prepared_plan.get(
                "director_mode", "llm"
            ) != "llm":
                raise ValueError(
                    "proposal-ranking activation requires LLM Director mode"
                )
            self.proposal_ranking = planned_ranking

    def run(self) -> dict[str, Any]:
        with campaign_lock(self.workspace):
            return asyncio.run(self._run())

    async def _run(self) -> dict[str, Any]:
        is_resume = self.campaign_id is not None and self.prepared_plan is None
        durable_plan = self.prepared_plan
        if is_resume:
            durable_plan = campaign_plan(
                self.workspace, str(self.campaign_id)
            )
            if durable_plan.get("plan_fingerprint") is not None:
                validate_campaign_plan_fingerprint(durable_plan)
        if self.prepared_plan is not None:
            effective_director_mode = str(
                self.prepared_plan.get("director_mode", "llm")
            )
            if (
                self.director_mode is not None
                and self.director_mode != effective_director_mode
            ):
                raise ValueError(
                    "start mode does not match the prepared campaign"
                )
        elif is_resume and self.director_mode is None:
            with ResearchStore(
                self.workspace / "results.sqlite3"
            ) as mode_store:
                effective_director_mode = str(
                    mode_store.campaign(str(self.campaign_id)).get(
                        "director_mode", "llm"
                    )
                )
        else:
            effective_director_mode = self.director_mode or "llm"
        if effective_director_mode not in DIRECTOR_MODES:
            raise ValueError("durable campaign has an unsupported director mode")
        self.effective_director_mode = effective_director_mode
        try:
            effective_proposal_ranking = normalize_proposal_ranking_catalog_id(
                (durable_plan or {}).get(
                    "proposal_ranking", self.proposal_ranking
                )
            )
        except ValueError as error:
            raise CampaignPlanError(str(error)) from error
        if is_resume and self.proposal_ranking is not None:
            if self.proposal_ranking != effective_proposal_ranking:
                raise ValueError(
                    "Resume cannot change the proposal-ranking contract"
                )
        self.proposal_ranking = effective_proposal_ranking
        if (
            self.proposal_ranking is not None
            and effective_director_mode != "llm"
        ):
            raise CampaignPlanError(
                "proposal-ranking activation requires LLM Director mode"
            )
        passive_plan = (durable_plan or {}).get("passive_scheduler", {})
        effective_passive_seed = int(
            passive_plan.get("seed", self.passive_seed)
        )
        if is_resume:
            director_contract = durable_plan.get("director") or {}
            expected_context = str(
                director_contract.get(
                    "context_mode", DirectorContextMode.STATELESS_TURNS.value
                )
            )
            if self.context_mode.value != expected_context:
                raise ValueError(
                    "Resume cannot change the Director context mode"
                )
            model_contract = str(director_contract.get("model") or "")
            if model_contract.endswith("-control"):
                expected_control = model_contract.removesuffix("-control")
                if self.controller_mode != expected_control:
                    raise ValueError(
                        "Resume cannot change the fake Director contract"
                    )
            elif (
                effective_director_mode == "llm"
                and self.controller_mode not in {"active_ai", "serial_ai"}
            ):
                raise ValueError(
                    "Resume cannot replace the authenticated Director"
                )
        self._effective_campaign_plan = durable_plan
        credential_application_data = (
            campaign_application_data(
                self.workspace,
                str((durable_plan or {})["campaign_id"]),
            )
            if durable_plan is not None
            else self.workspace / ".sglab"
        )
        uses_app_server = (
            effective_director_mode == "llm"
            and self.controller_mode in {"active_ai", "serial_ai"}
        )
        if uses_app_server and not auth_is_imported(
            credential_application_data
        ):
            raise RuntimeError(
                "Director authentication is not imported into the exact "
                "campaign runtime"
            )
        preflight = (
            generate_protocol_preflight(self.codex)
            if uses_app_server
            else {
                "codex_version_output": (
                    "passive-scheduler-v1"
                    if effective_director_mode == "passive"
                    else "synthetic-control-v1"
                ),
                "codex_executable_sha256": (
                    "not-applicable"
                    if effective_director_mode == "passive"
                    else "synthetic-control"
                ),
                "canonical_schema_hashes": {
                    "director-decision-v1": (
                        "reviewed-passive-contract"
                        if effective_director_mode == "passive"
                        else "synthetic-control"
                    )
                },
            }
        )
        store = ResearchStore(self.workspace / "results.sqlite3")
        campaign_id = self.campaign_id or new_id("campaign")
        campaign_dir = self.workspace / "research-campaigns" / campaign_id
        campaign_dir.mkdir(
            parents=True,
            exist_ok=self.campaign_id is not None,
        )
        if self.prepared_plan is not None:
            load_prepared_campaign_plan(
                self.workspace,
                campaign_id=campaign_id,
                expected_fingerprint=str(
                    self.prepared_plan["plan_fingerprint"]
                ),
            )
        search_plan = (durable_plan or {}).get("search_limits", {})
        score_profiling_enabled = search_plan.get(
            "score_profiling_enabled", True
        )
        if not isinstance(score_profiling_enabled, bool):
            raise CampaignPlanError(
                "score_profiling_enabled must be a boolean"
            )
        resources = CampaignResources.from_plan(
            durable_plan,
            overrides=self.resume_resource_overrides,
        )
        effective_resources = resources.as_dict()
        requested_resources = dict(effective_resources)
        if "maximum_active_lanes" in self.resume_resource_overrides:
            requested_resources["maximum_active_lanes"] = int(
                self.resume_resource_overrides["maximum_active_lanes"]
            )
        memory_plan = (durable_plan or {}).get("scientific_memory", {})
        memory_policy = ScientificMemoryPolicy(
            soft_limit_bytes=int(
                memory_plan.get(
                    "scientific_state_soft_limit_bytes",
                    DEFAULT_SCIENTIFIC_STATE_SOFT_BYTES,
                )
            ),
            hard_limit_bytes=int(
                memory_plan.get(
                    "scientific_state_hard_limit_bytes",
                    DEFAULT_SCIENTIFIC_STATE_HARD_BYTES,
                )
            ),
            snapshot_interval_cycles=int(
                memory_plan.get(
                    "scientific_snapshot_interval_cycles",
                    DEFAULT_SCIENTIFIC_SNAPSHOT_INTERVAL,
                )
            ),
        )
        manager = LaneManager(
            campaign_dir,
            max_active_lanes=resources.maximum_active_lanes,
            event_capacity=int(
                search_plan.get("event_queue_capacity", 512)
            ),
            command_capacity=int(
                search_plan.get("command_queue_capacity_per_lane", 32)
            ),
            telemetry_windows=int(
                search_plan.get("telemetry_windows_per_lane", 120)
            ),
            checkpoints_per_lane=int(
                search_plan.get("checkpoints_per_lane", 8)
            ),
            pinned_checkpoints=int(
                search_plan.get("pinned_checkpoints", 128)
            ),
            memory_limit_bytes=int(
                resources.lane_memory_bytes
            ),
            score_profiling_enabled=score_profiling_enabled,
        )
        dispatcher = LaneActionDispatcher(
            store=store, manager=manager, campaign_id=campaign_id
        )
        resume_thread_id: str | None = None
        attempt_id: str | None = None
        if self.prepared_plan is not None:
            deadline = datetime.now(UTC) + timedelta(
                seconds=float(self.duration_seconds)
            )
            store.start_prepared_campaign(
                campaign_id,
                deadline_at=deadline.isoformat(
                    timespec="seconds"
                ).replace("+00:00", "Z"),
            )
            atomic_write_json(
                campaign_dir / "campaign-plan.json",
                self.prepared_plan,
            )
        elif self.campaign_id is None:
            if (
                uses_app_server
                and self.context_mode is DirectorContextMode.PERSISTENT_THREAD
            ):
                warnings.warn(
                    "Persistent context may accumulate server-side history and "
                    "increase token usage. Stateless turns are the measured default.",
                    UserWarning,
                    stacklevel=2,
                )
            deadline = (
                datetime.now(UTC) + timedelta(seconds=float(self.duration_seconds))
                if self.duration_seconds is not None
                else None
            )
            store.create_campaign(
                campaign_id=campaign_id,
                target=self.target,
                target_definition_sha256=target_definition_sha256(self.target),
                stop_mode=self.stop_mode,
                deadline_at=(
                    deadline.isoformat(timespec="seconds").replace("+00:00", "Z")
                    if deadline
                    else None
                ),
                effective_context_mode=(
                    self.context_mode.value if uses_app_server else None
                ),
                context_recommendation_basis=(
                    CONTEXT_RECOMMENDATION_BASIS if uses_app_server else None
                ),
                director_mode=effective_director_mode,
            )
            generated_plan = {
                "schema_version": CAMPAIGN_PLAN_SCHEMA_VERSION,
                "campaign_id": campaign_id,
                "director_mode": effective_director_mode,
                "proposal_ranking": self.proposal_ranking,
                "target": self.target,
                "target_definition_sha256": target_definition_sha256(
                    self.target
                ),
                "director": {
                    "model": (
                        PRODUCTION_DIRECTOR_MODEL
                        if self.controller_mode
                        in {"active_ai", "serial_ai"}
                        else f"{self.controller_mode}-control"
                    ),
                    "reasoning_effort": (
                        PRODUCTION_DIRECTOR_EFFORT
                        if self.controller_mode
                        in {"active_ai", "serial_ai"}
                        else "none"
                    ),
                    "context_mode": self.context_mode.value,
                    "maximum_turns_including_replans": (
                        self.maximum_director_turns
                    ),
                },
                "passive_scheduler": {
                    "policy_id": PASSIVE_POLICY_ID,
                    "policy_version": PASSIVE_POLICY_VERSION,
                    "scheduler_state_version": (
                        PASSIVE_SCHEDULER_STATE_VERSION
                    ),
                    "seed": effective_passive_seed,
                    "review_candidate_delta": (
                        PASSIVE_REVIEW_CANDIDATE_DELTA
                    ),
                    "stagnation_windows": PASSIVE_STAGNATION_WINDOWS,
                    "decision_clock": (
                        "persisted_evaluation_boundaries"
                    ),
                    "wall_clock_scientific_input": False,
                },
                "search_limits": {
                    **search_plan,
                    "cpu_workers": resources.cpu_workers,
                    "maximum_active_lanes": (
                        resources.maximum_active_lanes
                    ),
                    "maximum_aggregate_resource_share": (
                        resources.maximum_aggregate_resource_share
                    ),
                    "lane_memory_limit_bytes": (
                        resources.lane_memory_bytes
                    ),
                },
                "verification_limits": {
                    "maximum_queue_depth": (
                        resources.verification_queue_depth
                    ),
                    "maximum_concurrent_jobs": (
                        resources.verifier_concurrency
                    ),
                    "verifier_memory_limit_bytes": (
                        resources.verifier_memory_bytes
                    ),
                },
                "scientific_memory": {
                    "scientific_state_soft_limit_bytes": (
                        memory_policy.soft_limit_bytes
                    ),
                    "scientific_state_hard_limit_bytes": (
                        memory_policy.hard_limit_bytes
                    ),
                    "scientific_snapshot_interval_cycles": (
                        memory_policy.snapshot_interval_cycles
                    ),
                },
                "runtime_limits": {},
            }
            generated_plan["plan_fingerprint"] = (
                _campaign_plan_fingerprint(generated_plan)
            )
            atomic_write_json(
                campaign_dir / "campaign-plan.json", generated_plan
            )
            durable_plan = generated_plan
            self._effective_campaign_plan = generated_plan
        else:
            campaign = store.campaign(campaign_id)
            previous_director_mode = str(
                campaign.get("director_mode", "llm")
            )
            resume_state_version = int(campaign["state_version"])
            if self.target != str(campaign["target"]):
                raise ValueError("Resume cannot change the scientific target")
            if durable_plan.get("target") != campaign["target"]:
                raise ValueError("durable campaign target contract mismatch")
            if (
                durable_plan.get("target_definition_sha256")
                != campaign["target_definition_sha256"]
            ):
                raise ValueError(
                    "durable campaign definition hash mismatch"
                )
            self.target = str(campaign["target"])
            store.backfill_legacy_execution_attempt(
                campaign_id,
                code_commit=str(
                    (durable_plan or {}).get(
                        "prepared_with_commit", "legacy-unknown"
                    )
                ),
                resource_contract=CampaignResources.from_plan(
                    durable_plan
                ).as_dict(),
            )
            stale_actions = store.terminalize_stale_candidate_actions(
                campaign_id
            )
            pre_resume_builder = SnapshotBuilder(
                store=store,
                manager=manager,
                campaign_id=campaign_id,
                campaign_dir=campaign_dir,
                memory_policy=memory_policy,
                proposal_ranking_catalog_id=self.proposal_ranking,
            )
            starting_memory = store.latest_memory_snapshot(campaign_id)
            pre_resume_builder.publish(memory_trigger="resume")
            additional = float(self.duration_seconds or 3600)
            deadline = (
                datetime.now(UTC) + timedelta(seconds=additional)
                if campaign["stop_mode"] == "time_limit"
                else None
            )
            previous_state = store.resume_campaign(
                campaign_id,
                deadline_at=(
                    deadline.isoformat(timespec="seconds").replace(
                        "+00:00", "Z"
                    )
                    if deadline is not None
                    else None
                ),
                repair_acknowledgement=self.repair_acknowledgement,
                host_restart_recovery=campaign["state"] == "running",
            )
            reason = self.attempt_reason or (
                "host_restart_recovery"
                if previous_state == "running"
                else (
                    "additional_budget"
                    if previous_state
                    in {
                        "completed_deadline_reached",
                        "deadline_reached",
                        "budget_exhausted",
                    }
                    else (
                        "infrastructure_recovery"
                        if previous_state
                        in {"paused_fault", "infrastructure_failure"}
                        else "operator_resume"
                    )
                )
            )
            latest_attempt = store.latest_execution_attempt(campaign_id)
            next_index = (
                int(latest_attempt["attempt_index"]) + 1
                if latest_attempt is not None
                else 1
            )
            attempt_id = proposed_attempt_id(
                campaign_id=campaign_id,
                attempt_index=next_index,
                state_version=resume_state_version,
                code_commit=self.code_commit,
                additional_wall_seconds=additional,
                resources=effective_resources,
                director_mode=effective_director_mode,
            )
            store.create_execution_attempt(
                attempt_id=attempt_id,
                campaign_id=campaign_id,
                reason=reason,
                code_commit=self.code_commit,
                requested_resources=requested_resources,
                effective_resources=effective_resources,
                additional_wall_seconds=additional,
                starting_memory_snapshot_id=(
                    str(starting_memory["memory_snapshot_id"])
                    if starting_memory is not None
                    else None
                ),
                starting_memory_sha256=(
                    str(starting_memory["sha256"])
                    if starting_memory is not None
                    else None
                ),
                starting_checkpoint_refs=store.checkpoint_references(
                    campaign_id
                ),
                repair_acknowledgement=self.repair_acknowledgement,
                runtime_provenance={
                    "fresh_process": True,
                    "historical_stale_actions_terminalized": stale_actions,
                    "director_mode": effective_director_mode,
                    "passive_scheduler": (
                        {
                            "policy_id": PASSIVE_POLICY_ID,
                            "policy_version": PASSIVE_POLICY_VERSION,
                            "seed": effective_passive_seed,
                        }
                        if effective_director_mode == "passive"
                        else None
                    ),
                    "proposal_ranking": self.proposal_ranking,
                    **_score_runtime_provenance(),
                },
                process_id=os.getpid(),
                director_mode=effective_director_mode,
                previous_director_mode=previous_director_mode,
                mode_transition={
                    "previous_mode": previous_director_mode,
                    "new_mode": effective_director_mode,
                    "changed": (
                        previous_director_mode
                        != effective_director_mode
                    ),
                },
                contract_fingerprint=_attempt_contract_fingerprint(
                    durable_plan, effective_director_mode
                ),
            )
            recovery = CampaignRecovery(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                campaign_id=campaign_id,
                campaign_dir=campaign_dir,
            ).recover()
            resume_thread_id = recovery.resume_thread_id
            manager.resume_all()
            store.activate_recovered_lanes(
                list(recovery.restored_lane_ids)
            )
        if attempt_id is None:
            attempt_id = new_id("execution-attempt")
            initial_previous_mode = None
            store.create_execution_attempt(
                attempt_id=attempt_id,
                campaign_id=campaign_id,
                reason="initial_start",
                code_commit=self.code_commit,
                requested_resources=requested_resources,
                effective_resources=effective_resources,
                additional_wall_seconds=float(self.duration_seconds or 0),
                starting_memory_snapshot_id=None,
                starting_memory_sha256=None,
                starting_checkpoint_refs=[],
                runtime_provenance={
                    "director_mode": effective_director_mode,
                    "passive_scheduler": (
                        {
                            "policy_id": PASSIVE_POLICY_ID,
                            "policy_version": PASSIVE_POLICY_VERSION,
                            "seed": effective_passive_seed,
                        }
                        if effective_director_mode == "passive"
                        else None
                    ),
                    "proposal_ranking": self.proposal_ranking,
                    **_score_runtime_provenance(),
                },
                process_id=os.getpid(),
                director_mode=effective_director_mode,
                previous_director_mode=initial_previous_mode,
                mode_transition={
                    "previous_mode": initial_previous_mode,
                    "new_mode": effective_director_mode,
                    "changed": False,
                },
                contract_fingerprint=_attempt_contract_fingerprint(
                    durable_plan or {}, effective_director_mode
                ),
            )
        application_data = campaign_attempt_application_data(
            self.workspace, campaign_id, attempt_id
        )
        attempt_private_root = application_data.parent
        attempt_private_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        attempt_private_root.chmod(0o700)
        self._attempt_private_root = attempt_private_root
        if uses_app_server:
            import_authorized_auth(
                director_home(credential_application_data),
                application_data,
            )
            atomic_write_json(
                application_data / "director" / "preflight.json", preflight
            )
        pointer = {
            "campaign_id": campaign_id,
            "pid": os.getpid(),
            "campaign_dir": str(campaign_dir),
            "started_at": utc_now(),
        }
        atomic_write_json(self.workspace / "active-research-campaign.json", pointer)
        protocol_hash = hashlib.sha256(
            json.dumps(
                preflight["canonical_schema_hashes"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        if uses_app_server:
            director_plan = (durable_plan or {}).get("director", {})
            runtime_plan = (durable_plan or {}).get("runtime_limits", {})
            client_config = AppServerConfig(
                application_data=application_data,
                launcher=(self.codex,),
                model=director_plan.get("model"),
                effort=str(
                    director_plan.get(
                        "reasoning_effort",
                        PRODUCTION_DIRECTOR_EFFORT,
                    )
                ),
                turn_timeout_seconds=float(
                    director_plan.get(
                        "turn_timeout_seconds",
                        900,
                    )
                ),
                stderr_limit_bytes=int(
                    runtime_plan.get(
                        "max_stderr_bytes",
                        PRODUCTION_MAX_STDERR_BYTES,
                    )
                ),
                wire_limit_bytes=int(
                    runtime_plan.get(
                        "max_wire_log_bytes",
                        PRODUCTION_MAX_WIRE_BYTES,
                    )
                ),
                max_jsonl_bytes=int(
                    runtime_plan.get(
                        "max_stdout_bytes",
                        PRODUCTION_MAX_STDOUT_BYTES,
                    )
                ),
                allow_retrying_errors=(
                    False if durable_plan is not None else True
                ),
            )

            def director_factory() -> ActiveDirector:
                return ActiveDirector(
                    client=AppServerClient(client_config),
                    store=store,
                    campaign_id=campaign_id,
                    campaign_dir=campaign_dir,
                    codex_version=str(preflight["codex_version_output"]),
                    executable_sha256=str(preflight["codex_executable_sha256"]),
                    protocol_schema_sha256=protocol_hash,
                    context_mode=self.context_mode,
                    enforce_model_contract=(
                        durable_plan is not None
                    ),
                )

            director = director_factory()
            provider = (
                AppServerDecisionProvider(director)
                if self.controller_mode == "active_ai"
                else SerialAppServerDecisionProvider(director, manager)
            )
        elif effective_director_mode == "passive":
            director = PassiveScheduler(
                store=store,
                campaign_id=campaign_id,
                seed=effective_passive_seed,
            )
            provider = director
        else:
            director = SyntheticControlProvider(
                store=store,
                campaign_id=campaign_id,
                mode=self.controller_mode,
                seed=self.controller_seed,
                proposal_ranking=self.proposal_ranking,
            )
            provider = director
        candidates = CandidateArchive(
            store=store, campaign_id=campaign_id, campaign_dir=campaign_dir
        )
        verification = M4VerificationBroker(
            store=store,
            manager=manager,
            campaign_id=campaign_id,
            campaign_dir=campaign_dir,
            max_queue=int(
                resources.verification_queue_depth
            ),
            max_concurrent=resources.verifier_concurrency,
            timeout_seconds=float(
                (durable_plan or {}).get("verification_limits", {}).get(
                    "timeout_seconds_per_exact_path",
                    PRODUCTION_VERIFICATION_TIMEOUT_SECONDS,
                )
            ),
            verifier_memory_bytes=int(
                resources.verifier_memory_bytes
            ),
            broker_memory_bytes=int(
                (durable_plan or {}).get("verification_limits", {}).get(
                    "broker_memory_limit_bytes",
                    PRODUCTION_VERIFICATION_BROKER_MEMORY_BYTES,
                )
            ),
        )
        scientific = ScientificActionDispatcher(
            store=store, campaign_id=campaign_id, campaign_dir=campaign_dir
        )
        passive_state = (
            store.passive_scheduler_state(campaign_id)
            if effective_director_mode == "passive"
            else None
        )
        passive_state_payload = (
            json.loads(str(passive_state["state_json"]))
            if passive_state is not None
            else {}
        )
        orchestrator = ActiveResearchOrchestrator(
            store=store,
            manager=manager,
            dispatcher=dispatcher,
            snapshots=SnapshotBuilder(
                store=store,
                manager=manager,
                campaign_id=campaign_id,
                campaign_dir=campaign_dir,
                memory_policy=memory_policy,
                proposal_ranking_catalog_id=self.proposal_ranking,
            ),
            provider=provider,
            triggers=(
                DeterministicReviewTrigger(
                    last_review_evaluations=int(
                        passive_state_payload.get(
                            "last_review_evaluations", 0
                        )
                    ),
                    candidate_delta=int(
                        passive_plan.get(
                            "review_candidate_delta",
                            PASSIVE_REVIEW_CANDIDATE_DELTA,
                        )
                    ),
                )
                if effective_director_mode == "passive"
                else TriggerEngine()
            ),
            campaign_id=campaign_id,
            candidates=candidates,
            verification=verification,
            scientific_actions=scientific,
        )
        control_version = int(
            read_json(
                self.workspace / "research-campaign-control.json",
                default={"version": 0},
            ).get("version", 0)
        )
        try:
            self._sample_runtime_resources(
                campaign_id,
                campaign_dir,
                stage=(
                    "before_passive_scheduler_start"
                    if effective_director_mode == "passive"
                    else "before_app_server_start"
                ),
                force=True,
            )
            await director.start(
                resume_thread_id=(
                    None
                    if effective_director_mode == "passive"
                    else resume_thread_id
                )
            )
            self._sample_runtime_resources(
                campaign_id,
                campaign_dir,
                stage=(
                    "after_passive_scheduler_start"
                    if effective_director_mode == "passive"
                    else "after_app_server_start"
                ),
                force=True,
            )
            orchestrator.bootstrap()
            director_task: asyncio.Task[Any] | None = None
            completed_director_turns = int(
                store.connection.execute(
                    """
                    SELECT count(*) FROM app_server_turns
                    WHERE campaign_id=? AND execution_attempt_id=?
                      AND status='completed_valid'
                    """,
                    (campaign_id, attempt_id),
                ).fetchone()[0]
            )
            while True:
                if director_task is not None and director_task.done():
                    try:
                        cycle = await director_task
                    except Exception:
                        if not uses_app_server:
                            raise
                        recovery_attempts = int(
                            (durable_plan or {}).get("director", {}).get(
                                "provider_recovery_attempts",
                                3,
                            )
                        )
                        if recovery_attempts == 0:
                            raise
                        director = await self._recover_director(
                            current=director,
                            factory=director_factory,
                            store=store,
                            campaign_id=campaign_id,
                            orchestrator=orchestrator,
                            maximum_attempts=recovery_attempts,
                        )
                        provider.director = director
                        orchestrator.triggers.offer("recovery")
                    else:
                        if (
                            cycle is not None
                            and effective_director_mode != "passive"
                        ):
                            completed_director_turns += (
                                1 + int(cycle.replan_count)
                            )
                        if director.rollover_due():
                            await director.rollover()
                    director_task = None
                campaign = store.campaign(campaign_id)
                if campaign["state"] in ATTEMPT_STOP_STATES:
                    break
                self._sample_runtime_resources(
                    campaign_id,
                    campaign_dir,
                    stage="campaign_loop",
                )
                control = read_json(
                    self.workspace / "research-campaign-control.json",
                    default={"version": control_version},
                )
                if int(control.get("version", 0)) > control_version:
                    control_version = int(control["version"])
                    action = str(control.get("action"))
                    if action == "STOP":
                        store.finish_campaign(
                            campaign_id, terminal_kind="stopped_by_operator"
                        )
                        break
                    if action == "PAUSE" and campaign["state"] == "running":
                        manager.pause_all()
                        store.set_campaign_coordination_state(
                            campaign_id,
                            expected_version=int(campaign["state_version"]),
                            state="paused_by_operator",
                        )
                        break
                campaign = store.campaign(campaign_id)
                if _deadline_reached(campaign):
                    store.finish_campaign(
                        campaign_id,
                        terminal_kind="completed_deadline_reached",
                    )
                    break
                turn_budget_available = (
                    effective_director_mode == "passive"
                    or self.maximum_director_turns is None
                    or completed_director_turns < self.maximum_director_turns
                )
                if (
                    campaign["state"] == "running"
                    and director_task is None
                    and not turn_budget_available
                ):
                    store.transition_campaign(
                        campaign_id,
                        expected_version=int(campaign["state_version"]),
                        state="budget_exhausted",
                    )
                    break
                if (
                    campaign["state"] == "running"
                    and director_task is None
                    and turn_budget_available
                ):
                    director_task = asyncio.create_task(orchestrator.tick())
                else:
                    orchestrator.pump_events()
                await asyncio.sleep(self.poll_seconds)
        except BaseException as error:
            campaign = store.campaign(campaign_id)
            if campaign["state"] not in TERMINAL_STATES:
                manager.pause_all()
                store.set_campaign_coordination_state(
                    campaign_id,
                    expected_version=int(campaign["state_version"]),
                    state="paused_fault",
                    fault_kind=type(error).__name__,
                    fault_detail=str(error)[:2000],
                )
            raise
        finally:
            task = locals().get("director_task")
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            try:
                terminal_state = store.campaign(campaign_id)["state"]
                trigger = {
                    "paused_by_operator": "pause",
                    "stopped_by_operator": "stop",
                    "completed_deadline_reached": "budget_exhaustion",
                    "budget_exhausted": "budget_exhaustion",
                    "director_replan_exhausted": "invalid_replan",
                    "paused_fault": "fault",
                    "succeeded_certified_counterexample": "certification",
                }.get(str(terminal_state), "attempt_terminal")
                orchestrator.snapshots.publish(memory_trigger=trigger)
            except Exception:
                # A terminal memory projection failure is retained as attempt
                # provenance; it must not overwrite the original campaign fault.
                pass
            resumable_lane_ids = [
                str(row["lane_id"])
                for row in store.connection.execute(
                    """
                    SELECT lane_id FROM research_lanes
                    WHERE campaign_id=? AND state IN (
                        'starting','running','paused','stopping'
                    )
                    """,
                    (campaign_id,),
                )
            ]
            verification.shutdown()
            manager.shutdown()
            for _ in range(max(1, 4 * len(manager.lanes))):
                if dispatcher.poll_once(timeout=0) is None:
                    break
            if store.campaign(campaign_id)["state"] in {
                "paused_by_operator",
                "paused_fault",
                "stopped_by_operator",
                "completed_deadline_reached",
                "budget_exhausted",
                "director_replan_exhausted",
            }:
                store.preserve_lanes_for_resume(resumable_lane_ids)
            await director.close()
            try:
                self._sample_runtime_resources(
                    campaign_id,
                    campaign_dir,
                    stage="after_shutdown",
                    force=True,
                )
            except CampaignResourceError:
                pass
            final = store.campaign(campaign_id)
            attempt = store.latest_execution_attempt(campaign_id)
            if (
                attempt is not None
                and attempt["attempt_id"] == attempt_id
                and attempt["terminal_at"] is None
            ):
                store.finish_execution_attempt(
                    attempt_id,
                    terminal_status=str(final["state"]),
                    terminal_reason=(
                        str(final["fault_detail"])
                        if final["fault_detail"]
                        else None
                    ),
                )
            if final["state"] == "succeeded_certified_counterexample":
                export_campaign(
                    store=store,
                    campaign_id=campaign_id,
                    campaign_dir=campaign_dir,
                    output=campaign_dir / "exports" / f"{campaign_id}.zip",
                )
            store.close()
        return campaign_status(self.workspace, campaign_id)

    def _sample_runtime_resources(
        self,
        campaign_id: str,
        campaign_dir: Path,
        *,
        stage: str,
        force: bool = False,
    ) -> None:
        if self._effective_campaign_plan is None:
            return
        sampled = monotonic()
        if not force and sampled - self._last_resource_sample < 0.5:
            return
        self._last_resource_sample = sampled
        private_root = getattr(
            self,
            "_attempt_private_root",
            _campaign_private_root(self.workspace, campaign_id),
        )
        accounting = account_execution_root(
            private_root,
            research_workspace=self.workspace,
            trusted_symlink_roots=(
                ()
                if getattr(self, "effective_director_mode", "llm")
                == "passive"
                else discover_trusted_codex_roots((self.codex,))
            ),
        )
        limits = self._effective_campaign_plan.get("runtime_limits", {})
        if not limits:
            return
        scratch = accounting.categories[RUNTIME_SCRATCH]
        logs = accounting.categories[LOGS]
        self._resource_peaks[RUNTIME_SCRATCH] = max(
            self._resource_peaks[RUNTIME_SCRATCH],
            scratch.apparent_bytes,
        )
        self._resource_peaks[LOGS] = max(
            self._resource_peaks[LOGS],
            logs.apparent_bytes,
        )
        largest_runtime = max(
            (
                value
                for value in accounting.files
                if value.category == RUNTIME_SCRATCH
            ),
            key=lambda value: value.apparent_bytes,
            default=None,
        )
        failure_code = accounting.policy_violation_code
        if accounting.accounting_status != "ok":
            failure_code = failure_code or "resource_accounting_error"
            enforcement = "accounting_failed"
        elif accounting.symlink_policy_status != "passed":
            enforcement = "filesystem_policy_failed"
        elif scratch.apparent_bytes > int(
            limits["max_runtime_scratch_bytes"]
        ):
            failure_code = "runtime_scratch_quota_exceeded"
            enforcement = "runtime_scratch_quota_exceeded"
        elif (
            largest_runtime is not None
            and largest_runtime.apparent_bytes
            > int(limits["max_single_runtime_file_bytes"])
        ):
            failure_code = "single_runtime_file_quota_exceeded"
            enforcement = "single_runtime_file_quota_exceeded"
        else:
            enforcement = "continue"
        payload = {
            "schema_version": "1.0",
            "campaign_id": campaign_id,
            "stage": stage,
            "accounting_status": accounting.accounting_status,
            "symlink_policy_status": accounting.symlink_policy_status,
            "policy_violation_code": accounting.policy_violation_code,
            "runtime_scratch": {
                "current_apparent_bytes": scratch.apparent_bytes,
                "peak_apparent_bytes": self._resource_peaks[
                    RUNTIME_SCRATCH
                ],
                "limit_bytes": int(
                    limits["max_runtime_scratch_bytes"]
                ),
            },
            "logs": {
                "current_apparent_bytes": logs.apparent_bytes,
                "peak_apparent_bytes": self._resource_peaks[LOGS],
            },
            "largest_runtime_file": (
                largest_runtime.as_dict()
                if largest_runtime is not None
                else None
            ),
            "symlinks": [
                value.as_dict() for value in accounting.symlinks
            ],
            "enforcement": enforcement,
            "failure_code": failure_code,
        }
        path = (
            campaign_dir
            / "director"
            / "runtime-resource-telemetry.json"
        )
        atomic_write_json(path, payload)
        if enforcement != "continue":
            raise CampaignResourceError(
                f"{enforcement} at {stage}: {failure_code}"
            )

    async def _recover_director(
        self,
        *,
        current: ActiveDirector,
        factory: Callable[[], ActiveDirector],
        store: ResearchStore,
        campaign_id: str,
        orchestrator: ActiveResearchOrchestrator,
        maximum_attempts: int = 3,
        maximum_wall_seconds: float = 90,
        retry_backoff_seconds: float = 1,
    ) -> ActiveDirector:
        await current.close()
        resume_thread_id = store.latest_app_server_thread(campaign_id)
        deadline = asyncio.get_running_loop().time() + maximum_wall_seconds
        last_error: Exception | None = None
        for attempt in range(maximum_attempts):
            if attempt:
                delay_until = (
                    asyncio.get_running_loop().time()
                    + attempt * retry_backoff_seconds
                )
                while asyncio.get_running_loop().time() < delay_until:
                    orchestrator.pump_events()
                    self._require_unexpired_lane_leases(store, campaign_id)
                    await asyncio.sleep(self.poll_seconds)
            candidate = factory()
            task = asyncio.create_task(
                candidate.start(resume_thread_id=resume_thread_id)
            )
            try:
                while not task.done():
                    orchestrator.pump_events()
                    self._require_unexpired_lane_leases(store, campaign_id)
                    if asyncio.get_running_loop().time() >= deadline:
                        raise RuntimeError("app-server recovery wall limit exceeded")
                    await asyncio.sleep(self.poll_seconds)
                await task
                return candidate
            except Exception as error:
                last_error = error
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await candidate.close()
        raise RuntimeError(
            f"app-server recovery failed after {maximum_attempts} attempts: "
            f"{last_error}"
        ) from last_error

    @staticmethod
    def _require_unexpired_lane_leases(
        store: ResearchStore, campaign_id: str
    ) -> None:
        rows = store.connection.execute(
            """
            SELECT lane_id, lease_expires_at FROM research_lanes
            WHERE campaign_id=? AND state IN ('starting', 'running')
            """,
            (campaign_id,),
        ).fetchall()
        now = datetime.now(UTC)
        expired = [
            str(row["lane_id"])
            for row in rows
            if row["lease_expires_at"] is not None
            and datetime.fromisoformat(
                str(row["lease_expires_at"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            <= now
        ]
        if expired:
            raise RuntimeError(
                "AI policy lease expired during provider outage: "
                + ", ".join(expired[:8])
            )


def _timestamp_at_or_after(value: Any, boundary: str) -> bool:
    try:
        timestamp = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        lower_bound = datetime.fromisoformat(
            boundary.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return False
    try:
        return timestamp >= lower_bound
    except TypeError:
        return False


def _deadline_reached(campaign: dict[str, Any]) -> bool:
    value = campaign.get("deadline_at")
    if not value:
        return False
    deadline = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return datetime.now(UTC) >= deadline.astimezone(UTC)

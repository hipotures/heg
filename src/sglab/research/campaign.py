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

from ..locations import asset_path
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
from ..targets import TARGETS
from .actions import LaneActionDispatcher
from .app_server_client import AppServerClient, AppServerConfig
from .app_server_protocol import generate_protocol_preflight
from .auth import auth_is_imported
from .candidates import CandidateArchive
from .context import (
    CONTEXT_RECOMMENDATION_BASIS,
    DEFAULT_DIRECTOR_CONTEXT_MODE,
    DirectorContextMode,
)
from .diagnostics import ScientificActionDispatcher
from .director import ActiveDirector
from .export import export_campaign
from .lanes import LaneManager
from .orchestrator import ActiveResearchOrchestrator
from .providers import (
    AppServerDecisionProvider,
    SerialAppServerDecisionProvider,
    SyntheticControlProvider,
)
from .recovery import CampaignRecovery
from .snapshot import SnapshotBuilder
from .store import ResearchStore, new_id
from .telemetry import TelemetrySeries
from .triggers import TriggerEngine
from .verification_broker import M4VerificationBroker


TERMINAL_STATES = {
    "succeeded_certified_counterexample",
    "completed_deadline_reached",
    "stopped_by_operator",
}
CONTROL_ACTIONS = {"PAUSE", "RESUME", "STOP"}
CONTROLLER_MODES = {"active_ai", "serial_ai", "static", "random"}
CAMPAIGN_PLAN_SCHEMA_VERSION = "1.0"
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
) -> dict[str, Any]:
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
                "automatic_compaction": False,
                "model_tools": False,
                "shell_or_code_requests": False,
                "provider_recovery_attempts": 0,
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
                "maximum_active_lanes": maximum_lanes,
                "maximum_resource_share_per_lane": 1.0,
                "maximum_aggregate_resource_share": float(maximum_lanes),
                "lane_memory_limit_bytes": PRODUCTION_LANE_MEMORY_BYTES,
                "event_queue_capacity": 512,
                "command_queue_capacity_per_lane": 32,
                "telemetry_windows_per_lane": 120,
                "checkpoints_per_lane": 8,
                "pinned_checkpoints": 128,
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
                 context_recommendation_basis)
                VALUES (?, ?, ?, 'erdos_gyarfas', ?, 'prepared', 0,
                        'time_limit', NULL, ?, ?)
                """,
                (
                    campaign_id,
                    now,
                    now,
                    plan["target_definition_sha256"],
                    PRODUCTION_CONTEXT_MODE.value,
                    CONTEXT_RECOMMENDATION_BASIS,
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
    stored = plan.get("plan_fingerprint")
    recomputed = _campaign_plan_fingerprint(plan)
    if not isinstance(stored, str) or stored != recomputed:
        raise CampaignPlanError("prepared campaign fingerprint mismatch")
    if expected_fingerprint is not None and stored != expected_fingerprint:
        raise CampaignPlanError(
            "prepared campaign does not match the authorized fingerprint"
        )
    with ResearchStore(root / "results.sqlite3") as store:
        campaign = store.campaign(selected)
        if campaign["state"] != "prepared":
            raise CampaignPlanError("prepared campaign is no longer prepared")
        if campaign["target_definition_sha256"] != plan[
            "target_definition_sha256"
        ]:
            raise CampaignPlanError("prepared target hash mismatch")
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
            return {"campaign_id": selected, "state": "NOT_FOUND"}
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
                SELECT metrics_json FROM lane_metric_windows
                WHERE lane_id=? ORDER BY end_at DESC, rowid DESC LIMIT 8
                """,
                (row["lane_id"],),
            ).fetchall()
            series = TelemetrySeries(maximum=8)
            for metric in reversed(metric_rows):
                series.append(json.loads(metric["metrics_json"]))
            lanes.append(
                {
                    **dict(row),
                    "parameters": json.loads(row["current_parameters_json"]),
                    "seed_lineage": json.loads(row["seed_lineage_json"]),
                    "metrics": series.recent(),
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
        turns = [
            dict(row)
            for row in connection.execute(
                """
                SELECT turn_record_id, thread_id, turn_id, status, wall_seconds,
                       input_tokens, cached_input_tokens,
                       cache_write_input_tokens, output_tokens,
                       reasoning_output_tokens, total_tokens, started_at,
                       completed_at, error_kind, final_agent_item_id,
                       thread_lifecycle
                FROM app_server_turns WHERE campaign_id=?
                ORDER BY started_at DESC, rowid DESC LIMIT 10
                """,
                (selected,),
            )
        ]
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
        try:
            pid = int(process.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        return {
            **dict(campaign),
            "auth_imported": auth_is_imported(auth_data),
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
            "verification": {
                key: int(value or 0) for key, value in verification.items()
            },
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
    ):
        if stop_mode not in {"time_limit", "until_success"}:
            raise ValueError("invalid stop mode")
        if target not in TARGETS:
            raise ValueError(f"unsupported target: {target}")
        if controller_mode not in CONTROLLER_MODES:
            raise ValueError("unsupported campaign controller mode")
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
        self.maximum_director_turns = maximum_director_turns
        self.context_mode = DirectorContextMode(context_mode)
        self.prepared_plan = prepared_plan
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

    def run(self) -> dict[str, Any]:
        with campaign_lock(self.workspace):
            return asyncio.run(self._run())

    async def _run(self) -> dict[str, Any]:
        application_data = (
            campaign_application_data(
                self.workspace,
                str(self.prepared_plan["campaign_id"]),
            )
            if self.prepared_plan is not None
            else self.workspace / ".sglab"
        )
        uses_app_server = self.controller_mode in {"active_ai", "serial_ai"}
        if uses_app_server and not auth_is_imported(application_data):
            raise RuntimeError(
                "Director authentication is not imported into the exact "
                "campaign runtime"
            )
        preflight = (
            generate_protocol_preflight(self.codex)
            if uses_app_server
            else {
                "codex_version_output": "synthetic-control-v1",
                "codex_executable_sha256": "synthetic-control",
                "canonical_schema_hashes": {
                    "director-decision-v1": "synthetic-control"
                },
            }
        )
        if uses_app_server:
            atomic_write_json(
                application_data / "director" / "preflight.json", preflight
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
        search_plan = (
            self.prepared_plan["search_limits"]
            if self.prepared_plan is not None
            else {}
        )
        manager = LaneManager(
            campaign_dir,
            max_active_lanes=int(
                search_plan.get(
                    "maximum_active_lanes",
                    max(2, min(8, recommended_workers(512))),
                )
            ),
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
                search_plan.get(
                    "lane_memory_limit_bytes",
                    PRODUCTION_LANE_MEMORY_BYTES,
                )
            ),
        )
        dispatcher = LaneActionDispatcher(
            store=store, manager=manager, campaign_id=campaign_id
        )
        resume_thread_id: str | None = None
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
            )
        else:
            campaign = store.campaign(campaign_id)
            self.target = str(campaign["target"])
            if campaign["state"] in TERMINAL_STATES:
                raise RuntimeError("terminal campaigns cannot be resumed")
            recovery = CampaignRecovery(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                campaign_id=campaign_id,
                campaign_dir=campaign_dir,
            ).recover()
            resume_thread_id = recovery.resume_thread_id
            if campaign["state"] != "running":
                store.set_campaign_coordination_state(
                    campaign_id,
                    expected_version=int(store.campaign(campaign_id)["state_version"]),
                    state="running",
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
            director_plan = (
                self.prepared_plan["director"]
                if self.prepared_plan is not None
                else {}
            )
            runtime_plan = (
                self.prepared_plan["runtime_limits"]
                if self.prepared_plan is not None
                else {}
            )
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
                    False if self.prepared_plan is not None else True
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
                        self.prepared_plan is not None
                    ),
                )

            director = director_factory()
            provider = (
                AppServerDecisionProvider(director)
                if self.controller_mode == "active_ai"
                else SerialAppServerDecisionProvider(director, manager)
            )
        else:
            director = SyntheticControlProvider(
                store=store,
                campaign_id=campaign_id,
                mode=self.controller_mode,
                seed=self.controller_seed,
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
                (
                    self.prepared_plan or {}
                ).get("verification_limits", {}).get(
                    "maximum_queue_depth",
                    PRODUCTION_VERIFICATION_QUEUE,
                )
            ),
            timeout_seconds=float(
                (
                    self.prepared_plan or {}
                ).get("verification_limits", {}).get(
                    "timeout_seconds_per_exact_path",
                    PRODUCTION_VERIFICATION_TIMEOUT_SECONDS,
                )
            ),
            verifier_memory_bytes=int(
                (
                    self.prepared_plan or {}
                ).get("verification_limits", {}).get(
                    "verifier_memory_limit_bytes",
                    PRODUCTION_VERIFIER_MEMORY_BYTES,
                )
            ),
            broker_memory_bytes=int(
                (
                    self.prepared_plan or {}
                ).get("verification_limits", {}).get(
                    "broker_memory_limit_bytes",
                    PRODUCTION_VERIFICATION_BROKER_MEMORY_BYTES,
                )
            ),
        )
        scientific = ScientificActionDispatcher(
            store=store, campaign_id=campaign_id, campaign_dir=campaign_dir
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
            ),
            provider=provider,
            triggers=TriggerEngine(),
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
                stage="before_app_server_start",
                force=True,
            )
            await director.start(resume_thread_id=resume_thread_id)
            self._sample_runtime_resources(
                campaign_id,
                campaign_dir,
                stage="after_app_server_start",
                force=True,
            )
            orchestrator.bootstrap()
            director_task: asyncio.Task[Any] | None = None
            completed_director_turns = int(
                store.connection.execute(
                    """
                    SELECT count(*) FROM app_server_turns
                    WHERE campaign_id=? AND status='completed_valid'
                    """,
                    (campaign_id,),
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
                            (
                                self.prepared_plan or {}
                            ).get("director", {}).get(
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
                        if cycle is not None:
                            completed_director_turns += 1
                        if director.rollover_due():
                            await director.rollover()
                    director_task = None
                campaign = store.campaign(campaign_id)
                if campaign["state"] in TERMINAL_STATES:
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
                    elif action == "RESUME" and campaign["state"] == "paused_by_operator":
                        manager.resume_all()
                        store.set_campaign_coordination_state(
                            campaign_id,
                            expected_version=int(campaign["state_version"]),
                            state="running",
                        )
                campaign = store.campaign(campaign_id)
                if _deadline_reached(campaign):
                    store.finish_campaign(
                        campaign_id,
                        terminal_kind="completed_deadline_reached",
                    )
                    break
                turn_budget_available = (
                    self.maximum_director_turns is None
                    or completed_director_turns < self.maximum_director_turns
                )
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
            verification.shutdown()
            manager.shutdown()
            for _ in range(max(1, 4 * len(manager.lanes))):
                if dispatcher.poll_once(timeout=0) is None:
                    break
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
        if self.prepared_plan is None:
            return
        sampled = monotonic()
        if not force and sampled - self._last_resource_sample < 0.5:
            return
        self._last_resource_sample = sampled
        private_root = _campaign_private_root(
            self.workspace,
            campaign_id,
        )
        accounting = account_execution_root(
            private_root,
            research_workspace=self.workspace,
            trusted_symlink_roots=discover_trusted_codex_roots(
                (self.codex,)
            ),
        )
        limits = self.prepared_plan["runtime_limits"]
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


def _deadline_reached(campaign: dict[str, Any]) -> bool:
    value = campaign.get("deadline_at")
    if not value:
        return False
    deadline = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return datetime.now(UTC) >= deadline.astimezone(UTC)

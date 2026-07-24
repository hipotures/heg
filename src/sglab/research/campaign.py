from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator
import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3

from ..locations import asset_path
from ..resources import (
    current_rss_bytes,
    disk_free_bytes,
    recommended_workers,
    sqlite_size_bytes,
)
from ..state import atomic_write_json, read_json, utc_now
from ..targets import TARGETS
from .actions import LaneActionDispatcher
from .app_server_client import AppServerClient, AppServerConfig
from .app_server_protocol import generate_protocol_preflight
from .auth import auth_is_imported
from .candidates import CandidateArchive
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
                       completed_at, error_kind, final_agent_item_id
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
                   started_at, last_resumed_at
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
            "auth_imported": auth_is_imported(root / ".sglab"),
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
            "auth_imported": auth_is_imported(root / ".sglab"),
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

    def run(self) -> dict[str, Any]:
        with campaign_lock(self.workspace):
            return asyncio.run(self._run())

    async def _run(self) -> dict[str, Any]:
        application_data = self.workspace / ".sglab"
        uses_app_server = self.controller_mode in {"active_ai", "serial_ai"}
        if uses_app_server and not auth_is_imported(application_data):
            raise RuntimeError(
                "Director authentication is not imported; run "
                "`sglab ai-director auth-import` with an explicitly authorized "
                "Codex home"
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
        campaign_dir.mkdir(parents=True, exist_ok=self.campaign_id is not None)
        manager = LaneManager(
            campaign_dir,
            max_active_lanes=max(2, min(8, recommended_workers(512))),
        )
        dispatcher = LaneActionDispatcher(
            store=store, manager=manager, campaign_id=campaign_id
        )
        resume_thread_id: str | None = None
        if self.campaign_id is None:
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
            client_config = AppServerConfig(
                application_data=application_data,
                launcher=(self.codex,),
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
            await director.start(resume_thread_id=resume_thread_id)
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
                        director = await self._recover_director(
                            current=director,
                            factory=director_factory,
                            store=store,
                            campaign_id=campaign_id,
                            orchestrator=orchestrator,
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

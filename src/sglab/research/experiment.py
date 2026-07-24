from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import asyncio
import hashlib
import json
import time

from ..state import atomic_write_json, utc_now
from .app_server_client import AppServerClient, AppServerConfig
from .app_server_protocol import generate_protocol_preflight
from .auth import auth_is_imported, director_work
from .campaign import campaign_status, target_definition_sha256
from .candidates import CandidateArchive
from .catalog import EXPERIMENT_ALGORITHMS, action_catalog
from .director import ActiveDirector
from .lanes import (
    LaneManager,
    LaneSpec,
    add_external_timing,
    run_bounded_lane_batch,
)
from .protocol import MAX_SNAPSHOT_BYTES, canonical_json
from .providers import (
    DecisionProvider,
    ReplayDecisionProvider,
    SingleTurnAppServerDecisionProvider,
)
from .snapshot import SnapshotBuilder
from .store import ResearchStore, new_id
from .validation import DecisionContext

MAX_EXPERIMENT_GRAPH_ORDER = 20


@dataclass(frozen=True, slots=True)
class CommittedExperimentDecision:
    decision_batch_id: str
    trigger_id: str
    snapshot: dict[str, Any]
    context: DecisionContext
    raw_decision: dict[str, Any]
    validated_decision: dict[str, Any]
    turn_record_id: str
    thread_id: str
    turn_id: str


class OneBatchExperiment:
    """Two decisions around one synchronous, bounded graph-search batch."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        manager: LaneManager,
        provider: DecisionProvider,
        campaign_id: str,
        campaign_dir: Path,
        evaluation_cap: int,
        wall_seconds_cap: float = 120,
    ):
        if not 100 <= evaluation_cap <= 10_000:
            raise ValueError("experiment evaluation cap must be in [100, 10,000]")
        if not 10 <= wall_seconds_cap <= 120:
            raise ValueError("experiment wall cap must be in [10, 120]")
        self.store = store
        self.manager = manager
        self.provider = provider
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.evaluation_cap = evaluation_cap
        self.wall_seconds_cap = wall_seconds_cap
        self.snapshots = SnapshotBuilder(
            store=store,
            manager=manager,
            campaign_id=campaign_id,
            campaign_dir=campaign_dir,
        )

    def publish_state(self) -> tuple[dict[str, Any], DecisionContext]:
        return self.snapshots.publish()

    async def request_first_decision(
        self,
        prepared_state: tuple[dict[str, Any], DecisionContext] | None = None,
    ) -> CommittedExperimentDecision:
        snapshot, context = prepared_state or self.publish_state()
        committed = await self._request_and_commit(
            snapshot=snapshot,
            context=context,
            reason="one_batch_experiment_initial_state",
            phase="first",
        )
        return committed

    def execute_one_batch(
        self, committed: CommittedExperimentDecision
    ) -> dict[str, Any]:
        action = committed.validated_decision["actions"][0]
        action_id = str(action["action_id"])
        spec_value = dict(action["spec"])
        parameters = dict(spec_value["parameters"])
        identity = hashlib.sha256(
            f"{self.campaign_id}:{action_id}".encode("ascii")
        ).hexdigest()
        lane_id = f"lane-{identity[:24]}"
        spec = LaneSpec(
            lane_id=lane_id,
            campaign_id=self.campaign_id,
            target=str(self.store.campaign(self.campaign_id)["target"]),
            algorithm=str(spec_value["algorithm"]),
            graph_family=str(spec_value["graph_family"]),
            seed=int(spec_value["seed"]),
            parameters=parameters,
            resource_share=float(spec_value["resource_share"]),
            created_by_action_id=action_id,
            seed_lineage=(int(spec_value["seed"]),),
        )
        spec.validate()
        self.store.create_lane(
            lane_id=lane_id,
            campaign_id=self.campaign_id,
            target=spec.target,
            parent_lane_id=None,
            parent_checkpoint_ref=None,
            action_id=action_id,
            algorithm=spec.algorithm,
            graph_family=spec.graph_family,
            parameters=parameters,
            seed_lineage=list(spec.seed_lineage),
            resource_share=spec.resource_share,
            lease_expires_at=self._action_lease(action_id),
        )
        proof = {
            "event": "decision_committed_before_search",
            "decision_batch_id": committed.decision_batch_id,
            "turn_record_id": committed.turn_record_id,
            "first_graph_evaluation_count": 0,
        }
        if not self.store.complete_lane_births(
            action_id=action_id,
            lane_ids=[lane_id],
            observed_effect=proof,
        ):
            raise RuntimeError("failed to persist pre-search action event")
        pre_search = self.store.connection.execute(
            """
            SELECT b.validation_status, a.validation_status,
                   o.application_status, o.applied_at
            FROM director_action_batches b
            JOIN director_actions a
              ON a.decision_batch_id=b.decision_batch_id
            JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE b.decision_batch_id=? AND a.action_id=?
            """,
            (committed.decision_batch_id, action_id),
        ).fetchone()
        if (
            pre_search is None
            or pre_search["validation_status"] != "accepted"
            or pre_search["application_status"] != "applied"
        ):
            raise RuntimeError("durable decision-before-search gate failed")

        started_at = utc_now()
        result = run_bounded_lane_batch(
            spec,
            max_evaluations=min(
                self.evaluation_cap,
                int(parameters["batch_candidates"]),
                int(action["evaluation_window"]["max_candidate_delta"]),
            ),
            max_wall_seconds=min(
                self.wall_seconds_cap,
                float(action["evaluation_window"]["max_wall_seconds"]),
            ),
        )
        ended_at = utc_now()
        checkpoint = dict(result.pop("checkpoint"))
        relative_checkpoint = (
            Path("lane-checkpoints")
            / f"{checkpoint['checkpoint_id']}.json"
        )
        atomic_write_json(
            self.campaign_dir / relative_checkpoint,
            checkpoint,
        )
        persistence_started = time.perf_counter()
        self.store.record_lane_checkpoint(
            lane_id=lane_id,
            lane_version=0,
            checkpoint_ref=str(relative_checkpoint),
            checkpoint_sha256=str(checkpoint["sha256"]),
            high_water=int(result["evaluation_count"]),
        )
        metric_window_id = new_id("metric")
        metrics = dict(result["metrics"])
        if not self.store.record_lane_metric_window(
            metric_window_id=metric_window_id,
            lane_id=lane_id,
            campaign_id=self.campaign_id,
            lane_version=0,
            start_high_water=0,
            end_high_water=int(result["evaluation_count"]),
            started_at=started_at,
            ended_at=ended_at,
            metrics=metrics,
        ):
            raise RuntimeError("failed to persist bounded batch metrics")
        candidate_id = CandidateArchive(
            store=self.store,
            campaign_id=self.campaign_id,
            campaign_dir=self.campaign_dir,
        ).observe_checkpoint(
            {
                "kind": "checkpoint",
                "lane_id": lane_id,
                "checkpoint": checkpoint,
            }
        )
        if candidate_id is None:
            raise RuntimeError("bounded batch did not retain its best candidate")
        add_external_timing(
            result["metrics"],
            "sqlite_persistence",
            time.perf_counter() - persistence_started,
        )
        if not self.store.update_lane_metric_window_metrics(
            metric_window_id=metric_window_id,
            metrics=result["metrics"],
        ):
            raise RuntimeError("failed to persist bounded batch timing")
        result["best_candidate_identifier"] = candidate_id
        result["lane_id"] = lane_id
        result["decision_batch_id"] = committed.decision_batch_id
        result["action_id"] = action_id
        result["metric_window_id"] = metric_window_id
        result["checkpoint_id"] = checkpoint["checkpoint_id"]
        result["checkpoint_ref"] = str(relative_checkpoint)
        result["decision_before_search"] = {
            **proof,
            "action_applied_at": pre_search["applied_at"],
            "batch_started_at": started_at,
        }
        outcome_relative = Path("experiment") / "batch-outcome.json"
        atomic_write_json(self.campaign_dir / outcome_relative, result)
        outcome_payload = (self.campaign_dir / outcome_relative).read_bytes()
        result["outcome_artifact_ref"] = str(outcome_relative)
        result["outcome_artifact_sha256"] = hashlib.sha256(
            outcome_payload
        ).hexdigest()
        if not self.store.complete_action_evaluation(
            action_id=action_id,
            pre_window_id=metric_window_id,
            post_window_id=metric_window_id,
            observed_effect=result,
            expectation_met=None,
        ):
            raise RuntimeError("failed to persist measured batch outcome")
        self.store.record_lane_exit(
            lane_id=lane_id,
            lane_version=0,
            failed=False,
            detail="one bounded experiment batch completed",
        )
        return result

    async def request_second_decision(
        self,
        prepared_state: tuple[dict[str, Any], DecisionContext] | None = None,
    ) -> CommittedExperimentDecision:
        snapshot, context = prepared_state or self.publish_state()
        committed = await self._request_and_commit(
            snapshot=snapshot,
            context=context,
            reason="one_batch_experiment_measured_outcome",
            phase="second",
        )
        return committed

    async def _request_and_commit(
        self,
        *,
        snapshot: dict[str, Any],
        context: DecisionContext,
        reason: str,
        phase: str,
    ) -> CommittedExperimentDecision:
        trigger_id = new_id("trigger")
        self.store.record_trigger(
            trigger_id=trigger_id,
            campaign_id=self.campaign_id,
            campaign_state_version=int(snapshot["campaign"]["state_version"]),
            reasons=[reason],
            first_event_at=utc_now(),
            snapshot_id=str(snapshot["snapshot_id"]),
        )
        evidence = await self.provider.decide(
            snapshot=snapshot,
            trigger_id=trigger_id,
            context=context,
        )
        if len(evidence.turn_record_ids) != 1:
            self.store.mark_trigger_status(trigger_id, "rejected_invalid")
            raise RuntimeError("experiment inference produced a hidden repair turn")
        if not evidence.validation.accepted or evidence.validation.normalized is None:
            self.store.mark_trigger_status(trigger_id, "rejected_invalid")
            raise RuntimeError("experiment decision failed structured validation")
        decision = evidence.validation.normalized
        try:
            self._validate_experiment_decision(decision, phase)
        except BaseException:
            self.store.mark_trigger_status(trigger_id, "rejected_invalid")
            raise
        decision_batch_id = new_id("decision-batch")
        statuses = self.store.commit_decision_batch(
            decision_batch_id=decision_batch_id,
            campaign_id=self.campaign_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            trigger_id=trigger_id,
            turn_record_id=evidence.turn_record_ids[0],
            decision=decision,
        )
        if not statuses or any(status != "accepted" for status in statuses.values()):
            raise RuntimeError(f"experiment decision was not fully accepted: {statuses}")
        raw = self._raw_decision(evidence.turn_record_ids[0], evidence.decision)
        return CommittedExperimentDecision(
            decision_batch_id=decision_batch_id,
            trigger_id=trigger_id,
            snapshot=snapshot,
            context=context,
            raw_decision=raw,
            validated_decision=decision,
            turn_record_id=evidence.turn_record_ids[0],
            thread_id=evidence.thread_id,
            turn_id=evidence.turn_id,
        )

    def _validate_experiment_decision(
        self, decision: dict[str, Any], phase: str
    ) -> None:
        if phase == "first":
            actions = decision["actions"]
            if len(actions) != 1 or actions[0]["type"] != "start_lane":
                raise RuntimeError(
                    "first experiment decision must contain exactly one "
                    "start_lane action"
                )
            action = actions[0]
            spec = action["spec"]
            if spec["algorithm"] not in EXPERIMENT_ALGORITHMS:
                raise RuntimeError(
                    "first decision selected a non-experiment algorithm"
                )
            if int(spec["parameters"]["batch_candidates"]) > self.evaluation_cap:
                raise RuntimeError("first decision exceeds the local evaluation cap")
            if int(spec["parameters"]["order"]) > MAX_EXPERIMENT_GRAPH_ORDER:
                raise RuntimeError("first decision exceeds the graph-order cap")
            window = action["evaluation_window"]
            if int(window["max_candidate_delta"]) > self.evaluation_cap:
                raise RuntimeError(
                    "first decision evaluation window exceeds the cap"
                )
            if float(window["max_wall_seconds"]) > self.wall_seconds_cap:
                raise RuntimeError("first decision wall window exceeds the cap")
            return
        if phase != "second":
            raise ValueError(f"unknown experiment decision phase: {phase}")
        assessment = str(decision["campaign_assessment"]).strip()
        if not assessment.startswith(
            ("CONTINUE:", "CHANGE_STRATEGY:", "STOP:")
        ):
            raise RuntimeError(
                "second assessment must classify CONTINUE, CHANGE_STRATEGY, or STOP"
            )

    def _raw_decision(
        self, turn_record_id: str, fallback: dict[str, Any]
    ) -> dict[str, Any]:
        row = self.store.connection.execute(
            """
            SELECT response_artifact_ref FROM app_server_turns
            WHERE turn_record_id=?
            """,
            (turn_record_id,),
        ).fetchone()
        if row is None or not row["response_artifact_ref"]:
            return json.loads(json.dumps(fallback))
        path = (self.campaign_dir / str(row["response_artifact_ref"])).resolve()
        path.relative_to(self.campaign_dir)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("raw decision artifact is not an object")
        return value

    def _action_lease(self, action_id: str) -> str:
        row = self.store.connection.execute(
            "SELECT lease_expires_at FROM director_actions WHERE action_id=?",
            (action_id,),
        ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return str(row["lease_expires_at"])


def build_experiment_prompt(
    snapshot: dict[str, Any],
    turn_index: int,
    *,
    evaluation_cap: int,
    wall_seconds_cap: int = 120,
) -> str:
    if turn_index not in {0, 1}:
        raise RuntimeError("the experiment permits exactly two Director turns")
    if turn_index == 0:
        contract = {
            "phase": "choose_one_bounded_experiment",
            "required_actions": "exactly one start_lane",
            "allowed_algorithms": list(EXPERIMENT_ALGORITHMS),
            "allowed_graph_families": [
                item["id"] for item in action_catalog()["graph_families"]
            ],
            "maximum_batch_evaluations": evaluation_cap,
            "maximum_batch_wall_seconds": wall_seconds_cap,
            "maximum_graph_order": MAX_EXPERIMENT_GRAPH_ORDER,
            "prohibited": [
                "tools",
                "commands",
                "code generation",
                "files",
                "new operators",
                "arbitrary text actions",
            ],
        }
    else:
        contract = {
            "phase": "assess_the_measured_outcome",
            "required_assessment_prefix": [
                "CONTINUE:",
                "CHANGE_STRATEGY:",
                "STOP:",
            ],
            "execution_contract": (
                "Return a schema-valid proposed next action batch. It will be "
                "persisted but not dispatched. If recommending STOP, use one "
                "set_review_trigger action as the inert schema-required action."
            ),
            "prohibited": [
                "tools",
                "commands",
                "code generation",
                "files",
                "another search batch",
            ],
        }
    payload = {
        "objective": (
            "Make one evidence-based structured research decision from the "
            "committed campaign state."
        ),
        "experiment_contract": contract,
        "available_action_and_parameter_catalog": action_catalog(),
        "committed_research_snapshot": snapshot,
        "admissible_evidence_ids": snapshot.get("available_evidence_ids", []),
        "required_response": "Return only the existing Director decision schema.",
    }
    return canonical_json(payload, max_bytes=MAX_SNAPSHOT_BYTES).decode("ascii")


def run_phase_a_audit(workspace: Path) -> dict[str, Any]:
    root = workspace.resolve()
    root.mkdir(parents=True, exist_ok=True)
    application_data = root / ".sglab"
    if auth_is_imported(application_data):
        raise RuntimeError("Phase A refuses a workspace with imported auth")
    store = ResearchStore(root / "results.sqlite3")
    campaign_id = new_id("phase-a")
    campaign_dir = root / "research-campaigns" / campaign_id
    campaign_dir.mkdir(parents=True)
    manager = LaneManager(campaign_dir, max_active_lanes=1)
    provider = ReplayDecisionProvider(
        {},
        store=store,
        campaign_id=campaign_id,
    )
    deadline = datetime.now(UTC) + timedelta(minutes=5)
    store.create_campaign(
        campaign_id=campaign_id,
        target="erdos_gyarfas",
        target_definition_sha256=target_definition_sha256(),
        stop_mode="time_limit",
        deadline_at=deadline.isoformat().replace("+00:00", "Z"),
    )
    atomic_write_json(
        root / "active-research-campaign.json",
        {
            "campaign_id": campaign_id,
            "campaign_dir": str(campaign_dir),
        },
    )
    experiment = OneBatchExperiment(
        store=store,
        manager=manager,
        provider=provider,
        campaign_id=campaign_id,
        campaign_dir=campaign_dir,
        evaluation_cap=500,
        wall_seconds_cap=10,
    )
    try:
        first_state = experiment.publish_state()
        first_snapshot_id = str(first_state[0]["snapshot_id"])
        provider.decisions[first_snapshot_id] = _phase_a_first_decision(
            first_snapshot_id
        )
        first = asyncio.run(experiment.request_first_decision(first_state))
        outcome = experiment.execute_one_batch(first)
        second_state = experiment.publish_state()
        second_snapshot = second_state[0]
        feedback = next(
            item
            for item in second_snapshot["recent_actions"]
            if item["action_id"]
            == first.validated_decision["actions"][0]["action_id"]
        )
        second_snapshot_id = str(second_snapshot["snapshot_id"])
        provider.decisions[second_snapshot_id] = _phase_a_second_decision(
            second_snapshot_id,
            str(feedback["evidence_id"]),
        )
        second = asyncio.run(experiment.request_second_decision(second_state))
        store.finish_campaign(
            campaign_id,
            terminal_kind="stopped_by_operator",
            detail="Phase A completed after the second persisted replay decision",
        )
        integrity = str(
            store.connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        counts = {
            "turns": int(
                store.connection.execute(
                    "SELECT count(*) FROM app_server_turns WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchone()[0]
            ),
            "decision_batches": int(
                store.connection.execute(
                    """
                    SELECT count(*) FROM director_action_batches
                    WHERE campaign_id=?
                    """,
                    (campaign_id,),
                ).fetchone()[0]
            ),
            "search_batches": int(
                store.connection.execute(
                    """
                    SELECT count(*) FROM lane_metric_windows
                    WHERE campaign_id=?
                    """,
                    (campaign_id,),
                ).fetchone()[0]
            ),
        }
        status = campaign_status(root, campaign_id)
        report = {
            "phase": "A",
            "provider": "ReplayDecisionProvider",
            "authenticated_model_calls": 0,
            "campaign_id": campaign_id,
            "first_decision_batch_id": first.decision_batch_id,
            "second_decision_batch_id": second.decision_batch_id,
            "first_snapshot_id": first_snapshot_id,
            "second_snapshot_id": second_snapshot_id,
            "decision_before_search": bool(
                outcome["decision_before_search"][
                    "first_graph_evaluation_count"
                ]
                == 0
            ),
            "batch_outcome_serialized_to_second_state": (
                feedback["observed_effect"]["evaluation_count"]
                == outcome["evaluation_count"]
            ),
            "batch": {
                key: outcome[key]
                for key in (
                    "algorithm",
                    "parameters",
                    "seed",
                    "graph_family",
                    "graph_order",
                    "evaluation_count",
                    "throughput",
                    "elapsed_seconds",
                    "peak_rss_bytes",
                    "initial_score",
                    "best_score",
                    "score_trajectory_summary",
                    "operator_statistics",
                    "best_candidate_identifier",
                    "verifier_result",
                    "termination_reason",
                )
            },
            "counts": counts,
            "sqlite_integrity_check": integrity,
            "dashboard": {
                "director_decision": status.get("assessment") is not None,
                "active_search_parameters": bool(
                    status.get("lanes")
                    and status["lanes"][0].get("parameters")
                ),
                "batch_progress": bool(
                    status.get("lanes")
                    and status["lanes"][0]["telemetry_high_water"] == 300
                ),
                "final_outcome": any(
                    (action.get("observed_effect") or {}).get("evaluation_count")
                    == 300
                    for action in status.get("actions", [])
                ),
            },
            "recommended_evaluation_cap": max(
                500,
                min(10_000, int(float(outcome["throughput"]) * 30)),
            ),
            "failures": [],
        }
        report["ok"] = (
            report["decision_before_search"]
            and report["batch_outcome_serialized_to_second_state"]
            and integrity == "ok"
            and counts
            == {"turns": 2, "decision_batches": 2, "search_batches": 1}
            and all(report["dashboard"].values())
        )
        if not report["ok"]:
            report["failures"].append("one or more Phase A gates failed")
        output = root / "phase-a-report.json"
        atomic_write_json(output, report)
        return {**report, "report_path": str(output)}
    finally:
        manager.shutdown()
        row = store.connection.execute(
            """
            SELECT session_record_id, state FROM app_server_sessions
            WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchone()
        if row is not None and row["state"] == "active":
            store.close_session(str(row["session_record_id"]), state="closed")
        store.close()


def run_authenticated_experiment(
    workspace: Path,
    *,
    codex: str = "codex",
    evaluation_cap: int,
) -> dict[str, Any]:
    return asyncio.run(
        _run_authenticated_experiment(
            workspace.resolve(),
            codex=codex,
            evaluation_cap=evaluation_cap,
        )
    )


async def _run_authenticated_experiment(
    root: Path,
    *,
    codex: str,
    evaluation_cap: int,
) -> dict[str, Any]:
    application_data = root / ".sglab"
    if not auth_is_imported(application_data):
        raise RuntimeError("authenticated experiment requires explicit auth import")
    work = director_work(application_data)
    if any(work.iterdir()):
        raise RuntimeError("private runtime workspace must be empty")
    database_path = root / "results.sqlite3"
    if database_path.exists():
        raise RuntimeError("authenticated experiment requires a new session workspace")
    preflight = generate_protocol_preflight(codex)
    atomic_write_json(
        application_data / "director" / "preflight.json",
        preflight,
    )
    store = ResearchStore(database_path)
    campaign_id = new_id("ai-experiment")
    campaign_dir = root / "research-campaigns" / campaign_id
    campaign_dir.mkdir(parents=True)
    manager = LaneManager(campaign_dir, max_active_lanes=1)
    deadline = datetime.now(UTC) + timedelta(minutes=10)
    store.create_campaign(
        campaign_id=campaign_id,
        target="erdos_gyarfas",
        target_definition_sha256=target_definition_sha256(),
        stop_mode="time_limit",
        deadline_at=deadline.isoformat().replace("+00:00", "Z"),
    )
    atomic_write_json(
        root / "active-research-campaign.json",
        {
            "campaign_id": campaign_id,
            "campaign_dir": str(campaign_dir),
        },
    )
    protocol_hash = hashlib.sha256(
        json.dumps(
            preflight["canonical_schema_hashes"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    client = AppServerClient(
        AppServerConfig(
            application_data=application_data,
            launcher=(codex,),
        )
    )
    director = ActiveDirector(
        client=client,
        store=store,
        campaign_id=campaign_id,
        campaign_dir=campaign_dir,
        codex_version=str(preflight["codex_version_output"]),
        executable_sha256=str(preflight["codex_executable_sha256"]),
        protocol_schema_sha256=protocol_hash,
    )
    provider = SingleTurnAppServerDecisionProvider(
        director=director,
        prompt_builder=lambda snapshot, index: build_experiment_prompt(
            snapshot,
            index,
            evaluation_cap=evaluation_cap,
        ),
    )
    experiment = OneBatchExperiment(
        store=store,
        manager=manager,
        provider=provider,
        campaign_id=campaign_id,
        campaign_dir=campaign_dir,
        evaluation_cap=evaluation_cap,
    )
    first: CommittedExperimentDecision | None = None
    second: CommittedExperimentDecision | None = None
    outcome: dict[str, Any] | None = None
    shutdown_mode: str | None = None
    try:
        await director.start()
        first = await experiment.request_first_decision()
        outcome = experiment.execute_one_batch(first)
        second = await experiment.request_second_decision()
        if first.thread_id != second.thread_id:
            raise RuntimeError("Director decisions used different threads")
        store.finish_campaign(
            campaign_id,
            terminal_kind="stopped_by_operator",
            detail="Stopped after persisting the second experiment decision",
        )
    finally:
        manager.shutdown()
        await director.close()
        shutdown_mode = client.last_shutdown_mode
        stderr_relative = Path("director") / "app-server.stderr.log"
        stderr_path = campaign_dir / stderr_relative
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.write_text(client.stderr_text, encoding="utf-8")
        stderr_path.chmod(0o600)
    if first is None or second is None or outcome is None:
        store.close()
        raise RuntimeError("authenticated experiment did not complete")
    turns = [
        dict(row)
        for row in store.connection.execute(
            """
            SELECT * FROM app_server_turns WHERE campaign_id=?
            ORDER BY started_at, rowid
            """,
            (campaign_id,),
        )
    ]
    decision_count = int(
        store.connection.execute(
            """
            SELECT count(*) FROM director_action_batches WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchone()[0]
    )
    search_batch_count = int(
        store.connection.execute(
            "SELECT count(*) FROM lane_metric_windows WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()[0]
    )
    integrity = str(
        store.connection.execute("PRAGMA integrity_check").fetchone()[0]
    )
    second_feedback = next(
        item
        for item in second.snapshot["recent_actions"]
        if item["action_id"] == outcome["action_id"]
    )
    correlations, protocol_observations = _wire_correlations(
        campaign_dir, turns
    )
    report = {
        "campaign_id": campaign_id,
        "codex_version": preflight["codex_version_output"],
        "thread_id": first.thread_id,
        "turn_ids": [first.turn_id, second.turn_id],
        "turn_record_ids": [first.turn_record_id, second.turn_record_id],
        "final_agent_item_ids": [
            turn["final_agent_item_id"] for turn in turns
        ],
        "request_turn_item_correlations": correlations,
        "first_raw_decision": first.raw_decision,
        "first_validated_decision": first.validated_decision,
        "first_decision_batch_id": first.decision_batch_id,
        "batch_outcome": outcome,
        "second_snapshot_id": second.snapshot["snapshot_id"],
        "second_feedback_evidence": second_feedback,
        "second_raw_decision": second.raw_decision,
        "second_validated_decision": second.validated_decision,
        "second_decision_batch_id": second.decision_batch_id,
        "usage": [_turn_usage(turn) for turn in turns],
        "model_inferences": len(turns),
        "decision_batches": decision_count,
        "search_batches": search_batch_count,
        "unsupported_server_requests": client.unsupported_server_requests,
        "tool_calls": protocol_observations["tool_calls"],
        "retrying_errors": protocol_observations["retrying_errors"],
        "turn_start_requests": protocol_observations["turn_start_requests"],
        "skills_isolated": client.skills_isolated,
        "graceful_shutdown": shutdown_mode == "graceful",
        "shutdown_mode": shutdown_mode,
        "sqlite_integrity_check": integrity,
        "decision_before_search": (
            outcome["decision_before_search"]["first_graph_evaluation_count"]
            == 0
        ),
        "outcome_feedback_to_llm": (
            second_feedback["observed_effect"]["outcome_artifact_sha256"]
            == outcome["outcome_artifact_sha256"]
        ),
        "second_batch_not_executed": search_batch_count == 1,
        "failures": [],
    }
    required = (
        report["model_inferences"] == 2
        and all(turn["status"] == "completed_valid" for turn in turns)
        and report["decision_batches"] == 2
        and report["search_batches"] == 1
        and report["unsupported_server_requests"] == 0
        and not report["tool_calls"]
        and not report["retrying_errors"]
        and report["turn_start_requests"] == 2
        and all(report["final_agent_item_ids"])
        and report["skills_isolated"]
        and report["graceful_shutdown"]
        and integrity == "ok"
        and report["decision_before_search"]
        and report["outcome_feedback_to_llm"]
        and report["second_batch_not_executed"]
    )
    report["ok"] = required
    if not required:
        report["failures"].append("one or more authenticated experiment gates failed")
    report["artifact_sha256"] = {
        **_artifact_hashes(campaign_dir),
        **_runtime_audit_hashes(application_data),
    }
    output = root / "ai-experiment-report.json"
    atomic_write_json(output, report)
    store.close()
    return {**report, "report_path": str(output)}


def _phase_a_first_decision(snapshot_id: str) -> dict[str, Any]:
    action = _common_replay_action("phase-a-start", "start_lane")
    action["spec"] = {
        "algorithm": "simulated_annealing",
        "graph_family": "connected_cubic",
        "seed": 20260724,
        "parameters": {
            "order": 10,
            "batch_candidates": 300,
            "witness_cap": 16,
            "temperature": 1.0,
            "cooling": 0.995,
            "restart_threshold": 1000,
            "promotion_penalty": 1000,
        },
        "resource_share": 1.0,
    }
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": "Run one small deterministic replay batch.",
        "hypothesis_updates": [],
        "actions": [action],
        "next_review": {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": 300,
            "events": ["meaningful_improvement"],
        },
    }


def _phase_a_second_decision(
    snapshot_id: str, evidence_id: str
) -> dict[str, Any]:
    action = _common_replay_action("phase-a-review", "set_review_trigger")
    action["evidence_ids"] = [evidence_id]
    action["review_trigger"] = {
        "min_wall_seconds": 10,
        "max_wall_seconds": 30,
        "candidate_delta": 300,
        "events": ["meaningful_improvement"],
    }
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": (
            "CONTINUE: the measured replay outcome supports another bounded "
            "experiment, but this proposal remains undispatched."
        ),
        "hypothesis_updates": [],
        "actions": [action],
        "next_review": {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": 300,
            "events": ["meaningful_improvement"],
        },
    }


def _common_replay_action(
    action_id: str, action_type: str
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "type": action_type,
        "priority": 50,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": "Deterministic no-model integration evidence.",
        "expected_effect": "Measure one bounded search batch.",
        "evaluation_window": {
            "max_wall_seconds": 10,
            "max_candidate_delta": 300,
        },
        "idempotency_key": f"phase-a-{action_id}",
        "lease_seconds": 120,
        "fallback": {"on_precondition_failure": "reject"},
    }


def _turn_usage(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        key: turn[key]
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
            "raw_usage_json",
        )
    }


def _artifact_hashes(root: Path) -> dict[str, str]:
    values = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            values[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return values


def _runtime_audit_hashes(application_data: Path) -> dict[str, str]:
    values = {}
    director = application_data / "director"
    for relative in (
        Path("preflight.json"),
        Path("audit") / "skills-before.json",
        Path("audit") / "skills-after.json",
    ):
        path = director / relative
        if path.is_file():
            values[f"runtime-audit/{relative}"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return values


def _wire_correlations(
    campaign_dir: Path, turns: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    correlations = []
    tool_calls: list[dict[str, Any]] = []
    retrying_errors: list[dict[str, Any]] = []
    turn_start_requests = 0
    tool_markers = (
        "tool",
        "commandexecution",
        "shell",
        "mcp",
        "websearch",
        "filechange",
    )
    for turn in turns:
        path = (
            campaign_dir / str(turn["wire_log_artifact_ref"])
        ).resolve()
        path.relative_to(campaign_dir)
        request_ids: list[int | str] = []
        for raw_line in path.read_text(
            encoding="utf-8", errors="strict"
        ).splitlines():
            if len(raw_line) < 3 or raw_line[:2] not in {"> ", "< "}:
                continue
            message = json.loads(raw_line[2:])
            if (
                raw_line.startswith("> ")
                and message.get("method") == "turn/start"
            ):
                request_ids.append(message["id"])
                turn_start_requests += 1
            if (
                message.get("method") == "error"
                and message.get("params", {}).get("willRetry") is True
            ):
                retrying_errors.append(message)
            item = message.get("params", {}).get("item")
            item_type = (
                str(item.get("type", "")).lower()
                if isinstance(item, dict)
                else ""
            )
            if item_type and any(marker in item_type for marker in tool_markers):
                tool_calls.append(
                    {
                        "turn_record_id": turn["turn_record_id"],
                        "item_id": item.get("id"),
                        "item_type": item.get("type"),
                    }
                )
        if len(request_ids) != 1:
            raise RuntimeError(
                "wire artifact must contain exactly one turn/start request"
            )
        correlations.append(
            {
                "json_rpc_request_id": request_ids[0],
                "turn_record_id": turn["turn_record_id"],
                "thread_id": turn["thread_id"],
                "turn_id": turn["turn_id"],
                "final_agent_item_id": turn["final_agent_item_id"],
                "snapshot_id": turn["snapshot_id"],
                "trigger_id": turn["trigger_id"],
            }
        )
    return correlations, {
        "tool_calls": tool_calls,
        "retrying_errors": retrying_errors,
        "turn_start_requests": turn_start_requests,
    }

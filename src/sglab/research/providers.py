from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Protocol
import copy

from .director import ActiveDirector, DirectorEvidence
from .lanes import LaneManager
from .validation import DecisionContext, validate_decision
from .store import ResearchStore, new_id


class DecisionProvider(Protocol):
    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence: ...


@dataclass(slots=True)
class AppServerDecisionProvider:
    """The only production Active Director provider."""

    director: ActiveDirector

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        return await self.director.request_decision(
            snapshot=snapshot,
            trigger_id=trigger_id,
            context=context,
        )


@dataclass(slots=True)
class SerialAppServerDecisionProvider:
    """Experimental M5-compatible control that stops search during inference."""

    director: ActiveDirector
    manager: LaneManager

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        self.manager.pause_all()
        try:
            return await self.director.request_decision(
                snapshot=snapshot,
                trigger_id=trigger_id,
                context=context,
            )
        finally:
            self.manager.resume_all()


class SyntheticControlProvider:
    """Durable static/random study control; never a production fallback."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        campaign_id: str,
        mode: str,
        seed: int,
    ):
        if mode not in {"static", "random"}:
            raise ValueError("synthetic control mode must be static or random")
        self.store = store
        self.campaign_id = campaign_id
        self.mode = mode
        self.rng = Random(seed)
        self.session_record_id = f"control-session:{campaign_id}"
        self.thread_id = f"control-thread:{campaign_id}"
        self._started = False
        self._turn_index = 0

    async def start(
        self,
        *,
        resume_thread_id: str | None = None,
        parent_thread_id: str | None = None,
    ) -> None:
        if resume_thread_id not in {None, self.thread_id}:
            raise RuntimeError("control thread does not match campaign")
        self.store.record_session(
            record_id=self.session_record_id,
            campaign_id=self.campaign_id,
            thread_id=self.thread_id,
            session_id=None,
            thread_path=None,
            parent_thread_id=parent_thread_id,
            model=f"{self.mode}-control",
            effort="none",
            codex_version="synthetic-control-v1",
            executable_sha256="synthetic-control",
            protocol_schema_sha256="director-decision-v1",
            resumed=resume_thread_id is not None,
        )
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        row = self.store.connection.execute(
            """
            SELECT state FROM app_server_sessions
            WHERE session_record_id=?
            """,
            (self.session_record_id,),
        ).fetchone()
        if row is not None and row["state"] == "active":
            self.store.close_session(self.session_record_id, state="closed")
        self._started = False

    def rollover_due(self) -> bool:
        return False

    async def rollover(self) -> None:
        raise RuntimeError("synthetic control sessions never roll over")

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        if not self._started:
            raise RuntimeError("synthetic control provider is not started")
        decision = self._decision(snapshot, context)
        validation = validate_decision(decision, context)
        if not validation.accepted:
            detail = "; ".join(
                f"{issue.path}: {issue.message}" for issue in validation.issues
            )
            raise RuntimeError(f"synthetic control produced invalid action: {detail}")
        turn_record_id = new_id("control-turn")
        self.store.begin_turn(
            turn_record_id=turn_record_id,
            session_record_id=self.session_record_id,
            campaign_id=self.campaign_id,
            thread_id=self.thread_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            trigger_id=trigger_id,
            request_artifact_ref="control/generated",
            request_sha256="synthetic-control",
            wire_artifact_ref="control/no-wire",
        )
        self.store.complete_turn(
            turn_record_id,
            turn_id=turn_record_id,
            status="completed_valid",
            usage={
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 0,
            },
            wall_seconds=0.0,
        )
        self._turn_index += 1
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id=self.session_record_id,
            turn_record_ids=(turn_record_id,),
            thread_id=self.thread_id,
            turn_id=turn_record_id,
        )

    def _decision(
        self,
        snapshot: dict[str, Any],
        context: DecisionContext,
    ) -> dict[str, Any]:
        active = [
            lane
            for lane in snapshot.get("lanes", [])
            if lane.get("state") in {"starting", "running", "paused"}
        ]
        if not active:
            actions = [
                self._start_action(index, snapshot)
                for index in range(min(2, context.max_active_lanes))
            ]
            assessment = "Initialize the fixed equal-budget control portfolio."
        elif self._unsubmitted_candidate(snapshot, context) is not None:
            actions = [
                self._verification_action(
                    self._unsubmitted_candidate(snapshot, context)
                )
            ]
            assessment = "Apply the fixed finalist-verification rule."
        elif self.mode == "static":
            actions = [self._review_action()]
            assessment = (
                "Preserve the deterministic static portfolio without scientific "
                "intervention."
            )
        else:
            actions = [self._random_action(active, context)]
            assessment = "Apply one seeded random admissible intervention."
        return {
            "schema_version": "1.0",
            "snapshot_id": snapshot["snapshot_id"],
            "campaign_assessment": assessment,
            "hypothesis_updates": [],
            "actions": actions,
            "next_review": {
                "min_wall_seconds": 10,
                "max_wall_seconds": 30,
                "candidate_delta": 100_000,
                "events": [
                    "new_global_best",
                    "verification_result",
                    "lane_failure",
                    "resource_pressure",
                ],
            },
        }

    @staticmethod
    def _unsubmitted_candidate(
        snapshot: dict[str, Any],
        context: DecisionContext,
    ) -> str | None:
        best = snapshot.get("global_best")
        if not isinstance(best, dict):
            return None
        candidate_id = best.get("candidate_id")
        if candidate_id not in context.candidate_ids:
            return None
        jobs = snapshot.get("verification", {}).get("jobs", [])
        if any(
            isinstance(job, dict) and job.get("candidate_id") == candidate_id
            for job in jobs
        ):
            return None
        return str(candidate_id)

    def _verification_action(self, candidate_id: str | None) -> dict[str, Any]:
        if candidate_id is None:
            raise RuntimeError("verification control requires a candidate")
        action = self._common("schedule_verification")
        action.update(
            {
                "candidate_ids": [candidate_id],
                "verification_priority": 50,
            }
        )
        return action

    def _start_action(
        self, index: int, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        action = self._common("start_lane")
        target = str(snapshot.get("target", {}).get("target_id", ""))
        order = 10 if target == "m6_hidden_witness_control_v1" else 20
        algorithm = (
            "simulated_annealing"
            if index % 2 == 0
            else "iterated_local_search"
        )
        parameters: dict[str, Any] = {
            "order": order,
            "batch_candidates": 2_000,
            "witness_cap": 64,
            "restart_threshold": 20_000,
            "promotion_penalty": 1_000,
        }
        if algorithm == "simulated_annealing":
            parameters.update({"temperature": 1.0, "cooling": 0.995})
        else:
            parameters.update(
                {"tabu_tenure": 64, "perturbation_interval": 500}
            )
        action["spec"] = {
            "algorithm": algorithm,
            "graph_family": "connected_cubic",
            "seed": self.rng.randrange(2**63),
            "parameters": parameters,
            "resource_share": 0.5,
        }
        return action

    def _review_action(self) -> dict[str, Any]:
        action = self._common("set_review_trigger")
        action["review_trigger"] = {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": 100_000,
            "events": [
                "new_global_best",
                "verification_result",
                "lane_failure",
                "resource_pressure",
            ],
        }
        return action

    def _random_action(
        self,
        active: list[dict[str, Any]],
        context: DecisionContext,
    ) -> dict[str, Any]:
        lane = self.rng.choice(active)
        lane_id = str(lane["lane_id"])
        lane_version = int(lane["lane_version"])
        choices = ["patch", "restart", "reallocate"]
        checkpoint_id = lane.get("checkpoint_id")
        if checkpoint_id and len(active) < context.max_active_lanes:
            choices.append("fork")
        choice = self.rng.choice(choices)
        if choice == "patch":
            action = self._common("patch_lane")
            action.update(
                {
                    "lane_id": lane_id,
                    "expected_lane_version": lane_version,
                    "patch": {
                        "restart_threshold": self.rng.randint(1_000, 50_000)
                    },
                }
            )
            return action
        if choice == "restart":
            action = self._common("restart_lane")
            action.update(
                {
                    "lane_id": lane_id,
                    "expected_lane_version": lane_version,
                    "restart_spec": {
                        "source": "new_seed",
                        "seed": self.rng.randrange(2**63),
                    },
                }
            )
            return action
        if choice == "fork":
            action = self._common("fork_lane")
            action.update(
                {
                    "lane_id": lane_id,
                    "expected_lane_version": lane_version,
                    "checkpoint_id": checkpoint_id,
                    "variants": [
                        {
                            "name": "random-control",
                            "patch": {
                                "restart_threshold": self.rng.randint(
                                    1_000, 50_000
                                )
                            },
                            "resource_share": 0.25,
                        }
                    ],
                }
            )
            return action
        action = self._common("reallocate_resources")
        share = self.rng.random()
        allocations = []
        if len(active) == 1:
            allocations.append(
                {
                    "lane_id": lane_id,
                    "expected_lane_version": lane_version,
                    "resource_share": 1.0,
                }
            )
        else:
            first, second = active[:2]
            allocations.extend(
                [
                    {
                        "lane_id": str(first["lane_id"]),
                        "expected_lane_version": int(first["lane_version"]),
                        "resource_share": share,
                    },
                    {
                        "lane_id": str(second["lane_id"]),
                        "expected_lane_version": int(second["lane_version"]),
                        "resource_share": 1.0 - share,
                    },
                ]
            )
        action["allocations"] = allocations
        return action

    def _common(self, action_type: str) -> dict[str, Any]:
        suffix = f"{self._turn_index}-{self.rng.randrange(2**63)}"
        return {
            "action_id": f"{self.mode}-{action_type}-{suffix}",
            "type": action_type,
            "priority": 50,
            "hypothesis_ids": [],
            "evidence_ids": [],
            "rationale": f"{self.mode} equal-budget control policy",
            "expected_effect": "Control observation without an AI prediction.",
            "evaluation_window": {
                "max_wall_seconds": 30,
                "max_candidate_delta": 100_000,
            },
            "idempotency_key": f"{self.mode}-control-{action_type}-{suffix}",
            "lease_seconds": 120,
            "fallback": {"on_precondition_failure": "replan"},
        }


class ReplayDecisionProvider:
    """Model-free decision replay for audit and recovery tests only."""

    def __init__(
        self,
        decisions: dict[str, dict[str, Any]],
        *,
        store: ResearchStore | None = None,
        campaign_id: str | None = None,
    ):
        if (store is None) != (campaign_id is None):
            raise ValueError("durable replay requires store and campaign_id")
        self.decisions = copy.deepcopy(decisions)
        self.store = store
        self.campaign_id = campaign_id
        self._session_recorded = False

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        snapshot_id = str(snapshot["snapshot_id"])
        decision = copy.deepcopy(self.decisions[snapshot_id])
        validation = validate_decision(decision, context)
        if not validation.accepted:
            raise RuntimeError("recorded replay decision no longer validates")
        turn_record_id = f"replay:{trigger_id}"
        if self.store is not None and self.campaign_id is not None:
            if not self._session_recorded:
                thread_id = f"replay-thread:{self.campaign_id}"
                resumed = (
                    self.store.connection.execute(
                        """
                        SELECT 1 FROM app_server_sessions
                        WHERE campaign_id=? AND thread_id=?
                        """,
                        (self.campaign_id, thread_id),
                    ).fetchone()
                    is not None
                )
                self.store.record_session(
                    record_id=f"replay-session:{self.campaign_id}",
                    campaign_id=self.campaign_id,
                    thread_id=thread_id,
                    session_id=None,
                    thread_path=None,
                    parent_thread_id=None,
                    model="deterministic-replay",
                    effort="low",
                    codex_version="replay",
                    executable_sha256="replay",
                    protocol_schema_sha256="replay",
                    resumed=resumed,
                )
                self._session_recorded = True
            self.store.begin_turn(
                turn_record_id=turn_record_id,
                session_record_id=f"replay-session:{self.campaign_id}",
                campaign_id=self.campaign_id,
                thread_id=f"replay-thread:{self.campaign_id}",
                snapshot_id=snapshot_id,
                trigger_id=trigger_id,
                request_artifact_ref="replay/no-request",
                request_sha256="replay",
                wire_artifact_ref="replay/no-wire",
            )
            self.store.complete_turn(
                turn_record_id,
                turn_id=turn_record_id,
                status="completed_valid",
            )
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="replay",
            turn_record_ids=(turn_record_id,),
            thread_id="replay",
            turn_id=f"replay:{snapshot_id}",
        )

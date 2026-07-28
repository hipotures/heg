from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import copy
import hashlib
import json

from ..state import utc_now
from .director import DirectorEvidence
from .protocol import canonical_json
from .store import ResearchStore
from .triggers import TriggerBatch
from .validation import DecisionContext, validate_decision


PASSIVE_POLICY_ID = "balanced_v1"
PASSIVE_POLICY_VERSION = 1
PASSIVE_SCHEDULER_STATE_VERSION = 1
PASSIVE_REVIEW_CANDIDATE_DELTA = 4_000
PASSIVE_STAGNATION_WINDOWS = 2
PASSIVE_INITIAL_ALGORITHMS = (
    "random_restart",
    "simulated_annealing",
    "iterated_local_search",
    "iterated_local_search_tabu",
)
PASSIVE_CRITICAL_REASONS = {
    "action_lease_expired",
    "bootstrap",
    "lane_failure",
    "recovery",
    "resource_pressure",
    "verification_result",
    "verifier_disagreement",
}


class PassiveSchedulerFault(RuntimeError):
    pass


class DeterministicReviewTrigger:
    """Evaluation-boundary trigger with no wall-clock decision input."""

    def __init__(
        self,
        *,
        last_review_evaluations: int = 0,
        candidate_delta: int = PASSIVE_REVIEW_CANDIDATE_DELTA,
    ):
        if last_review_evaluations < 0:
            raise ValueError("last review evaluations cannot be negative")
        if candidate_delta < 1:
            raise ValueError("candidate delta must be positive")
        self.last_review_evaluations = last_review_evaluations
        self.candidate_delta = candidate_delta
        self._pending: set[str] = set()
        self._first_event_at: str | None = None

    def offer(
        self, reason: str, *, at: str | None = None, now: float | None = None
    ) -> bool:
        del now
        if reason not in PASSIVE_CRITICAL_REASONS:
            return False
        if not self._pending:
            self._first_event_at = at or utc_now()
        self._pending.add(reason)
        return True

    def observe_lane_event(
        self, event: dict[str, Any], *, recent_metrics: dict[str, Any]
    ) -> None:
        del recent_metrics
        if event.get("kind") == "exit" and event.get("reason") == "failure":
            self.offer("lane_failure", at=str(event.get("at") or utc_now()))

    def configure(self, review: dict[str, Any]) -> None:
        candidate_delta = int(review["candidate_delta"])
        if candidate_delta < 1:
            raise ValueError("candidate delta must be positive")
        self.candidate_delta = candidate_delta

    def due(
        self, *, total_candidates: int, now: float | None = None
    ) -> bool:
        del now
        if (
            total_candidates - self.last_review_evaluations
            >= self.candidate_delta
        ):
            if not self._pending:
                self._first_event_at = utc_now()
            self._pending.add("candidate_delta_reached")
        return bool(self._pending)

    def consume(
        self, *, total_candidates: int, now: float | None = None
    ) -> TriggerBatch:
        del now
        if not self.due(total_candidates=total_candidates):
            raise RuntimeError("passive scheduler trigger is not due")
        batch = TriggerBatch(
            reasons=tuple(sorted(self._pending)),
            first_event_at=self._first_event_at or utc_now(),
        )
        self._pending.clear()
        self._first_event_at = None
        self.last_review_evaluations = total_candidates
        return batch

    @property
    def pending_reasons(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending))


@dataclass(slots=True)
class _HashRng:
    seed: int
    counter: int

    def next_int(self, maximum: int = 2**63) -> int:
        if maximum < 1:
            raise ValueError("maximum must be positive")
        payload = canonical_json(
            {
                "policy_id": PASSIVE_POLICY_ID,
                "policy_version": PASSIVE_POLICY_VERSION,
                "seed": self.seed,
                "counter": self.counter,
            },
            max_bytes=4096,
        )
        self.counter += 1
        return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % maximum


class PassiveScheduler:
    """Versioned conservative host scheduler over reviewed action contracts."""

    source_kind = "passive_scheduler"

    def __init__(
        self,
        *,
        store: ResearchStore,
        campaign_id: str,
        seed: int,
    ):
        if not 0 <= seed < 2**63:
            raise ValueError("passive scheduler seed must be in [0, 2**63)")
        self.store = store
        self.campaign_id = campaign_id
        self.seed = seed
        self.state = self._initial_state(seed)
        self.review_boundary_evaluations: int | None = None
        self._started = False

    @staticmethod
    def _initial_state(seed: int) -> dict[str, Any]:
        return {
            "schema_version": PASSIVE_SCHEDULER_STATE_VERSION,
            "policy_id": PASSIVE_POLICY_ID,
            "policy_version": PASSIVE_POLICY_VERSION,
            "state_version": 0,
            "seed": seed,
            "rng_counter": 0,
            "review_index": 0,
            "last_review_evaluations": 0,
            "exploration_cursor": 0,
            "best_scalar_by_lane": {},
            "stagnation_windows_by_lane": {},
        }

    async def start(
        self,
        *,
        resume_thread_id: str | None = None,
        parent_thread_id: str | None = None,
    ) -> None:
        del parent_thread_id
        if resume_thread_id is not None:
            raise PassiveSchedulerFault(
                "passive scheduler cannot resume an App Server thread"
            )
        stored = self.store.passive_scheduler_state(self.campaign_id)
        if stored is not None:
            state = json.loads(str(stored["state_json"]))
            if (
                state.get("policy_id") != PASSIVE_POLICY_ID
                or int(state.get("policy_version", -1))
                != PASSIVE_POLICY_VERSION
                or int(state.get("seed", -1)) != self.seed
            ):
                raise PassiveSchedulerFault(
                    "persisted passive scheduler contract does not match"
                )
            self.state = state
        self._started = True

    async def close(self) -> None:
        self._started = False

    def rollover_due(self) -> bool:
        return False

    async def rollover(self) -> None:
        raise PassiveSchedulerFault("passive scheduler does not use sessions")

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        if not self._started:
            raise PassiveSchedulerFault("passive scheduler is not started")
        before = copy.deepcopy(self.state)
        decision, after, metrics, reason_codes = self._decision(
            snapshot, context
        )
        validation = validate_decision(decision, context)
        identity_payload = canonical_json(
            {
                "campaign_id": self.campaign_id,
                "policy_id": PASSIVE_POLICY_ID,
                "policy_version": PASSIVE_POLICY_VERSION,
                "state_version": before["state_version"],
                "review_index": before["review_index"],
                "trigger_id": trigger_id,
            },
            max_bytes=4096,
        )
        scheduler_decision_id = (
            "passive-decision-"
            + hashlib.sha256(identity_payload).hexdigest()[:32]
        )
        if validation.accepted:
            self.state = after
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="",
            turn_record_ids=(),
            thread_id="",
            turn_id="",
            source_kind="passive_scheduler",
            source_record_id=scheduler_decision_id,
            source_metadata={
                "policy_id": PASSIVE_POLICY_ID,
                "policy_version": PASSIVE_POLICY_VERSION,
                "scheduler_state_version": (
                    PASSIVE_SCHEDULER_STATE_VERSION
                ),
                "state_before": before,
                "state_after": after,
                "input_snapshot_version": int(
                    snapshot["campaign"]["state_version"]
                ),
                "input_metrics": metrics,
                "reason_codes": reason_codes,
            },
        )

    def _decision(
        self,
        snapshot: dict[str, Any],
        context: DecisionContext,
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        list[str],
    ]:
        state = copy.deepcopy(self.state)
        rng = _HashRng(int(state["seed"]), int(state["rng_counter"]))
        lanes = sorted(
            (
                lane
                for lane in snapshot.get("lanes", [])
                if str(lane.get("lane_id")) in context.lane_versions
            ),
            key=lambda lane: str(lane["lane_id"]),
        )
        current_evaluations = sum(
            int(lane.get("metrics", {}).get("end_high_water", 0))
            for lane in lanes
        )
        lane_metrics: dict[str, Any] = {}
        active_ids = {str(lane["lane_id"]) for lane in lanes}
        previous_best = dict(state["best_scalar_by_lane"])
        stagnation = dict(state["stagnation_windows_by_lane"])
        for lane in lanes:
            lane_id = str(lane["lane_id"])
            metrics = lane.get("metrics") or {}
            best = float(metrics.get("best_scalar", 0.0))
            previous = previous_best.get(lane_id)
            improved = previous is None or best < float(previous)
            previous_best[lane_id] = best
            stagnation[lane_id] = 0 if improved else int(
                stagnation.get(lane_id, 0)
            ) + 1
            lane_metrics[lane_id] = {
                "lane_version": int(lane["lane_version"]),
                "algorithm": str(lane["algorithm"]),
                "end_high_water": int(metrics.get("end_high_water", 0)),
                "best_scalar": best,
                "operator_yield": float(
                    metrics.get("operator_yield", 0.0)
                ),
                "stagnation_windows": stagnation[lane_id],
                "checkpoint_id": lane.get("checkpoint_id"),
                "resource_share": float(lane.get("resource_share", 0.0)),
            }
        state["best_scalar_by_lane"] = {
            key: value
            for key, value in previous_best.items()
            if key in active_ids
        }
        state["stagnation_windows_by_lane"] = {
            key: value for key, value in stagnation.items() if key in active_ids
        }
        state["last_review_evaluations"] = int(
            self.review_boundary_evaluations
            if self.review_boundary_evaluations is not None
            else current_evaluations
        )

        actions: list[dict[str, Any]] = []
        reasons: list[str] = []
        candidate_id = self._unsubmitted_candidate(snapshot, context)
        if candidate_id is not None:
            actions.append(
                self._verification_action(
                    state, len(actions), candidate_id
                )
            )
            reasons.append("eligible_candidate_verification")

        initial_size = min(
            len(PASSIVE_INITIAL_ALGORITHMS), context.max_active_lanes
        )
        if len(lanes) < initial_size:
            missing = initial_size - len(lanes)
            present = {str(lane["algorithm"]) for lane in lanes}
            algorithms = [
                algorithm
                for algorithm in PASSIVE_INITIAL_ALGORITHMS
                if algorithm not in present
            ]
            for algorithm in algorithms[:missing]:
                actions.append(
                    self._start_action(
                        state,
                        rng,
                        len(actions),
                        snapshot,
                        algorithm,
                        resource_share=1.0 / max(1, initial_size),
                    )
                )
            reasons.extend(
                ("initial_portfolio", "exploration_floor_preserved")
            )
        elif len(lanes) < context.max_active_lanes:
            fill_count = min(2, context.max_active_lanes - len(lanes))
            for _ in range(fill_count):
                cursor = int(state["exploration_cursor"])
                algorithm = PASSIVE_INITIAL_ALGORITHMS[
                    cursor % len(PASSIVE_INITIAL_ALGORITHMS)
                ]
                actions.append(
                    self._start_action(
                        state,
                        rng,
                        len(actions),
                        snapshot,
                        algorithm,
                        resource_share=1.0 / context.max_active_lanes,
                    )
                )
            reasons.extend(
                ("fill_unused_capacity", "exploration_floor_preserved")
            )

        stagnant = sorted(
            (
                lane
                for lane in lanes
                if int(
                    state["stagnation_windows_by_lane"].get(
                        str(lane["lane_id"]), 0
                    )
                )
                >= PASSIVE_STAGNATION_WINDOWS
            ),
            key=lambda lane: (
                -int(
                    state["stagnation_windows_by_lane"][
                        str(lane["lane_id"])
                    ]
                ),
                str(lane["lane_id"]),
            ),
        )
        if stagnant and len(actions) < 12:
            lane = stagnant[0]
            actions.append(
                self._restart_action(
                    state, rng, len(actions), lane
                )
            )
            state["stagnation_windows_by_lane"][
                str(lane["lane_id"])
            ] = 0
            reasons.append(
                "promising_checkpoint_restart"
                if lane.get("checkpoint_id")
                else "lane_stagnation_restart"
            )

        if not actions:
            allocations = self._balanced_allocations(lanes)
            if allocations is not None:
                action = self._common_action(
                    state, len(actions), "reallocate_resources"
                )
                action["allocations"] = allocations
                actions.append(action)
                reasons.extend(
                    ("resource_rebalance", "exploration_floor_preserved")
                )
            else:
                actions.append(
                    self._review_action(state, len(actions))
                )
                reasons.extend(
                    ("continue_promising_lanes", "exploration_floor_preserved")
                )

        state["rng_counter"] = rng.counter
        state["review_index"] = int(state["review_index"]) + 1
        state["state_version"] = int(state["state_version"]) + 1
        reasons = sorted(set(reasons))
        metrics = {
            "review_index": int(self.state["review_index"]),
            "total_evaluations": current_evaluations,
            "active_lane_count": len(lanes),
            "max_active_lanes": context.max_active_lanes,
            "lanes": lane_metrics,
        }
        decision = {
            "schema_version": "1.0",
            "snapshot_id": snapshot["snapshot_id"],
            "campaign_assessment": (
                "No-LLM passive search: " + ", ".join(reasons)
            ),
            "hypothesis_updates": [],
            "actions": actions[:12],
            "next_review": self._review_contract(),
        }
        return decision, state, metrics, reasons

    @staticmethod
    def _unsubmitted_candidate(
        snapshot: dict[str, Any], context: DecisionContext
    ) -> str | None:
        best = snapshot.get("global_best")
        if not isinstance(best, dict):
            return None
        candidate_id = best.get("candidate_id")
        if (
            candidate_id not in context.candidate_ids
            or candidate_id not in context.executable_target_ids
        ):
            return None
        jobs = snapshot.get("verification", {}).get("jobs", [])
        if any(
            isinstance(job, dict) and job.get("candidate_id") == candidate_id
            for job in jobs
        ):
            return None
        return str(candidate_id)

    def _start_action(
        self,
        state: dict[str, Any],
        rng: _HashRng,
        index: int,
        snapshot: dict[str, Any],
        algorithm: str,
        *,
        resource_share: float,
    ) -> dict[str, Any]:
        action = self._common_action(state, index, "start_lane")
        target = str(snapshot.get("target", {}).get("target_id", ""))
        parameters: dict[str, Any] = {
            "order": 10 if target == "m6_hidden_witness_control_v1" else 20,
            "batch_candidates": 2_000,
            "witness_cap": 64,
        }
        if algorithm == "simulated_annealing":
            parameters.update(
                {
                    "temperature": 1.0,
                    "cooling": 0.995,
                    "restart_threshold": 20_000,
                    "mutation_weights": {
                        "uniform_two_edge_switch": 0.75,
                        "forbidden_cycle_break_switch": 0.25,
                    },
                }
            )
        elif algorithm in {
            "iterated_local_search",
            "iterated_local_search_tabu",
        }:
            parameters.update(
                {
                    "tabu_tenure": 64,
                    "perturbation_interval": 500,
                    "mutation_weights": {
                        "uniform_two_edge_switch": 0.5,
                        "forbidden_cycle_break_switch": 0.5,
                    },
                }
            )
        action["spec"] = {
            "algorithm": algorithm,
            "graph_family": "connected_cubic",
            "seed": rng.next_int(),
            "parameters": parameters,
            "resource_share": resource_share,
        }
        state["exploration_cursor"] = int(state["exploration_cursor"]) + 1
        return action

    def _restart_action(
        self,
        state: dict[str, Any],
        rng: _HashRng,
        index: int,
        lane: dict[str, Any],
    ) -> dict[str, Any]:
        action = self._common_action(state, index, "restart_lane")
        checkpoint_id = lane.get("checkpoint_id")
        restart = {
            "source": "checkpoint" if checkpoint_id else "new_seed",
            "seed": rng.next_int(),
        }
        if checkpoint_id:
            restart["checkpoint_id"] = checkpoint_id
        action.update(
            {
                "lane_id": str(lane["lane_id"]),
                "expected_lane_version": int(lane["lane_version"]),
                "restart_spec": restart,
            }
        )
        return action

    def _verification_action(
        self, state: dict[str, Any], index: int, candidate_id: str
    ) -> dict[str, Any]:
        action = self._common_action(
            state, index, "schedule_verification"
        )
        action.update(
            {
                "candidate_ids": [candidate_id],
                "verification_priority": 50,
            }
        )
        return action

    def _review_action(
        self, state: dict[str, Any], index: int
    ) -> dict[str, Any]:
        action = self._common_action(
            state, index, "set_review_trigger"
        )
        action["review_trigger"] = self._review_contract()
        return action

    @staticmethod
    def _balanced_allocations(
        lanes: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if not lanes:
            return None
        share = 1.0 / len(lanes)
        if all(
            abs(float(lane.get("resource_share", 0.0)) - share) < 1e-9
            for lane in lanes
        ):
            return None
        return [
            {
                "lane_id": str(lane["lane_id"]),
                "expected_lane_version": int(lane["lane_version"]),
                "resource_share": share,
            }
            for lane in lanes
        ]

    def _common_action(
        self, state: dict[str, Any], index: int, action_type: str
    ) -> dict[str, Any]:
        payload = canonical_json(
            {
                "campaign_id": self.campaign_id,
                "policy_id": PASSIVE_POLICY_ID,
                "policy_version": PASSIVE_POLICY_VERSION,
                "state_version": state["state_version"],
                "review_index": state["review_index"],
                "action_index": index,
                "action_type": action_type,
            },
            max_bytes=4096,
        )
        suffix = hashlib.sha256(payload).hexdigest()[:24]
        return {
            "action_id": f"passive-{action_type}-{suffix}",
            "type": action_type,
            "priority": 50,
            "hypothesis_ids": [],
            "evidence_ids": [],
            "rationale": (
                f"{PASSIVE_POLICY_ID} deterministic host policy"
            ),
            "expected_effect": (
                "Bounded search progress under reviewed host controls."
            ),
            "evaluation_window": {
                "max_wall_seconds": 30,
                "max_candidate_delta": PASSIVE_REVIEW_CANDIDATE_DELTA,
            },
            "idempotency_key": (
                f"passive:{PASSIVE_POLICY_ID}:{suffix}"
            ),
            "lease_seconds": 120,
            "fallback": {"on_precondition_failure": "reject"},
        }

    @staticmethod
    def _review_contract() -> dict[str, Any]:
        return {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": PASSIVE_REVIEW_CANDIDATE_DELTA,
            "events": [
                "verification_result",
                "verifier_disagreement",
                "lane_failure",
                "resource_pressure",
                "action_lease_expired",
            ],
        }

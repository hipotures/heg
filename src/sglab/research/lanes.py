from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from queue import Empty, Full
from random import Random
from typing import Any
import ast
import dataclasses
import hashlib
import json
import math
import resource
import time

from ..model import BitGraph
from ..resources import set_address_space_limit
from ..state import atomic_write_json, utc_now
from ..targets import TARGETS
from ..targets.base import ScoreResult
from .catalog import (
    ALGORITHMS,
    ALGORITHM_PARAMETERS,
    GRAPH_FAMILIES,
    MUTATION_OPERATORS,
    MUTATION_WEIGHTS_PARAMETER,
    PARAMETER_DOMAINS,
)
from .protocol import canonical_json
from .telemetry import TelemetrySeries


ANCESTRY_LIMIT = 64
TIMING_COUNTER_NAMES = (
    "mutation_generation",
    "graph_validation",
    "witness_counting",
    "score_calculation",
    "duplicate_detection",
    "tabu_bookkeeping",
    "ancestry_construction",
    "telemetry_construction",
    "sqlite_persistence",
    "exact_final_verification",
)


@dataclass(frozen=True, slots=True)
class LaneSpec:
    lane_id: str
    campaign_id: str
    target: str
    algorithm: str
    graph_family: str
    seed: int
    parameters: dict[str, Any]
    resource_share: float
    lane_version: int = 0
    parent_lane_id: str | None = None
    created_by_action_id: str | None = None
    parent_checkpoint_id: str | None = None
    seed_lineage: tuple[int, ...] = ()

    def validate(self) -> None:
        if self.target not in TARGETS:
            raise ValueError(f"unsupported lane target: {self.target}")
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"unsupported lane algorithm: {self.algorithm}")
        if self.graph_family not in GRAPH_FAMILIES:
            raise ValueError(f"unsupported graph family: {self.graph_family}")
        if not 0 < self.resource_share <= 1:
            raise ValueError("resource_share must be in (0, 1]")
        if self.lane_version < 0:
            raise ValueError("lane_version cannot be negative")
        allowed = ALGORITHM_PARAMETERS[self.algorithm]
        if set(self.parameters) - allowed:
            raise ValueError("lane has parameters outside its algorithm domain")
        for required in ("order", "batch_candidates", "witness_cap"):
            if required not in self.parameters:
                raise ValueError(f"lane parameter is required: {required}")
        for name, value in self.parameters.items():
            if name == MUTATION_WEIGHTS_PARAMETER:
                if not isinstance(value, dict) or set(value) != set(
                    MUTATION_OPERATORS
                ):
                    raise ValueError(
                        "mutation_weights must contain every reviewed operator"
                    )
                if any(
                    isinstance(weight, bool)
                    or not isinstance(weight, (int, float))
                    or weight < 0
                    for weight in value.values()
                ):
                    raise ValueError("mutation weights must be non-negative")
                if not math.isclose(
                    sum(float(weight) for weight in value.values()),
                    1.0,
                    rel_tol=0,
                    abs_tol=1e-9,
                ):
                    raise ValueError("mutation weights must be normalized")
                continue
            domain = PARAMETER_DOMAINS[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"lane parameter must be numeric: {name}")
            if domain["type"] == "integer" and not isinstance(value, int):
                raise ValueError(f"lane parameter must be an integer: {name}")
            if not domain["minimum"] <= value <= domain["maximum"]:
                raise ValueError(f"lane parameter outside reviewed domain: {name}")
        if (
            self.graph_family == "connected_cubic"
            and int(self.parameters["order"]) % 2
        ):
            raise ValueError("connected_cubic requires even order")


@dataclass(slots=True)
class LaneRuntime:
    spec: LaneSpec
    process: Any
    commands: Any
    stop_event: Any
    pause_event: Any
    state: str = "starting"
    lane_version: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)
    resource_share: float = 0.0
    latest_checkpoint_id: str | None = None
    latest_checkpoint: dict[str, Any] | None = None
    telemetry: TelemetrySeries = field(default_factory=TelemetrySeries)
    high_water: int = 0
    improvements: list[dict[str, Any]] = field(default_factory=list)
    pending_actions: set[str] = field(default_factory=set)
    completed_action_ids: set[str] = field(default_factory=set)
    action_outcomes: list[dict[str, Any]] = field(default_factory=list)


class _LaneKernel:
    def __init__(
        self,
        spec: LaneSpec,
        checkpoint: dict[str, Any] | None,
        fork_seed: int | None,
        *,
        instrumentation_enabled: bool = True,
    ):
        self.spec = spec
        self.plugin = TARGETS[spec.target]
        self.parameters = dict(spec.parameters)
        self.mode = GRAPH_FAMILIES[spec.graph_family]
        self.instrumentation_enabled = instrumentation_enabled
        self.timing_ns = (
            {name: 0 for name in TIMING_COUNTER_NAMES}
            if instrumentation_enabled
            else None
        )
        self.accepted_ancestry: deque[dict[str, Any]] = deque(
            maxlen=ANCESTRY_LIMIT
        )
        self.best_ancestry: list[dict[str, Any]] = []
        self.current_candidate_id = ""
        self.best_candidate_id = ""
        self.rng = Random(spec.seed)
        self.algorithm_evaluated = 0
        self.stagnation = 0
        self.tabu: deque[str] = deque(maxlen=4096)
        self.high_water = 0
        self.total_accepted = 0
        self.total_improvements = 0
        self.actual_restarts = 0
        self.recent_hashes: deque[str] = deque(maxlen=4096)
        self.recent_hash_set: set[str] = set()
        if checkpoint is None:
            self._new_seed(spec.seed)
        else:
            self.graph = BitGraph.from_graph6(str(checkpoint["graph6"]))
            self.score = _score_from_payload(checkpoint["score"])
            self.best_graph = BitGraph.from_graph6(
                str(checkpoint.get("best_graph6", checkpoint["graph6"]))
            )
            self.best_score = _score_from_payload(
                checkpoint.get("best_score", checkpoint["score"])
            )
            if fork_seed is None:
                self.rng.setstate(ast.literal_eval(str(checkpoint["rng_state"])))
                self.algorithm_evaluated = int(
                    checkpoint.get("algorithm_evaluated", 0)
                )
                self.stagnation = int(checkpoint.get("stagnation", 0))
                self.high_water = int(checkpoint.get("high_water", 0))
            else:
                self.rng = Random(fork_seed)
            restored_tabu = (
                checkpoint.get("tabu", [])
                if fork_seed is None
                else [self.graph.stable_hash()]
            )
            self.tabu = deque(
                (str(value) for value in restored_tabu),
                maxlen=int(self.parameters.get("tabu_tenure", 128)),
            )
            if not self.tabu:
                self.tabu.append(self.graph.stable_hash())
            self.accepted_ancestry = deque(
                (
                    dict(value)
                    for value in checkpoint.get("accepted_ancestry", [])
                ),
                maxlen=ANCESTRY_LIMIT,
            )
            self.best_ancestry = [
                dict(value)
                for value in checkpoint.get("best_ancestry", [])
            ][-ANCESTRY_LIMIT:]
            self.current_candidate_id = str(
                checkpoint.get(
                    "current_candidate_id",
                    _candidate_id(self.spec.campaign_id, self.graph),
                )
            )
            self.best_candidate_id = str(
                checkpoint.get(
                    "best_candidate_id",
                    _candidate_id(self.spec.campaign_id, self.best_graph),
                )
            )

    def _new_seed(self, seed: int) -> None:
        self.rng = Random(seed)
        self.graph = self.plugin.generate_seed(
            self.rng,
            {"order": int(self.parameters["order"]), "mode": self.mode},
        )
        self.score = self.plugin.cheap_score(
            self.graph, int(self.parameters["witness_cap"])
        )
        self.best_graph = self.graph
        self.best_score = self.score
        self.current_candidate_id = _candidate_id(
            self.spec.campaign_id, self.graph
        )
        self.best_candidate_id = self.current_candidate_id
        self.accepted_ancestry.clear()
        self.best_ancestry = []
        self.algorithm_evaluated = 0
        self.stagnation = 0
        self.tabu.clear()
        self.tabu.append(self.graph.stable_hash())
        self.recent_hashes.clear()
        self.recent_hash_set.clear()

    def restart(self, seed: int) -> None:
        self._new_seed(seed)

    def restart_from_checkpoint(
        self, checkpoint: dict[str, Any], seed: int
    ) -> None:
        self.graph = BitGraph.from_graph6(str(checkpoint["graph6"]))
        self.score = _score_from_payload(checkpoint["score"])
        self.best_graph = BitGraph.from_graph6(
            str(checkpoint.get("best_graph6", checkpoint["graph6"]))
        )
        self.best_score = _score_from_payload(
            checkpoint.get("best_score", checkpoint["score"])
        )
        self.accepted_ancestry = deque(
            (
                dict(value)
                for value in checkpoint.get("accepted_ancestry", [])
            ),
            maxlen=ANCESTRY_LIMIT,
        )
        self.best_ancestry = [
            dict(value) for value in checkpoint.get("best_ancestry", [])
        ][-ANCESTRY_LIMIT:]
        self.current_candidate_id = str(
            checkpoint.get(
                "current_candidate_id",
                _candidate_id(self.spec.campaign_id, self.graph),
            )
        )
        self.best_candidate_id = str(
            checkpoint.get(
                "best_candidate_id",
                _candidate_id(self.spec.campaign_id, self.best_graph),
            )
        )
        self.rng = Random(seed)
        self.algorithm_evaluated = 0
        self.stagnation = 0
        self.tabu.clear()
        self.tabu.append(self.graph.stable_hash())
        self.recent_hashes.clear()
        self.recent_hash_set.clear()

    def patch(self, patch: dict[str, Any]) -> None:
        if "order" in patch and int(patch["order"]) != self.graph.n:
            raise ValueError("running lane order can change only through restart")
        self.parameters.update(patch)
        self.tabu = deque(
            self.tabu,
            maxlen=int(self.parameters.get("tabu_tenure", 128)),
        )

    def run_batch(
        self,
        stop_event: Any,
        *,
        max_evaluations: int | None = None,
        max_wall_seconds: float | None = None,
    ) -> dict[str, Any]:
        target = min(
            int(self.parameters["batch_candidates"]),
            max_evaluations
            if max_evaluations is not None
            else int(self.parameters["batch_candidates"]),
        )
        if target < 1:
            raise ValueError("batch evaluation limit must be positive")
        if max_wall_seconds is not None and max_wall_seconds <= 0:
            raise ValueError("batch wall limit must be positive")
        if self.timing_ns is not None:
            for name in self.timing_ns:
                self.timing_ns[name] = 0
        started = time.perf_counter()
        deadline = (
            started + max_wall_seconds
            if max_wall_seconds is not None
            else None
        )
        initial_score = self.score
        score_counts_truncated = not initial_score.complete
        trajectory: list[dict[str, Any]] = []
        global_records: list[dict[str, Any]] = []
        ancestry_operator_statistics: dict[str, dict[str, int]] = {}
        evaluated = accepted = legal = improvements = duplicates = 0
        accepted_at_last_record = 0
        for _ in range(target):
            if stop_event.is_set():
                break
            if deadline is not None and time.perf_counter() >= deadline:
                break
            if (
                self.algorithm == "simulated_annealing"
                and self.algorithm_evaluated > 0
                and self.algorithm_evaluated
                % int(self.parameters.get("restart_threshold", 50_000))
                == 0
            ):
                self._new_seed(self.rng.randrange(2**63))
                self.actual_restarts += 1
            mutation_started = (
                time.perf_counter_ns()
                if self.timing_ns is not None
                else 0
            )
            mutation_operator = (
                "random_restart_seed"
                if self.algorithm == "random_restart"
                else self._choose_mutation_operator()
            )
            operator_counts = ancestry_operator_statistics.setdefault(
                mutation_operator,
                {"uses": 0, "accepted": 0, "global_records": 0},
            )
            operator_counts["uses"] += 1
            candidate = (
                self.plugin.generate_seed(
                    self.rng,
                    {
                        "order": int(self.parameters["order"]),
                        "mode": self.mode,
                    },
                )
                if self.algorithm == "random_restart"
                else self.plugin.mutate(
                    self.graph,
                    self.rng,
                    {
                        "mode": self.mode,
                        "mutation_operator": mutation_operator,
                    },
                )
            )
            if self.timing_ns is not None:
                self.timing_ns["mutation_generation"] += (
                    time.perf_counter_ns() - mutation_started
                )
            evaluated += 1
            self.algorithm_evaluated += 1
            if candidate == self.graph:
                continue
            legal += 1
            duplicate_started = (
                time.perf_counter_ns()
                if self.timing_ns is not None
                else 0
            )
            key = candidate.stable_hash()
            if key in self.recent_hash_set:
                duplicates += 1
            self._remember_hash(key)
            if self.timing_ns is not None:
                self.timing_ns["duplicate_detection"] += (
                    time.perf_counter_ns() - duplicate_started
                )
            candidate_score = self._score(candidate)
            score_counts_truncated = (
                score_counts_truncated or not candidate_score.complete
            )
            tabu_started = (
                time.perf_counter_ns()
                if self.timing_ns is not None
                and self.algorithm
                in {"iterated_local_search", "iterated_local_search_tabu"}
                else 0
            )
            accept = (
                True
                if self.algorithm == "random_restart"
                else self._accept(candidate_score, key)
            )
            if tabu_started and self.timing_ns is not None:
                self.timing_ns["tabu_bookkeeping"] += (
                    time.perf_counter_ns() - tabu_started
                )
            global_record = (
                candidate_score.ordering_key
                < self.best_score.ordering_key
            )
            mutation_record: dict[str, Any] | None = None
            if self.instrumentation_enabled and (accept or global_record):
                ancestry_started = time.perf_counter_ns()
                mutation_record = _mutation_record(
                    campaign_id=self.spec.campaign_id,
                    parent=self.graph,
                    child=candidate,
                    parent_candidate_id=self.current_candidate_id,
                    score_before=self.score,
                    score_after=candidate_score,
                    evaluation=evaluated,
                    accepted=accept,
                    global_record=global_record,
                    mutation_operator=mutation_operator,
                )
                if self.timing_ns is not None:
                    self.timing_ns["ancestry_construction"] += (
                        time.perf_counter_ns() - ancestry_started
                    )
            operator_counts["accepted"] += int(accept)
            operator_counts["global_records"] += int(global_record)
            if accept:
                self.graph = candidate
                self.score = candidate_score
                if mutation_record is not None:
                    self.accepted_ancestry.append(mutation_record)
                    self.current_candidate_id = str(
                        mutation_record["candidate_id"]
                    )
                accepted += 1
                self.total_accepted += 1
            if global_record:
                self.best_graph = candidate
                self.best_score = candidate_score
                self.best_candidate_id = _candidate_id(
                    self.spec.campaign_id, candidate
                )
                if mutation_record is not None:
                    if accept:
                        self.best_ancestry = list(self.accepted_ancestry)
                    else:
                        self.best_ancestry = (
                            list(self.accepted_ancestry)[
                                -(ANCESTRY_LIMIT - 1) :
                            ]
                            + [mutation_record]
                        )
                    global_records.append(mutation_record)
                improvements += 1
                self.total_improvements += 1
                accepted_at_last_record = accepted
                self.stagnation = 0
                if len(trajectory) < 64:
                    trajectory.append(
                        {
                            "evaluation": evaluated,
                            "score": list(candidate_score.ordering_key),
                        }
                    )
            else:
                self.stagnation += 1
        self.high_water += evaluated
        loop_finished = time.perf_counter()
        elapsed = max(loop_finished - started, 1e-9)
        termination_reason = (
            "stop_requested"
            if stop_event.is_set()
            else (
                "wall_time_limit"
                if deadline is not None
                and evaluated < target
                and time.perf_counter() >= deadline
                else "evaluation_limit"
            )
        )
        telemetry_started = (
            time.perf_counter_ns()
            if self.timing_ns is not None
            else 0
        )
        for counts in ancestry_operator_statistics.values():
            counts["yield"] = counts["global_records"] / max(1, counts["uses"])
            counts["acceptance_rate"] = counts["accepted"] / max(
                1, counts["uses"]
            )
        plateau_evaluations = (
            evaluated - int(trajectory[-1]["evaluation"])
            if trajectory
            else evaluated
        )
        accepted_since_record = accepted - accepted_at_last_record
        remaining_budget = max(0, target - evaluated)
        plateau_threshold = max(25, min(250, target // 3))
        plateau_signal = {
            "active": (
                plateau_evaluations >= plateau_threshold
                and accepted_since_record > 0
                and (1.0 - duplicates / max(1, legal)) >= 0.25
                and remaining_budget > 0
            ),
            "evaluations_since_last_global_record": plateau_evaluations,
            "accepted_moves_since_last_global_record": accepted_since_record,
            "diversity": 1.0 - duplicates / max(1, legal),
            "remaining_evaluation_budget": remaining_budget,
            "evaluation_threshold": plateau_threshold,
            "telemetry_only": True,
        }
        result = {
            "evaluated": evaluated,
            "accepted": accepted,
            "legal": legal,
            "improvements": improvements,
            "duplicates": duplicates,
            "elapsed_seconds": elapsed,
            "candidates_per_second": evaluated / elapsed,
            "acceptance_rate": accepted / max(1, legal),
            "duplicate_rate": duplicates / max(1, legal),
            "diversity": 1.0 - duplicates / max(1, legal),
            "operator_yield": improvements / max(1, legal),
            "best_score": list(self.best_score.ordering_key),
            "best_scalar": _score_scalar(self.best_score),
            "initial_score": _score_payload(initial_score),
            "final_score": _score_payload(self.score),
            "score_trajectory_summary": {
                "initial": list(initial_score.ordering_key),
                "final": list(self.score.ordering_key),
                "best": list(self.best_score.ordering_key),
                "improvement_count": improvements,
                "improvement_samples": trajectory,
                "samples_truncated": improvements > len(trajectory),
            },
            "operator_statistics": {
                "accepted": accepted,
                "legal": legal,
                "improvements": improvements,
                "duplicates": duplicates,
                "acceptance_rate": accepted / max(1, legal),
                "duplicate_rate": duplicates / max(1, legal),
                "operator_yield": improvements / max(1, legal),
                "mutation_operators": ancestry_operator_statistics,
            },
            "best_evaluation": (
                int(trajectory[-1]["evaluation"]) if trajectory else 0
            ),
            "plateau_evaluations": plateau_evaluations,
            "plateau_signal": plateau_signal,
            "global_record_count": improvements,
            "actual_restart_occurred": self.actual_restarts > 0,
            "actual_restart_count": self.actual_restarts,
            "score_counts_truncated_by_witness_cap": score_counts_truncated,
            "mutation_ancestry": _ancestry_payload(
                global_records=global_records,
                final_best_ancestry=self.best_ancestry,
                current_accepted_ancestry=list(self.accepted_ancestry),
                maximum_evaluations=target,
            ),
            "termination_reason": termination_reason,
            "end_high_water": self.high_water,
        }
        if self.timing_ns is not None:
            self.timing_ns["telemetry_construction"] += (
                time.perf_counter_ns() - telemetry_started
            )
            result["timing"] = _timing_payload(
                self.timing_ns,
                search_loop_seconds=elapsed,
            )
        return result

    def _choose_mutation_operator(self) -> str:
        weights = self.parameters.get(MUTATION_WEIGHTS_PARAMETER)
        if not isinstance(weights, dict):
            return MUTATION_OPERATORS[0]
        draw = self.rng.random()
        cumulative = 0.0
        for name in MUTATION_OPERATORS:
            cumulative += float(weights[name])
            if draw <= cumulative:
                return name
        return MUTATION_OPERATORS[-1]

    @property
    def algorithm(self) -> str:
        return self.spec.algorithm

    def _accept(self, candidate_score: ScoreResult, key: str) -> bool:
        if self.algorithm == "simulated_annealing":
            initial = float(self.parameters.get("temperature", 8.0))
            cooling = float(self.parameters.get("cooling", 0.9995))
            threshold = int(self.parameters.get("restart_threshold", 50_000))
            temperature = max(
                0.001,
                initial * (cooling ** (self.algorithm_evaluated % threshold)),
            )
            delta = _score_scalar(candidate_score) - _score_scalar(self.score)
            return delta <= 0 or self.rng.random() < math.exp(
                -min(delta, 700) / temperature
            )
        tenure = int(self.parameters.get("tabu_tenure", 128))
        if self.tabu.maxlen != tenure:
            self.tabu = deque(self.tabu, maxlen=tenure)
        perturb = int(self.parameters.get("perturbation_interval", 64))
        accept = (
            key not in self.tabu
            and candidate_score.ordering_key <= self.score.ordering_key
        ) or self.algorithm_evaluated % perturb == 0
        if accept:
            self.tabu.append(key)
        return accept

    def _remember_hash(self, key: str) -> None:
        if len(self.recent_hashes) == self.recent_hashes.maxlen:
            removed = self.recent_hashes.popleft()
            if removed not in self.recent_hashes:
                self.recent_hash_set.discard(removed)
        self.recent_hashes.append(key)
        self.recent_hash_set.add(key)

    def _score(self, graph: BitGraph) -> ScoreResult:
        cap = int(self.parameters["witness_cap"])
        if self.timing_ns is None:
            return self.plugin.cheap_score(graph, cap)
        profiled = getattr(self.plugin, "cheap_score_profiled", None)
        if profiled is None:
            started = time.perf_counter_ns()
            score = self.plugin.cheap_score(graph, cap)
            self.timing_ns["score_calculation"] += (
                time.perf_counter_ns() - started
            )
            return score
        score, timings = profiled(graph, cap)
        self.timing_ns["graph_validation"] += int(
            timings["graph_validation_ns"]
        )
        self.timing_ns["witness_counting"] += int(
            timings["witness_counting_ns"]
        )
        self.timing_ns["score_calculation"] += int(
            timings["score_calculation_ns"]
        )
        return score

    def checkpoint(self, lane_version: int) -> dict[str, Any]:
        payload = {
            "lane_id": self.spec.lane_id,
            "lane_version": lane_version,
            "graph6": self.graph.to_graph6(),
            "score": _score_payload(self.score),
            "best_graph6": self.best_graph.to_graph6(),
            "best_score": _score_payload(self.best_score),
            "rng_state": repr(self.rng.getstate()),
            "algorithm_evaluated": self.algorithm_evaluated,
            "stagnation": self.stagnation,
            "tabu": list(self.tabu),
            "parameters": dict(self.parameters),
            "high_water": self.high_water,
            "accepted_ancestry": list(self.accepted_ancestry),
            "best_ancestry": list(self.best_ancestry),
            "current_candidate_id": (
                self.current_candidate_id
                if self.instrumentation_enabled
                else _candidate_id(self.spec.campaign_id, self.graph)
            ),
            "best_candidate_id": (
                self.best_candidate_id
                if self.instrumentation_enabled
                else _candidate_id(self.spec.campaign_id, self.best_graph)
            ),
        }
        digest = hashlib.sha256(
            canonical_json(payload, max_bytes=1024 * 1024)
        ).hexdigest()
        return {**payload, "checkpoint_id": f"checkpoint-{digest[:24]}", "sha256": digest}


def _lane_worker(
    spec: LaneSpec,
    commands: Any,
    events: Any,
    stop_event: Any,
    pause_event: Any,
    checkpoint: dict[str, Any] | None,
    fork_seed: int | None,
    memory_limit_bytes: int | None,
) -> None:
    try:
        set_address_space_limit(memory_limit_bytes)
        kernel = _LaneKernel(spec, checkpoint, fork_seed)
        lane_version = spec.lane_version
        resource_share = spec.resource_share
        current_checkpoint = kernel.checkpoint(lane_version)
        _emit(
            events,
            {
                "kind": "checkpoint",
                "lane_id": spec.lane_id,
                "checkpoint": current_checkpoint,
                "at": utc_now(),
            },
            important=True,
        )
        _emit(
            events,
            {
                "kind": "ready",
                "lane_id": spec.lane_id,
                "lane_version": lane_version,
                "parameters": kernel.parameters,
                "resource_share": resource_share,
                "at": utc_now(),
            },
            important=True,
        )
        while not stop_event.is_set():
            lane_version, resource_share, current_checkpoint = _apply_commands(
                spec,
                kernel,
                commands,
                events,
                stop_event,
                lane_version,
                resource_share,
                current_checkpoint,
            )
            if stop_event.is_set():
                break
            if pause_event.is_set() or resource_share <= 0:
                time.sleep(0.02)
                continue
            batch_started = time.perf_counter()
            metrics = kernel.run_batch(stop_event)
            current_checkpoint = kernel.checkpoint(lane_version)
            _emit(
                events,
                {
                    "kind": "checkpoint",
                    "lane_id": spec.lane_id,
                    "checkpoint": current_checkpoint,
                    "at": utc_now(),
                },
                important=True,
            )
            _emit(
                events,
                {
                    "kind": "telemetry",
                    "lane_id": spec.lane_id,
                    "lane_version": lane_version,
                    "metrics": metrics,
                    "at": utc_now(),
                },
            )
            if metrics["improvements"]:
                _emit(
                    events,
                    {
                        "kind": "improvement",
                        "lane_id": spec.lane_id,
                        "lane_version": lane_version,
                        "graph6": kernel.best_graph.to_graph6(),
                        "score": _score_payload(kernel.best_score),
                        "checkpoint_id": current_checkpoint["checkpoint_id"],
                        "at": utc_now(),
                    },
                    important=True,
                )
            elapsed = time.perf_counter() - batch_started
            if 0 < resource_share < 1:
                time.sleep(min(1.0, elapsed * (1.0 / resource_share - 1.0)))
        _emit(
            events,
            {
                "kind": "exit",
                "lane_id": spec.lane_id,
                "lane_version": lane_version,
                "checkpoint": current_checkpoint,
                "reason": "stopped",
                "at": utc_now(),
            },
            important=True,
        )
    except BaseException as error:
        _emit(
            events,
            {
                "kind": "exit",
                "lane_id": spec.lane_id,
                "reason": "failure",
                "error": f"{type(error).__name__}: {error}",
                "at": utc_now(),
            },
            important=True,
        )
        raise


def _apply_commands(
    spec: LaneSpec,
    kernel: _LaneKernel,
    commands: Any,
    events: Any,
    stop_event: Any,
    lane_version: int,
    resource_share: float,
    checkpoint: dict[str, Any],
) -> tuple[int, float, dict[str, Any]]:
    while True:
        try:
            command = commands.get_nowait()
        except Empty:
            break
        action_id = str(command["action_id"])
        expected = int(command["expected_lane_version"])
        if expected != lane_version:
            _emit(
                events,
                {
                    "kind": "action_outcome",
                    "lane_id": spec.lane_id,
                    "action_id": action_id,
                    "status": "rejected_stale_state",
                    "resulting_lane_version": lane_version,
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "at": utc_now(),
                },
                important=True,
            )
            continue
        kind = command["kind"]
        try:
            if kind == "patch":
                kernel.patch(dict(command["patch"]))
            elif kind == "restart":
                source_checkpoint = command.get("checkpoint")
                if isinstance(source_checkpoint, dict):
                    kernel.restart_from_checkpoint(
                        source_checkpoint, int(command["seed"])
                    )
                else:
                    kernel.restart(int(command["seed"]))
            elif kind == "reallocate":
                resource_share = float(command["resource_share"])
            elif kind == "stop":
                stop_event.set()
            else:
                raise ValueError(f"unsupported lane command: {kind}")
            lane_version += 1
            checkpoint = kernel.checkpoint(lane_version)
            _emit(
                events,
                {
                    "kind": "checkpoint",
                    "lane_id": spec.lane_id,
                    "checkpoint": checkpoint,
                    "at": utc_now(),
                },
                important=True,
            )
            _emit(
                events,
                {
                    "kind": "action_outcome",
                    "lane_id": spec.lane_id,
                    "action_id": action_id,
                    "status": "applied",
                    "command_kind": kind,
                    "resulting_lane_version": lane_version,
                    "parameters": dict(kernel.parameters),
                    "resource_share": resource_share,
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "at": utc_now(),
                },
                important=True,
            )
        except BaseException as error:
            _emit(
                events,
                {
                    "kind": "action_outcome",
                    "lane_id": spec.lane_id,
                    "action_id": action_id,
                    "status": "failed",
                    "resulting_lane_version": lane_version,
                    "failure": f"{type(error).__name__}: {error}",
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "at": utc_now(),
                },
                important=True,
            )
    return lane_version, resource_share, checkpoint


def _emit(events: Any, value: dict[str, Any], important: bool = False) -> None:
    try:
        events.put(value, timeout=0.5 if important else 0)
    except Full:
        if important:
            events.put(value, timeout=2)


class LaneManager:
    def __init__(
        self,
        campaign_dir: Path,
        *,
        max_active_lanes: int = 8,
        event_capacity: int = 512,
        command_capacity: int = 32,
        telemetry_windows: int = 120,
        checkpoints_per_lane: int = 8,
        pinned_checkpoints: int = 128,
        memory_limit_bytes: int | None = 512 * 1024 * 1024,
    ):
        if checkpoints_per_lane < 2:
            raise ValueError("checkpoints_per_lane must be at least 2")
        if memory_limit_bytes is not None and memory_limit_bytes <= 0:
            raise ValueError("memory_limit_bytes must be positive")
        if pinned_checkpoints < 1:
            raise ValueError("pinned_checkpoints must be positive")
        self.campaign_dir = campaign_dir.resolve()
        self.max_active_lanes = max_active_lanes
        self.command_capacity = command_capacity
        self.telemetry_windows = telemetry_windows
        self.checkpoints_per_lane = checkpoints_per_lane
        self.pinned_checkpoints = pinned_checkpoints
        self.memory_limit_bytes = memory_limit_bytes
        self.context = get_context("spawn")
        self.events = self.context.Queue(maxsize=event_capacity)
        self.lanes: dict[str, LaneRuntime] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self._checkpoint_order: dict[str, deque[str]] = {}
        self._pinned_checkpoint_ids: set[str] = set()
        self._pinned_checkpoint_order: deque[str] = deque()
        self._deferred_events: deque[dict[str, Any]] = deque()
        self.checkpoint_dir = self.campaign_dir / "lane-checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def start_lane(
        self,
        spec: LaneSpec,
        *,
        checkpoint: dict[str, Any] | None = None,
        fork_seed: int | None = None,
    ) -> LaneRuntime:
        spec.validate()
        if spec.lane_id in self.lanes:
            raise ValueError(f"duplicate lane id: {spec.lane_id}")
        if len(self.active_lanes()) >= self.max_active_lanes:
            raise RuntimeError("active lane limit reached")
        commands = self.context.Queue(maxsize=self.command_capacity)
        stop_event = self.context.Event()
        pause_event = self.context.Event()
        process = self.context.Process(
            target=_lane_worker,
            args=(
                spec,
                commands,
                self.events,
                stop_event,
                pause_event,
                checkpoint,
                fork_seed,
                self.memory_limit_bytes,
            ),
            name=f"sglab-lane-{spec.lane_id}",
        )
        runtime = LaneRuntime(
            spec=spec,
            process=process,
            commands=commands,
            stop_event=stop_event,
            pause_event=pause_event,
            lane_version=spec.lane_version,
            parameters=dict(spec.parameters),
            resource_share=spec.resource_share,
            telemetry=TelemetrySeries(self.telemetry_windows),
        )
        self.lanes[spec.lane_id] = runtime
        process.start()
        return runtime

    def active_lanes(self) -> list[LaneRuntime]:
        return [
            lane
            for lane in self.lanes.values()
            if lane.state in {"starting", "running", "paused", "stopping"}
        ]

    def send_patch(
        self,
        lane_id: str,
        *,
        action_id: str,
        expected_lane_version: int,
        patch: dict[str, Any],
    ) -> None:
        self._send(
            lane_id,
            {
                "kind": "patch",
                "action_id": action_id,
                "expected_lane_version": expected_lane_version,
                "patch": dict(patch),
            },
        )

    def restart_lane(
        self,
        lane_id: str,
        *,
        action_id: str,
        expected_lane_version: int,
        seed: int,
        checkpoint_id: str | None = None,
    ) -> None:
        checkpoint = None
        if checkpoint_id is not None:
            checkpoint = self.checkpoints.get(checkpoint_id)
            if checkpoint is None:
                raise KeyError(
                    f"restart checkpoint is not available: {checkpoint_id}"
                )
            self.pin_checkpoint(checkpoint_id)
        self._send(
            lane_id,
            {
                "kind": "restart",
                "action_id": action_id,
                "expected_lane_version": expected_lane_version,
                "seed": seed,
                "checkpoint": checkpoint,
            },
        )

    def reallocate_lane(
        self,
        lane_id: str,
        *,
        action_id: str,
        expected_lane_version: int,
        resource_share: float,
    ) -> None:
        if not 0 <= resource_share <= 1:
            raise ValueError("resource_share must be between 0 and 1")
        self._send(
            lane_id,
            {
                "kind": "reallocate",
                "action_id": action_id,
                "expected_lane_version": expected_lane_version,
                "resource_share": resource_share,
            },
        )

    def stop_lane(
        self,
        lane_id: str,
        *,
        action_id: str,
        expected_lane_version: int,
    ) -> None:
        runtime = self._runtime(lane_id)
        runtime.state = "stopping"
        self._send(
            lane_id,
            {
                "kind": "stop",
                "action_id": action_id,
                "expected_lane_version": expected_lane_version,
            },
        )

    def fork_lane(
        self,
        parent_lane_id: str,
        *,
        child_lane_id: str,
        action_id: str,
        expected_lane_version: int,
        checkpoint_id: str,
        patch: dict[str, Any],
        resource_share: float,
    ) -> LaneRuntime:
        parent = self._runtime(parent_lane_id)
        if parent.lane_version != expected_lane_version:
            raise RuntimeError("stale parent lane version")
        checkpoint = self.checkpoints.get(checkpoint_id)
        if checkpoint is None or checkpoint.get("lane_id") != parent_lane_id:
            raise RuntimeError("fork checkpoint is not available for parent")
        self.pin_checkpoint(checkpoint_id)
        parameters = {**parent.parameters, **patch}
        fork_seed = int.from_bytes(
            hashlib.sha256(f"{action_id}:{child_lane_id}".encode()).digest()[:8],
            "big",
        ) & (2**63 - 1)
        spec = LaneSpec(
            lane_id=child_lane_id,
            campaign_id=parent.spec.campaign_id,
            target=parent.spec.target,
            algorithm=parent.spec.algorithm,
            graph_family=parent.spec.graph_family,
            seed=fork_seed,
            parameters=parameters,
            resource_share=resource_share,
            lane_version=0,
            parent_lane_id=parent_lane_id,
            created_by_action_id=action_id,
            parent_checkpoint_id=checkpoint_id,
            seed_lineage=(*parent.spec.seed_lineage, parent.spec.seed, fork_seed),
        )
        return self.start_lane(spec, checkpoint=checkpoint, fork_seed=fork_seed)

    def _send(self, lane_id: str, command: dict[str, Any]) -> None:
        runtime = self._runtime(lane_id)
        action_id = str(command["action_id"])
        if action_id in runtime.pending_actions:
            raise RuntimeError("action is already pending for lane")
        if action_id in runtime.completed_action_ids:
            raise RuntimeError("action has already been applied or rejected")
        runtime.commands.put(command, timeout=0.5)
        runtime.pending_actions.add(action_id)

    def _runtime(self, lane_id: str) -> LaneRuntime:
        try:
            return self.lanes[lane_id]
        except KeyError as error:
            raise KeyError(f"unknown lane: {lane_id}") from error

    def poll(self, timeout: float = 0.1) -> dict[str, Any] | None:
        if self._deferred_events:
            return self._deferred_events.popleft()
        try:
            event = self.events.get(timeout=timeout)
        except Empty:
            return None
        self._apply_event(event)
        return event

    def _apply_event(self, event: dict[str, Any]) -> None:
        runtime = self._runtime(str(event["lane_id"]))
        kind = event["kind"]
        if kind == "ready":
            runtime.state = (
                "paused" if runtime.pause_event.is_set() else "running"
            )
            runtime.lane_version = int(event["lane_version"])
            runtime.parameters = dict(event["parameters"])
            runtime.resource_share = float(event["resource_share"])
        elif kind == "checkpoint":
            checkpoint = dict(event["checkpoint"])
            self._remember_checkpoint(runtime, checkpoint)
        elif kind == "telemetry":
            metrics = dict(event["metrics"])
            runtime.telemetry.append(metrics)
            runtime.high_water = max(
                runtime.high_water, int(metrics["end_high_water"])
            )
        elif kind == "improvement":
            runtime.improvements.append(dict(event))
            if len(runtime.improvements) > 64:
                del runtime.improvements[:-64]
        elif kind == "action_outcome":
            runtime.action_outcomes.append(dict(event))
            if len(runtime.action_outcomes) > 128:
                del runtime.action_outcomes[:-128]
            runtime.pending_actions.discard(str(event["action_id"]))
            runtime.completed_action_ids.add(str(event["action_id"]))
            checkpoint_id = event.get("checkpoint_id")
            if isinstance(checkpoint_id, str):
                self.pin_checkpoint(checkpoint_id)
            runtime.lane_version = int(event["resulting_lane_version"])
            if event["status"] == "applied":
                runtime.parameters = dict(
                    event.get("parameters", runtime.parameters)
                )
                runtime.resource_share = float(
                    event.get("resource_share", runtime.resource_share)
                )
        elif kind == "exit":
            runtime.state = (
                "failed" if event.get("reason") == "failure" else "stopped"
            )
            checkpoint = event.get("checkpoint")
            if isinstance(checkpoint, dict):
                self._remember_checkpoint(runtime, checkpoint)

    def _remember_checkpoint(
        self, runtime: LaneRuntime, checkpoint: dict[str, Any]
    ) -> None:
        checkpoint_id = str(checkpoint["checkpoint_id"])
        runtime.latest_checkpoint_id = checkpoint_id
        runtime.latest_checkpoint = checkpoint
        runtime.high_water = max(
            runtime.high_water, int(checkpoint.get("high_water", 0))
        )
        self.checkpoints[checkpoint_id] = checkpoint
        order = self._checkpoint_order.setdefault(
            runtime.spec.lane_id, deque()
        )
        if checkpoint_id not in order:
            order.append(checkpoint_id)
        path = self.checkpoint_dir / f"{checkpoint_id}.json"
        atomic_write_json(path, checkpoint)
        while len(order) > self.checkpoints_per_lane:
            expired = order.popleft()
            if expired in self._pinned_checkpoint_ids:
                continue
            if any(
                expired in lane_order
                for lane_order in self._checkpoint_order.values()
            ):
                continue
            self.checkpoints.pop(expired, None)
            expired_path = self.checkpoint_dir / f"{expired}.json"
            try:
                expired_path.unlink()
            except FileNotFoundError:
                pass

    def pin_checkpoint(self, checkpoint_id: str) -> None:
        if checkpoint_id not in self.checkpoints:
            raise KeyError(f"checkpoint is not available: {checkpoint_id}")
        if checkpoint_id in self._pinned_checkpoint_ids:
            return
        self._pinned_checkpoint_ids.add(checkpoint_id)
        self._pinned_checkpoint_order.append(checkpoint_id)
        while len(self._pinned_checkpoint_order) > self.pinned_checkpoints:
            expired = self._pinned_checkpoint_order.popleft()
            self._pinned_checkpoint_ids.discard(expired)
            self._drop_checkpoint_if_unretained(expired)

    def _drop_checkpoint_if_unretained(self, checkpoint_id: str) -> None:
        if checkpoint_id in self._pinned_checkpoint_ids:
            return
        if any(
            checkpoint_id in lane_order
            for lane_order in self._checkpoint_order.values()
        ):
            return
        self.checkpoints.pop(checkpoint_id, None)
        path = self.checkpoint_dir / f"{checkpoint_id}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def pause_all(self) -> None:
        for runtime in self.active_lanes():
            runtime.pause_event.set()
            runtime.state = "paused"

    def resume_all(self) -> None:
        for runtime in self.active_lanes():
            runtime.pause_event.clear()
            runtime.state = "running"

    def total_candidates(self) -> int:
        return sum(runtime.high_water for runtime in self.lanes.values())

    def shutdown(self, timeout: float = 3.0) -> None:
        for runtime in self.active_lanes():
            runtime.stop_event.set()
            runtime.pause_event.clear()
        deadline = time.monotonic() + timeout
        while (
            any(runtime.process.is_alive() for runtime in self.lanes.values())
            and time.monotonic() < deadline
        ):
            try:
                event = self.events.get(
                    timeout=min(0.05, max(0.0, deadline - time.monotonic()))
                )
            except Empty:
                pass
            else:
                self._apply_event(event)
                self._deferred_events.append(event)
            for runtime in self.lanes.values():
                runtime.process.join(timeout=0)
        for runtime in self.lanes.values():
            if runtime.process.is_alive():
                runtime.process.kill()
                runtime.process.join(timeout=1)
            if runtime.state not in {"failed", "stopped"}:
                runtime.state = "stopped"


def _score_payload(score: ScoreResult) -> dict[str, Any]:
    return {
        "valid": score.valid,
        "witness_counts": {
            str(length): count for length, count in score.witness_counts
        },
        "weighted_penalty": score.weighted_penalty,
        "complete": score.complete,
        "novelty": score.novelty,
        "simplicity": score.simplicity,
        "ordering_key": list(score.ordering_key),
    }


def _candidate_id(campaign_id: str, graph: BitGraph) -> str:
    graph_sha256 = hashlib.sha256(
        graph.to_graph6().encode("ascii")
    ).hexdigest()
    identity = hashlib.sha256(
        f"{campaign_id}:{graph_sha256}".encode("ascii")
    ).hexdigest()
    return f"candidate-{identity[:24]}"


def _mutation_record(
    *,
    campaign_id: str,
    parent: BitGraph,
    child: BitGraph,
    parent_candidate_id: str,
    score_before: ScoreResult,
    score_after: ScoreResult,
    evaluation: int,
    accepted: bool,
    global_record: bool,
    mutation_operator: str,
) -> dict[str, Any]:
    parent_edges = set(parent.edges())
    child_edges = set(child.edges())
    removed = sorted(parent_edges - child_edges)
    added = sorted(child_edges - parent_edges)
    mutated_vertices = sorted(
        {vertex for edge in (*removed, *added) for vertex in edge}
    )
    return {
        "candidate_id": _candidate_id(campaign_id, child),
        "parent_candidate_id": parent_candidate_id,
        "mutation_operator": mutation_operator,
        "mutated_vertices": mutated_vertices,
        "mutated_edges": {
            "removed": [list(edge) for edge in removed],
            "added": [list(edge) for edge in added],
        },
        "score_before": list(score_before.ordering_key),
        "score_after": list(score_after.ordering_key),
        "witness_counts_before": {
            str(length): count
            for length, count in score_before.witness_counts
        },
        "witness_counts_after": {
            str(length): count
            for length, count in score_after.witness_counts
        },
        "evaluation": evaluation,
        "accepted": accepted,
        "global_record": global_record,
    }


def _ancestry_payload(
    *,
    global_records: list[dict[str, Any]],
    final_best_ancestry: list[dict[str, Any]],
    current_accepted_ancestry: list[dict[str, Any]],
    maximum_evaluations: int,
) -> dict[str, Any]:
    records = (
        global_records
        + final_best_ancestry
        + current_accepted_ancestry
    )
    encoded_sizes = [
        len(json.dumps(record, sort_keys=True, separators=(",", ":")))
        for record in records
    ]
    maximum_record_bytes = max(encoded_sizes, default=0)
    maximum_live_records = maximum_evaluations + 2 * ANCESTRY_LIMIT
    return {
        "limit_per_retained_candidate": ANCESTRY_LIMIT,
        "global_record_improvements": global_records,
        "final_best_ancestry": final_best_ancestry[-ANCESTRY_LIMIT:],
        "global_record_count": len(global_records),
        "final_best_ancestry_length": min(
            len(final_best_ancestry), ANCESTRY_LIMIT
        ),
        "rejected_non_record_candidates_stored": 0,
        "memory_estimate": {
            "live_record_count": len(records),
            "maximum_live_records": maximum_live_records,
            "largest_observed_record_bytes": maximum_record_bytes,
            "conservative_maximum_bytes": (
                maximum_live_records * maximum_record_bytes * 2
            ),
            "note": (
                "The factor of two covers Python container and object "
                "overhead beyond compact JSON size."
            ),
        },
    }


def _timing_payload(
    timings_ns: dict[str, int],
    *,
    search_loop_seconds: float,
) -> dict[str, Any]:
    counters = {
        name: value / 1_000_000_000
        for name, value in timings_ns.items()
    }
    search_names = (
        "mutation_generation",
        "graph_validation",
        "witness_counting",
        "score_calculation",
        "duplicate_detection",
        "tabu_bookkeeping",
        "ancestry_construction",
    )
    accounted_search = sum(counters[name] for name in search_names)
    return {
        "enabled": True,
        "counters_seconds": counters,
        "search_loop_seconds": search_loop_seconds,
        "accounted_search_seconds": accounted_search,
        "unattributed_search_seconds": max(
            0.0, search_loop_seconds - accounted_search
        ),
        "measured_total_seconds": (
            search_loop_seconds
            + counters["telemetry_construction"]
            + counters["sqlite_persistence"]
            + counters["exact_final_verification"]
        ),
    }


def add_external_timing(
    metrics: dict[str, Any],
    name: str,
    elapsed_seconds: float,
) -> None:
    timing = metrics.get("timing")
    if not isinstance(timing, dict):
        return
    counters = timing["counters_seconds"]
    counters[name] = float(counters.get(name, 0.0)) + elapsed_seconds
    timing["measured_total_seconds"] = (
        float(timing["search_loop_seconds"])
        + float(counters["telemetry_construction"])
        + float(counters["sqlite_persistence"])
        + float(counters["exact_final_verification"])
    )


def _score_from_payload(payload: dict[str, Any]) -> ScoreResult:
    return ScoreResult(
        valid=bool(payload["valid"]),
        witness_counts=tuple(
            sorted(
                (int(length), int(count))
                for length, count in payload["witness_counts"].items()
            )
        ),
        weighted_penalty=int(payload["weighted_penalty"]),
        complete=bool(payload["complete"]),
        novelty=float(payload.get("novelty", 0)),
        simplicity=int(payload.get("simplicity", 0)),
    )


def _score_scalar(score: ScoreResult) -> float:
    invalid, total, weighted, novelty, simplicity = score.ordering_key
    return (
        invalid * 2_000_000
        + total
        + weighted / 2_000_000
        + novelty / 4_000_000_000_000
        + simplicity / 80_000_000_000_000_000
    )


class _NeverStop:
    def is_set(self) -> bool:
        return False


def replay_micro_batches(
    spec: LaneSpec,
    checkpoint: dict[str, Any],
    *,
    batches: int = 1,
) -> dict[str, Any]:
    """Deterministically replay bounded lane batches without persistence."""

    if not 1 <= batches <= 100:
        raise ValueError("replay batches must be between 1 and 100")
    spec.validate()
    if checkpoint.get("lane_id") != spec.lane_id:
        raise ValueError("replay checkpoint belongs to another lane")
    kernel = _LaneKernel(spec, checkpoint, fork_seed=None)
    metrics = []
    stop = _NeverStop()
    for _ in range(batches):
        metrics.append(kernel.run_batch(stop))
    return {
        "metrics": metrics,
        "checkpoint": kernel.checkpoint(spec.lane_version),
    }


def run_bounded_lane_batch(
    spec: LaneSpec,
    *,
    max_evaluations: int,
    max_wall_seconds: float,
    instrumentation_enabled: bool = True,
) -> dict[str, Any]:
    """Run exactly one bounded batch in the coordinator process."""

    if not 1 <= max_evaluations <= 1_000_000:
        raise ValueError("evaluation limit must be between 1 and 1,000,000")
    if not 0 < max_wall_seconds <= 120:
        raise ValueError("batch wall limit must be in (0, 120]")
    spec.validate()
    kernel = _LaneKernel(
        spec,
        checkpoint=None,
        fork_seed=None,
        instrumentation_enabled=instrumentation_enabled,
    )
    metrics = kernel.run_batch(
        _NeverStop(),
        max_evaluations=max_evaluations,
        max_wall_seconds=max_wall_seconds,
    )
    checkpoint = kernel.checkpoint(spec.lane_version)
    graph6 = kernel.best_graph.to_graph6()
    graph_sha256 = hashlib.sha256(graph6.encode("ascii")).hexdigest()
    verification_started = (
        time.perf_counter()
        if instrumentation_enabled
        else 0.0
    )
    verification = kernel.plugin.exact_verify(kernel.best_graph)
    if instrumentation_enabled:
        add_external_timing(
            metrics,
            "exact_final_verification",
            time.perf_counter() - verification_started,
        )
    return {
        "algorithm": spec.algorithm,
        "parameters": dict(spec.parameters),
        "seed": spec.seed,
        "graph_family": spec.graph_family,
        "graph_order": kernel.best_graph.n,
        "evaluation_count": int(metrics["evaluated"]),
        "throughput": float(metrics["candidates_per_second"]),
        "elapsed_seconds": float(metrics["elapsed_seconds"]),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * 1024,
        "initial_score": metrics["initial_score"],
        "best_score": _score_payload(kernel.best_score),
        "score_trajectory_summary": metrics["score_trajectory_summary"],
        "operator_statistics": metrics["operator_statistics"],
        "mutation_ancestry": metrics["mutation_ancestry"],
        "timing": metrics.get(
            "timing",
            {"enabled": False, "counters_seconds": {}},
        ),
        "best_candidate_identifier": kernel.best_candidate_id,
        "best_graph6": graph6,
        "best_graph_sha256": graph_sha256,
        "verifier_result": dataclasses.asdict(verification),
        "termination_reason": metrics["termination_reason"],
        "metrics": metrics,
        "checkpoint": checkpoint,
    }

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from queue import Empty, Full
from random import Random
from threading import Event, Thread
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
from ..score_worker import (
    DEFAULT_WORKER_MEMORY_BYTES,
    PersistentScoreWorker,
    PROTOCOL_VERSION,
    ScoreWorkerError,
)
from ..state import atomic_write_json, utc_now
from ..targets import TARGETS
from ..targets.base import MutationResult, ScoreResult, SeedGenerationTrace
from .catalog import (
    ALGORITHMS,
    ALGORITHM_PARAMETERS,
    GRAPH_FAMILIES,
    MUTATION_OPERATORS,
    MUTATION_WEIGHTS_PARAMETER,
    PARAMETER_DOMAINS,
    REVIEWED_PROPOSAL_RANKING_CATALOG_ID,
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
LIVE_FRONTIER_INTERVAL_SECONDS = 1.0
LIVE_FRONTIER_PAYLOAD_LIMIT_BYTES = 64 * 1024
LEGACY_GRAPH_KEY_SCHEME = "legacy_sha_graph6_v1"
FAST_GRAPH_KEY_SCHEME = "delta_local_v2"
_LEGACY_GRAPH_KEY_ALIAS = "sha256_graph6_v1"
_FAST_GRAPH_KEY_ALIAS = "zobrist256_v1"
PROVENANCE_SCHEMA_VERSION = 2
MUTATION_CHAIN_PROVENANCE = "mutation_chain"
INDEPENDENT_SAMPLE_PROVENANCE = "independent_sample"
GENERATOR_VERSION = "erdos_gyarfas.generate_seed_v1"
_UINT64_MASK = (1 << 64) - 1
SEED_GENERATION_SOURCES = (
    "initial_lane_seed",
    "automatic_algorithm_restart",
    "explicit_director_restart",
    "random_restart_candidate",
)
SEED_ATTEMPT_BUCKET_UPPER_BOUNDS = (
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1_024,
    2_048,
)
SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS = (
    10_000,
    50_000,
    100_000,
    500_000,
    1_000_000,
    5_000_000,
    10_000_000,
    50_000_000,
    100_000_000,
    500_000_000,
    1_000_000_000,
    5_000_000_000,
)
SEED_FAILURE_CATEGORIES = (
    "cubic_matching_construction_exhaustion",
    "mixed_degree_stub_construction_exhaustion",
    "invalid_generator_configuration",
    "other_implementation_failure",
)


def _bounded_histogram_index(
    value: int, upper_bounds: tuple[int, ...]
) -> int:
    for index, upper_bound in enumerate(upper_bounds):
        if value <= upper_bound:
            return index
    return len(upper_bounds)


def _histogram_percentile(
    counts: list[int],
    upper_bounds: tuple[int, ...],
    percentile: float,
) -> int:
    total = sum(counts)
    if total == 0:
        return 0
    target = max(1, math.ceil(total * percentile))
    observed = 0
    for index, count in enumerate(counts):
        observed += count
        if observed >= target:
            if index < len(upper_bounds):
                return upper_bounds[index]
            return upper_bounds[-1] + 1
    return upper_bounds[-1] + 1


@dataclass(slots=True)
class SeedMetricCounters:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    attempts_total: int = 0
    attempts_max: int = 0
    retry_budget_total: int = 0
    retry_budget_max: int = 0
    retry_budget_exhaustions: int = 0
    elapsed_ns_total: int = 0
    elapsed_ns_max: int = 0
    search_loop_elapsed_ns: int = 0
    attempt_histogram: list[int] = field(
        default_factory=lambda: [
            0
            for _ in range(
                len(SEED_ATTEMPT_BUCKET_UPPER_BOUNDS) + 1
            )
        ]
    )
    elapsed_ns_histogram: list[int] = field(
        default_factory=lambda: [
            0
            for _ in range(
                len(SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS) + 1
            )
        ]
    )
    failure_categories: dict[str, int] = field(
        default_factory=lambda: {
            category: 0 for category in SEED_FAILURE_CATEGORIES
        }
    )

    def record(
        self,
        *,
        attempts: int,
        retry_budget: int,
        elapsed_ns: int,
        failure_category: str | None,
        in_search_loop: bool,
    ) -> None:
        self.calls += 1
        self.attempts_total += attempts
        self.attempts_max = max(self.attempts_max, attempts)
        self.retry_budget_total += retry_budget
        self.retry_budget_max = max(self.retry_budget_max, retry_budget)
        self.elapsed_ns_total += elapsed_ns
        self.elapsed_ns_max = max(self.elapsed_ns_max, elapsed_ns)
        if in_search_loop:
            self.search_loop_elapsed_ns += elapsed_ns
        self.attempt_histogram[
            _bounded_histogram_index(
                attempts, SEED_ATTEMPT_BUCKET_UPPER_BOUNDS
            )
        ] += 1
        self.elapsed_ns_histogram[
            _bounded_histogram_index(
                elapsed_ns, SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS
            )
        ] += 1
        if failure_category is None:
            self.successes += 1
            return
        self.failures += 1
        category = (
            failure_category
            if failure_category in self.failure_categories
            else "other_implementation_failure"
        )
        self.failure_categories[category] += 1
        if retry_budget > 0 and attempts >= retry_budget:
            self.retry_budget_exhaustions += 1

    def payload(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "attempts_total": self.attempts_total,
            "attempts_mean": (
                self.attempts_total / self.calls if self.calls else 0.0
            ),
            "attempts_max": self.attempts_max,
            "attempt_percentiles": {
                "p50": _histogram_percentile(
                    self.attempt_histogram,
                    SEED_ATTEMPT_BUCKET_UPPER_BOUNDS,
                    0.50,
                ),
                "p95": _histogram_percentile(
                    self.attempt_histogram,
                    SEED_ATTEMPT_BUCKET_UPPER_BOUNDS,
                    0.95,
                ),
                "p99": _histogram_percentile(
                    self.attempt_histogram,
                    SEED_ATTEMPT_BUCKET_UPPER_BOUNDS,
                    0.99,
                ),
            },
            "retry_budget_total": self.retry_budget_total,
            "retry_budget_mean": (
                self.retry_budget_total / self.calls
                if self.calls
                else 0.0
            ),
            "retry_budget_max": self.retry_budget_max,
            "maximum_retry_budget_fraction": (
                self.attempts_max / self.retry_budget_max
                if self.retry_budget_max
                else 0.0
            ),
            "retry_budget_exhaustions": self.retry_budget_exhaustions,
            "elapsed_ns_total": self.elapsed_ns_total,
            "elapsed_ns_mean": (
                self.elapsed_ns_total / self.calls if self.calls else 0.0
            ),
            "elapsed_ns_max": self.elapsed_ns_max,
            "elapsed_ns_percentiles": {
                "p50": _histogram_percentile(
                    self.elapsed_ns_histogram,
                    SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS,
                    0.50,
                ),
                "p95": _histogram_percentile(
                    self.elapsed_ns_histogram,
                    SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS,
                    0.95,
                ),
                "p99": _histogram_percentile(
                    self.elapsed_ns_histogram,
                    SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS,
                    0.99,
                ),
            },
            "search_loop_elapsed_ns": self.search_loop_elapsed_ns,
            "attempt_histogram": list(self.attempt_histogram),
            "elapsed_ns_histogram": list(self.elapsed_ns_histogram),
            "failure_categories": dict(self.failure_categories),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SeedMetricCounters:
        counters = cls()
        for name in (
            "calls",
            "successes",
            "failures",
            "attempts_total",
            "attempts_max",
            "retry_budget_total",
            "retry_budget_max",
            "retry_budget_exhaustions",
            "elapsed_ns_total",
            "elapsed_ns_max",
            "search_loop_elapsed_ns",
        ):
            setattr(counters, name, int(payload.get(name, 0)))
        attempts = payload.get("attempt_histogram", [])
        elapsed = payload.get("elapsed_ns_histogram", [])
        if isinstance(attempts, list) and len(attempts) == len(
            counters.attempt_histogram
        ):
            counters.attempt_histogram = [int(value) for value in attempts]
        if isinstance(elapsed, list) and len(elapsed) == len(
            counters.elapsed_ns_histogram
        ):
            counters.elapsed_ns_histogram = [
                int(value) for value in elapsed
            ]
        categories = payload.get("failure_categories", {})
        if isinstance(categories, dict):
            counters.failure_categories = {
                category: int(categories.get(category, 0))
                for category in SEED_FAILURE_CATEGORIES
            }
        return counters


@dataclass(slots=True)
class SeedGenerationAccumulator:
    total: SeedMetricCounters = field(default_factory=SeedMetricCounters)
    sources: dict[str, SeedMetricCounters] = field(
        default_factory=lambda: {
            source: SeedMetricCounters()
            for source in SEED_GENERATION_SOURCES
        }
    )
    measured_search_loop_ns: int = 0

    def record(
        self,
        *,
        source: str,
        trace: SeedGenerationTrace,
        elapsed_ns: int,
        in_search_loop: bool,
    ) -> None:
        if source not in self.sources:
            raise ValueError(f"unsupported seed generation source: {source}")
        values = {
            "attempts": trace.attempts,
            "retry_budget": trace.retry_budget,
            "elapsed_ns": elapsed_ns,
            "failure_category": trace.failure_category,
            "in_search_loop": in_search_loop,
        }
        self.total.record(**values)
        self.sources[source].record(**values)

    def payload(
        self,
        *,
        graph_family: str,
        graph_order: int,
        generator_mode: str,
    ) -> dict[str, Any]:
        total = self.total.payload()
        return {
            "schema_version": 1,
            "graph_family": graph_family,
            "graph_order": graph_order,
            "generator_mode": generator_mode,
            "attempt_bucket_upper_bounds": list(
                SEED_ATTEMPT_BUCKET_UPPER_BOUNDS
            ),
            "elapsed_ns_bucket_upper_bounds": list(
                SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS
            ),
            "measured_search_loop_ns": self.measured_search_loop_ns,
            "generator_time_share": (
                self.total.search_loop_elapsed_ns
                / self.measured_search_loop_ns
                if self.measured_search_loop_ns
                else 0.0
            ),
            "total": total,
            "sources": {
                source: self.sources[source].payload()
                for source in SEED_GENERATION_SOURCES
            },
        }

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any]
    ) -> SeedGenerationAccumulator:
        result = cls()
        total = payload.get("total")
        if isinstance(total, dict):
            result.total = SeedMetricCounters.from_payload(total)
        sources = payload.get("sources")
        if isinstance(sources, dict):
            result.sources = {
                source: SeedMetricCounters.from_payload(
                    sources.get(source, {})
                    if isinstance(sources.get(source), dict)
                    else {}
                )
                for source in SEED_GENERATION_SOURCES
            }
        result.measured_search_loop_ns = int(
            payload.get("measured_search_loop_ns", 0)
        )
        return result


def _splitmix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & _UINT64_MASK
    value = (
        (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9
    ) & _UINT64_MASK
    value = (
        (value ^ (value >> 27)) * 0x94D049BB133111EB
    ) & _UINT64_MASK
    return value ^ (value >> 31)


def _zobrist_token(value: int) -> int:
    result = 0
    for domain in range(4):
        word = _splitmix64(
            value ^ (0xD6E8FEB86659FD93 * (domain + 1))
        )
        result |= word << (domain * 64)
    return result


def _zobrist_graph_key(graph: BitGraph) -> str:
    value = _zobrist_token(0x8000000000000000 | graph.n)
    for u, v in graph.edges():
        value ^= _zobrist_token((u << 32) | v)
    return f"{value:064x}"


def _zobrist_update_key(
    key: str,
    *,
    removed_edges: tuple[tuple[int, int], ...],
    added_edges: tuple[tuple[int, int], ...],
) -> str:
    value = int(key, 16)
    for edge in (*removed_edges, *added_edges):
        u, v = sorted(edge)
        value ^= _zobrist_token((u << 32) | v)
    return f"{value:064x}"


def _normalize_duplicate_key_scheme(value: object) -> str:
    scheme = str(value)
    if scheme in {LEGACY_GRAPH_KEY_SCHEME, _LEGACY_GRAPH_KEY_ALIAS}:
        return LEGACY_GRAPH_KEY_SCHEME
    if scheme in {FAST_GRAPH_KEY_SCHEME, _FAST_GRAPH_KEY_ALIAS}:
        return FAST_GRAPH_KEY_SCHEME
    raise ValueError(f"unsupported duplicate key scheme: {scheme}")


def _duplicate_key_compatibility_alias(scheme: str) -> str:
    return (
        _FAST_GRAPH_KEY_ALIAS
        if scheme == FAST_GRAPH_KEY_SCHEME
        else _LEGACY_GRAPH_KEY_ALIAS
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
            if name == "proposal_ranking":
                if value != REVIEWED_PROPOSAL_RANKING_CATALOG_ID:
                    raise ValueError(
                        "proposal_ranking must use the reviewed catalog ID"
                    )
                continue
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
        if "proposal_ranking" in self.parameters and self.algorithm == "random_restart":
            raise ValueError("reviewed proposal ranking requires a mutation lane")


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
    latest_live_frontier: dict[str, Any] | None = None
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
        score_profiling_enabled: bool = True,
        score_worker_memory_bytes: int = DEFAULT_WORKER_MEMORY_BYTES,
        optimized_legacy_key: bool = True,
        independent_sample_provenance: bool = True,
        mutation_witness_cache: bool = True,
        proposal_ranking_profile_enabled: bool = False,
    ):
        self.spec = spec
        self.plugin = TARGETS[spec.target]
        self.parameters = dict(spec.parameters)
        self.mode = GRAPH_FAMILIES[spec.graph_family]
        self.proposal_ranking_catalog_id = self.parameters.get("proposal_ranking")
        self.proposal_ranking = None
        self._last_policy_ranking_started_ns: int | None = None
        if self.proposal_ranking_catalog_id is not None:
            from .proposal_ranking import (
                HegPolicyBridge,
                require_checkpoint_identity,
            )

            if checkpoint is not None:
                require_checkpoint_identity(checkpoint, enabled=True)
            self.proposal_ranking = HegPolicyBridge(
                catalog_id=str(self.proposal_ranking_catalog_id),
                profile_enabled=proposal_ranking_profile_enabled,
            )
        elif checkpoint is not None:
            from .proposal_ranking import require_checkpoint_identity

            require_checkpoint_identity(checkpoint, enabled=False)
        self.instrumentation_enabled = instrumentation_enabled
        self.optimized_legacy_key = optimized_legacy_key
        self.independent_sample_provenance = (
            independent_sample_provenance
        )
        self.mutation_witness_cache_enabled = mutation_witness_cache
        self._forbidden_witness_edge_choices = getattr(
            self.plugin, "forbidden_witness_edge_choices", None
        )
        mutation_context_factory = getattr(
            self.plugin, "new_mutation_context", None
        )
        self.mutation_context = (
            mutation_context_factory(cache_enabled=mutation_witness_cache)
            if mutation_context_factory is not None
            else None
        )
        self.graph6_workspace = bytearray()
        self.score_profiling_enabled = (
            instrumentation_enabled and score_profiling_enabled
        )
        mutation_profile_factory = getattr(
            self.plugin, "new_mutation_profile", None
        )
        self.mutation_profile = (
            mutation_profile_factory()
            if self.score_profiling_enabled
            and mutation_profile_factory is not None
            else None
        )
        self.timing_ns = (
            {name: 0 for name in TIMING_COUNTER_NAMES}
            if instrumentation_enabled
            else None
        )
        profile_factory = getattr(self.plugin, "new_score_profile", None)
        self.score_profile = (
            profile_factory()
            if self.score_profiling_enabled
            and profile_factory is not None
            else None
        )
        self._count_result_score = getattr(
            self.plugin, "score_from_cycle_counts", None
        )
        self._record_count_profile = getattr(
            self.plugin, "record_cycle_count_profile", None
        )
        if self._count_result_score is None:
            raise RuntimeError(
                "target does not support mandatory C++ heuristic scoring"
            )
        self.score_early_exit_enabled = True
        self.fast_duplicate_key_enabled = True
        self.score_backend_batch = {
            "cpp_requests": 0,
            "worker_restarts": 0,
        }
        self.score_worker = PersistentScoreWorker(
            memory_limit_bytes=score_worker_memory_bytes
        )
        try:
            self.score_worker.start()
        except ScoreWorkerError:
            self.score_worker.close()
            raise
        self.accepted_ancestry: deque[dict[str, Any]] = deque(
            maxlen=ANCESTRY_LIMIT
        )
        self.best_ancestry: list[dict[str, Any]] = []
        self.current_candidate_id: str | None = None
        self.best_candidate_id = ""
        self.current_provenance: dict[str, Any] | None = None
        self.best_provenance: dict[str, Any] | None = None
        self.current_evaluation_index = 0
        self.best_evaluation_index = 0
        self.batch_source_checkpoint_id: str | None = None
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
        self.seed_generation_batch = SeedGenerationAccumulator()
        restored_seed_generation = (
            checkpoint.get("seed_generation")
            if checkpoint is not None
            and fork_seed is None
            and instrumentation_enabled
            else None
        )
        self.seed_generation_cumulative = (
            SeedGenerationAccumulator.from_payload(
                restored_seed_generation
            )
            if isinstance(restored_seed_generation, dict)
            else SeedGenerationAccumulator()
        )
        checkpoint_key_scheme = LEGACY_GRAPH_KEY_SCHEME
        if checkpoint is not None:
            raw_scheme = checkpoint.get(
                "duplicate_key_scheme",
                checkpoint.get(
                    "tabu_key_scheme", _LEGACY_GRAPH_KEY_ALIAS
                ),
            )
            checkpoint_key_scheme = _normalize_duplicate_key_scheme(
                raw_scheme
            )
        self.tabu_key_scheme = (
            checkpoint_key_scheme
            if checkpoint is not None
            else (
                FAST_GRAPH_KEY_SCHEME
                if self.fast_duplicate_key_enabled
                else LEGACY_GRAPH_KEY_SCHEME
            )
        )
        if checkpoint is None:
            self._new_seed(spec.seed, source="initial_lane_seed")
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
                else [self._full_search_key(self.graph)]
            )
            self.tabu = deque(
                (str(value) for value in restored_tabu),
                maxlen=int(self.parameters.get("tabu_tenure", 128)),
            )
            if not self.tabu:
                self.tabu.append(self._full_search_key(self.graph))
            self.current_graph_key = self._full_search_key(self.graph)
            if (
                self.algorithm == "random_restart"
                and self.independent_sample_provenance
            ):
                self.accepted_ancestry.clear()
                self.best_ancestry = []
            else:
                self.accepted_ancestry = deque(
                    (
                        dict(value)
                        for value in checkpoint.get(
                            "accepted_ancestry", []
                        )
                    ),
                    maxlen=ANCESTRY_LIMIT,
                )
                self.best_ancestry = [
                    dict(value)
                    for value in checkpoint.get("best_ancestry", [])
                ][-ANCESTRY_LIMIT:]
            restored_current_id = checkpoint.get("current_candidate_id")
            self.current_candidate_id = (
                str(restored_current_id)
                if restored_current_id is not None
                else (
                    None
                    if self.algorithm == "random_restart"
                    and self.independent_sample_provenance
                    else self._candidate_id(self.graph)
                )
            )
            self.best_candidate_id = str(
                checkpoint.get(
                    "best_candidate_id",
                    self._candidate_id(self.best_graph),
                )
            )
            current_provenance = checkpoint.get("current_provenance")
            best_provenance = checkpoint.get("best_provenance")
            self.current_provenance = (
                dict(current_provenance)
                if isinstance(current_provenance, dict)
                else None
            )
            self.best_provenance = (
                dict(best_provenance)
                if isinstance(best_provenance, dict)
                else None
            )
            self.current_evaluation_index = int(
                checkpoint.get(
                    "current_evaluation_index", self.high_water
                )
            )
            self.best_evaluation_index = int(
                checkpoint.get(
                    "best_evaluation_index", self.high_water
                )
            )
        self.live_frontier_state = (
            self.graph,
            self.score,
            self.current_candidate_id,
            self.high_water,
        )

    def _generate_seed(
        self, *, source: str, in_search_loop: bool
    ) -> BitGraph:
        config = {
            "order": int(self.parameters["order"]),
            "mode": self.mode,
        }
        if not self.instrumentation_enabled:
            return self.plugin.generate_seed(self.rng, config)
        trace = SeedGenerationTrace(generator_mode=self.mode)
        started = time.perf_counter_ns()
        try:
            graph = self.plugin.generate_seed(
                self.rng, config, trace=trace
            )
        except BaseException as error:
            if trace.failure_category is None:
                trace.failure_category = "other_implementation_failure"
            elapsed_ns = time.perf_counter_ns() - started
            self.seed_generation_batch.record(
                source=source,
                trace=trace,
                elapsed_ns=elapsed_ns,
                in_search_loop=in_search_loop,
            )
            self.seed_generation_cumulative.record(
                source=source,
                trace=trace,
                elapsed_ns=elapsed_ns,
                in_search_loop=in_search_loop,
            )
            observation = {
                "source": source,
                "graph_family": self.spec.graph_family,
                "graph_order": int(self.parameters["order"]),
                "generator_mode": trace.generator_mode,
                "attempts": trace.attempts,
                "retry_budget": trace.retry_budget,
                "elapsed_ns": elapsed_ns,
                "failure_category": trace.failure_category,
            }
            try:
                setattr(error, "seed_generation_observation", observation)
            except Exception:
                pass
            raise
        elapsed_ns = time.perf_counter_ns() - started
        self.seed_generation_batch.record(
            source=source,
            trace=trace,
            elapsed_ns=elapsed_ns,
            in_search_loop=in_search_loop,
        )
        self.seed_generation_cumulative.record(
            source=source,
            trace=trace,
            elapsed_ns=elapsed_ns,
            in_search_loop=in_search_loop,
        )
        return graph

    def _effective_seed_generator_mode(self) -> str:
        if (
            self.mode == "unrestricted_min_degree_3"
            and int(self.parameters["order"]) % 2
        ):
            return "minimal_structure_mixed_degree"
        return self.mode

    def _new_seed(self, seed: int, *, source: str) -> None:
        self.rng = Random(seed)
        self.tabu_key_scheme = (
            FAST_GRAPH_KEY_SCHEME
            if self.fast_duplicate_key_enabled
            else LEGACY_GRAPH_KEY_SCHEME
        )
        self.graph = self._generate_seed(
            source=source,
            in_search_loop=source == "automatic_algorithm_restart",
        )
        self._invalidate_mutation_witness_cache()
        if self.proposal_ranking is not None:
            self.proposal_ranking.invalidate_graph_cache()
        self.score = self._score(self.graph)
        self.best_graph = self.graph
        self.best_score = self.score
        self.current_candidate_id = self._candidate_id(self.graph)
        self.best_candidate_id = self.current_candidate_id
        self.current_provenance = None
        self.best_provenance = None
        self.current_evaluation_index = 0
        self.best_evaluation_index = 0
        self.batch_source_checkpoint_id = None
        self.accepted_ancestry.clear()
        self.best_ancestry = []
        self.algorithm_evaluated = 0
        self.stagnation = 0
        self.tabu.clear()
        self.current_graph_key = self._full_search_key(self.graph)
        self.tabu.append(self.current_graph_key)
        self.recent_hashes.clear()
        self.recent_hash_set.clear()
        self.live_frontier_state = (
            self.graph,
            self.score,
            self.current_candidate_id,
            self.high_water,
        )

    def restart(self, seed: int) -> None:
        self._new_seed(seed, source="explicit_director_restart")

    def restart_from_checkpoint(
        self, checkpoint: dict[str, Any], seed: int
    ) -> None:
        self.graph = BitGraph.from_graph6(str(checkpoint["graph6"]))
        self._invalidate_mutation_witness_cache()
        if self.proposal_ranking is not None:
            self.proposal_ranking.invalidate_graph_cache()
        self.tabu_key_scheme = (
            FAST_GRAPH_KEY_SCHEME
            if self.fast_duplicate_key_enabled
            else LEGACY_GRAPH_KEY_SCHEME
        )
        self.current_graph_key = self._full_search_key(self.graph)
        self.score = _score_from_payload(checkpoint["score"])
        self.best_graph = BitGraph.from_graph6(
            str(checkpoint.get("best_graph6", checkpoint["graph6"]))
        )
        self.best_score = _score_from_payload(
            checkpoint.get("best_score", checkpoint["score"])
        )
        if (
            self.algorithm == "random_restart"
            and self.independent_sample_provenance
        ):
            self.accepted_ancestry.clear()
            self.best_ancestry = []
        else:
            self.accepted_ancestry = deque(
                (
                    dict(value)
                    for value in checkpoint.get(
                        "accepted_ancestry", []
                    )
                ),
                maxlen=ANCESTRY_LIMIT,
            )
            self.best_ancestry = [
                dict(value)
                for value in checkpoint.get("best_ancestry", [])
            ][-ANCESTRY_LIMIT:]
        restored_current_id = checkpoint.get("current_candidate_id")
        self.current_candidate_id = (
            str(restored_current_id)
            if restored_current_id is not None
            else self._candidate_id(self.graph)
        )
        self.best_candidate_id = str(
            checkpoint.get(
                "best_candidate_id",
                self._candidate_id(self.best_graph),
            )
        )
        self.current_provenance = None
        self.best_provenance = None
        self.current_evaluation_index = 0
        self.best_evaluation_index = 0
        self.batch_source_checkpoint_id = None
        self.rng = Random(seed)
        self.algorithm_evaluated = 0
        self.stagnation = 0
        self.tabu.clear()
        self.tabu.append(self.current_graph_key)
        self.recent_hashes.clear()
        self.recent_hash_set.clear()
        self.live_frontier_state = (
            self.graph,
            self.score,
            self.current_candidate_id,
            self.high_water,
        )

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
        source_checkpoint_id: str | None = None,
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
        self.batch_source_checkpoint_id = source_checkpoint_id
        if self.timing_ns is not None:
            for name in self.timing_ns:
                self.timing_ns[name] = 0
        if self.score_profile is not None:
            self.score_profile.reset()
        if self.mutation_profile is not None:
            self.mutation_profile.reset()
        for name in self.score_backend_batch:
            self.score_backend_batch[name] = 0
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
        early_rejected = 0
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
                self._new_seed(
                    self.rng.randrange(2**63),
                    source="automatic_algorithm_restart",
                )
                self.actual_restarts += 1
            mutation_started = (
                time.perf_counter_ns()
                if self.timing_ns is not None
                else 0
            )
            mutation_operator = (
                "random_restart_seed"
                if self.algorithm == "random_restart"
                else (
                    "reviewed_proposal_ranking"
                    if self.proposal_ranking is not None
                    else self._choose_mutation_operator()
                )
            )
            operator_counts = ancestry_operator_statistics.setdefault(
                mutation_operator,
                {"uses": 0, "accepted": 0, "global_records": 0},
            )
            operator_counts["uses"] += 1
            mutation_delta = None
            if self.proposal_ranking is not None:
                self._last_policy_ranking_started_ns = time.perf_counter_ns()
                mutation_delta = self._policy_mutation(
                    self.graph,
                    step=self.high_water + evaluated,
                )
                candidate = mutation_delta.graph
            elif self.algorithm == "random_restart":
                candidate = self._generate_seed(
                    source="random_restart_candidate",
                    in_search_loop=True,
                )
            else:
                mutation_config = {
                    "mode": self.mode,
                    "mutation_operator": mutation_operator,
                }
                if (
                    mutation_operator
                    == "forbidden_cycle_break_switch"
                    and self._forbidden_witness_edge_choices is not None
                ):
                    mutation_config[
                        "forbidden_witness_edge_choices"
                    ] = self._mutation_witness_choices_for(self.graph)
                    if self.mutation_profile is not None:
                        mutation_config["mutation_profile"] = (
                            self.mutation_profile
                        )
                mutate_with_delta = getattr(
                    self.plugin, "mutate_with_delta", None
                )
                if mutate_with_delta is None:
                    candidate = self.plugin.mutate(
                        self.graph,
                        self.rng,
                        mutation_config,
                    )
                else:
                    mutation_delta = mutate_with_delta(
                        self.graph,
                        self.rng,
                        mutation_config,
                    )
                    candidate = mutation_delta.graph
            if self.timing_ns is not None:
                mutation_elapsed = (
                    time.perf_counter_ns() - mutation_started
                )
                self.timing_ns["mutation_generation"] += mutation_elapsed
                if self.mutation_profile is not None:
                    self.mutation_profile.record_operator(
                        mutation_operator, mutation_elapsed
                    )
            evaluated += 1
            self.algorithm_evaluated += 1
            if candidate == self.graph:
                self.live_frontier_state = (
                    self.graph,
                    self.score,
                    self.current_candidate_id,
                    self.high_water + evaluated,
                )
                continue
            legal += 1
            duplicate_started = (
                time.perf_counter_ns()
                if self.timing_ns is not None
                else 0
            )
            key = self._candidate_search_key(candidate, mutation_delta)
            if key in self.recent_hash_set:
                duplicates += 1
            self._remember_hash(key)
            if self.timing_ns is not None:
                self.timing_ns["duplicate_detection"] += (
                    time.perf_counter_ns() - duplicate_started
                )
            score_cutoff = self._score_cutoff(key)
            selected_score_started = (
                time.perf_counter_ns()
                if self.proposal_ranking is not None
                and self.proposal_ranking.profile is not None
                else None
            )
            candidate_score = self._score(candidate, score_cutoff)
            if self.proposal_ranking is not None and selected_score_started is not None:
                self.proposal_ranking.record_external_phase(
                    "authoritative_selected_plan_scoring",
                    time.perf_counter_ns() - selected_score_started,
                )
                if self._last_policy_ranking_started_ns is not None:
                    self.proposal_ranking.record_ranked_evaluation(
                        time.perf_counter_ns() - self._last_policy_ranking_started_ns
                    )
                    self._last_policy_ranking_started_ns = None
            if candidate_score is None:
                early_rejected += 1
                self.stagnation += 1
                self.live_frontier_state = (
                    self.graph,
                    self.score,
                    self.current_candidate_id,
                    self.high_water + evaluated,
                )
                continue
            score_counts_truncated = (
                score_counts_truncated or not candidate_score.complete
            )
            global_record = (
                candidate_score.ordering_key
                < self.best_score.ordering_key
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
            mutation_record: dict[str, Any] | None = None
            build_mutation_chain = not (
                self.algorithm == "random_restart"
                and self.independent_sample_provenance
            )
            if (
                self.instrumentation_enabled
                and build_mutation_chain
                and (accept or global_record)
            ):
                ancestry_started = time.perf_counter_ns()
                mutation_record = _mutation_record(
                    campaign_id=self.spec.campaign_id,
                    parent=self.graph,
                    child=candidate,
                    parent_candidate_id=str(self.current_candidate_id),
                    score_before=self.score,
                    score_after=candidate_score,
                    evaluation=evaluated,
                    accepted=accept,
                    global_record=global_record,
                    mutation_operator=mutation_operator,
                    child_graph_sha256=(
                        key
                        if self.tabu_key_scheme
                        == LEGACY_GRAPH_KEY_SCHEME
                        else None
                    ),
                )
                if self.timing_ns is not None:
                    self.timing_ns["ancestry_construction"] += (
                        time.perf_counter_ns() - ancestry_started
                    )
            operator_counts["accepted"] += int(accept)
            operator_counts["global_records"] += int(global_record)
            if accept:
                self.graph = candidate
                self._invalidate_mutation_witness_cache()
                if self.proposal_ranking is not None:
                    self.proposal_ranking.invalidate_graph_cache()
                self.score = candidate_score
                self.current_graph_key = key
                self.current_evaluation_index = (
                    self.high_water + evaluated
                )
                if mutation_record is not None:
                    self.accepted_ancestry.append(mutation_record)
                    self.current_candidate_id = str(
                        mutation_record["candidate_id"]
                    )
                elif (
                    self.algorithm == "random_restart"
                    and self.independent_sample_provenance
                ):
                    self.current_candidate_id = None
                    self.current_provenance = None
                accepted += 1
                self.total_accepted += 1
            if global_record:
                self.best_graph = candidate
                self.best_score = candidate_score
                self.best_evaluation_index = self.high_water + evaluated
                if (
                    self.algorithm == "random_restart"
                    and self.independent_sample_provenance
                ):
                    provenance_started = (
                        time.perf_counter_ns()
                        if self.timing_ns is not None
                        else 0
                    )
                    graph_sha256 = self._graph_sha256(candidate)
                    self.best_candidate_id = (
                        _candidate_id_from_graph_sha256(
                            self.spec.campaign_id, graph_sha256
                        )
                    )
                    self.best_provenance = (
                        self._independent_sample_provenance(
                            graph_sha256=graph_sha256,
                            score=candidate_score,
                            evaluation_index=self.high_water + evaluated,
                            record_status="global_record",
                        )
                    )
                    if accept:
                        self.current_candidate_id = self.best_candidate_id
                        self.current_provenance = dict(
                            self.best_provenance
                        )
                    if self.timing_ns is not None:
                        self.timing_ns[
                            "ancestry_construction"
                        ] += (
                            time.perf_counter_ns()
                            - provenance_started
                        )
                elif mutation_record is not None:
                    self.best_candidate_id = str(
                        mutation_record["candidate_id"]
                    )
                else:
                    self.best_candidate_id = self._candidate_id(candidate)
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
            self.live_frontier_state = (
                self.graph,
                self.score,
                (
                    self.current_candidate_id
                    if self.instrumentation_enabled
                    else self._candidate_id(self.graph)
                ),
                self.high_water + evaluated,
            )
        self.high_water += evaluated
        loop_finished = time.perf_counter()
        elapsed = max(loop_finished - started, 1e-9)
        if self.instrumentation_enabled:
            elapsed_ns = max(1, round(elapsed * 1_000_000_000))
            self.seed_generation_batch.measured_search_loop_ns += elapsed_ns
            self.seed_generation_cumulative.measured_search_loop_ns += (
                elapsed_ns
            )
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
            "early_rejected": early_rejected,
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
            "candidate_provenance": (
                dict(self.best_provenance)
                if self.best_provenance is not None
                else None
            ),
            "termination_reason": termination_reason,
            "end_high_water": self.high_water,
            "score_backend": {
                "implementation": "cpp",
                "early_exit_enabled": self.score_early_exit_enabled,
                "duplicate_key_scheme": self.tabu_key_scheme,
                "score_worker_protocol_version": PROTOCOL_VERSION,
                "mutation_witness_cache_enabled": (
                    self.mutation_witness_cache_enabled
                ),
                "score_worker_sha256": self.score_worker.binary_sha256,
                **self.score_backend_batch,
            },
        }
        if self.proposal_ranking is not None:
            result["proposal_ranking"] = self.proposal_ranking.telemetry_payload()
        if self.timing_ns is not None:
            if self.score_profile is not None:
                self.timing_ns["graph_validation"] = (
                    self.score_profile.graph_validation_ns
                )
                self.timing_ns["witness_counting"] = (
                    self.score_profile.witness_counting_ns
                )
                self.timing_ns["score_calculation"] = (
                    self.score_profile.score_calculation_ns
                )
            self.timing_ns["telemetry_construction"] += (
                time.perf_counter_ns() - telemetry_started
            )
            result["timing"] = _timing_payload(
                self.timing_ns,
                search_loop_seconds=elapsed,
                score_profile=(
                    self.score_profile.payload()
                    if self.score_profile is not None
                    else None
                ),
                mutation_profile=(
                    self.mutation_profile.payload(
                        cache_enabled=self.mutation_witness_cache_enabled
                    )
                    if self.mutation_profile is not None
                    else None
                ),
            )
        if self.instrumentation_enabled:
            result["seed_generation"] = {
                "schema_version": 1,
                "batch": self.seed_generation_batch.payload(
                    graph_family=self.spec.graph_family,
                    graph_order=int(self.parameters["order"]),
                    generator_mode=self._effective_seed_generator_mode(),
                ),
                "cumulative": self.seed_generation_cumulative.payload(
                    graph_family=self.spec.graph_family,
                    graph_order=int(self.parameters["order"]),
                    generator_mode=self._effective_seed_generator_mode(),
                ),
            }
            self.seed_generation_batch = SeedGenerationAccumulator()
        return result

    def _policy_mutation(
        self,
        graph: BitGraph,
        *,
        step: int,
    ) -> MutationResult:
        """Generate/rank/apply one host-owned proposal without lane RNG draws."""

        if self.proposal_ranking is None:
            raise RuntimeError("proposal-ranking capability is disabled")
        seed_material = canonical_json(
            {
                "lane_id": self.spec.lane_id,
                "lane_version": self.spec.lane_version,
                "step": step,
                "catalog_id": self.proposal_ranking_catalog_id,
            },
            max_bytes=4096,
        )
        policy_seed = int.from_bytes(
            hashlib.sha256(seed_material).digest()[:8], "big"
        )
        selection, selected_graph, pool = self.proposal_ranking.select_for_graph(
            graph,
            policy_seed=policy_seed,
            step=step,
            remaining_steps=max(
                0,
                int(self.parameters["batch_candidates"])
                - int(self.algorithm_evaluated),
            ),
            apply_selected=True,
            return_details=True,
            score=self.score,
        )
        selected = next(
            candidate
            for candidate in pool.candidates
            if candidate.proposal_id == selection.selected_proposal_id
        )
        if selected_graph == graph:
            raise RuntimeError("reviewed policy selected a no-op proposal")
        return MutationResult(
            selected_graph,
            removed_edges=selected.rewrite.removed_edges,
            added_edges=selected.rewrite.added_edges,
        )

    def _mutation_witness_choices_for(
        self, graph: BitGraph
    ) -> tuple[tuple[tuple[int, int], ...], ...]:
        if (
            self.mutation_context is None
            or self._forbidden_witness_edge_choices is None
        ):
            return ()
        return self._forbidden_witness_edge_choices(
            graph,
            context=self.mutation_context,
            profile=self.mutation_profile,
        )

    def _invalidate_mutation_witness_cache(self) -> None:
        if self.mutation_context is not None:
            self.mutation_context.invalidate()

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

    def _full_search_key(self, graph: BitGraph) -> str:
        if self.tabu_key_scheme == FAST_GRAPH_KEY_SCHEME:
            return _zobrist_graph_key(graph)
        return self._graph_sha256(graph)

    def _candidate_search_key(
        self,
        graph: BitGraph,
        mutation_delta: Any | None,
    ) -> str:
        if self.tabu_key_scheme != FAST_GRAPH_KEY_SCHEME:
            return self._graph_sha256(graph)
        if (
            mutation_delta is not None
            and mutation_delta.graph == graph
            and (
                mutation_delta.removed_edges
                or mutation_delta.added_edges
            )
        ):
            return _zobrist_update_key(
                self.current_graph_key,
                removed_edges=mutation_delta.removed_edges,
                added_edges=mutation_delta.added_edges,
            )
        return _zobrist_graph_key(graph)

    def _graph_sha256(self, graph: BitGraph) -> str:
        if self.optimized_legacy_key:
            return graph.stable_hash(self.graph6_workspace)
        return _legacy_graph_key_reference(graph)

    def _candidate_id(self, graph: BitGraph) -> str:
        return _candidate_id_from_graph_sha256(
            self.spec.campaign_id, self._graph_sha256(graph)
        )

    def _independent_sample_provenance(
        self,
        *,
        graph_sha256: str,
        score: ScoreResult,
        evaluation_index: int,
        record_status: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "provenance_kind": INDEPENDENT_SAMPLE_PROVENANCE,
            "lane_id": self.spec.lane_id,
            "source_checkpoint_id": self.batch_source_checkpoint_id,
            "retaining_checkpoint_id": None,
            "seed_lineage": list(
                self.spec.seed_lineage or (self.spec.seed,)
            ),
            "evaluation_index": evaluation_index,
            "generator_version": GENERATOR_VERSION,
            "graph_sha256": graph_sha256,
            "score": _score_payload(score),
            "record_status": record_status,
        }

    def retained_best_provenance(
        self, retaining_checkpoint_id: str
    ) -> dict[str, Any]:
        if self.best_provenance is not None:
            return {
                **self.best_provenance,
                "retaining_checkpoint_id": retaining_checkpoint_id,
            }
        return {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "provenance_kind": MUTATION_CHAIN_PROVENANCE,
            "lane_id": self.spec.lane_id,
            "source_checkpoint_id": self.batch_source_checkpoint_id,
            "retaining_checkpoint_id": retaining_checkpoint_id,
            "seed_lineage": list(
                self.spec.seed_lineage or (self.spec.seed,)
            ),
            "evaluation_index": self.best_evaluation_index,
            "generator_version": GENERATOR_VERSION,
            "graph_sha256": self._graph_sha256(self.best_graph),
            "score": _score_payload(self.best_score),
            "record_status": "global_record",
            "mutation_ancestry": list(self.best_ancestry),
        }

    def _remember_hash(self, key: str) -> None:
        if len(self.recent_hashes) == self.recent_hashes.maxlen:
            removed = self.recent_hashes.popleft()
            if removed not in self.recent_hashes:
                self.recent_hash_set.discard(removed)
        self.recent_hashes.append(key)
        self.recent_hash_set.add(key)

    def _score_cutoff(
        self, key: str
    ) -> tuple[tuple[int, int, int, int, int], bool] | None:
        if (
            not self.score_early_exit_enabled
            or self.algorithm not in {
                "iterated_local_search",
                "iterated_local_search_tabu",
            }
        ):
            return None
        perturb = int(self.parameters.get("perturbation_interval", 64))
        if self.algorithm_evaluated % perturb == 0:
            return None
        if key in self.tabu:
            return self.best_score.ordering_key, True
        return self.score.ordering_key, False

    def _score(
        self,
        graph: BitGraph,
        cutoff: (
            tuple[tuple[int, int, int, int, int], bool] | None
        ) = None,
    ) -> ScoreResult | None:
        return self._cpp_score(graph, cutoff)

    def _cpp_score(
        self,
        graph: BitGraph,
        cutoff: (
            tuple[tuple[int, int, int, int, int], bool] | None
        ),
    ) -> ScoreResult | None:
        worker = self.score_worker
        cap = int(self.parameters["witness_cap"])
        node_budget = max(4_096, min(50_000, cap * 1_024))
        last_error: BaseException | None = None
        for attempt in range(2):
            try:
                response = worker.score(
                    graph,
                    lengths=self.plugin.forbidden_lengths(graph.n),
                    limit=cap + 1,
                    node_budget=node_budget,
                    cutoff=(
                        (
                            cutoff[0][1],
                            cutoff[0][2],
                            cutoff[0][4],
                        )
                        if cutoff is not None
                        else None
                    ),
                    cutoff_inclusive=(
                        cutoff[1] if cutoff is not None else False
                    ),
                )
                self.score_backend_batch["cpp_requests"] += 1
                if response.dominated:
                    if (
                        self.score_profile is not None
                        and self._record_count_profile is not None
                    ):
                        self._record_count_profile(
                            response.results,
                            self.score_profile,
                            cutoff=True,
                        )
                    return None
                return self._count_result_score(
                    graph,
                    cap,
                    response.results,
                    self.score_profile,
                )
            except (OSError, ScoreWorkerError, ValueError) as error:
                last_error = error
                if attempt == 0:
                    self.score_backend_batch["worker_restarts"] += 1
                    try:
                        worker.restart()
                    except ScoreWorkerError as restart_error:
                        last_error = restart_error
                        break
        worker.close()
        raise ScoreWorkerError(
            "mandatory C++ score worker failed after one restart"
        ) from last_error

    def close(self) -> None:
        if self.proposal_ranking is not None:
            self.proposal_ranking.close()
        self.score_worker.close()

    def checkpoint(self, lane_version: int) -> dict[str, Any]:
        current_candidate_id = self.current_candidate_id
        current_provenance = self.current_provenance
        best_provenance = self.best_provenance
        if (
            self.algorithm == "random_restart"
            and self.independent_sample_provenance
        ):
            current_graph_sha256 = self._graph_sha256(self.graph)
            current_candidate_id = _candidate_id_from_graph_sha256(
                self.spec.campaign_id, current_graph_sha256
            )
            current_provenance = self._independent_sample_provenance(
                graph_sha256=current_graph_sha256,
                score=self.score,
                evaluation_index=self.current_evaluation_index,
                record_status="checkpoint_current",
            )
            if best_provenance is None:
                best_graph_sha256 = (
                    current_graph_sha256
                    if self.best_graph == self.graph
                    else self._graph_sha256(self.best_graph)
                )
                best_provenance = self._independent_sample_provenance(
                    graph_sha256=best_graph_sha256,
                    score=self.best_score,
                    evaluation_index=self.best_evaluation_index,
                    record_status="checkpoint_best",
                )
        else:
            if current_candidate_id is None:
                current_candidate_id = self._candidate_id(self.graph)
            current_provenance = {
                "schema_version": PROVENANCE_SCHEMA_VERSION,
                "provenance_kind": MUTATION_CHAIN_PROVENANCE,
                "lane_id": self.spec.lane_id,
                "evaluation_index": self.current_evaluation_index,
                "candidate_id": current_candidate_id,
                "ancestry_field": "accepted_ancestry",
            }
            best_provenance = {
                "schema_version": PROVENANCE_SCHEMA_VERSION,
                "provenance_kind": MUTATION_CHAIN_PROVENANCE,
                "lane_id": self.spec.lane_id,
                "evaluation_index": self.best_evaluation_index,
                "candidate_id": self.best_candidate_id,
                "ancestry_field": "best_ancestry",
            }
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
            "duplicate_key_scheme": self.tabu_key_scheme,
            "tabu_key_scheme": _duplicate_key_compatibility_alias(
                self.tabu_key_scheme
            ),
            "parameters": dict(self.parameters),
            "high_water": self.high_water,
            "accepted_ancestry": list(self.accepted_ancestry),
            "best_ancestry": list(self.best_ancestry),
            "current_candidate_id": current_candidate_id,
            "best_candidate_id": (
                self.best_candidate_id
                if self.instrumentation_enabled
                else self._candidate_id(self.best_graph)
            ),
            "current_evaluation_index": self.current_evaluation_index,
            "best_evaluation_index": self.best_evaluation_index,
            "current_provenance": current_provenance,
            "best_provenance": best_provenance,
        }
        if self.instrumentation_enabled:
            seed_generation = self.seed_generation_cumulative.payload(
                graph_family=self.spec.graph_family,
                graph_order=int(self.parameters["order"]),
                generator_mode=self._effective_seed_generator_mode(),
            )
            payload["seed_generation"] = seed_generation
            payload["seed_generation_sha256"] = hashlib.sha256(
                canonical_json(seed_generation, max_bytes=256 * 1024)
            ).hexdigest()
        if self.proposal_ranking_catalog_id is not None:
            from .proposal_ranking import checkpoint_policy_identity

            payload["proposal_ranking_identity"] = checkpoint_policy_identity()
        digest = checkpoint_scientific_sha256(payload)
        return {
            **payload,
            "checkpoint_id": f"checkpoint-{digest[:24]}",
            "sha256": digest,
        }


def _live_frontier_payload(
    *,
    lane_id: str,
    lane_version: int,
    graph: BitGraph,
    score: ScoreResult,
    candidate_id: str | None,
    high_water: int,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "lane_id": lane_id,
        "lane_version": lane_version,
        "graph6": graph.to_graph6(),
        "score": _score_payload(score),
        "current_candidate_id": candidate_id,
        "high_water": high_water,
        "published_at": utc_now(),
        "transient": True,
    }
    digest = hashlib.sha256(
        canonical_json(payload, max_bytes=LIVE_FRONTIER_PAYLOAD_LIMIT_BYTES)
    ).hexdigest()
    return {
        **payload,
        "preview_id": f"live-frontier-{digest[:24]}",
        "sha256": digest,
    }


def checkpoint_scientific_sha256(payload: dict[str, Any]) -> str:
    scientific = dict(payload)
    scientific.pop("checkpoint_id", None)
    scientific.pop("sha256", None)
    scientific.pop("seed_generation", None)
    scientific.pop("seed_generation_sha256", None)
    return hashlib.sha256(
        canonical_json(scientific, max_bytes=1024 * 1024)
    ).hexdigest()


def checkpoint_seed_generation_sha256(
    payload: dict[str, Any],
) -> str | None:
    seed_generation = payload.get("seed_generation")
    claimed = payload.get("seed_generation_sha256")
    if seed_generation is None and claimed is None:
        return None
    if not isinstance(seed_generation, dict) or not isinstance(claimed, str):
        raise ValueError("checkpoint seed telemetry envelope is incomplete")
    return hashlib.sha256(
        canonical_json(seed_generation, max_bytes=256 * 1024)
    ).hexdigest()


def _publish_live_frontier(
    events: Any,
    spec: LaneSpec,
    kernel: _LaneKernel,
    lane_version: int,
) -> None:
    graph, score, candidate_id, high_water = kernel.live_frontier_state
    _emit(
        events,
        {
            "kind": "live_frontier",
            "lane_id": spec.lane_id,
            "preview": _live_frontier_payload(
                lane_id=spec.lane_id,
                lane_version=lane_version,
                graph=graph,
                score=score,
                candidate_id=candidate_id,
                high_water=high_water,
            ),
            "at": utc_now(),
        },
    )


def _lane_worker(
    spec: LaneSpec,
    commands: Any,
    events: Any,
    stop_event: Any,
    pause_event: Any,
    checkpoint: dict[str, Any] | None,
    fork_seed: int | None,
    memory_limit_bytes: int | None,
    score_profiling_enabled: bool,
) -> None:
    preview_stop: Event | None = None
    preview_thread: Thread | None = None
    kernel: _LaneKernel | None = None
    try:
        if (
            memory_limit_bytes is not None
            and memory_limit_bytes < 128 * 1024 * 1024
        ):
            raise RuntimeError(
                "lane memory limit must be at least 128 MiB for the "
                "mandatory C++ score worker"
            )
        parent_memory_limit = memory_limit_bytes
        if memory_limit_bytes is not None:
            parent_memory_limit = (
                memory_limit_bytes - DEFAULT_WORKER_MEMORY_BYTES
            )
        set_address_space_limit(parent_memory_limit)
        kernel = _LaneKernel(
            spec,
            checkpoint,
            fork_seed,
            score_profiling_enabled=score_profiling_enabled,
            score_worker_memory_bytes=DEFAULT_WORKER_MEMORY_BYTES,
        )
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
        preview_stop = Event()

        def publish_live_frontier() -> None:
            while not preview_stop.wait(LIVE_FRONTIER_INTERVAL_SECONDS):
                try:
                    _publish_live_frontier(
                        events, spec, kernel, lane_version
                    )
                except Exception:
                    continue

        preview_thread = Thread(
            target=publish_live_frontier,
            name=f"sglab-live-frontier-{spec.lane_id}",
            daemon=True,
        )
        preview_thread.start()
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
            metrics = kernel.run_batch(
                stop_event,
                source_checkpoint_id=str(
                    current_checkpoint["checkpoint_id"]
                ),
            )
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
                        "provenance": kernel.retained_best_provenance(
                            str(current_checkpoint["checkpoint_id"])
                        ),
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
        error_detail = f"{type(error).__name__}: {error}"
        seed_failure = getattr(
            error, "seed_generation_observation", None
        )
        if isinstance(seed_failure, dict):
            error_detail = (
                f"{error_detail}; seed_generation="
                f"{json.dumps(seed_failure, sort_keys=True, separators=(',', ':'))}"
            )
        _emit(
            events,
            {
                "kind": "exit",
                "lane_id": spec.lane_id,
                "reason": "failure",
                "error": error_detail,
                "at": utc_now(),
            },
            important=True,
        )
        raise
    finally:
        if preview_stop is not None:
            preview_stop.set()
        if preview_thread is not None:
            preview_thread.join(timeout=1)
        if kernel is not None:
            kernel.close()


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
        score_profiling_enabled: bool = True,
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
        self.score_profiling_enabled = score_profiling_enabled
        self.context = get_context("spawn")
        self.events = self.context.Queue(maxsize=event_capacity)
        self.lanes: dict[str, LaneRuntime] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self._checkpoint_order: dict[str, deque[str]] = {}
        self._pinned_checkpoint_ids: set[str] = set()
        self._pinned_checkpoint_order: deque[str] = deque()
        self._deferred_events: deque[dict[str, Any]] = deque()
        self._queues_closed = False
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
                self.score_profiling_enabled,
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
        if self._queues_closed:
            return None
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
        elif kind == "live_frontier":
            preview = dict(event["preview"])
            self._remember_live_frontier(runtime, preview)
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

    def _remember_live_frontier(
        self, runtime: LaneRuntime, preview: dict[str, Any]
    ) -> None:
        if str(preview.get("lane_id")) != runtime.spec.lane_id:
            raise ValueError("live frontier lane mismatch")
        runtime.latest_live_frontier = preview
        runtime.high_water = max(
            runtime.high_water, int(preview.get("high_water", 0))
        )
        lane_digest = hashlib.sha256(
            runtime.spec.lane_id.encode("utf-8")
        ).hexdigest()
        path = self.checkpoint_dir / f"live-frontier-{lane_digest[:24]}.json"
        atomic_write_json(path, preview)

    def pin_checkpoint(self, checkpoint_id: str) -> None:
        self.pin_checkpoints((checkpoint_id,))

    def pin_checkpoints(self, checkpoint_ids: tuple[str, ...]) -> None:
        identifiers = tuple(dict.fromkeys(checkpoint_ids))
        missing = [
            checkpoint_id
            for checkpoint_id in identifiers
            if checkpoint_id not in self.checkpoints
        ]
        if missing:
            raise KeyError(
                f"checkpoint is not available: {missing[0]}"
            )
        if len(identifiers) > self.pinned_checkpoints:
            raise ValueError(
                "checkpoint pin batch exceeds the retention limit"
            )
        desired = set(identifiers)
        retained = [
            checkpoint_id
            for checkpoint_id in self._pinned_checkpoint_order
            if (
                checkpoint_id in self._pinned_checkpoint_ids
                and checkpoint_id not in desired
            )
        ]
        self._pinned_checkpoint_ids = set(retained) | desired
        self._pinned_checkpoint_order = deque((*retained, *identifiers))
        while len(self._pinned_checkpoint_order) > self.pinned_checkpoints:
            expired = self._pinned_checkpoint_order.popleft()
            self._pinned_checkpoint_ids.discard(expired)
            self._drop_checkpoint_if_unretained(expired)

    def register_restored_checkpoint(
        self, lane_id: str, checkpoint: dict[str, Any]
    ) -> None:
        runtime = self.lanes.get(lane_id)
        if runtime is None:
            raise KeyError(f"restored lane is unavailable: {lane_id}")
        self._remember_checkpoint(runtime, dict(checkpoint))

    def register_archived_checkpoint(
        self, checkpoint: dict[str, Any]
    ) -> None:
        checkpoint_id = str(checkpoint["checkpoint_id"])
        lane_id = str(checkpoint["lane_id"])
        self.checkpoints[checkpoint_id] = dict(checkpoint)
        order = self._checkpoint_order.setdefault(lane_id, deque())
        if checkpoint_id not in order:
            order.append(checkpoint_id)

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
        if not self._queues_closed:
            while True:
                try:
                    event = self.events.get_nowait()
                except Empty:
                    break
                self._apply_event(event)
                self._deferred_events.append(event)
            for runtime in self.lanes.values():
                runtime.commands.cancel_join_thread()
                runtime.commands.close()
            self.events.cancel_join_thread()
            self.events.close()
            self._queues_closed = True


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


def _legacy_graph_key_reference(graph: BitGraph) -> str:
    if graph.n <= 62:
        prefix = bytes((graph.n + 63,))
    elif graph.n <= 258047:
        prefix = bytes(
            (
                126,
                ((graph.n >> 12) & 63) + 63,
                ((graph.n >> 6) & 63) + 63,
                (graph.n & 63) + 63,
            )
        )
    else:
        raise ValueError("graph6 export supports at most 258047 vertices")
    bits = [
        int(graph.has_edge(u, v))
        for v in range(1, graph.n)
        for u in range(v)
    ]
    bits.extend([0] * ((-len(bits)) % 6))
    data = bytes(
        sum(
            bits[offset + bit] << (5 - bit)
            for bit in range(6)
        )
        + 63
        for offset in range(0, len(bits), 6)
    )
    return hashlib.sha256(prefix + data).hexdigest()


def _candidate_id_from_graph_sha256(
    campaign_id: str, graph_sha256: str
) -> str:
    identity = hashlib.sha256(
        f"{campaign_id}:{graph_sha256}".encode("ascii")
    ).hexdigest()
    return f"candidate-{identity[:24]}"


def _candidate_id(campaign_id: str, graph: BitGraph) -> str:
    return _candidate_id_from_graph_sha256(
        campaign_id, graph.stable_hash()
    )


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
    child_graph_sha256: str | None = None,
) -> dict[str, Any]:
    parent_edges = set(parent.edges())
    child_edges = set(child.edges())
    removed = sorted(parent_edges - child_edges)
    added = sorted(child_edges - parent_edges)
    mutated_vertices = sorted(
        {vertex for edge in (*removed, *added) for vertex in edge}
    )
    return {
        "candidate_id": (
            _candidate_id_from_graph_sha256(
                campaign_id, child_graph_sha256
            )
            if child_graph_sha256 is not None
            else _candidate_id(campaign_id, child)
        ),
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
    score_profile: dict[str, int] | None = None,
    mutation_profile: dict[str, Any] | None = None,
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
    result = {
        "enabled": True,
        "counters_seconds": counters,
        "search_loop_seconds": search_loop_seconds,
        "candidate_evaluation_seconds": search_loop_seconds,
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
    if score_profile is not None:
        result["score_profile"] = score_profile
    if mutation_profile is not None:
        result["mutation_profile"] = mutation_profile
    return result


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
    try:
        for _ in range(batches):
            metrics.append(kernel.run_batch(stop))
        return {
            "metrics": metrics,
            "checkpoint": kernel.checkpoint(spec.lane_version),
        }
    finally:
        kernel.close()


def run_bounded_lane_batch(
    spec: LaneSpec,
    *,
    max_evaluations: int,
    max_wall_seconds: float,
    instrumentation_enabled: bool = True,
    score_profiling_enabled: bool = True,
    optimized_legacy_key: bool = True,
    independent_sample_provenance: bool = True,
    proposal_ranking_profile_enabled: bool = False,
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
        score_profiling_enabled=score_profiling_enabled,
        optimized_legacy_key=optimized_legacy_key,
        independent_sample_provenance=independent_sample_provenance,
        proposal_ranking_profile_enabled=proposal_ranking_profile_enabled,
    )
    try:
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
            "peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * 1024,
            "initial_score": metrics["initial_score"],
            "best_score": _score_payload(kernel.best_score),
            "score_trajectory_summary": metrics[
                "score_trajectory_summary"
            ],
            "operator_statistics": metrics["operator_statistics"],
            "mutation_ancestry": metrics["mutation_ancestry"],
            "candidate_provenance": metrics["candidate_provenance"],
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
    finally:
        kernel.close()

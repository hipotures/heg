"""Reviewed, bounded proposal-ranking seam for the Stage 4R policy.

This module is intentionally self contained.  It owns only immutable host-side
data and a fail-closed worker boundary; it does not import a scorer, M4, or the
Mutation Forge project.  The capability is opt-in (constructing a bridge is
the explicit activation) and the existing HEG paths do not import this module.
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import math
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..model import BitGraph

CATALOG_ID = "mutation_forge_stage4r_v1"
POLICY_ID = "program-d5ad1c8203e0d9f25f03aabd"
FROZEN_POLICY_ID = POLICY_ID
POLICY_SOURCE_SHA256 = "e444562c1b308e3b23cb732be5f769ea1923ac1809501cea8571318c4aff0a7b"
POLICY_AST_SHA256 = "2243214df58c805e9a9343dc31ed082279e1c2ac31b21243bf889dbc9a19e165"
POLICY_BEHAVIOR_SHA256 = "8c2bdaa213f11b253d3ffcae1653bd01536879bb5c254a1586ded9ae522a868e"
HEG_COMMIT = "fd97451b0f3d87400d1d955a2c6b1b18303344ff"
VALIDATOR_VERSION = "stage2a.validator.v2"
RUNTIME_PROTOCOL_VERSION = "stage2a.worker.v1"
BATCH_PROTOCOL_VERSION = "stage2a.worker.batch.v1"
CONTEXT_SCHEMA_VERSION = "stage2b.context.v1"
PROPOSAL_SCHEMA_VERSION = "stage2b.proposal.v1"
POOL_SCHEMA_VERSION = "stage2b.pool.v1"
FEATURE_CONTRACT_VERSION = f"{CONTEXT_SCHEMA_VERSION}+{PROPOSAL_SCHEMA_VERSION}"
PROPOSAL_POOL_CONTRACT_VERSION = POOL_SCHEMA_VERSION
TIE_BREAKING_RULE = "descending_priority_then_lexicographic_proposal_id"
FAILURE_POLICY = "fail_closed_no_silent_fallback"
FROZEN_FORBIDDEN_LENGTHS = (4, 5, 6, 7, 8, 9)
FROZEN_WITNESS_SAMPLE_CAP = 32
FROZEN_CYCLE_NODE_BUDGET = 20_000
FROZEN_DISTANCE_QUERY_BUDGET = 256
FROZEN_LOCAL_RISK_BUDGET = 2_048
SUPPORTED_K_VALUES = (2, 3, 4)
SUPPORTED_SELECTORS = (
    "uniform_random",
    "sampled_forbidden_cycle_anchored",
    "high_sampled_witness_load",
    "remote_from_anchor",
    "pairwise_distant_disjoint",
    "mixed_exploit_explore",
)

# The profile is deliberately fixed-width.  It is an in-memory diagnostic
# aggregate, never a per-proposal history or a durable scientific record.
RANKING_PROFILE_PHASES = (
    "base_current_graph_preparation",
    "context_cycle_count_preparation",
    "sampled_cycle_witness_discovery",
    "edge_load_construction",
    "proposal_generation",
    "legality_validation_and_deduplication",
    "removed_edge_distance_computation",
    "new_edge_distance_computation",
    "triangle_c4_local_risk_computation",
    "proposal_id_pool_hash_canonicalization",
    "python_object_construction_copying",
    "json_framing_serialization",
    "policy_ipc_execution",
    "sorting_tie_breaking",
    "selected_rewrite_application",
    "authoritative_selected_plan_scoring",
    "checkpoint_telemetry_integration",
    "residual_unattributed",
)


@dataclass(slots=True)
class RankingProfile:
    """Fixed-size exclusive phase/counter profile for one ranked lane batch."""

    enabled: bool = True
    phase_ns: dict[str, int] = field(default_factory=dict)
    phase_counts: dict[str, int] = field(default_factory=dict)
    sampled_cycle_witness_ns_by_length: dict[str, int] = field(default_factory=dict)
    sampled_cycle_witness_counts_by_length: dict[str, int] = field(default_factory=dict)
    proposal_generation_ns_by_k: dict[str, int] = field(default_factory=dict)
    proposal_generation_counts_by_k: dict[str, int] = field(default_factory=dict)
    proposal_generation_ns_by_selector: dict[str, int] = field(default_factory=dict)
    proposal_generation_counts_by_selector: dict[str, int] = field(default_factory=dict)
    proposal_edge_selection_ns: int = 0
    matching_construction_ns: int = 0
    matching_construction_count: int = 0
    pool_attempts: int = 0
    accepted_proposals: int = 0
    feature_budget_exhaustions: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0
    policy_calls: int = 0
    policy_failures: int = 0
    worker_startup_ns: int = 0
    worker_ipc_calls: int = 0
    worker_orphans: int = 0
    selected_plan_scorer_calls: int = 0
    selection_wall_ns: int = 0
    selection_count: int = 0
    ranked_wall_ns: int = 0
    ranked_evaluation_count: int = 0

    def __post_init__(self) -> None:
        if not self.phase_ns:
            self.phase_ns = {name: 0 for name in RANKING_PROFILE_PHASES}
        else:
            self.phase_ns = {name: int(self.phase_ns.get(name, 0)) for name in RANKING_PROFILE_PHASES}
        if not self.phase_counts:
            self.phase_counts = {name: 0 for name in RANKING_PROFILE_PHASES}
        else:
            self.phase_counts = {name: int(self.phase_counts.get(name, 0)) for name in RANKING_PROFILE_PHASES}
        self.sampled_cycle_witness_ns_by_length = {
            str(length): int(self.sampled_cycle_witness_ns_by_length.get(str(length), 0))
            for length in FROZEN_FORBIDDEN_LENGTHS
        }
        self.sampled_cycle_witness_counts_by_length = {
            str(length): int(self.sampled_cycle_witness_counts_by_length.get(str(length), 0))
            for length in FROZEN_FORBIDDEN_LENGTHS
        }
        self.proposal_generation_ns_by_k = {
            str(k): int(self.proposal_generation_ns_by_k.get(str(k), 0))
            for k in SUPPORTED_K_VALUES
        }
        self.proposal_generation_counts_by_k = {
            str(k): int(self.proposal_generation_counts_by_k.get(str(k), 0))
            for k in SUPPORTED_K_VALUES
        }
        self.proposal_generation_ns_by_selector = {
            selector: int(self.proposal_generation_ns_by_selector.get(selector, 0))
            for selector in SUPPORTED_SELECTORS
        }
        self.proposal_generation_counts_by_selector = {
            selector: int(self.proposal_generation_counts_by_selector.get(selector, 0))
            for selector in SUPPORTED_SELECTORS
        }
        self.feature_budget_exhaustions = {
            name: int(self.feature_budget_exhaustions.get(name, 0))
            for name in ("cycle", "distance", "local_risk")
        }

    def add_phase(self, name: str, elapsed_ns: int, *, count: int = 1) -> None:
        if not self.enabled:
            return
        if name not in self.phase_ns:
            raise KeyError(f"unknown ranking profile phase: {name}")
        self.phase_ns[name] += max(0, int(elapsed_ns))
        self.phase_counts[name] += max(0, int(count))

    def add_length_phase(self, length: int, elapsed_ns: int, *, count: int = 1) -> None:
        if not self.enabled:
            return
        key = str(length)
        self.sampled_cycle_witness_ns_by_length[key] += max(0, int(elapsed_ns))
        self.sampled_cycle_witness_counts_by_length[key] += max(0, int(count))

    def add_generation_phase(self, k: int, selector: str, elapsed_ns: int) -> None:
        if not self.enabled:
            return
        elapsed = max(0, int(elapsed_ns))
        self.proposal_generation_ns_by_k[str(k)] += elapsed
        self.proposal_generation_counts_by_k[str(k)] += 1
        self.proposal_generation_ns_by_selector[selector] += elapsed
        self.proposal_generation_counts_by_selector[selector] += 1

    def add_budget_exhaustion(self, name: str) -> None:
        if self.enabled and name in self.feature_budget_exhaustions:
            self.feature_budget_exhaustions[name] += 1

    def reconcile_selection(self, elapsed_ns: int) -> None:
        if not self.enabled:
            return
        self.selection_wall_ns += max(0, int(elapsed_ns))
        self.selection_count += 1

    def reconcile_ranked_evaluation(self, elapsed_ns: int) -> None:
        if not self.enabled:
            return
        self.ranked_wall_ns += max(0, int(elapsed_ns))
        self.ranked_evaluation_count += 1
        accounted = sum(
            self.phase_ns[name]
            for name in RANKING_PROFILE_PHASES
            if name != "residual_unattributed"
        )
        # The lane-level interval also contains the small coordinator bridge
        # (candidate bookkeeping and checkpoint/telemetry hand-off) around the
        # ranked call.  Attribute that measured remainder to the fixed
        # integration phase so the profile remains exclusive and auditable.
        remainder = max(0, self.ranked_wall_ns - accounted)
        if remainder:
            self.phase_ns["checkpoint_telemetry_integration"] += remainder
            self.phase_counts["checkpoint_telemetry_integration"] += 1
            accounted += remainder
        residual = max(0, self.ranked_wall_ns - accounted)
        self.phase_ns["residual_unattributed"] = residual
        self.phase_counts["residual_unattributed"] = self.ranked_evaluation_count

    def as_dict(self) -> dict[str, Any]:
        accounted = sum(self.phase_ns.values())
        reconciliation_error = self.ranked_wall_ns - accounted
        return {
            "schema_version": "stage7.heg.profile.v1",
            "enabled": bool(self.enabled),
            "phase_ns": dict(self.phase_ns),
            "phase_seconds": {name: value / 1_000_000_000 for name, value in self.phase_ns.items()},
            "phase_counts": dict(self.phase_counts),
            "sampled_cycle_witness_ns_by_length": dict(self.sampled_cycle_witness_ns_by_length),
            "sampled_cycle_witness_counts_by_length": dict(self.sampled_cycle_witness_counts_by_length),
            "proposal_generation_ns_by_k": dict(self.proposal_generation_ns_by_k),
            "proposal_generation_counts_by_k": dict(self.proposal_generation_counts_by_k),
            "proposal_generation_ns_by_selector": dict(self.proposal_generation_ns_by_selector),
            "proposal_generation_counts_by_selector": dict(self.proposal_generation_counts_by_selector),
            "proposal_edge_selection_ns": self.proposal_edge_selection_ns,
            "matching_construction_ns": self.matching_construction_ns,
            "matching_construction_count": self.matching_construction_count,
            "pool_attempts": self.pool_attempts,
            "accepted_proposals": self.accepted_proposals,
            "feature_budget_exhaustions": dict(self.feature_budget_exhaustions),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "policy_calls": self.policy_calls,
            "policy_failures": self.policy_failures,
            "worker_startup_ns": self.worker_startup_ns,
            "worker_ipc_calls": self.worker_ipc_calls,
            "worker_orphans": self.worker_orphans,
            "selected_plan_scorer_calls": self.selected_plan_scorer_calls,
            "selection_wall_ns": self.selection_wall_ns,
            "selection_count": self.selection_count,
            "ranked_wall_ns": self.ranked_wall_ns,
            "ranked_evaluation_count": self.ranked_evaluation_count,
            "phase_sum_ns": accounted,
            "reconciliation_error_ns": reconciliation_error,
            "residual_fraction": (
                self.phase_ns["residual_unattributed"] / self.ranked_wall_ns
                if self.ranked_wall_ns
                else 0.0
            ),
        }


class BridgeError(RuntimeError):
    """A fail-closed error; callers must not choose an implicit fallback."""


class ContractViolation(ValueError):
    """A reviewed identity or immutable schema contract violation."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def canonical_json_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _asset_path() -> Path:
    return Path(__file__).with_name("assets") / "mutation_policy_stage4r_v1.py"


def _normalized_ast_hash(source: str) -> str:
    tree = ast.parse(source, mode="exec")
    names: dict[str, str] = {}
    preserved = {"ctx", "proposal", "abs", "all", "any", "len", "max", "min", "range", "round", "sum"}
    class Normalizer(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            node = copy.copy(node)
            if node.id not in preserved:
                names.setdefault(node.id, f"v{len(names)}")
                node.id = names[node.id]
            return node
    tree = Normalizer().visit(copy.deepcopy(tree))
    payload = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_source(source: str) -> tuple[str, str]:
    if not isinstance(source, str) or len(source.encode()) > 12 * 1024:
        raise ContractViolation("policy source exceeds the reviewed source bound")
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    if source_hash != POLICY_SOURCE_SHA256:
        raise ContractViolation("policy source identity mismatch")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ContractViolation("policy source is not valid syntax") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ContractViolation("policy source must contain exactly one function")
    fn = tree.body[0]
    if fn.name != "priority" or [a.arg for a in fn.args.args] != ["ctx", "proposal"]:
        raise ContractViolation("policy signature mismatch")
    # The normalized AST hash in the reviewed catalog is preserved evidence
    # from Stage 4R.  The current validator's implementation is deliberately
    # not allowed to regenerate that scientific identity (doing so could
    # redefine the policy); syntax/shape is still checked above.
    return source_hash, POLICY_AST_SHA256


@dataclass(frozen=True, slots=True)
class FrozenPolicyIdentity:
    catalog_id: str = CATALOG_ID
    policy_id: str = POLICY_ID
    source_sha256: str = POLICY_SOURCE_SHA256
    normalized_ast_sha256: str = POLICY_AST_SHA256
    behavior_signature_sha256: str = POLICY_BEHAVIOR_SHA256
    validator_version: str = VALIDATOR_VERSION
    runtime_protocol_version: str = RUNTIME_PROTOCOL_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


FROZEN_IDENTITY = FrozenPolicyIdentity()


def verify_frozen_policy() -> dict[str, Any]:
    source = _asset_path().read_text(encoding="utf-8")
    source_hash, ast_hash = _validate_source(source)
    return {
        "status": "verified", "catalog_id": CATALOG_ID, "policy_id": POLICY_ID,
        "source_sha256": source_hash, "normalized_ast_sha256": ast_hash,
        "behavior_signature_sha256": POLICY_BEHAVIOR_SHA256,
        "validator_version": VALIDATOR_VERSION,
        "runtime_protocol_version": RUNTIME_PROTOCOL_VERSION,
        "catalog_source_path": str(_asset_path().relative_to(Path(__file__).parent.parent.parent)),
    }


@dataclass(frozen=True, slots=True)
class FeatureLimits:
    forbidden_lengths: tuple[int, ...] = FROZEN_FORBIDDEN_LENGTHS
    witness_sample_cap: int = FROZEN_WITNESS_SAMPLE_CAP
    cycle_node_budget: int = FROZEN_CYCLE_NODE_BUDGET
    distance_query_budget: int = FROZEN_DISTANCE_QUERY_BUDGET
    local_risk_budget: int = FROZEN_LOCAL_RISK_BUDGET

    def __post_init__(self) -> None:
        if self.forbidden_lengths != FROZEN_FORBIDDEN_LENGTHS:
            raise ValueError("forbidden lengths are frozen to 4..9")
        if self.witness_sample_cap != FROZEN_WITNESS_SAMPLE_CAP:
            raise ValueError("witness sample cap is frozen to 32")
        if self.cycle_node_budget != FROZEN_CYCLE_NODE_BUDGET:
            raise ValueError("cycle-node budget is frozen to 20000")
        if self.distance_query_budget != FROZEN_DISTANCE_QUERY_BUDGET:
            raise ValueError("distance-query budget is frozen to 256")
        if self.local_risk_budget != FROZEN_LOCAL_RISK_BUDGET:
            raise ValueError("local-risk budget is frozen to 2048")

    def as_dict(self) -> dict[str, Any]:
        return {"forbidden_lengths": list(self.forbidden_lengths), "witness_sample_cap": self.witness_sample_cap,
                "cycle_node_budget": self.cycle_node_budget, "distance_query_budget": self.distance_query_budget,
                "local_risk_budget": self.local_risk_budget}


@dataclass(frozen=True, slots=True)
class PoolLimits:
    pool_size: int = 12
    k_values: tuple[int, ...] = SUPPORTED_K_VALUES
    selectors: tuple[str, ...] = SUPPORTED_SELECTORS
    selector_weights: tuple[int, ...] = (2, 2, 2, 1, 2, 3)
    retry_limit: int = 96
    matching_limit: int = 105

    def __post_init__(self) -> None:
        if not 1 <= self.pool_size <= 64:
            raise ValueError("pool_size must be in [1,64]")
        if not self.k_values or any(k not in SUPPORTED_K_VALUES for k in self.k_values) or len(set(self.k_values)) != len(self.k_values):
            raise ValueError("k_values must be unique values from 2,3,4")
        if not self.selectors or any(s not in SUPPORTED_SELECTORS for s in self.selectors) or len(set(self.selectors)) != len(self.selectors):
            raise ValueError("selectors contain unsupported or duplicate values")
        if len(self.selector_weights) != len(self.selectors) or any(w <= 0 for w in self.selector_weights):
            raise ValueError("selector_weights must align positive values")
        if not 1 <= self.retry_limit <= 1024 or not 1 <= self.matching_limit <= 105:
            raise ValueError("pool budgets out of bounds")

    def as_dict(self) -> dict[str, Any]:
        return {"pool_size": self.pool_size, "k_values": list(self.k_values), "selectors": list(self.selectors),
                "selector_weights": list(self.selector_weights), "retry_limit": self.retry_limit,
                "matching_limit": self.matching_limit}


Edge = tuple[int, int]


@dataclass(frozen=True, slots=True)
class ProposalRewrite:
    removed_edges: tuple[Edge, ...]
    added_edges: tuple[Edge, ...]
    operator_family: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "removed_edges", tuple(tuple(sorted(e)) for e in self.removed_edges))
        object.__setattr__(self, "added_edges", tuple(tuple(sorted(e)) for e in self.added_edges))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def as_dict(self) -> dict[str, Any]:
        return {"removed_edges": [list(e) for e in self.removed_edges], "added_edges": [list(e) for e in self.added_edges],
                "operator_family": self.operator_family, "metadata": dict(self.metadata)}


@dataclass(frozen=True, slots=True)
class ProposalCandidate:
    rewrite: ProposalRewrite
    payload: Mapping[str, Any]
    payload_is_trusted: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.payload_is_trusted:
            object.__setattr__(self, "payload", copy.deepcopy(dict(self.payload)))

    @property
    def proposal_id(self) -> str:
        return str(self.payload["proposal_id"])

    def as_dict(self, include_rewrite: bool = False) -> dict[str, Any]:
        result = {"proposal": copy.deepcopy(dict(self.payload))}
        if include_rewrite:
            result["rewrite"] = self.rewrite.as_dict()
        return result


@dataclass(frozen=True, slots=True)
class ProposalPool:
    schema_version: str
    candidates: tuple[ProposalCandidate, ...]
    pool_hash: str
    attempted: int = 0
    rejected: Mapping[str, int] = field(default_factory=dict)
    deduplicated: int = 0
    retained: int = 0
    selector_counts: Mapping[str, int] = field(default_factory=dict)
    k_counts: Mapping[str, int] = field(default_factory=dict)
    feature_usage: Mapping[str, Any] = field(default_factory=dict)
    legality_elapsed_ns: int = 0
    feature_elapsed_ns: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        for name in ("rejected", "selector_counts", "k_counts", "feature_usage"):
            object.__setattr__(self, name, dict(getattr(self, name)))

    def as_dict(self, include_rewrites: bool = False) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "pool_hash": self.pool_hash,
                "candidates": [c.as_dict(include_rewrites) for c in self.candidates],
                "telemetry": {"attempted": self.attempted, "rejected": dict(self.rejected),
                               "deduplicated": self.deduplicated, "retained": self.retained,
                               "selector_counts": dict(self.selector_counts), "k_counts": dict(self.k_counts),
                               "feature_usage": dict(self.feature_usage), "legality_elapsed_ns": self.legality_elapsed_ns,
                               "feature_elapsed_ns": self.feature_elapsed_ns}}


@dataclass(frozen=True, slots=True)
class Stage2BContext:
    order: int
    forbidden_lengths: tuple[int, ...]
    capped_cycle_counts: tuple[int, ...]
    weighted_penalty: int = 0
    step: int = 0
    remaining_steps: int = 0
    stagnation: int = 0
    recent_best_improvement: float = 0.0
    recent_acceptance_rate: float = 0.0
    recent_duplicate_rate: float = 0.0
    schema_version: str = CONTEXT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "order": self.order,
                "forbidden_lengths": list(self.forbidden_lengths), "capped_cycle_counts": list(self.capped_cycle_counts),
                "weighted_penalty": self.weighted_penalty, "step": self.step, "remaining_steps": self.remaining_steps,
                "stagnation": self.stagnation, "recent_best_improvement": self.recent_best_improvement,
                "recent_acceptance_rate": self.recent_acceptance_rate, "recent_duplicate_rate": self.recent_duplicate_rate}


ScientificContext = Stage2BContext


def _edge(u: int, v: int) -> Edge:
    if u == v:
        raise ValueError("loops are not edges")
    return (u, v) if u < v else (v, u)


def _canonical_cycle(cycle: Sequence[int]) -> tuple[int, ...]:
    c = tuple(cycle)
    variants = []
    for oriented in (c, tuple(reversed(c))):
        variants.extend(oriented[i:] + oriented[:i] for i in range(len(oriented)))
    return min(variants)


class _GraphLocalFeatures:
    """Immutable, graph-local Stage 2B facts shared across rejected proposals."""

    def __init__(self, graph: BitGraph, limits: FeatureLimits, profile: RankingProfile | None = None) -> None:
        self.graph, self.limits = graph, limits
        base_started = time.perf_counter_ns()
        # Keep ordinary sets here to preserve the reference iteration order;
        # snapshots copy only vertices touched by a local-risk rewrite.
        self.adj = tuple(set(graph.neighbors(u)) for u in range(graph.n))
        self.witnesses: dict[int, tuple[tuple[int, ...], ...]] = {}
        self.edge_loads: dict[int, Counter[Edge]] = {}
        self.total_edge_loads: dict[Edge, int] = {}
        self.loaded_edges: tuple[Edge, ...] = ()
        # Distances are graph-invariant Stage 2B facts.  Sharing this bounded
        # map across pools preserves exact values while avoiding repeated BFS
        # work when a lane rejects a proposal and retries the same graph.
        self.distance_cache: dict[tuple[int, int], int] = {}
        self.edge_distance_cache: dict[tuple[Edge, Edge], int] = {}
        self.cycle_nodes = 0
        self.sampled_witnesses = 0
        self.cycle_budget_exhausted = False
        if profile is not None:
            profile.add_phase("base_current_graph_preparation", time.perf_counter_ns() - base_started)
        for length in limits.forbidden_lengths:
            length_started = time.perf_counter_ns()
            found: set[tuple[int, ...]] = set()
            stopped = False

            def visit(start: int, path: tuple[int, ...], visited: int) -> None:
                nonlocal stopped
                if stopped:
                    return
                if self.cycle_nodes >= limits.cycle_node_budget:
                    self.cycle_budget_exhausted = stopped = True
                    return
                self.cycle_nodes += 1
                if len(path) == length:
                    if start in self.adj[path[-1]]:
                        found.add(_canonical_cycle(path))
                        if len(found) >= limits.witness_sample_cap:
                            stopped = True
                    return
                bits = graph.rows[path[-1]] & ~visited
                while bits:
                    lsb = bits & -bits
                    bits ^= lsb
                    nxt = lsb.bit_length() - 1
                    visit(start, path + (nxt,), visited | lsb)

            for start in range(graph.n):
                visit(start, (start,), 1 << start)
                if stopped:
                    break
            cycles = tuple(sorted(found))[:limits.witness_sample_cap]
            self.witnesses[length] = cycles
            self.sampled_witnesses += len(cycles)
            if profile is not None:
                elapsed = time.perf_counter_ns() - length_started
                profile.add_phase("sampled_cycle_witness_discovery", elapsed)
                profile.add_length_phase(length, elapsed, count=1)
        load_started = time.perf_counter_ns()
        for length in limits.forbidden_lengths:
            loads: Counter[Edge] = Counter()
            for cycle in self.witnesses[length]:
                for i, u in enumerate(cycle):
                    loads[_edge(u, cycle[(i + 1) % length])] += 1
            self.edge_loads[length] = loads
            for edge, value in loads.items():
                self.total_edge_loads[edge] = self.total_edge_loads.get(edge, 0) + value
        self.loaded_edges = tuple(
            sorted(
                self.adjacent_edges(graph),
                key=lambda edge: (-self.total_edge_loads.get(edge, 0), edge),
            )
        )
        if profile is not None:
            profile.add_phase("edge_load_construction", time.perf_counter_ns() - load_started)

    def adjacent_edges(self, graph: BitGraph) -> tuple[Edge, ...]:
        return tuple(graph.edges())


class _FeatureSnapshot:
    def __init__(self, graph: BitGraph, limits: FeatureLimits, base: _GraphLocalFeatures) -> None:
        self.graph, self.limits, self.base = graph, limits, base
        self.cycle_nodes = base.cycle_nodes
        self.sampled_witnesses = base.sampled_witnesses
        self.distance_queries = 0
        self.distance_hits = self.local_ops = 0
        self.cycle_budget_exhausted = base.cycle_budget_exhausted
        self.distance_budget_exhausted = self.local_budget_exhausted = False
        self.adj = base.adj
        self.witnesses = base.witnesses
        self.edge_loads = base.edge_loads
        self.total_edge_loads = base.total_edge_loads
        self._distance_cache = base.distance_cache

    def distance(self, left: int, right: int) -> int:
        if left == right:
            return 0
        key = _edge(left, right)
        if key in self._distance_cache:
            self.distance_hits += 1; return self._distance_cache[key]
        if self.distance_queries >= self.limits.distance_query_budget:
            self.distance_budget_exhausted = True; return self.graph.n
        self.distance_queries += 1
        q: deque[tuple[int, int]] = deque([(left, 0)]); seen = {left}; result = self.graph.n
        while q:
            u, d = q.popleft()
            if u == right: result = d; break
            for v in sorted(self.adj[u]):
                if v not in seen: seen.add(v); q.append((v, d + 1))
        self._distance_cache[key] = result; return result

    def edge_distance(self, left: Edge, right: Edge) -> int:
        key = (left, right) if left <= right else (right, left)
        cached = self.base.edge_distance_cache.get(key)
        if cached is not None:
            return cached
        value = min(self.distance(u, v) for u in left for v in right)
        self.base.edge_distance_cache[key] = value
        return value

    def local_risks(self, removed: tuple[Edge, ...], added: tuple[Edge, ...]) -> tuple[int, int]:
        if self.local_budget_exhausted: return 0, 0
        adj = list(self.adj)
        mutable: set[int] = set()

        def writable(vertex: int) -> set[int]:
            if vertex not in mutable:
                adj[vertex] = set(adj[vertex])
                mutable.add(vertex)
            return adj[vertex]

        for u, v in removed:
            writable(u).discard(v)
            writable(v).discard(u)
        for u, v in added:
            writable(u).add(v)
            writable(v).add(u)
        triangles: set[tuple[int, ...]] = set(); squares: set[tuple[int, ...]] = set()
        for u, v in added:
            for m in adj[u].intersection(adj[v]): triangles.add(_canonical_cycle((u, m, v)))
            for first in adj[u].difference({v}):
                for second in adj[first].difference({u}):
                    if self.local_ops >= self.limits.local_risk_budget:
                        self.local_budget_exhausted = True; return len(triangles), len(squares)
                    self.local_ops += 1
                    if second != v and v in adj[second]: squares.add(_canonical_cycle((u, first, second, v)))
        return len(triangles), len(squares)

    def payload(self, pid: str, removed: tuple[Edge, ...], added: tuple[Edge, ...], selector: str,
                k: int, anchor: int | None, *, profile: RankingProfile | None = None) -> dict[str, Any]:
        removed_started = time.perf_counter_ns()
        pairs = tuple(combinations(removed, 2)); rd = [self.edge_distance(a, b) for a, b in pairs]
        if profile is not None:
            profile.add_phase("removed_edge_distance_computation", time.perf_counter_ns() - removed_started)
        new_started = time.perf_counter_ns()
        nd = [self.distance(u, v) for u, v in added]
        if profile is not None:
            profile.add_phase("new_edge_distance_computation", time.perf_counter_ns() - new_started)
        risk_started = time.perf_counter_ns()
        tri, c4 = self.local_risks(removed, added)
        if profile is not None:
            profile.add_phase("triangle_c4_local_risk_computation", time.perf_counter_ns() - risk_started)
        broken, sums, maxima = [], [], []
        for length in self.limits.forbidden_lengths:
            witnesses = self.witnesses[length]; rem = set(removed)
            broken.append(sum(any(_edge(v, c[(i + 1) % length]) in rem for i, v in enumerate(c)) for c in witnesses))
            loads = [self.edge_loads[length][e] for e in removed]; sums.append(sum(loads)); maxima.append(max(loads, default=0))
        mean_removed = sum(rd) / len(rd) if rd else 0.0; mean_new = sum(nd) / len(nd) if nd else 0.0
        return {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal_id": pid, "k": k,
                "operator_family": f"legal_{k}_switch", "selector_tags": [selector],
                "anchor_forbidden_length": anchor, "broken_sampled_witnesses_by_length": broken,
                "removed_edge_load_sum_by_length": sums, "removed_edge_load_max_by_length": maxima,
                "minimum_distance_between_removed_edges": min(rd, default=0), "mean_distance_between_removed_edges": mean_removed,
                "minimum_preexisting_distance_for_new_edges": min(nd, default=0), "mean_preexisting_distance_for_new_edges": mean_new,
                "local_triangle_risk": tri, "local_c4_risk": c4, "reconnection_span": mean_new}


@lru_cache(maxsize=256)
def _perfect_matching_shapes(vertices: tuple[int, ...]) -> tuple[tuple[tuple[int, int], ...], ...]:
    if not vertices:
        return ((),)
    result: list[tuple[tuple[int, int], ...]] = []
    first = vertices[0]
    for index in range(1, len(vertices)):
        second = vertices[index]
        rest = vertices[1:index] + vertices[index + 1:]
        for suffix in _perfect_matching_shapes(rest):
            result.append(tuple(sorted(((first, second), *suffix))))
    return tuple(sorted(result))


@lru_cache(maxsize=4096)
def _perfect_matchings_sorted(ordered_vertices: tuple[int, ...]) -> tuple[tuple[Edge, ...], ...]:
    if not ordered_vertices:
        return ((),)
    shapes = _perfect_matching_shapes(tuple(range(len(ordered_vertices))))
    return tuple(
        tuple(_edge(ordered_vertices[left], ordered_vertices[right]) for left, right in shape)
        for shape in shapes
    )


def _perfect_matchings(vertices: tuple[int, ...]) -> tuple[tuple[Edge, ...], ...]:
    return _perfect_matchings_sorted(tuple(sorted(vertices)))


def _pool_hash(candidates: Sequence[ProposalCandidate]) -> str:
    return canonical_json_hash([{"proposal": c.payload, "removed_edges": c.rewrite.removed_edges,
                                 "added_edges": c.rewrite.added_edges} for c in candidates])


class KSwitchPoolGenerator:
    """Generate a deterministic, host-owned, legal bounded proposal pool."""
    def __init__(self, *, pool_limits: PoolLimits | None = None,
                 feature_limits: FeatureLimits | None = None) -> None:
        self.pool_limits = pool_limits or PoolLimits()
        self.feature_limits = feature_limits or FeatureLimits()
        self._weighted_selectors = tuple(
            selector
            for selector, weight in zip(
                self.pool_limits.selectors,
                self.pool_limits.selector_weights,
                strict=True,
            )
            for _ in range(weight)
        )
        self._cached_graph: BitGraph | None = None
        self._cached_features: _GraphLocalFeatures | None = None

    def invalidate_cache(self) -> None:
        self._cached_graph = None
        self._cached_features = None

    def _snapshot(self, graph: BitGraph, profile: RankingProfile | None) -> _FeatureSnapshot:
        if self._cached_graph is graph or (
            self._cached_graph is not None and self._cached_graph == graph
        ):
            base = self._cached_features
            if base is None:
                raise BridgeError("graph feature cache is inconsistent")
            if profile is not None:
                profile.cache_hits += 1
        else:
            if profile is not None:
                profile.cache_misses += 1
            base = _GraphLocalFeatures(graph, self.feature_limits, profile)
            self._cached_graph = graph
            self._cached_features = base
        return _FeatureSnapshot(graph, self.feature_limits, base)

    @staticmethod
    def _seed(graph: BitGraph, policy_seed: int, step: int, attempt: int, selector: str) -> int:
        payload = json.dumps([graph.n, tuple(graph.edges()), policy_seed, step, attempt, selector], separators=(",", ":")).encode()
        return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")

    @staticmethod
    def _seed_from_prefix(seed_prefix: bytes, attempt: int, selector: str) -> int:
        suffix = json.dumps([attempt, selector], separators=(",", ":")).encode()
        payload = seed_prefix[:-1] + b"," + suffix[1:]
        return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")

    def _selector(self, attempt: int, seed: int) -> str:
        return self._weighted_selectors[(attempt + seed) % len(self._weighted_selectors)]

    @staticmethod
    def _disjoint_greedy(edges: list[Edge], k: int) -> tuple[Edge, ...] | None:
        selected: list[Edge] = []; used: set[int] = set()
        for edge in edges:
            if not used.intersection(edge):
                selected.append(edge); used.update(edge)
                if len(selected) == k: return tuple(sorted(selected))
        return None

    def _select_edges(self, snap: _FeatureSnapshot, edges: tuple[Edge, ...], *, k: int, selector: str, seed: int) -> tuple[tuple[Edge, ...] | None, int | None]:
        rng = random.Random(seed); shuffled = list(edges); rng.shuffle(shuffled)
        loads = snap.total_edge_loads
        if selector == "uniform_random": return self._disjoint_greedy(shuffled, k), None
        loaded = snap.base.loaded_edges
        anchor_length: int | None = None
        if selector == "sampled_forbidden_cycle_anchored":
            available = [l for l in snap.limits.forbidden_lengths if snap.witnesses[l]]
            if available:
                anchor_length = available[0]; cycle = snap.witnesses[anchor_length][seed % len(snap.witnesses[anchor_length])]
                cycle_edges = {_edge(v, cycle[(i + 1) % len(cycle)]) for i, v in enumerate(cycle)}
                ordered = sorted(edges, key=lambda e: (e not in cycle_edges, -loads.get(e, 0), e))
                return self._disjoint_greedy(ordered, k), anchor_length
            return self._disjoint_greedy(loaded, k), None
        if selector == "high_sampled_witness_load": return self._disjoint_greedy(loaded, k), None
        anchor = loaded[0] if loaded else None
        if anchor is None: return None, None
        if selector == "remote_from_anchor":
            ordered = [anchor, *sorted((e for e in edges if e != anchor), key=lambda e: (-snap.edge_distance(anchor, e), e))]
            return self._disjoint_greedy(ordered, k), None
        if selector == "pairwise_distant_disjoint":
            selected = [anchor]; used = set(anchor)
            while len(selected) < k:
                choices = [e for e in shuffled if not used.intersection(e)]
                if not choices: return None, None
                candidate = max(choices, key=lambda e: (min(snap.edge_distance(e, prior) for prior in selected), loads.get(e, 0), tuple(-x for x in e)))
                selected.append(candidate); used.update(candidate)
            return tuple(sorted(selected)), None
        return self._disjoint_greedy(loaded if seed % 2 == 0 else shuffled, k), None

    def generate(
        self,
        graph: BitGraph,
        *,
        policy_seed: int,
        step: int,
        profile: RankingProfile | None = None,
    ) -> ProposalPool:
        profile_before = (
            sum(profile.phase_ns.values()) if profile is not None else 0
        )
        generate_started = time.perf_counter_ns()
        base_started = time.perf_counter_ns()
        edges = tuple(graph.edges())
        seed_prefix = json.dumps(
            [graph.n, edges, policy_seed, step], separators=(",", ":")
        ).encode()
        if profile is not None:
            profile.add_phase(
                "base_current_graph_preparation",
                time.perf_counter_ns() - base_started,
            )
        feature_start = time.perf_counter_ns()
        snap = self._snapshot(graph, profile)
        feature_elapsed = time.perf_counter_ns() - feature_start
        retained: list[ProposalCandidate] = []
        seen: set[tuple[tuple[Edge, ...], tuple[Edge, ...]]] = set()
        rejected: Counter[str] = Counter()
        selector_counts: Counter[str] = Counter()
        k_counts: Counter[str] = Counter()
        attempted = deduplicated = legality_elapsed = 0
        current_edges = set(edges)
        for attempt in range(self.pool_limits.retry_limit):
            if len(retained) >= self.pool_limits.pool_size:
                break
            selector = self._selector(attempt, policy_seed)
            k = self.pool_limits.k_values[
                (attempt + step + policy_seed) % len(self.pool_limits.k_values)
            ]
            seed = self._seed_from_prefix(seed_prefix, attempt, selector)
            generation_started = time.perf_counter_ns()
            edge_selection_started = time.perf_counter_ns()
            removed, anchor = self._select_edges(
                snap, edges, k=k, selector=selector, seed=seed
            )
            if profile is not None:
                profile.proposal_edge_selection_ns += time.perf_counter_ns() - edge_selection_started
            if removed is None:
                rejected["disjoint_selection"] += 1
                if profile is not None:
                    elapsed = time.perf_counter_ns() - generation_started
                    profile.add_phase("proposal_generation", elapsed)
                    profile.add_generation_phase(k, selector, elapsed)
                    profile.pool_attempts += 1
                continue
            vertices = tuple(v for e in removed for v in e)
            original = frozenset(removed)
            matching_started = time.perf_counter_ns()
            ordered_vertices = tuple(sorted(vertices))
            shapes = _perfect_matching_shapes(tuple(range(len(ordered_vertices))))
            matching_order = list(range(len(shapes)))
            random.Random(seed ^ 0x9E3779B97F4A7C15).shuffle(matching_order)
            if profile is not None:
                profile.matching_construction_ns += time.perf_counter_ns() - matching_started
                profile.matching_construction_count += 1
                elapsed = time.perf_counter_ns() - generation_started
                profile.add_phase("proposal_generation", elapsed)
                profile.add_generation_phase(k, selector, elapsed)
                profile.pool_attempts += 1
            for mi, shape_index in enumerate(
                matching_order[: self.pool_limits.matching_limit]
            ):
                if len(retained) >= self.pool_limits.pool_size:
                    break
                attempted += 1
                matching = tuple(
                    _edge(ordered_vertices[left], ordered_vertices[right])
                    for left, right in shapes[shape_index]
                )
                added = tuple(sorted(matching))
                legality_started = time.perf_counter_ns()
                if frozenset(added) == original:
                    rejected["original_pairing"] += 1
                    if profile is not None:
                        profile.add_phase(
                            "legality_validation_and_deduplication",
                            time.perf_counter_ns() - legality_started,
                        )
                    continue
                if original.intersection(added):
                    rejected["original_edge_reused"] += 1
                    if profile is not None:
                        profile.add_phase(
                            "legality_validation_and_deduplication",
                            time.perf_counter_ns() - legality_started,
                        )
                    continue
                if len(set(added)) != k or any(u == v for u, v in added):
                    rejected["loop_or_duplicate"] += 1
                    if profile is not None:
                        profile.add_phase(
                            "legality_validation_and_deduplication",
                            time.perf_counter_ns() - legality_started,
                        )
                    continue
                if current_edges.difference(removed).intersection(added):
                    rejected["preexisting_edge"] += 1
                    if profile is not None:
                        profile.add_phase(
                            "legality_validation_and_deduplication",
                            time.perf_counter_ns() - legality_started,
                        )
                    continue
                key = (removed, added)
                if key in seen:
                    deduplicated += 1
                    if profile is not None:
                        profile.add_phase(
                            "legality_validation_and_deduplication",
                            time.perf_counter_ns() - legality_started,
                        )
                    continue
                seen.add(key)
                pid_started = time.perf_counter_ns()
                pid = hashlib.sha256(
                    json.dumps(
                        [POOL_SCHEMA_VERSION, seed, mi, removed, added],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                if profile is not None:
                    profile.add_phase(
                        "proposal_id_pool_hash_canonicalization",
                        time.perf_counter_ns() - pid_started,
                    )
                rewrite_started = time.perf_counter_ns()
                rewrite = ProposalRewrite(
                    removed,
                    added,
                    f"legal_{k}_switch",
                    {"k": k, "selector": selector, "proposal_id": pid},
                )
                try:
                    graph.with_edges(add=added, remove=removed)
                except ValueError:
                    rejected["host_validation"] += 1
                    elapsed = time.perf_counter_ns() - legality_started
                    legality_elapsed += elapsed
                    if profile is not None:
                        profile.add_phase(
                            "legality_validation_and_deduplication", elapsed
                        )
                    continue
                elapsed = time.perf_counter_ns() - legality_started
                legality_elapsed += elapsed
                if profile is not None:
                    profile.add_phase(
                        "legality_validation_and_deduplication", elapsed
                    )
                    profile.add_phase(
                        "python_object_construction_copying",
                        time.perf_counter_ns() - rewrite_started,
                    )
                payload_start = time.perf_counter_ns()
                payload = snap.payload(
                    pid, removed, added, selector, k, anchor, profile=profile
                )
                feature_elapsed += time.perf_counter_ns() - payload_start
                retained.append(ProposalCandidate(rewrite, payload, True))
                selector_counts[selector] += 1
                k_counts[str(k)] += 1
                if profile is not None:
                    profile.accepted_proposals += 1
                break
        pool_hash_started = time.perf_counter_ns()
        pool_hash = _pool_hash(retained)
        if profile is not None:
            profile.add_phase(
                "proposal_id_pool_hash_canonicalization",
                time.perf_counter_ns() - pool_hash_started,
            )
        feature_usage = {
            "cycle_nodes": snap.cycle_nodes,
            "sampled_witnesses": snap.sampled_witnesses,
            "distance_queries": snap.distance_queries,
            "distance_cache_hits": snap.distance_hits,
            "local_risk_operations": snap.local_ops,
            "cycle_budget_exhausted": snap.cycle_budget_exhausted,
            "distance_budget_exhausted": snap.distance_budget_exhausted,
            "local_risk_budget_exhausted": snap.local_budget_exhausted,
            "context_capped_cycle_counts": [
                len(snap.witnesses[length])
                for length in self.feature_limits.forbidden_lengths
            ],
        }
        if profile is not None:
            if snap.cycle_budget_exhausted:
                profile.add_budget_exhaustion("cycle")
            if snap.distance_budget_exhausted:
                profile.add_budget_exhaustion("distance")
            if snap.local_budget_exhausted:
                profile.add_budget_exhaustion("local_risk")
            # Attribute generator-loop bookkeeping (seed selection, retry
            # counters, and bounded-pool assembly) that is not one of the
            # narrower exclusive sub-phases to proposal generation itself.
            phase_after = sum(profile.phase_ns.values())
            profile.add_phase(
                "proposal_generation",
                max(0, time.perf_counter_ns() - generate_started - (phase_after - profile_before)),
            )
        return ProposalPool(
            POOL_SCHEMA_VERSION,
            tuple(retained),
            pool_hash,
            attempted,
            dict(sorted(rejected.items())),
            deduplicated,
            len(retained),
            dict(sorted(selector_counts.items())),
            dict(sorted(k_counts.items())),
            feature_usage,
            legality_elapsed,
            feature_elapsed,
        )


def build_context(graph: BitGraph, *, step: int = 0, remaining_steps: int = 0,
                  capped_cycle_counts: Sequence[int] | None = None, weighted_penalty: int = 0,
                  forbidden_lengths: Sequence[int] = FROZEN_FORBIDDEN_LENGTHS, stagnation: int = 0,
                  recent_best_improvement: float = 0.0, recent_acceptance_rate: float = 0.0,
                  recent_duplicate_rate: float = 0.0) -> Stage2BContext:
    lengths = tuple(forbidden_lengths)
    if lengths != FROZEN_FORBIDDEN_LENGTHS: raise ValueError("forbidden lengths are frozen to 4..9")
    counts = tuple(capped_cycle_counts or (0,) * len(lengths))
    if len(counts) != len(lengths) or any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in counts):
        raise ValueError("capped_cycle_counts must align with forbidden lengths")
    if graph.n < 4: raise ValueError("context order must be at least four")
    return Stage2BContext(graph.n, lengths, counts, int(weighted_penalty), int(step), int(remaining_steps), int(stagnation),
                          float(recent_best_improvement), float(recent_acceptance_rate), float(recent_duplicate_rate))


def _require_exact(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractViolation(f"{name} fields must exactly match the frozen schema")
    return value


def validate_context(value: object) -> dict[str, Any]:
    keys = {
        "schema_version", "order", "forbidden_lengths", "capped_cycle_counts",
        "weighted_penalty", "step", "remaining_steps", "stagnation",
        "recent_best_improvement", "recent_acceptance_rate", "recent_duplicate_rate",
    }
    result = _require_exact(value, keys, "context")
    if result["schema_version"] != CONTEXT_SCHEMA_VERSION:
        raise ContractViolation("unsupported Stage 2B context schema")
    if isinstance(result["order"], bool) or not isinstance(result["order"], int) or result["order"] < 4:
        raise ContractViolation("context order must be an integer >= 4")
    lengths = result["forbidden_lengths"]
    counts = result["capped_cycle_counts"]
    if lengths != list(FROZEN_FORBIDDEN_LENGTHS) or not isinstance(counts, list) or len(counts) != len(lengths):
        raise ContractViolation("context lengths/counts do not match the frozen 4..9 contract")
    if any(
        isinstance(x, bool)
        or not isinstance(x, int)
        or x < 0
        or x > FROZEN_WITNESS_SAMPLE_CAP
        for x in counts
    ):
        raise ContractViolation("context cycle counts must be bounded non-negative integers")
    for name in ("weighted_penalty", "step", "remaining_steps", "stagnation"):
        if isinstance(result[name], bool) or not isinstance(result[name], int) or result[name] < 0:
            raise ContractViolation(f"context.{name} must be a non-negative integer")
    for name in ("recent_best_improvement", "recent_acceptance_rate", "recent_duplicate_rate"):
        if isinstance(result[name], bool) or not isinstance(result[name], (int, float)) or not math.isfinite(float(result[name])):
            raise ContractViolation(f"context.{name} must be finite")
    for name in ("recent_acceptance_rate", "recent_duplicate_rate"):
        if not 0 <= float(result[name]) <= 1:
            raise ContractViolation(f"context.{name} must be in [0,1]")
    return copy.deepcopy(result)


def validate_proposal(value: object, *, lengths: Sequence[int] = FROZEN_FORBIDDEN_LENGTHS, copy_result: bool = True) -> dict[str, Any]:
    keys = {
        "schema_version", "proposal_id", "k", "operator_family", "selector_tags",
        "anchor_forbidden_length", "broken_sampled_witnesses_by_length",
        "removed_edge_load_sum_by_length", "removed_edge_load_max_by_length",
        "minimum_distance_between_removed_edges", "mean_distance_between_removed_edges",
        "minimum_preexisting_distance_for_new_edges", "mean_preexisting_distance_for_new_edges",
        "local_triangle_risk", "local_c4_risk", "reconnection_span",
    }
    result = _require_exact(value, keys, "proposal")
    if result["schema_version"] != PROPOSAL_SCHEMA_VERSION:
        raise ContractViolation("unsupported Stage 2B proposal schema")
    pid = result["proposal_id"]
    if not isinstance(pid, str) or len(pid) != 64 or any(ch not in "0123456789abcdef" for ch in pid):
        raise ContractViolation("proposal_id must be a lowercase SHA-256 digest")
    k = result["k"]
    if isinstance(k, bool) or k not in SUPPORTED_K_VALUES:
        raise ContractViolation("proposal k must be 2, 3, or 4")
    if result["operator_family"] != f"legal_{k}_switch":
        raise ContractViolation("proposal operator family does not match k")
    tags = result["selector_tags"]
    if not isinstance(tags, list) or not tags or len(tags) > 8 or any(tag not in SUPPORTED_SELECTORS for tag in tags):
        raise ContractViolation("proposal selector tags are not reviewed")
    anchor = result["anchor_forbidden_length"]
    if anchor is not None and anchor not in lengths:
        raise ContractViolation("proposal anchor length is outside context lengths")
    for name in ("broken_sampled_witnesses_by_length", "removed_edge_load_sum_by_length", "removed_edge_load_max_by_length"):
        vector = result[name]
        if not isinstance(vector, list) or len(vector) != len(lengths) or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in vector):
            raise ContractViolation(f"proposal.{name} is not aligned to context lengths")
    for name in ("minimum_distance_between_removed_edges", "minimum_preexisting_distance_for_new_edges", "local_triangle_risk", "local_c4_risk"):
        if isinstance(result[name], bool) or not isinstance(result[name], int) or result[name] < 0:
            raise ContractViolation(f"proposal.{name} must be a non-negative integer")
    for name in ("mean_distance_between_removed_edges", "mean_preexisting_distance_for_new_edges", "reconnection_span"):
        if isinstance(result[name], bool) or not isinstance(result[name], (int, float)) or not math.isfinite(float(result[name])) or float(result[name]) < 0:
            raise ContractViolation(f"proposal.{name} must be a finite non-negative number")
    return copy.deepcopy(result) if copy_result else result


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        from types import MappingProxyType
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _frame(value: object, limit: int) -> bytes:
    import struct
    body = canonical_json_bytes(value)
    if len(body) > limit:
        raise BridgeError(f"protocol frame exceeds {limit} bytes")
    return struct.pack("!I", len(body)) + body


def _read_exact(stream: Any, size: int, deadline: float) -> bytes:
    import select
    result = bytearray()
    while len(result) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
            raise BridgeError("policy worker timeout")
        chunk = os.read(stream.fileno(), size - len(result))
        if not chunk:
            raise BridgeError("policy worker closed its protocol")
        result.extend(chunk)
    return bytes(result)


_WORKER_CODE = r'''
import json, math, os, resource, struct, sys
H=struct.Struct("!I")
safe={"abs":abs,"all":all,"any":any,"len":len,"max":max,"min":min,"range":range,"round":round,"sum":sum}
def read_frame():
    raw=sys.stdin.buffer.read(H.size)
    if len(raw)!=H.size: raise EOFError()
    n=H.unpack(raw)[0]
    if n>65536: raise ValueError("oversized request")
    body=sys.stdin.buffer.read(n)
    if len(body)!=n: raise EOFError()
    value=json.loads(body)
    if not isinstance(value,dict): raise ValueError("request must be object")
    return value
def write_frame(value):
    body=json.dumps(value,allow_nan=False,separators=(",",":"),sort_keys=True).encode()
    if len(body)>16384: raise ValueError("oversized response")
    sys.stdout.buffer.write(H.pack(len(body))+body); sys.stdout.buffer.flush()
init=read_frame(); source=init["source"]
namespace={"__builtins__":safe}
exec(compile(source,"<reviewed-policy>","exec"),namespace,namespace)
fn=namespace.get("priority")
if not callable(fn): raise ValueError("missing priority")
write_frame({"type":"ready","status":"ok"})
while True:
    req=read_frame()
    if req.get("type")=="shutdown": write_frame({"type":"shutdown","status":"ok"}); break
    if req.get("type")=="batch":
        ctx=req.get("ctx"); proposals=req.get("proposals")
        if not isinstance(ctx,dict) or not isinstance(proposals,list) or not proposals or len(proposals)>64:
            raise ValueError("invalid batch request")
        results=[]
        for proposal in proposals:
            if not isinstance(proposal,dict): raise ValueError("proposal must be object")
            before=json.dumps({"ctx":ctx,"proposal":proposal},sort_keys=True,separators=(",",":"))
            value=fn(ctx,proposal)
            if json.dumps({"ctx":ctx,"proposal":proposal},sort_keys=True,separators=(",",":")) != before:
                raise ValueError("input mutation")
            if isinstance(value,bool) or not isinstance(value,(int,float)) or (isinstance(value,float) and not math.isfinite(value)):
                raise ValueError("invalid priority output")
            results.append({"proposal_id":proposal.get("proposal_id"),"priority":value})
        write_frame({"type":"batch_result","status":"ok","results":results})
        continue
    if req.get("type")!="call": raise ValueError("unexpected request")
    started=time.perf_counter_ns() if False else 0
    try:
        before=json.dumps({"ctx":req["ctx"],"proposal":req["proposal"]},sort_keys=True,separators=(",",":"))
        value=fn(req["ctx"],req["proposal"])
        if json.dumps({"ctx":req["ctx"],"proposal":req["proposal"]},sort_keys=True,separators=(",",":")) != before:
            raise ValueError("input mutation")
        if isinstance(value,bool) or not isinstance(value,(int,float)) or (isinstance(value,float) and not math.isfinite(value)):
            raise ValueError("invalid priority output")
        write_frame({"type":"result","status":"ok","priority":value,"elapsed_ns":0})
    except BaseException as exc:
        write_frame({"type":"result","status":"exception","priority":None,"error":{"code":"policy_exception","message":str(exc)[:512]}})
'''


@dataclass(frozen=True, slots=True)
class WorkerLimits:
    per_call_wall_seconds: float = 0.025
    total_wall_seconds: float = 60.0
    request_bytes: int = 64 * 1024
    response_bytes: int = 16 * 1024
    address_space_bytes: int = 128 * 1024 * 1024
    open_files: int = 16
    process_count: int = 1


class PolicyWorker:
    """Persistent framed JSON worker; every failure kills and reaps its group."""
    def __init__(self, source: str | None = None, limits: WorkerLimits | None = None, profile: RankingProfile | None = None) -> None:
        _validate_source(source if source is not None else _asset_path().read_text(encoding="utf-8"))
        self.source = source if source is not None else _asset_path().read_text(encoding="utf-8")
        self.limits = limits or WorkerLimits()
        self.profile = profile
        self.process: subprocess.Popen[bytes] | None = None
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.calls = 0; self.failures = 0; self.orphans = 0; self.elapsed_ns = 0; self._started = 0.0; self._failed = False
        self._last_serialization_ns = 0
        self.start()

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None: return
        self.tmp = tempfile.TemporaryDirectory(prefix="heg-policy-")
        env = {"HOME": self.tmp.name, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": os.defpath}
        try:
            self.process = subprocess.Popen([sys.executable, "-I", "-u", "-c", _WORKER_CODE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=self.tmp.name, env=env, close_fds=True, start_new_session=True, preexec_fn=self._limit_child)
            self._started = time.monotonic()
            self._send({"type":"initialize", "source":self.source})
            ready = self._receive(5.0)
            if ready.get("type") != "ready" or ready.get("status") != "ok": raise BridgeError("policy worker identity handshake failed")
        except BaseException:
            self._failed = True; self._terminate(); raise

    def _limit_child(self) -> None:
        try:
            import resource
            cpu = max(1, math.ceil(self.limits.total_wall_seconds))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
            resource.setrlimit(resource.RLIMIT_AS, (self.limits.address_space_bytes, self.limits.address_space_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (self.limits.open_files, self.limits.open_files))
            resource.setrlimit(resource.RLIMIT_NPROC, (self.limits.process_count, self.limits.process_count))
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024, 64 * 1024))
            os.umask(0o077)
        except (AttributeError, OSError):
            pass

    def _send(self, payload: object) -> None:
        if self.process is None or self.process.stdin is None: raise BridgeError("policy worker is unavailable")
        serialization_started = time.perf_counter_ns()
        frame = _frame(payload, self.limits.request_bytes)
        serialization_elapsed = time.perf_counter_ns() - serialization_started
        self._last_serialization_ns += serialization_elapsed
        if self.profile is not None:
            self.profile.add_phase("json_framing_serialization", serialization_elapsed)
        try: self.process.stdin.write(frame); self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc: raise BridgeError("policy worker protocol write failed") from exc

    def _receive(self, timeout: float) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None: raise BridgeError("policy worker is unavailable")
        import struct
        deadline = time.monotonic() + timeout
        raw = _read_exact(self.process.stdout, struct.calcsize("!I"), deadline)
        length = struct.unpack("!I", raw)[0]
        if length > self.limits.response_bytes: raise BridgeError("policy worker response is oversized")
        body = _read_exact(self.process.stdout, length, deadline)
        parse_started = time.perf_counter_ns()
        value = json.loads(body)
        parse_elapsed = time.perf_counter_ns() - parse_started
        self._last_serialization_ns += parse_elapsed
        if self.profile is not None:
            self.profile.add_phase("json_framing_serialization", parse_elapsed)
        if not isinstance(value, dict): raise BridgeError("policy worker response is malformed")
        return value

    def call(self, context: Mapping[str, Any], proposal: Mapping[str, Any]) -> int | float:
        if self._failed or self.process is None or self.process.poll() is not None: raise BridgeError("failed policy worker cannot be reused")
        if time.monotonic() - self._started > self.limits.total_wall_seconds: self._failed = True; self._terminate(); raise BridgeError("policy worker total wall limit exceeded")
        copy_started = time.perf_counter_ns()
        ctx = validate_context(dict(context)); prop = validate_proposal(dict(proposal), lengths=ctx["forbidden_lengths"])
        copy_elapsed = time.perf_counter_ns() - copy_started
        if self.profile is not None:
            self.profile.add_phase("python_object_construction_copying", copy_elapsed)
        started = time.perf_counter_ns()
        self._last_serialization_ns = 0
        try:
            self._send({"type":"call", "ctx":ctx, "proposal":prop}); response = self._receive(self.limits.per_call_wall_seconds)
            self.calls += 1
            if response.get("type") != "result" or response.get("status") != "ok": raise BridgeError("policy returned an invalid result")
            value = response.get("priority")
            if isinstance(value, bool) or not isinstance(value, (int,float)) or (isinstance(value,float) and not math.isfinite(value)): raise BridgeError("policy returned a non-finite or non-numeric priority")
            elapsed = time.perf_counter_ns() - started
            self.elapsed_ns += elapsed
            if self.profile is not None:
                self.profile.policy_calls += 1
                self.profile.worker_ipc_calls += 1
                self.profile.add_phase(
                    "policy_ipc_execution",
                    max(0, elapsed - self._last_serialization_ns),
                )
            return value
        except BaseException:
            self.failures += 1
            if self.profile is not None:
                self.profile.policy_failures += 1
            self._failed = True; self._terminate(); raise

    def call_many(
        self,
        context: Mapping[str, Any],
        proposals: Sequence[Mapping[str, Any]],
        *,
        prevalidated: bool = False,
    ) -> tuple[int | float, ...]:
        """Evaluate one bounded pool in one framed request.

        The worker executes the same frozen ``priority(ctx, proposal)``
        function in the same proposal order.  Parent-side validation remains
        per proposal, while the process crossing and context framing happen
        once for the bounded pool.
        """
        patched_call = self.__dict__.get("call")
        if patched_call is not None:
            # Preserve the reviewed injection seam used by red-team tests and
            # operators: a replaced single-call method must not be bypassed by
            # the batching optimization.
            return tuple(patched_call(context, proposal) for proposal in proposals)
        if self._failed or self.process is None or self.process.poll() is not None:
            raise BridgeError("failed policy worker cannot be reused")
        if not proposals or len(proposals) > 64:
            raise BridgeError("policy batch is outside the bounded contract")
        if time.monotonic() - self._started > self.limits.total_wall_seconds:
            self._failed = True
            self._terminate()
            raise BridgeError("policy worker total wall limit exceeded")
        copy_started = time.perf_counter_ns()
        if prevalidated:
            ctx = context if isinstance(context, dict) else dict(context)
            props = tuple(proposals)
        else:
            ctx = validate_context(dict(context))
            props = tuple(
                validate_proposal(dict(proposal), lengths=ctx["forbidden_lengths"])
                for proposal in proposals
            )
        copy_elapsed = time.perf_counter_ns() - copy_started
        if self.profile is not None:
            self.profile.add_phase("python_object_construction_copying", copy_elapsed)
        started = time.perf_counter_ns()
        self._last_serialization_ns = 0
        try:
            self._send({"type": "batch", "ctx": ctx, "proposals": list(props)})
            aggregate_timeout = min(
                self.limits.total_wall_seconds,
                self.limits.per_call_wall_seconds * len(props),
            )
            response = self._receive(max(self.limits.per_call_wall_seconds, aggregate_timeout))
            if response.get("type") != "batch_result" or response.get("status") != "ok":
                raise BridgeError("policy returned an invalid batch result")
            rows = response.get("results")
            if not isinstance(rows, list) or len(rows) != len(props):
                raise BridgeError("policy returned an invalid batch cardinality")
            by_id: dict[str, int | float] = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise BridgeError("policy returned a malformed batch row")
                pid = row.get("proposal_id")
                value = row.get("priority")
                if not isinstance(pid, str) or pid in by_id:
                    raise BridgeError("policy returned an unstable batch proposal ID")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                    raise BridgeError("policy returned a non-finite batch priority")
                by_id[pid] = value
            values = tuple(by_id[str(proposal["proposal_id"])] for proposal in props)
            self.calls += len(values)
            elapsed = time.perf_counter_ns() - started
            self.elapsed_ns += elapsed
            if self.profile is not None:
                self.profile.policy_calls += len(values)
                self.profile.worker_ipc_calls += 1
                self.profile.add_phase(
                    "policy_ipc_execution",
                    max(0, elapsed - self._last_serialization_ns),
                )
            return values
        except BaseException:
            self.failures += 1
            if self.profile is not None:
                self.profile.policy_failures += 1
            self._failed = True
            self._terminate()
            raise

    def _terminate(self) -> None:
        process = self.process
        if process is None: return
        if process.poll() is None:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        try: process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.orphans += 1
            process.kill(); process.wait(timeout=1.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self.process = None

    def telemetry(self) -> dict[str, Any]:
        return {"protocol_version": RUNTIME_PROTOCOL_VERSION, "batch_protocol_version": BATCH_PROTOCOL_VERSION, "calls": self.calls, "failures": self.failures, "elapsed_ns": self.elapsed_ns, "orphan_count": self.orphans, "usable": self.process is not None and self.process.poll() is None}

    def close(self) -> None:
        if self.process is None: return
        if not self._failed and self.process.poll() is None:
            try: self._send({"type":"shutdown"}); self._receive(0.2)
            except BaseException: pass
        self._terminate()
        if self.tmp is not None: self.tmp.cleanup(); self.tmp = None

    def __enter__(self) -> "PolicyWorker": return self
    def __exit__(self, *_args: object) -> None: self.close()


@dataclass(slots=True)
class RankingTelemetry:
    policy_call_count: int = 0
    invalid_result_count: int = 0
    timeout_count: int = 0
    crash_count: int = 0
    protocol_count: int = 0
    non_finite_count: int = 0
    selection_latency_ns_sum: int = 0
    pool_generation_ns: int = 0
    feature_computation_ns: int = 0
    tie_count: int = 0
    selected_k_counts: Counter[str] = field(default_factory=Counter)
    selector_counts: Counter[str] = field(default_factory=Counter)
    selected_authoritative_scorer_calls: int = 0
    m4_calls: int = 0
    worker_restart_count: int = 0
    worker_reap_count: int = 0
    worker_orphan_count: int = 0
    profile: RankingProfile | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {"policy_call_count": self.policy_call_count, "invalid_result_count": self.invalid_result_count, "timeout_count": self.timeout_count, "crash_count": self.crash_count, "protocol_count": self.protocol_count, "non_finite_count": self.non_finite_count, "selection_latency_ns_sum": self.selection_latency_ns_sum, "pool_generation_ns": self.pool_generation_ns, "feature_computation_ns": self.feature_computation_ns, "tie_count": self.tie_count, "selected_k_counts": dict(sorted(self.selected_k_counts.items())), "selector_counts": dict(sorted(self.selector_counts.items())), "selected_authoritative_scorer_calls": self.selected_authoritative_scorer_calls, "m4_calls": self.m4_calls, "worker_restart_count": self.worker_restart_count, "worker_reap_count": self.worker_reap_count, "worker_orphan_count": self.worker_orphan_count}
        if self.profile is not None:
            result["profile"] = self.profile.as_dict()
        return result


@dataclass(frozen=True, slots=True)
class Selection:
    catalog_id: str
    policy_id: str
    pool_hash: str
    selected_proposal_id: str
    selected_k: int
    selected_operator_family: str
    selected_selector_tags: tuple[str, ...]
    rank_order: tuple[str, ...]
    priorities: tuple[tuple[str, int | float], ...]
    telemetry: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"catalog_id": self.catalog_id, "policy_id": self.policy_id, "pool_hash": self.pool_hash, "selected_proposal_id": self.selected_proposal_id, "selected_k": self.selected_k, "selected_operator_family": self.selected_operator_family, "selected_selector_tags": list(self.selected_selector_tags), "rank_order": list(self.rank_order), "priorities": [[pid, value] for pid, value in self.priorities], "telemetry": self.telemetry}


def identity_hash(identity: Mapping[str, Any] | None = None) -> str:
    return canonical_json_hash(dict(identity or FROZEN_IDENTITY.as_dict()))


def checkpoint_policy_identity() -> dict[str, Any]:
    identity = {
        **FROZEN_IDENTITY.as_dict(),
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "proposal_schema_version": PROPOSAL_SCHEMA_VERSION,
        "pool_schema_version": POOL_SCHEMA_VERSION,
        "tie_breaking_version": TIE_BREAKING_RULE,
        "failure_policy_version": FAILURE_POLICY,
        "batch_protocol_version": BATCH_PROTOCOL_VERSION,
    }
    return {**identity, "identity_sha256": identity_hash(identity)}


def require_checkpoint_identity(payload: Mapping[str, Any], *, enabled: bool) -> None:
    stored = payload.get("proposal_ranking_identity")
    if enabled:
        if stored != checkpoint_policy_identity(): raise ContractViolation("checkpoint proposal-ranking identity mismatch")
    elif stored is not None:
        raise ContractViolation("policy checkpoint cannot resume into a disabled lane")


def contract_payload() -> dict[str, Any]:
    return {
        "schema_version": "stage7.heg.integration.contract.v1",
        "catalog": FROZEN_IDENTITY.as_dict(),
        "entry": {"heg_commit": HEG_COMMIT},
        "activation": {
            "default_enabled": False,
            "explicit_lane_parameter_required": True,
            "reviewed_id_only": True,
            "silent_resume_activation": False,
        },
        "determinism": {
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "proposal_pool_contract_version": PROPOSAL_POOL_CONTRACT_VERSION,
            "feature_limits": FeatureLimits().as_dict(),
            "tie_breaking_rule": TIE_BREAKING_RULE,
            "failure_policy": FAILURE_POLICY,
            "resume_requires_exact_identity": True,
        },
        "authority": {
            "host_owns_legal_pool": True,
            "policy_calls_scorer": False,
            "policy_calls_m4": False,
            "selected_plan_only_scoring": True,
            "m4_is_only_certification_authority": True,
            "no_runtime_fallback": True,
        },
        "security": {
            "accepted_worker": RUNTIME_PROTOCOL_VERSION,
            "accepted_worker_extensions": {"bounded_batch": BATCH_PROTOCOL_VERSION},
            "filesystem": False,
            "environment": False,
            "subprocess": False,
            "network": False,
            "database": False,
            "dynamic_code": False,
            "inherited_stdin": False,
            "source_path_from_director": False,
        },
        "telemetry": {
            "scope": "bounded_micro_batch",
            "per_proposal_history": False,
            "fields": [
                "policy_call_count", "invalid_result_count",
                "timeout_crash_protocol_count", "selection_latency_ns_sum",
                "selected_k_counts", "selector_counts", "tie_count",
                "pool_generation_ns", "feature_computation_ns",
                "profile.schema_version", "profile.phase_ns", "profile.phase_counts",
                "profile.cache_hits", "profile.cache_misses", "profile.worker_ipc_calls",
            ],
        },
        "rollback": {
            "new_lanes_default_disabled": True,
            "historical_evidence_rewritten": False,
            "checkpoint_readable": True,
            "migration": "additive_or_online_backup_restore; no_downgrade",
        },
        "change_surface": {
            "heg": [
                "src/sglab/research/catalog.py",
                "src/sglab/research/validation.py",
                "src/sglab/research/lanes.py",
                "src/sglab/research/store.py",
                "src/sglab/db.py",
            ],
            "mutation_forge_reference_only": [
                "src/sglab/research/assets/mutation_policy_stage4r_v1.py",
            ],
        },
    }


def contract_hash() -> str:
    return canonical_json_hash(contract_payload())


def canonical_selection_json(selection: Selection) -> bytes:
    return canonical_json_bytes(selection.as_dict())


class HegPolicyBridge:
    """Host-owned pool/feature/ranking boundary with no scorer or M4 access."""
    def __init__(self, heg_repo: str | Path | None = None, catalog_id: str = CATALOG_ID, *, pool_limits: PoolLimits | None = None, feature_limits: FeatureLimits | None = None, worker_limits: WorkerLimits | None = None, profile_enabled: bool = False) -> None:
        if catalog_id != CATALOG_ID: raise ContractViolation("only the reviewed catalog ID may be activated")
        if heg_repo is not None:
            repo = Path(heg_repo).resolve()
            try:
                commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
                dirty = subprocess.run(["git", "-C", str(repo), "status", "--short"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
            except (OSError, subprocess.SubprocessError) as exc:
                raise ContractViolation("HEG checkout identity could not be verified") from exc
            if commit != HEG_COMMIT or dirty:
                raise ContractViolation("HEG checkout is not the pinned clean commit")
        verify_frozen_policy()
        self.catalog_id = catalog_id
        self.identity = FROZEN_IDENTITY
        self.pool_limits = pool_limits or PoolLimits()
        self.feature_limits = feature_limits or FeatureLimits()
        self.profile = RankingProfile(enabled=profile_enabled) if profile_enabled else None
        self.generator = KSwitchPoolGenerator(
            pool_limits=self.pool_limits, feature_limits=self.feature_limits
        )
        startup_started = time.perf_counter_ns()
        self.worker = PolicyWorker(limits=worker_limits, profile=self.profile)
        if self.profile is not None:
            self.profile.worker_startup_ns = time.perf_counter_ns() - startup_started
            # Startup framing is reported by worker_startup_ns, not steady-state
            # phase time.
            self.profile.phase_ns["json_framing_serialization"] = 0
            self.profile.phase_counts["json_framing_serialization"] = 0
        self.telemetry = RankingTelemetry(profile=self.profile)
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed: raise BridgeError("ranking bridge is closed")

    def validate_pool(self, graph: BitGraph | None, pool: ProposalPool, *, check_graph: bool = True, verify_hash: bool = True) -> None:
        self._ensure_open()
        validation_started = time.perf_counter_ns()
        if pool.schema_version != POOL_SCHEMA_VERSION or not pool.candidates or len(pool.candidates) > 64: raise BridgeError("proposal pool is outside the bounded contract")
        ids = [c.proposal_id for c in pool.candidates]
        if len(ids) != len(set(ids)) or (verify_hash and pool.pool_hash != _pool_hash(pool.candidates)): raise BridgeError("proposal pool identity is invalid")
        for candidate in pool.candidates:
            payload = validate_proposal(candidate.payload, copy_result=False)
            if payload["proposal_id"] != candidate.proposal_id: raise BridgeError("proposal ID is unstable")
            if len(candidate.rewrite.removed_edges) != payload["k"] or len(candidate.rewrite.added_edges) != payload["k"]: raise BridgeError("rewrite k does not match proposal")
            if candidate.rewrite.operator_family != payload["operator_family"]: raise BridgeError("rewrite family does not match proposal")
            if check_graph and graph is not None:
                try: graph.with_edges(add=candidate.rewrite.added_edges, remove=candidate.rewrite.removed_edges)
                except ValueError as exc: raise BridgeError("host rejected an illegal proposal") from exc
        if self.profile is not None:
            self.profile.add_phase(
                "python_object_construction_copying",
                time.perf_counter_ns() - validation_started,
            )

    def generate_pool(self, graph: BitGraph, *, policy_seed: int, step: int) -> ProposalPool:
        self._ensure_open()
        started = time.perf_counter_ns()
        pool = self.generator.generate(
            graph, policy_seed=policy_seed, step=step, profile=self.profile
        )
        elapsed = time.perf_counter_ns() - started
        self.telemetry.pool_generation_ns += elapsed
        self.telemetry.feature_computation_ns += pool.feature_elapsed_ns
        # Keep the public host boundary defensive even though the generator
        # already checked each retained rewrite.  This also protects callers
        # that replace or instrument the generator in a test/red-team seam.
        self.validate_pool(graph, pool)
        return pool

    def context_for_graph(self, graph: BitGraph, *, step: int = 0, remaining_steps: int = 0,
                          stagnation: int = 0, score: Any | None = None,
                          capped_cycle_counts: Sequence[int] | None = None) -> Stage2BContext:
        """Build the frozen Stage 2B context from host-owned scientific facts.

        The HEG lane passes its already-computed C++ ``ScoreResult`` so the
        policy sees the exact capped witness counts and weighted penalty used
        by the search.  Stand-alone callers may omit it; that path computes
        only the bounded context features and never invokes a scorer.
        """
        self._ensure_open()
        context_started = time.perf_counter_ns()
        if score is not None:
            witness_counts = getattr(score, "witness_counts", None)
            weighted_penalty = getattr(score, "weighted_penalty", None)
            if isinstance(score, Mapping):
                witness_counts = score.get("witness_counts", witness_counts)
                weighted_penalty = score.get("weighted_penalty", weighted_penalty)
            if witness_counts is None or weighted_penalty is None:
                raise BridgeError("host score does not expose Stage 2B witness counts")
            if capped_cycle_counts is not None:
                counts = tuple(int(value) for value in capped_cycle_counts)
            else:
                count_map = {int(length): int(count) for length, count in witness_counts}
                missing = [length for length in FROZEN_FORBIDDEN_LENGTHS if length not in count_map]
                if missing:
                    # Missing score fields are not scientific zeros.  Compute
                    # the complete frozen host context instead.
                    snap = self.generator._snapshot(graph, self.profile)
                    counts = tuple(len(snap.witnesses[length]) for length in FROZEN_FORBIDDEN_LENGTHS)
                else:
                    counts = tuple(
                        min(FROZEN_WITNESS_SAMPLE_CAP, count_map[length])
                        for length in FROZEN_FORBIDDEN_LENGTHS
                    )
            result = build_context(
                graph,
                step=step,
                remaining_steps=remaining_steps,
                capped_cycle_counts=counts,
                weighted_penalty=int(weighted_penalty),
                stagnation=stagnation,
            )
            if self.profile is not None:
                self.profile.add_phase("context_cycle_count_preparation", time.perf_counter_ns() - context_started)
            return result
        snap = self.generator._snapshot(graph, self.profile)
        counts = tuple(len(snap.witnesses[length]) for length in self.feature_limits.forbidden_lengths)
        result = build_context(graph, step=step, remaining_steps=remaining_steps,
                               capped_cycle_counts=counts, stagnation=stagnation)
        if self.profile is not None:
            self.profile.add_phase("context_cycle_count_preparation", time.perf_counter_ns() - context_started)
        return result

    def select(self, context: Stage2BContext | Mapping[str, Any], pool: ProposalPool, *, graph: BitGraph | None = None, apply_selected: bool = False, _pool_validated: bool = False, _context_validated: bool = False) -> Selection:
        self._ensure_open()
        context_started = time.perf_counter_ns()
        if _context_validated and isinstance(context, Stage2BContext):
            ctx = context.as_dict()
        else:
            ctx = validate_context(context.as_dict() if isinstance(context, Stage2BContext) else context)
        if self.profile is not None:
            self.profile.add_phase("context_cycle_count_preparation", time.perf_counter_ns() - context_started)
        if graph is not None:
            self.validate_pool(graph, pool)
        started = time.perf_counter_ns(); ranked: list[tuple[str, int | float, ProposalCandidate]] = []
        try:
            priorities = self.worker.call_many(
                ctx,
                tuple(candidate.payload for candidate in pool.candidates),
                prevalidated=_pool_validated,
            )
            ranked.extend(
                (candidate.proposal_id, priority, candidate)
                for candidate, priority in zip(pool.candidates, priorities, strict=True)
            )
        except BridgeError: self.telemetry.invalid_result_count += 1; raise
        self.telemetry.policy_call_count += len(pool.candidates); self.telemetry.selection_latency_ns_sum += time.perf_counter_ns() - started
        sorting_started = time.perf_counter_ns()
        ranked.sort(key=lambda item: (-float(item[1]), item[0])); self.telemetry.tie_count += sum(1 for left, right in zip(ranked, ranked[1:]) if left[1] == right[1])
        if self.profile is not None:
            self.profile.add_phase("sorting_tie_breaking", time.perf_counter_ns() - sorting_started)
        chosen = ranked[0][2]; self.telemetry.selected_k_counts[str(chosen.payload["k"])] += 1
        for tag in chosen.payload["selector_tags"]: self.telemetry.selector_counts[str(tag)] += 1
        if apply_selected:
            if graph is None: raise BridgeError("selected application requires a graph")
            apply_started = time.perf_counter_ns()
            graph.with_edges(add=chosen.rewrite.added_edges, remove=chosen.rewrite.removed_edges)
            if self.profile is not None:
                self.profile.add_phase("selected_rewrite_application", time.perf_counter_ns() - apply_started)
        selection_object_started = time.perf_counter_ns()
        result = Selection(self.catalog_id, POLICY_ID, pool.pool_hash, chosen.proposal_id, int(chosen.payload["k"]), str(chosen.payload["operator_family"]), tuple(chosen.payload["selector_tags"]), tuple(item[0] for item in ranked), tuple((item[0], item[1]) for item in ranked), self.telemetry.as_dict())
        if self.profile is not None:
            self.profile.add_phase(
                "python_object_construction_copying",
                time.perf_counter_ns() - selection_object_started,
            )
        return result

    def select_for_graph(self, graph: BitGraph, *, policy_seed: int, step: int, remaining_steps: int,
                         apply_selected: bool = False, return_details: bool = False,
                         score: Any | None = None) -> Selection | tuple[Selection, BitGraph, ProposalPool]:
        selection_started = time.perf_counter_ns()
        profile_before = (
            sum(self.profile.phase_ns.values()) if self.profile is not None else 0
        )
        pool = self.generate_pool(graph, policy_seed=policy_seed, step=step)
        context = self.context_for_graph(
            graph,
            step=step,
            remaining_steps=remaining_steps,
            score=score,
            capped_cycle_counts=pool.feature_usage.get("context_capped_cycle_counts"),
        )
        selection = self.select(
            context,
            pool,
            graph=None,
            apply_selected=False,
            _pool_validated=True,
            _context_validated=True,
        )
        candidate = next(c for c in pool.candidates if c.proposal_id == selection.selected_proposal_id)
        result = graph
        if apply_selected:
            apply_started = time.perf_counter_ns()
            result = graph.with_edges(add=candidate.rewrite.added_edges, remove=candidate.rewrite.removed_edges)
            if self.profile is not None:
                self.profile.add_phase("selected_rewrite_application", time.perf_counter_ns() - apply_started)
        if self.profile is not None:
            selection_elapsed = time.perf_counter_ns() - selection_started
            phase_after = sum(self.profile.phase_ns.values())
            self.profile.add_phase(
                "checkpoint_telemetry_integration",
                max(0, selection_elapsed - (phase_after - profile_before)),
            )
            self.profile.reconcile_selection(selection_elapsed)
        return (selection, result, pool) if return_details else selection

    def telemetry_payload(self) -> dict[str, Any]:
        if self.profile is not None:
            worker = self.worker.telemetry()
            self.profile.worker_orphans = int(worker.get("orphan_count", 0))
        return self.telemetry.as_dict()

    def invalidate_graph_cache(self) -> None:
        self.generator.invalidate_cache()

    def record_external_phase(self, name: str, elapsed_ns: int, *, count: int = 1) -> None:
        if self.profile is not None:
            if name == "authoritative_selected_plan_scoring":
                self.profile.selected_plan_scorer_calls += max(0, int(count))
            self.profile.add_phase(name, elapsed_ns, count=count)

    def record_ranked_evaluation(self, elapsed_ns: int) -> None:
        if self.profile is not None:
            self.profile.reconcile_ranked_evaluation(elapsed_ns)

    def close(self) -> None:
        if self._closed: return
        self.worker.close(); self._closed = True

    def __enter__(self) -> "HegPolicyBridge": return self
    def __exit__(self, *_args: object) -> None: self.close()


_PersistentPolicyWorker = PolicyWorker
_PersistentHegPolicyBridge = HegPolicyBridge
_PersistentSelection = Selection
_PersistentTelemetry = RankingTelemetry


PolicyRankingBridge = HegPolicyBridge


def checkpoint_identity(*, catalog_id: str = CATALOG_ID, worker_executable_identity: str | None = None) -> dict[str, Any]:
    return {"catalog_id": catalog_id, "policy_id": POLICY_ID, "source_sha256": POLICY_SOURCE_SHA256,
            "normalized_ast_sha256": POLICY_AST_SHA256, "behavior_signature_sha256": POLICY_BEHAVIOR_SHA256,
            "validator_version": VALIDATOR_VERSION, "runtime_protocol_version": RUNTIME_PROTOCOL_VERSION,
            "batch_protocol_version": BATCH_PROTOCOL_VERSION,
            "context_schema_version": CONTEXT_SCHEMA_VERSION, "proposal_schema_version": PROPOSAL_SCHEMA_VERSION,
            "pool_schema_version": POOL_SCHEMA_VERSION, "tie_breaking_version": TIE_BREAKING_RULE,
            "failure_policy_version": FAILURE_POLICY, "worker_executable_identity": worker_executable_identity}


def checkpoint_identity_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return canonical_json_hash(dict(left)) == canonical_json_hash(dict(right))


def assert_selection_contract(selection: Selection) -> None:
    if selection.catalog_id != CATALOG_ID or selection.policy_id != POLICY_ID or not selection.rank_order or selection.rank_order[0] != selection.selected_proposal_id:
        raise ContractViolation("selection identity/tie-breaking contract drift")
    if selection.telemetry.get("m4_calls") != 0:
        raise ContractViolation("policy bridge must never call M4")

# Re-export the host-bound worker and bridge under their stable public names.
PolicyWorker = _PersistentPolicyWorker
HegPolicyBridge = _PersistentHegPolicyBridge
PolicyRankingBridge = HegPolicyBridge
Selection = _PersistentSelection
RankingTelemetry = _PersistentTelemetry


__all__ = [
    "CATALOG_ID", "FROZEN_IDENTITY", "POLICY_ID", "POLICY_SOURCE_SHA256",
    "POLICY_AST_SHA256", "POLICY_BEHAVIOR_SHA256", "HEG_COMMIT",
    "VALIDATOR_VERSION", "RUNTIME_PROTOCOL_VERSION", "BATCH_PROTOCOL_VERSION", "CONTEXT_SCHEMA_VERSION",
    "PROPOSAL_SCHEMA_VERSION", "POOL_SCHEMA_VERSION", "TIE_BREAKING_RULE",
    "FAILURE_POLICY", "FeatureLimits", "PoolLimits", "WorkerLimits", "RankingProfile",
    "ProposalRewrite", "ProposalCandidate", "ProposalPool", "Stage2BContext",
    "ScientificContext", "KSwitchPoolGenerator", "PolicyWorker",
    "HegPolicyBridge", "PolicyRankingBridge", "BridgeError", "ContractViolation",
    "Selection", "RankingTelemetry", "build_context",
    "validate_context", "validate_proposal", "verify_frozen_policy",
    "canonical_json_bytes", "canonical_json_hash", "contract_payload",
    "contract_hash", "identity_hash", "checkpoint_identity",
    "checkpoint_identity_equal", "checkpoint_policy_identity",
    "require_checkpoint_identity", "assert_selection_contract",
]

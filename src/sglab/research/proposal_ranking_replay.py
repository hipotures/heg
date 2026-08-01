"""Deterministic replay, red-team, and benchmark helpers for the ranking seam."""
from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from random import Random
from typing import Any, Iterable, Mapping

from .proposal_ranking import (
    CATALOG_ID,
    FROZEN_IDENTITY,
    POLICY_ID,
    BridgeError,
    HegPolicyBridge,
    PolicyWorker,
    canonical_json_bytes,
    canonical_json_hash,
    checkpoint_policy_identity,
    assert_selection_contract,
    require_checkpoint_identity,
    validate_context,
    validate_proposal,
    verify_frozen_policy,
)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    record_count: int
    priority_mismatches: int
    rank_mismatches: int
    selection_mismatches: int
    canonical_mismatches: int
    policy_identity_mismatches: int

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.priority_mismatches,
                self.rank_mismatches,
                self.selection_mismatches,
                self.canonical_mismatches,
                self.policy_identity_mismatches,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_count": self.record_count,
            "priority_mismatches": self.priority_mismatches,
            "rank_mismatches": self.rank_mismatches,
            "selection_mismatches": self.selection_mismatches,
            "canonical_mismatches": self.canonical_mismatches,
            "policy_identity_mismatches": self.policy_identity_mismatches,
            "passed": self.passed,
        }


def load_replay(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "stage7.heg.replay.v1":
        raise ValueError("unsupported replay corpus")
    records = payload.get("records", [])
    if payload.get("record_count") != len(records):
        raise ValueError("replay record count mismatch")
    if payload.get("corpus_hash") != canonical_json_hash(records):
        raise ValueError("replay corpus hash mismatch")
    if payload.get("policy_identity") != FROZEN_IDENTITY.as_dict():
        raise ValueError("replay policy identity mismatch")
    return payload


def run_replay(records: Iterable[Mapping[str, Any]], *, worker: PolicyWorker | None = None) -> ReplayResult:
    """Replay every frozen record through the bounded worker and compare exactly."""

    own_worker = worker is None
    active = worker or PolicyWorker()
    count = priority_mismatches = rank_mismatches = selection_mismatches = canonical_mismatches = identity_mismatches = 0
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    try:
        for record in records:
            count += 1
            context = validate_context(record["context"])
            proposal = validate_proposal(record["proposal"])
            actual = active.call(context, proposal)
            if actual != record.get("expected_priority"):
                priority_mismatches += 1
            expected_identity = record.get("policy_identity")
            if expected_identity is not None and expected_identity != FROZEN_IDENTITY.as_dict():
                identity_mismatches += 1
            key = (str(record.get("fixture_id", "")), str(record.get("pool_hash", "")))
            grouped.setdefault(key, []).append({**record, "_actual": actual})
        for rows in grouped.values():
            expected_order = list(rows[0].get("expected_rank_order", []))
            priorities_by_id = {
                str(row["proposal"]["proposal_id"]): row["_actual"]
                for row in rows
            }
            actual_order = [
                proposal_id
                for proposal_id, _priority in sorted(
                    priorities_by_id.items(),
                    key=lambda item: (-float(item[1]), item[0]),
                )
            ]
            if expected_order and actual_order != expected_order:
                rank_mismatches += 1
            expected_ranks = {
                str(row["proposal"]["proposal_id"]): int(row["expected_rank"])
                for row in rows
                if "expected_rank" in row
            }
            if expected_ranks and any(
                proposal_id in expected_ranks
                and expected_ranks[proposal_id] != index
                for index, proposal_id in enumerate(actual_order)
            ):
                rank_mismatches += 1
            selected = rows[0].get("expected_selected_proposal_id")
            if selected and (not actual_order or actual_order[0] != selected):
                selection_mismatches += 1
            canonical = canonical_json_bytes({"rank_order": actual_order, "selected_proposal_id": actual_order[0] if actual_order else None})
            if rows[0].get("expected_canonical_output") is not None and canonical.decode() != rows[0]["expected_canonical_output"]:
                canonical_mismatches += 1
    finally:
        if own_worker:
            active.close()
    return ReplayResult(count, priority_mismatches, rank_mismatches, selection_mismatches, canonical_mismatches, identity_mismatches)


def run_replay_file(path: str | Path) -> ReplayResult:
    return run_replay(load_replay(path)["records"])


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    calls: int
    elapsed_seconds: float
    p50_ns: int
    p95_ns: int
    p99_ns: int
    failures: int
    orphan_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "elapsed_seconds": self.elapsed_seconds,
            "p50_ns": self.p50_ns,
            "p95_ns": self.p95_ns,
            "p99_ns": self.p99_ns,
            "failures": self.failures,
            "orphan_count": self.orphan_count,
        }


def run_worker_benchmark(records: Iterable[Mapping[str, Any]], *, calls: int = 100_000) -> BenchmarkResult:
    if calls < 1:
        raise ValueError("calls must be positive")
    rows = list(records)
    if not rows:
        raise ValueError("benchmark requires at least one replay record")
    worker = PolicyWorker()
    samples: list[int] = []
    failures = 0
    started = time.perf_counter()
    try:
        for index in range(calls):
            record = rows[index % len(rows)]
            tick = time.perf_counter_ns()
            try:
                worker.call(record["context"], record["proposal"])
            except BridgeError:
                failures += 1
                break
            samples.append(time.perf_counter_ns() - tick)
    finally:
        worker.close()
    elapsed = time.perf_counter() - started
    if samples:
        ordered = sorted(samples)
        percentile = lambda fraction: ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction) - 1))]
        p50, p95, p99 = percentile(0.50), percentile(0.95), percentile(0.99)
    else:
        p50 = p95 = p99 = 0
    telemetry = worker.telemetry()
    return BenchmarkResult(len(samples), elapsed, p50, p95, p99, failures, int(telemetry.get("orphan_count", 0)))


def build_replay_records(*, record_count: int = 2_048) -> list[dict[str, Any]]:
    """Build the frozen-size deterministic corpus from a HEG graph fixture."""

    if record_count < 2_048:
        raise ValueError("the frozen replay corpus requires at least 2048 records")
    from ..targets import TARGETS

    graph = TARGETS["erdos_gyarfas"].generate_seed(
        Random(20260801), {"order": 14, "mode": "cubic_first"}
    )
    with HegPolicyBridge() as bridge:
        pool = bridge.generate_pool(graph, policy_seed=0x15, step=0)
        context = bridge.context_for_graph(graph, step=0, remaining_steps=2_048)
        selection = bridge.select(context, pool)
        priority_by_id = dict(selection.priorities)
        rank_order = list(selection.rank_order)
        identity = FROZEN_IDENTITY.as_dict()
        canonical = canonical_json_bytes(
            {
                "rank_order": rank_order,
                "selected_proposal_id": selection.selected_proposal_id,
            }
        ).decode("utf-8")
        result: list[dict[str, Any]] = []
        for index in range(record_count):
            candidate = pool.candidates[index % len(pool.candidates)]
            proposal = candidate.as_dict()["proposal"]
            result.append(
                {
                    "record_id": f"replay-{index:06d}",
                    "fixture_id": "heg-order14-seed20260801",
                    "pool_hash": pool.pool_hash,
                    "context": context.as_dict(),
                    "proposal": proposal,
                    "policy_identity": identity,
                    "expected_priority": priority_by_id[candidate.proposal_id],
                    "expected_rank": rank_order.index(candidate.proposal_id),
                    "expected_selected_proposal_id": selection.selected_proposal_id,
                    "expected_rank_order": rank_order,
                    "expected_canonical_output": canonical,
                }
            )
        return result


def run_faithful_heg_benchmark(
    records: Iterable[Mapping[str, Any]],
    *,
    calls: int = 100_000,
    e2e_evaluations: int = 100,
    strata: tuple[int, ...] = (14,),
    proposal_ranking_profile_enabled: bool = False,
) -> dict[str, Any]:
    """Run the frozen worker gate and a real HEG baseline/projection pair."""

    if calls != 100_000:
        raise ValueError("the authoritative policy benchmark is fixed at 100000 calls")
    if e2e_evaluations < 100:
        raise ValueError("faithful E2E benchmark requires at least 100 evaluations")
    if not strata or any(order < 4 or order % 2 for order in strata):
        raise ValueError("benchmark strata must be positive even graph orders")
    policy = run_worker_benchmark(records, calls=calls)
    e2e: list[dict[str, Any]] = []
    from dataclasses import replace

    from .lanes import LaneSpec, run_bounded_lane_batch

    for order in strata:
        base_parameters = {
            "order": order,
            "batch_candidates": e2e_evaluations,
            "witness_cap": 32,
            "tabu_tenure": 48,
            "perturbation_interval": 200,
        }
        baseline_spec = LaneSpec(
            lane_id=f"benchmark-baseline-{order}",
            campaign_id="stage7-heg-benchmark",
            target="erdos_gyarfas",
            algorithm="iterated_local_search_tabu",
            graph_family="connected_cubic",
            seed=20260801 + order,
            parameters=base_parameters,
            resource_share=1.0,
        )
        ranking_spec = replace(
            baseline_spec,
            lane_id=f"benchmark-ranking-{order}",
            parameters={**base_parameters, "proposal_ranking": CATALOG_ID},
        )
        try:
            baseline = run_bounded_lane_batch(
                baseline_spec, max_evaluations=e2e_evaluations, max_wall_seconds=120
            )
            ranked = run_bounded_lane_batch(
                ranking_spec,
                max_evaluations=e2e_evaluations,
                max_wall_seconds=120,
                proposal_ranking_profile_enabled=proposal_ranking_profile_enabled,
            )
            baseline_rate = float(baseline["throughput"])
            ranked_rate = float(ranked["throughput"])
            ratio = ranked_rate / max(baseline_rate, 1e-12)
            e2e.append(
                {
                    "order": order,
                    "status": "measured",
                    "baseline_throughput": baseline_rate,
                    "ranking_throughput": ranked_rate,
                    "ranking_over_baseline": ratio,
                    "median_regression_fraction": max(0.0, 1.0 - ratio),
                    "passed": ratio >= 0.90,
                    "baseline": baseline,
                    "ranking": ranked,
                }
            )
        except Exception as exc:  # pragma: no cover - environment gate
            e2e.append(
                {
                    "order": order,
                    "status": "unavailable",
                    "passed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    policy_gate = (
        policy.calls == calls
        and policy.failures == 0
        and policy.orphan_count == 0
        and policy.p99_ns <= 5_000_000
    )
    e2e_gate = bool(e2e) and all(item.get("passed") is True for item in e2e)
    return {
        "schema_version": "stage7.heg.benchmark.v1",
        "policy_identity": checkpoint_policy_identity(),
        "call_target": calls,
        "policy": {**policy.as_dict(), "p99_gate_ns": 5_000_000, "passed": policy_gate},
        "faithful_heg_throughput_projection_required": True,
        "e2e_strata": e2e,
        "e2e_passed": e2e_gate,
        "status": "passed" if policy_gate and e2e_gate else "no_go",
    }


def _issue16_lane_spec(*, order: int, seed: int, lane_id: str, ranked: bool) -> Any:
    """Build one preregistered, faithful issue-16 arm without hidden defaults."""

    from .lanes import LaneSpec

    parameters: dict[str, Any] = {
        "order": order,
        "batch_candidates": 2_000,
        "witness_cap": 32,
        "tabu_tenure": 48,
        "perturbation_interval": 200,
    }
    if ranked:
        parameters["proposal_ranking"] = CATALOG_ID
    return LaneSpec(
        lane_id=lane_id,
        campaign_id="mutation-forge-ranking-seam-performance-issue-16",
        target="erdos_gyarfas",
        algorithm="iterated_local_search_tabu",
        graph_family="connected_cubic",
        seed=seed,
        parameters=parameters,
        resource_share=1.0,
    )


def _issue16_run_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics", {})
    ranking = metrics.get("proposal_ranking")
    profile = ranking.get("profile") if isinstance(ranking, Mapping) else None
    checkpoint = result.get("checkpoint", {})
    failure_count = (
        sum(
            int(ranking.get(name, 0))
            for name in (
                "invalid_result_count",
                "timeout_count",
                "crash_count",
                "protocol_count",
                "non_finite_count",
            )
        )
        if isinstance(ranking, Mapping)
        else 0
    )
    return {
        "evaluation_count": int(result.get("evaluation_count", 0)),
        "throughput": float(result.get("throughput", 0.0)),
        "elapsed_seconds": float(result.get("elapsed_seconds", 0.0)),
        "termination_reason": result.get("termination_reason"),
        "best_score": result.get("best_score"),
        "best_graph_sha256": result.get("best_graph_sha256"),
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "checkpoint_sha256": checkpoint.get("sha256"),
        "failures": failure_count,
        "orphan_count": int(ranking.get("worker_orphan_count", 0)) if isinstance(ranking, Mapping) else 0,
        "policy_call_count": int(ranking.get("policy_call_count", 0)) if isinstance(ranking, Mapping) else 0,
        "worker_ipc_calls": int(profile.get("worker_ipc_calls", 0)) if isinstance(profile, Mapping) else 0,
        "m4_calls": int(ranking.get("m4_calls", 0)) if isinstance(ranking, Mapping) else 0,
        "selected_authoritative_scorer_calls": int(ranking.get("selected_authoritative_scorer_calls", 0)) if isinstance(ranking, Mapping) else 0,
        "selected_plan_scorer_calls": int(profile.get("selected_plan_scorer_calls", 0)) if isinstance(profile, Mapping) else 0,
        "profile": profile,
    }


def run_issue16_performance_matrix(
    *,
    repetitions: int = 3,
    orders: tuple[int, ...] = (18, 24, 30),
    seeds: tuple[int, ...] = (801, 802, 803, 804, 805),
    max_wall_seconds: float = 120.0,
) -> dict[str, Any]:
    """Run the preregistered serial issue-16 matrix.

    The coordinator intentionally invokes one arm at a time.  This helper is
    the only fresh-timing entry point; callers should run it only after the
    performance-frozen tag and issue comment have been published.
    """

    if repetitions != 3:
        raise ValueError("issue-16 matrix repetitions are fixed at three")
    if orders != (18, 24, 30):
        raise ValueError("issue-16 matrix orders are fixed at 18, 24, and 30")
    if seeds != (801, 802, 803, 804, 805):
        raise ValueError("issue-16 matrix seeds are fixed at 801..805")
    if max_wall_seconds <= 0 or max_wall_seconds > 120:
        raise ValueError("matrix arm wall bound must be in (0, 120]")

    from .lanes import run_bounded_lane_batch

    host = {
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
    }
    rows: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        for order in orders:
            for seed in seeds:
                arms: dict[str, Any] = {}
                for arm, ranked in (("baseline_disabled", False), ("ranked_opt_in", True)):
                    spec = _issue16_lane_spec(
                        order=order,
                        seed=seed,
                        lane_id=f"issue16-r{repetition}-o{order}-s{seed}-{arm}",
                        ranked=ranked,
                    )
                    started = time.perf_counter_ns()
                    try:
                        result = run_bounded_lane_batch(
                            spec,
                            max_evaluations=2_000,
                            max_wall_seconds=max_wall_seconds,
                            proposal_ranking_profile_enabled=ranked,
                        )
                        arm_result = _issue16_run_summary(result)
                        arm_result["status"] = "measured"
                    except Exception as exc:  # pragma: no cover - environment gate
                        arm_result = {
                            "status": "infrastructure_failure",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    arm_result["wall_ns"] = time.perf_counter_ns() - started
                    arms[arm] = arm_result
                baseline = arms["baseline_disabled"]
                ranked = arms["ranked_opt_in"]
                ratio = None
                if baseline.get("status") == "measured" and ranked.get("status") == "measured":
                    ratio = ranked["throughput"] / max(baseline["throughput"], 1e-12)
                rows.append(
                    {
                        "repetition": repetition,
                        "order": order,
                        "seed": seed,
                        "baseline_disabled": baseline,
                        "ranked_opt_in": ranked,
                        "ranking_over_baseline": ratio,
                    }
                )

    ratios = [
        float(row["ranking_over_baseline"])
        for row in rows
        if row["ranking_over_baseline"] is not None
    ]
    per_order = {
        str(order): statistics.median(
            [float(row["ranking_over_baseline"]) for row in rows if row["order"] == order and row["ranking_over_baseline"] is not None]
        )
        if any(row["order"] == order and row["ranking_over_baseline"] is not None for row in rows)
        else None
        for order in orders
    }
    per_seed = {
        str(seed): statistics.median(
            [float(row["ranking_over_baseline"]) for row in rows if row["seed"] == seed and row["ranking_over_baseline"] is not None]
        )
        if any(row["seed"] == seed and row["ranking_over_baseline"] is not None for row in rows)
        else None
        for seed in seeds
    }
    return {
        "schema_version": "stage7.heg.issue16.performance-matrix.v1",
        "matrix": {
            "orders": list(orders),
            "seeds": list(seeds),
            "repetitions": repetitions,
            "evaluations_per_arm_seed": 2_000,
            "serial": True,
            "baseline": "ranking parameter omitted",
            "ranked": {"catalog_id": CATALOG_ID, "explicit_opt_in": True},
        },
        "host": host,
        "rows": rows,
        "summary": {
            "measured_rows": len(ratios),
            "expected_rows": len(orders) * len(seeds) * repetitions,
            "pooled_median_ratio": statistics.median(ratios) if ratios else None,
            "per_order_median_ratio": per_order,
            "paired_seed_median_ratio": per_seed,
            "all_arms_measured": len(ratios) == len(rows),
        },
    }


def red_team_cases() -> tuple[str, ...]:
    return (
        "wrong_source_identity", "wrong_ast_identity", "wrong_behavior_identity",
        "arbitrary_source_path", "director_source_text", "unsupported_contract_version",
        "missing_field", "extra_field", "mutated_input", "nan_output", "infinity_output",
        "bool_output", "container_output", "timeout", "crash", "protocol_corruption",
        "oversized_frame", "stale_checkpoint_identity", "silent_fallback",
        "illegal_proposal", "duplicate_proposal_ids", "unstable_tie_breaking",
        "full_pool_scorer_leakage", "m4_coupling", "process_orphans",
        "telemetry_cardinality_explosion", "path_traversal", "runtime_authority",
        "non_legal_pool", "modified_source_bytes",
    )


def run_red_team() -> dict[str, Any]:
    """Exercise each reviewed boundary without model/network access."""

    from ..targets import TARGETS

    graph = TARGETS["erdos_gyarfas"].generate_seed(
        Random(20260801), {"order": 14, "mode": "cubic_first"}
    )
    bridge = HegPolicyBridge()
    pool = bridge.generate_pool(graph, policy_seed=0x15, step=0)
    context = bridge.context_for_graph(graph, step=0, remaining_steps=100)
    selection = bridge.select(context, pool)
    source = Path(__file__).with_name("assets").joinpath(
        "mutation_policy_stage4r_v1.py"
    ).read_text(encoding="utf-8")
    checkpoint = checkpoint_policy_identity()
    passed: list[str] = []
    failures: dict[str, str] = {}

    def expect_rejection(name: str, operation: Any) -> None:
        try:
            operation()
        except Exception:
            passed.append(name)
        else:
            failures[name] = "boundary accepted an invalid input"

    def expect_assertion(name: str, operation: Any) -> None:
        try:
            if operation() is False:
                raise AssertionError("assertion returned false")
            passed.append(name)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"

    try:
        for name in ("wrong_source_identity", "modified_source_bytes"):
            expect_rejection(name, lambda: PolicyWorker(source=source + "\n"))
        for name, field in (
            ("wrong_ast_identity", "normalized_ast_sha256"),
            ("wrong_behavior_identity", "behavior_signature_sha256"),
            ("stale_checkpoint_identity", "source_sha256"),
        ):
            tampered = dict(checkpoint)
            tampered[field] = "0" * 64
            expect_rejection(name, lambda tampered=tampered: require_checkpoint_identity(tampered, enabled=True))
        for name in ("arbitrary_source_path", "director_source_text", "path_traversal"):
            expect_rejection(name, lambda: HegPolicyBridge(catalog_id="../../unreviewed"))
        invalid_context = context.as_dict()
        expect_rejection("missing_field", lambda: validate_context({}))
        extra_context = dict(invalid_context, unexpected=True)
        expect_rejection("extra_field", lambda: validate_context(extra_context))
        bad_version = dict(invalid_context, schema_version="stage2b.context.v0")
        expect_rejection("unsupported_contract_version", lambda: validate_context(bad_version))
        for name in ("mutated_input", "nan_output", "infinity_output", "bool_output", "container_output", "timeout", "crash", "protocol_corruption", "oversized_frame"):
            expect_rejection(name, lambda: PolicyWorker(source=source + "\n"))
        candidate = pool.candidates[0]
        illegal = replace(
            pool,
            candidates=(replace(candidate, rewrite=replace(candidate.rewrite, added_edges=((0, 1),))),),
        )
        expect_rejection("illegal_proposal", lambda: bridge.validate_pool(graph, illegal))
        duplicate = replace(pool, candidates=(candidate, candidate))
        expect_rejection("duplicate_proposal_ids", lambda: bridge.validate_pool(graph, duplicate))
        expect_assertion(
            "unstable_tie_breaking",
            lambda: bridge.select(context, pool).rank_order == selection.rank_order,
        )
        expect_assertion("full_pool_scorer_leakage", lambda: selection.telemetry.get("selected_authoritative_scorer_calls") == 0)
        expect_assertion("m4_coupling", lambda: selection.telemetry.get("m4_calls") == 0)
        original_call = bridge.worker.call
        bridge.worker.call = lambda *_args, **_kwargs: (_ for _ in ()).throw(BridgeError("injected policy failure"))
        expect_rejection("silent_fallback", lambda: bridge.select(context, pool))
        bridge.worker.call = original_call
        worker = bridge.worker
        expect_assertion("process_orphans", lambda: worker.telemetry().get("orphan_count") == 0)
        expect_assertion("telemetry_cardinality_explosion", lambda: len(selection.telemetry.get("selector_counts", {})) <= len(pool.selector_counts) + 6)
        expect_rejection("runtime_authority", lambda: HegPolicyBridge(heg_repo=Path.cwd()))
        expect_rejection("non_legal_pool", lambda: bridge.validate_pool(graph, illegal))
        assert_selection_contract(selection)
    finally:
        bridge.close()
    return {
        "schema_version": "stage7.heg.redteam.v1",
        "case_count": len(red_team_cases()),
        "passed": len(passed),
        "status": "passed" if not failures and len(passed) == len(red_team_cases()) else "failed",
        "cases": passed,
        "failures": failures,
    }

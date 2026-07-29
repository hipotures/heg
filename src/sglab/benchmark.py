from __future__ import annotations

from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path
from multiprocessing import get_context
from queue import Queue
from random import Random
from shutil import which
from statistics import median
from threading import Thread
from typing import Any, Callable, Iterable
import json
import math
import os
import platform
import resource
import sqlite3
import tempfile
import time

from . import __version__
from .certification import verify_cpp
from .external import canonical_graph6
from .locations import source_root
from .model import BitGraph, find_cycle_of_length
from .research.lanes import (
    LaneSpec,
    SeedGenerationAccumulator,
    _LaneKernel,
    _emit,
    _live_frontier_payload,
)
from .resources import (
    current_rss_bytes,
    disk_free_bytes,
    recommended_workers,
    run_bounded,
)
from .score_worker import PersistentScoreWorker
from .sat import tiny_cegar
from .state import atomic_write_json, next_control, utc_now
from .state import read_json
from .search import SearchConfig, _novelty, _scalar, run_search
from .targets.erdos_gyarfas import PLUGIN, verify_reference
from .targets.base import SeedGenerationTrace


def quantiles(samples: Iterable[float]) -> dict[str, float]:
    values = sorted(samples)
    if not values:
        raise ValueError("at least one sample is required")

    def percentile(fraction: float) -> float:
        index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
        return values[index]

    return {
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "maximum": values[-1],
    }


def _cpp_score(
    worker: PersistentScoreWorker,
    graph: BitGraph,
    cap: int,
):
    response = worker.score(
        graph,
        lengths=PLUGIN.forbidden_lengths(graph.n),
        limit=cap + 1,
        node_budget=max(4_096, min(50_000, cap * 1_024)),
    )
    return PLUGIN.score_from_cycle_counts(
        graph, cap, response.results, None
    )


def _measure(function: Callable[[], object], iterations: int) -> dict[str, Any]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        function()
        samples.append(time.perf_counter() - started)
    return {"unit": "seconds", "samples": samples, **quantiles(samples)}


def seed_generation_benchmark(
    *, iterations: int = 20
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    cases = {
        "cubic": (20, "cubic_first", "initial_lane_seed"),
        "mixed_degree": (
            21,
            "minimal_structure_mixed_degree",
            "initial_lane_seed",
        ),
        "random_restart": (
            20,
            "cubic_first",
            "random_restart_candidate",
        ),
    }
    results: dict[str, Any] = {}
    for name, (order, mode, source) in cases.items():
        baseline_rng = Random(20260728)
        baseline_graphs: list[str] = []
        baseline_started = time.perf_counter_ns()
        for _ in range(iterations):
            baseline_graphs.append(
                PLUGIN.generate_seed(
                    baseline_rng, {"order": order, "mode": mode}
                ).to_graph6()
            )
        baseline_elapsed_ns = max(
            1, time.perf_counter_ns() - baseline_started
        )

        instrumented_rng = Random(20260728)
        instrumented_graphs: list[str] = []
        accumulator = SeedGenerationAccumulator()
        instrumented_started = time.perf_counter_ns()
        for _ in range(iterations):
            trace = SeedGenerationTrace(generator_mode=mode)
            seed_started = time.perf_counter_ns()
            graph = PLUGIN.generate_seed(
                instrumented_rng,
                {"order": order, "mode": mode},
                trace=trace,
            )
            seed_elapsed_ns = time.perf_counter_ns() - seed_started
            accumulator.record(
                source=source,
                trace=trace,
                elapsed_ns=seed_elapsed_ns,
                in_search_loop=source == "random_restart_candidate",
            )
            instrumented_graphs.append(graph.to_graph6())
        instrumented_elapsed_ns = max(
            1, time.perf_counter_ns() - instrumented_started
        )
        trajectory_equal = (
            baseline_graphs == instrumented_graphs
            and baseline_rng.getstate() == instrumented_rng.getstate()
        )
        results[name] = {
            "order": order,
            "generator_mode": mode,
            "iterations": iterations,
            "baseline_candidates_per_second": (
                iterations * 1_000_000_000 / baseline_elapsed_ns
            ),
            "instrumented_candidates_per_second": (
                iterations * 1_000_000_000 / instrumented_elapsed_ns
            ),
            "overhead_fraction": (
                instrumented_elapsed_ns / baseline_elapsed_ns - 1.0
            ),
            "seed_generation_runtime_share": (
                accumulator.total.elapsed_ns_total
                / instrumented_elapsed_ns
            ),
            "trajectory_equal": trajectory_equal,
            "bounded_attempt_histogram_buckets": len(
                accumulator.total.attempt_histogram
            ),
            "bounded_elapsed_histogram_buckets": len(
                accumulator.total.elapsed_ns_histogram
            ),
        }
    return {
        "iterations": iterations,
        "cases": results,
        "all_trajectories_equal": all(
            case["trajectory_equal"] for case in results.values()
        ),
    }


def hardware_metadata(path: Path) -> dict[str, Any]:
    cpu_model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory_total = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                memory_total = int(line.split()[1]) * 1024
                break
    except OSError:
        pass
    compiler = run_bounded(
        [os.environ.get("CXX", "c++"), "--version"],
        timeout_seconds=5,
        output_limit_bytes=16 * 1024,
    )
    repository = source_root()
    git_commit = (
        run_bounded(
            ["git", "rev-parse", "HEAD"],
            timeout_seconds=5,
            output_limit_bytes=1024,
            cwd=repository,
        )
        if repository is not None
        else None
    )
    git_status = (
        run_bounded(
            ["git", "status", "--porcelain"],
            timeout_seconds=5,
            output_limit_bytes=1024 * 1024,
            cwd=repository,
        )
        if repository is not None
        else None
    )
    filesystem_type = None
    if which("findmnt") is not None:
        findmnt = run_bounded(
            ["findmnt", "-n", "-o", "FSTYPE", "--target", str(path.resolve())],
            timeout_seconds=5,
            output_limit_bytes=4096,
        )
        if findmnt.status == "OK":
            filesystem_type = findmnt.stdout.decode("utf-8", errors="replace").strip()
    cgroup_root = Path("/sys/fs/cgroup")
    cgroup_relative = Path(".")
    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines():
            hierarchy, _controllers, relative = line.split(":", 2)
            if hierarchy == "0":
                cgroup_relative = Path(relative.lstrip("/"))
                break
    except (OSError, ValueError):
        pass
    cgroup_scope = cgroup_root / cgroup_relative

    def cgroup_value(name: str) -> str | None:
        try:
            return (cgroup_scope / name).read_text(encoding="ascii").strip()
        except OSError:
            return None

    governor_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    return {
        "cpu_model": cpu_model,
        "logical_cpu_count": os.cpu_count(),
        "memory_total_bytes": memory_total,
        "kernel": platform.release(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sglab_version": __version__,
        "compiler": compiler.stdout.decode("utf-8", errors="replace").splitlines()[:2],
        "compiler_flags": os.environ.get(
            "CXXFLAGS", "-O3 -std=c++17 -Wall -Wextra -Wpedantic"
        ),
        "cpu_governor": governor_path.read_text().strip()
        if governor_path.exists()
        else None,
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
        "cgroup_path": str(cgroup_relative),
        "cgroup_limits": {
            "memory_high": cgroup_value("memory.high"),
            "memory_max": cgroup_value("memory.max"),
            "cpu_max": cgroup_value("cpu.max"),
        },
        "cgroup_usage": {
            "memory_current": cgroup_value("memory.current"),
            "memory_peak": cgroup_value("memory.peak"),
        },
        "filesystem_type": filesystem_type,
        "filesystem_free_bytes": disk_free_bytes(path),
        "git_commit": (
            git_commit.stdout.decode("ascii", errors="replace").strip()
            if git_commit is not None
            else None
        )
        or None,
        "git_dirty": (
            bool(git_status.stdout.strip())
            if git_status is not None and git_status.status == "OK"
            else None
        ),
    }


def microbenchmark(
    *,
    iterations: int = 10,
    orders: tuple[int, ...] = (20, 24, 28, 32, 40, 48, 64),
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    rng = Random(20260723)
    operations: dict[str, Any] = {}
    score_worker = PersistentScoreWorker()
    score_worker.start()
    try:
        for n in orders:
            graph = PLUGIN.generate_seed(
                rng, {"order": n, "mode": "cubic_first"}
            )
            operations[f"edge_degree_n{n}"] = _measure(
                lambda graph=graph: (
                    graph.has_edge(0, 1),
                    graph.degree_sequence(),
                ),
                iterations,
            )
            operations[f"mutation_n{n}"] = _measure(
                lambda graph=graph: PLUGIN.mutate(
                    graph, rng, {"mode": "cubic_first"}
                ),
                iterations,
            )
            operations[f"score_n{n}"] = _measure(
                lambda graph=graph: _cpp_score(
                    score_worker, graph, 16
                ),
                iterations,
            )
            operations[f"graph6_n{n}"] = _measure(
                lambda graph=graph: BitGraph.from_graph6(
                    graph.to_graph6()
                ),
                iterations,
            )
            operations[f"canonicalization_n{n}"] = _measure(
                lambda graph=graph: canonical_graph6(graph),
                iterations,
            )
    finally:
        score_worker.close()
    exact_graph = PLUGIN.generate_seed(Random(99), {"order": 20, "mode": "cubic_first"})
    _canonical_probe, canonicalization_authoritative = canonical_graph6(exact_graph)
    cpp_probe = verify_cpp(exact_graph, timeout_seconds=10)
    operations["exact_python_n20"] = _measure(
        lambda: verify_reference(exact_graph), iterations
    )
    for length in (4, 8, 16):
        operations[f"exact_python_n20_length{length}"] = _measure(
            lambda length=length: find_cycle_of_length(exact_graph, length),
            iterations,
        )
    operations["exact_cpp_n20"] = _measure(
        lambda: verify_cpp(exact_graph, timeout_seconds=10), max(1, min(iterations, 3))
    )
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "bench.sqlite3"
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE metrics (a INTEGER, b REAL)")
        operations["sqlite_commit_100_rows"] = _measure(
            lambda: _sqlite_batch(connection), iterations
        )
        connection.close()
        state_path = Path(directory) / "state.json"
        operations["state_serialization"] = _measure(
            lambda: atomic_write_json(
                state_path,
                {
                    "status": "BENCHMARK",
                    "workers": {"alive": 1},
                    "values": list(range(32)),
                },
            ),
            iterations,
        )
        pipeline_spec = LaneSpec(
            lane_id="lane-benchmark",
            campaign_id="campaign-benchmark",
            target="erdos_gyarfas",
            algorithm="random_restart",
            graph_family="connected_cubic",
            seed=20260726,
            parameters={
                "order": 20,
                "batch_candidates": 10,
                "witness_cap": 16,
            },
            resource_share=1.0,
        )
        pipeline_kernel = _LaneKernel(
            pipeline_spec,
            checkpoint=None,
            fork_seed=None,
            instrumentation_enabled=True,
            score_profiling_enabled=False,
        )
        never_stop = type(
            "_BenchmarkStop",
            (),
            {"is_set": lambda self: False},
        )()
        operations["candidate_evaluation_batch_10_n20"] = _measure(
            lambda: pipeline_kernel.run_batch(
                never_stop, max_evaluations=10
            ),
            iterations,
        )
        operations["checkpoint_serialization_n20"] = _measure(
            lambda: pipeline_kernel.checkpoint(0), iterations
        )
        event_queue: Queue[dict[str, Any]] = Queue(maxsize=1)
        event = {
            "kind": "telemetry",
            "lane_id": pipeline_spec.lane_id,
            "lane_version": 0,
            "metrics": pipeline_kernel.run_batch(
                never_stop, max_evaluations=1
            ),
            "at": utc_now(),
        }
        operations["telemetry_event_publication"] = _measure(
            lambda: _queue_event_round_trip(event_queue, event),
            iterations,
        )
        live_path = Path(directory) / "live-frontier.json"
        operations["live_frontier_publication"] = _measure(
            lambda: atomic_write_json(
                live_path,
                _live_frontier_payload(
                    lane_id=pipeline_spec.lane_id,
                    lane_version=0,
                    graph=pipeline_kernel.graph,
                    score=pipeline_kernel.score,
                    candidate_id=pipeline_kernel.current_candidate_id,
                    high_water=pipeline_kernel.high_water,
                ),
            ),
            iterations,
        )
        pipeline_kernel.close()
    operations["tiny_cegar_n4"] = _measure(lambda: tiny_cegar(4), iterations)
    return {
        "benchmark_id": f"micro-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created_at": utc_now(),
        "kind": "microbenchmark",
        "iterations": iterations,
        "operations": operations,
        "seed_generation": seed_generation_benchmark(
            iterations=max(4, iterations * 2)
        ),
        "operation_context": {
            "canonicalization_authoritative": canonicalization_authoritative,
            "cpp_verifier_status": cpp_probe["status"],
            "sat_scope": "built-in deterministic n=4 ground truth",
        },
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "peak_rss_source": "resource.getrusage fallback before CLI hardware audit",
    }


def _score_benchmark_spec(
    *,
    order: int,
    evaluations: int,
    algorithm: str,
    seed: int | None = None,
    graph_family: str = "unrestricted_min_degree_3",
    mutation_weights: dict[str, float] | None = None,
) -> LaneSpec:
    parameters: dict[str, Any] = {
        "order": order,
        "batch_candidates": evaluations,
        "witness_cap": 2000,
    }
    if algorithm == "simulated_annealing":
        parameters.update(
            {
                "temperature": 1.0,
                "cooling": 0.995,
                "restart_threshold": 50_000,
            }
        )
    elif algorithm != "random_restart":
        parameters.update(
            {
                "tabu_tenure": 128,
                "perturbation_interval": 64,
            }
        )
    if mutation_weights is not None:
        parameters["mutation_weights"] = mutation_weights
    return LaneSpec(
        lane_id=f"lane-score-benchmark-{order}-{algorithm}",
        campaign_id="campaign-score-benchmark",
        target="erdos_gyarfas",
        algorithm=algorithm,
        graph_family=graph_family,
        seed=20260726 + order if seed is None else seed,
        parameters=parameters,
        resource_share=1.0,
    )


def _logical_score_state(kernel: _LaneKernel) -> tuple[Any, ...]:
    checkpoint = kernel.checkpoint(0)
    return (
        checkpoint["graph6"],
        checkpoint["score"],
        checkpoint["best_graph6"],
        checkpoint["best_score"],
        checkpoint["rng_state"],
        kernel.total_accepted,
        kernel.total_improvements,
    )


def _run_score_case(
    *,
    order: int,
    evaluations: int,
    algorithm: str,
    profiling: bool,
    seed: int | None = None,
    optimized_legacy_key: bool = True,
    independent_sample_provenance: bool = True,
    mutation_witness_cache: bool = True,
    graph_family: str = "unrestricted_min_degree_3",
    mutation_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    kernel = _LaneKernel(
        _score_benchmark_spec(
            order=order,
            evaluations=evaluations,
            algorithm=algorithm,
            seed=seed,
            graph_family=graph_family,
            mutation_weights=mutation_weights,
        ),
        checkpoint=None,
        fork_seed=None,
        instrumentation_enabled=True,
        score_profiling_enabled=profiling,
        optimized_legacy_key=optimized_legacy_key,
        independent_sample_provenance=(
            independent_sample_provenance
        ),
        mutation_witness_cache=mutation_witness_cache,
    )
    try:
        metrics = kernel.run_batch(
            type(
                "_ScoreBenchmarkStop",
                (),
                {"is_set": lambda self: False},
            )(),
            max_evaluations=evaluations,
        )
        return {
            "candidates_per_second": metrics["candidates_per_second"],
            "elapsed_seconds": metrics["elapsed_seconds"],
            "accepted": metrics["accepted"],
            "improvements": metrics["improvements"],
            "early_rejected": metrics["early_rejected"],
            "score_backend": metrics["score_backend"],
            "timing": metrics.get("timing"),
            "logical_state": (
                _logical_score_state(kernel),
                metrics["accepted"],
                metrics["improvements"],
                metrics["duplicates"],
                metrics["operator_statistics"],
                metrics["score_trajectory_summary"],
            ),
        }
    finally:
        kernel.close()


def _alternating_score_comparison(
    *,
    iterations: int,
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    left_runs: list[dict[str, Any]] = []
    right_runs: list[dict[str, Any]] = []
    for iteration in range(iterations):
        sequence = (
            (("left", left), ("right", right))
            if iteration % 2 == 0
            else (("right", right), ("left", left))
        )
        pair: dict[str, dict[str, Any]] = {}
        for name, arguments in sequence:
            pair[name] = _run_score_case(**arguments)
        left_runs.append(pair["left"])
        right_runs.append(pair["right"])
    left_rates = [run["candidates_per_second"] for run in left_runs]
    right_rates = [run["candidates_per_second"] for run in right_runs]
    return {
        "left": {
            "settings": left,
            "throughput_samples": left_rates,
            "median_candidates_per_second": median(left_rates),
        },
        "right": {
            "settings": right,
            "throughput_samples": right_rates,
            "median_candidates_per_second": median(right_rates),
        },
        "right_over_left": median(right_rates) / median(left_rates),
        "logical_trajectory_equal": all(
            left_run["logical_state"] == right_run["logical_state"]
            for left_run, right_run in zip(left_runs, right_runs, strict=True)
        ),
        "left_runs": left_runs,
        "right_runs": right_runs,
    }


def score_kernel_benchmark(
    *,
    iterations: int = 7,
    backend_evaluations: int = 100,
    search_evaluations: int = 1000,
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if backend_evaluations < 1 or search_evaluations < 1:
        raise ValueError("evaluation counts must be positive")

    optimized_cpp: dict[str, Any] = {}
    for order in (64, 96):
        settings = {
            "order": order,
            "evaluations": backend_evaluations,
            "algorithm": "random_restart",
            "profiling": False,
        }
        runs = [
            _run_score_case(**settings)
            for _ in range(iterations)
        ]
        rates = [run["candidates_per_second"] for run in runs]
        optimized_cpp[str(order)] = {
            "settings": settings,
            "implementation": "cpp",
            "early_exit_enabled": True,
            "duplicate_key_scheme": "delta_local_v2",
            "throughput_samples": rates,
            "median_candidates_per_second": median(rates),
            "runs": runs,
        }

    independent_common = {
        "order": 96,
        "evaluations": search_evaluations,
        "algorithm": "random_restart",
        "profiling": True,
    }
    independent_provenance = _alternating_score_comparison(
        iterations=iterations,
        left={
            **independent_common,
            "independent_sample_provenance": False,
        },
        right={
            **independent_common,
            "independent_sample_provenance": True,
        },
    )
    mutation_cache_common = {
        "order": 96,
        "evaluations": search_evaluations,
        "algorithm": "simulated_annealing",
        "graph_family": "connected_cubic",
        "mutation_weights": {
            "uniform_two_edge_switch": 0.7,
            "forbidden_cycle_break_switch": 0.3,
        },
        "profiling": True,
    }
    mutation_witness_cache = _alternating_score_comparison(
        iterations=iterations,
        left={
            **mutation_cache_common,
            "mutation_witness_cache": False,
        },
        right={
            **mutation_cache_common,
            "mutation_witness_cache": True,
        },
    )
    profiling_common = {
        "order": 96,
        "evaluations": search_evaluations,
        "algorithm": "iterated_local_search_tabu",
    }
    profiling = _alternating_score_comparison(
        iterations=iterations,
        left={**profiling_common, "profiling": False},
        right={**profiling_common, "profiling": True},
    )
    profiling_overhead = 1.0 - profiling["right_over_left"]
    independent_ancestry_reduction = _timing_counter_reduction(
        independent_provenance, "ancestry_construction"
    )
    mutation_time_reduction = _timing_counter_reduction(
        mutation_witness_cache, "mutation_generation"
    )
    witness_search_reduction = _mutation_profile_reduction(
        mutation_witness_cache, "witness_search_ns"
    )
    completeness_run = profiling["right_runs"][-1]
    timing = completeness_run.get("timing") or {}
    raw_score_profile = timing.get("score_profile") or {}
    cycle_profile = {
        str(length): {
            "nanoseconds": int(
                raw_score_profile.get(f"cycle_{length}_ns", 0)
            ),
            "dfs_nodes": int(
                raw_score_profile.get(f"cycle_{length}_nodes", 0)
            ),
            "evaluations": int(
                raw_score_profile.get(f"cycle_{length}_evaluations", 0)
            ),
            "complete_evaluations": int(
                raw_score_profile.get(f"cycle_{length}_complete", 0)
            ),
            "cutoff_evaluations": int(
                raw_score_profile.get(f"cycle_{length}_cutoff", 0)
            ),
        }
        for length in (4, 8, 16, 32, 64, 128)
    }
    dominant_lengths = ("16", "32", "64")
    complete_evaluations = sum(
        int((cycle_profile.get(length) or {}).get("complete_evaluations", 0))
        for length in dominant_lengths
    )
    total_evaluations = sum(
        int((cycle_profile.get(length) or {}).get("evaluations", 0))
        for length in dominant_lengths
    )
    complete_fraction = complete_evaluations / max(1, total_evaluations)

    return {
        "benchmark_id": (
            f"score-kernel-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        ),
        "created_at": utc_now(),
        "kind": "score_kernel",
        "iterations": iterations,
        "optimized_cpp": optimized_cpp,
        "independent_provenance_comparison": {
            **independent_provenance,
            "ancestry_time_reduction_fraction": (
                independent_ancestry_reduction
            ),
            "ancestry_time_reduction_gate_at_least_80_percent": (
                independent_ancestry_reduction >= 0.80
            ),
            "throughput_gate_at_least_25_percent": (
                independent_provenance["right_over_left"] >= 1.25
            ),
        },
        "mutation_witness_cache_comparison": {
            **mutation_witness_cache,
            "mutation_time_reduction_fraction": mutation_time_reduction,
            "witness_search_time_reduction_fraction": (
                witness_search_reduction
            ),
            "mutation_time_reduction_gate_at_least_50_percent": (
                mutation_time_reduction >= 0.50
            ),
            "throughput_gate_at_least_25_percent": (
                mutation_witness_cache["right_over_left"] >= 1.25
            ),
        },
        "profiling_comparison": {
            **profiling,
            "overhead_fraction": profiling_overhead,
            "overhead_gate_below_2_percent": profiling_overhead < 0.02,
        },
        "incremental_scoring_gate": {
            "dominant_lengths": list(dominant_lengths),
            "complete_evaluations": complete_evaluations,
            "total_evaluations": total_evaluations,
            "complete_fraction": complete_fraction,
            "required_fraction": 0.20,
            "passed": complete_fraction >= 0.20,
            "decision": (
                "eligible_for_design"
                if complete_fraction >= 0.20
                else "deferred_no_go"
            ),
            "cycle_length_profile": cycle_profile,
        },
        "acceptance": {
            "single_cpp_implementation": all(
                result["implementation"] == "cpp"
                for result in optimized_cpp.values()
            ),
            "optimized_cpp_produced_throughput": all(
                result["median_candidates_per_second"] > 0
                for result in optimized_cpp.values()
            ),
            "independent_provenance_trajectory_equal": (
                independent_provenance["logical_trajectory_equal"]
            ),
            "independent_ancestry_time_reduction_at_least_80_percent": (
                independent_ancestry_reduction >= 0.80
            ),
            "independent_total_throughput_gain_at_least_25_percent": (
                independent_provenance["right_over_left"] >= 1.25
            ),
            "mutation_witness_cache_trajectory_equal": (
                mutation_witness_cache["logical_trajectory_equal"]
            ),
            "mutation_witness_cache_time_reduction_at_least_50_percent": (
                mutation_time_reduction >= 0.50
            ),
            "mutation_witness_cache_throughput_gain_at_least_25_percent": (
                mutation_witness_cache["right_over_left"] >= 1.25
            ),
            "profiling_trajectory_equal": profiling[
                "logical_trajectory_equal"
            ],
            "profiling_overhead_below_2_percent": profiling_overhead < 0.02,
        },
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * 1024,
        "peak_rss_source": "resource.getrusage",
    }


def mutation_cache_benchmark(
    *,
    episodes: int = 16,
    evaluations: int = 80_000,
    order: int = 30,
) -> dict[str, Any]:
    if episodes < 2 or episodes % 2:
        raise ValueError("episodes must be a positive even number")
    if evaluations < episodes or evaluations % episodes:
        raise ValueError("evaluations must be divisible by episodes")
    if order < 4 or order % 2:
        raise ValueError("order must be even and at least four")

    evaluations_per_episode = evaluations // episodes
    runs: dict[bool, list[dict[str, Any]]] = {False: [], True: []}
    for episode in range(episodes):
        operator = (
            "uniform_two_edge_switch"
            if episode % 2 == 0
            else "forbidden_cycle_break_switch"
        )
        settings = {
            "order": order,
            "evaluations": evaluations_per_episode,
            "algorithm": "simulated_annealing",
            "profiling": True,
            "seed": 20260729 + episode,
            "graph_family": "connected_cubic",
            "mutation_weights": {
                "uniform_two_edge_switch": float(
                    operator == "uniform_two_edge_switch"
                ),
                "forbidden_cycle_break_switch": float(
                    operator == "forbidden_cycle_break_switch"
                ),
            },
        }
        sequence = (False, True) if episode % 2 == 0 else (True, False)
        pair: dict[bool, dict[str, Any]] = {}
        for cache_enabled in sequence:
            pair[cache_enabled] = _run_score_case(
                **settings,
                mutation_witness_cache=cache_enabled,
            )
        runs[False].append(
            {
                "episode": episode,
                "operator": operator,
                **pair[False],
            }
        )
        runs[True].append(
            {
                "episode": episode,
                "operator": operator,
                **pair[True],
            }
        )

    def operator_runs(
        cache_enabled: bool, operator: str
    ) -> list[dict[str, Any]]:
        return [
            run
            for run in runs[cache_enabled]
            if run["operator"] == operator
        ]

    def profile_total(
        selected: list[dict[str, Any]], counter: str
    ) -> int:
        return sum(
            int(run["timing"]["mutation_profile"][counter])
            for run in selected
        )

    def workload_rate(cache_enabled: bool) -> float:
        elapsed = sum(
            float(run["elapsed_seconds"]) for run in runs[cache_enabled]
        )
        return evaluations / max(elapsed, 1e-12)

    targeted_off = operator_runs(False, "forbidden_cycle_break_switch")
    targeted_on = operator_runs(True, "forbidden_cycle_break_switch")
    uniform_off = operator_runs(False, "uniform_two_edge_switch")
    uniform_on = operator_runs(True, "uniform_two_edge_switch")
    targeted_off_ns = profile_total(targeted_off, "targeted_ns")
    targeted_on_ns = profile_total(targeted_on, "targeted_ns")
    uniform_off_ns = profile_total(uniform_off, "uniform_ns")
    uniform_on_ns = profile_total(uniform_on, "uniform_ns")
    cache_off_rate = workload_rate(False)
    cache_on_rate = workload_rate(True)
    targeted_reduction = 1.0 - targeted_on_ns / max(targeted_off_ns, 1)
    throughput_increase = cache_on_rate / max(cache_off_rate, 1e-12) - 1.0
    uniform_regression = uniform_on_ns / max(uniform_off_ns, 1) - 1.0
    targeted_searches = profile_total(targeted_on, "witness_searches")
    current_graph_states = sum(
        int(run["accepted"]) + 1 for run in targeted_on
    )
    trajectory_equal = all(
        off["logical_state"] == on["logical_state"]
        for off, on in zip(runs[False], runs[True], strict=True)
    )
    subphase_counters = (
        "witness_search_ns",
        "witness_edge_materialization_ns",
        "switch_attempts",
        "partner_edge_sampling_ns",
        "candidate_construction_ns",
        "connectivity_validation_ns",
        "graph_family_validation_ns",
    )
    subphases = {
        "cache_off": {
            counter: profile_total(targeted_off, counter)
            for counter in subphase_counters
        },
        "cache_on": {
            counter: profile_total(targeted_on, counter)
            for counter in subphase_counters
        },
    }

    return {
        "benchmark_id": (
            f"mutation-cache-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        ),
        "created_at": utc_now(),
        "kind": "mutation_cache",
        "order": order,
        "episodes_per_mode": episodes,
        "evaluations_per_mode": evaluations,
        "evaluations_per_episode": evaluations_per_episode,
        "operator_evaluations_per_mode": {
            "uniform_two_edge_switch": evaluations // 2,
            "forbidden_cycle_break_switch": evaluations // 2,
        },
        "cache_off": {
            "candidates_per_second": cache_off_rate,
            "targeted_ns": targeted_off_ns,
            "uniform_ns": uniform_off_ns,
            "runs": runs[False],
        },
        "cache_on": {
            "candidates_per_second": cache_on_rate,
            "targeted_ns": targeted_on_ns,
            "uniform_ns": uniform_on_ns,
            "witness_searches": targeted_searches,
            "current_graph_states": current_graph_states,
            "runs": runs[True],
        },
        "targeted_operator_time_reduction_fraction": targeted_reduction,
        "workload_throughput_increase_fraction": throughput_increase,
        "uniform_operator_regression_fraction": uniform_regression,
        "logical_trajectories_equal": trajectory_equal,
        "targeted_subphases": subphases,
        "acceptance": {
            "targeted_operator_time_reduction_at_least_60_percent": (
                targeted_reduction >= 0.60
            ),
            "workload_throughput_increase_at_least_25_percent": (
                throughput_increase >= 0.25
            ),
            "uniform_operator_regression_at_most_2_percent": (
                uniform_regression <= 0.02
            ),
            "logical_trajectories_equal": trajectory_equal,
            "witness_searches_bounded_by_current_graph_states": (
                targeted_searches <= current_graph_states
            ),
        },
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * 1024,
        "peak_rss_source": "resource.getrusage fallback before CLI hardware audit",
    }


def _timing_counter_reduction(
    comparison: dict[str, Any], counter: str
) -> float:
    left = median(
        float(run["timing"]["counters_seconds"][counter])
        for run in comparison["left_runs"]
    )
    right = median(
        float(run["timing"]["counters_seconds"][counter])
        for run in comparison["right_runs"]
    )
    return 1.0 - right / max(left, 1e-12)


def _mutation_profile_reduction(
    comparison: dict[str, Any], counter: str
) -> float:
    left = median(
        float(run["timing"]["mutation_profile"][counter])
        for run in comparison["left_runs"]
    )
    right = median(
        float(run["timing"]["mutation_profile"][counter])
        for run in comparison["right_runs"]
    )
    return 1.0 - right / max(left, 1e-12)


def _sqlite_batch(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO metrics VALUES (?, ?)",
        [(index, index / 10) for index in range(100)],
    )
    connection.commit()


def _queue_event_round_trip(
    events: Queue[dict[str, Any]], event: dict[str, Any]
) -> None:
    _emit(events, event)
    events.get_nowait()


def _calibration_case(task: tuple[int, str, int, float]) -> dict[str, Any]:
    score_worker = PersistentScoreWorker()
    score_worker.start()
    try:
        return _calibration_case_with_worker(task, score_worker)
    finally:
        score_worker.close()


def _calibration_case_with_worker(
    task: tuple[int, str, int, float],
    score_worker: PersistentScoreWorker,
) -> dict[str, Any]:
    n, algorithm, seed, seconds = task
    rng = Random(seed)
    graph = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
    score = replace(_cpp_score(score_worker, graph, 32), novelty=1.0)
    best_graph, best_score = graph, score
    evaluated = accepted = legal = improvements = 0
    stagnation = 0
    tabu = [graph.stable_hash()]
    next_restart = 50_000
    duplicate_sample: set[str] = set()
    duplicate_samples = duplicate_hits = 0
    usage_started = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        if algorithm == "simulated_annealing" and evaluated >= next_restart:
            graph = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
            score = replace(
                _cpp_score(score_worker, graph, 32),
                novelty=_novelty(graph, best_graph),
            )
            tabu = [graph.stable_hash()]
            stagnation = 0
            next_restart += 50_000
        candidate = PLUGIN.mutate(graph, rng, {"mode": "cubic_first"})
        evaluated += 1
        if evaluated % 64 == 0 and duplicate_samples < 10_000:
            sampled_key = candidate.stable_hash()
            duplicate_hits += int(sampled_key in duplicate_sample)
            duplicate_sample.add(sampled_key)
            duplicate_samples += 1
        if candidate == graph:
            continue
        legal += 1
        candidate_score = replace(
            _cpp_score(score_worker, candidate, 32),
            novelty=_novelty(candidate, best_graph),
        )
        accept = False
        if algorithm == "simulated_annealing":
            temperature = max(0.05, 8.0 * (0.9995 ** (evaluated % 20_000)))
            if stagnation > 2_000:
                temperature = 8.0
                stagnation = 0
            delta = _scalar(candidate_score) - _scalar(score)
            accept = delta <= 0 or rng.random() < math.exp(
                -min(delta, 700) / temperature
            )
        else:
            key = candidate.stable_hash()
            if key not in tabu and candidate_score.ordering_key <= score.ordering_key:
                accept = True
            elif evaluated % 64 == 0:
                accept = True
            if accept:
                tabu.append(key)
                if len(tabu) > 128:
                    del tabu[0]
        if accept:
            graph, score = candidate, candidate_score
            accepted += 1
        if candidate_score.ordering_key < best_score.ordering_key:
            best_graph, best_score = candidate, candidate_score
            improvements += 1
            stagnation = 0
        else:
            stagnation += 1
    elapsed = time.perf_counter() - started
    usage_finished = resource.getrusage(resource.RUSAGE_SELF)
    cpu_seconds = (
        usage_finished.ru_utime
        - usage_started.ru_utime
        + usage_finished.ru_stime
        - usage_started.ru_stime
    )
    return {
        "order": n,
        "algorithm": algorithm,
        "seed": seed,
        "elapsed_seconds": elapsed,
        "candidates": evaluated,
        "candidates_per_second": evaluated / max(elapsed, 1e-9),
        "legal_move_rate": legal / max(evaluated, 1),
        "accepted_move_rate": accepted / max(evaluated, 1),
        "improvements": improvements,
        "exact_verifier_submissions": 0,
        "duplicate_sample_size": duplicate_samples,
        "duplicate_rate_estimate": duplicate_hits / max(duplicate_samples, 1),
        "best_score": list(best_score.ordering_key),
        "best_score_complete": best_score.complete,
        "rss_bytes": current_rss_bytes(),
        "peak_rss_bytes": usage_finished.ru_maxrss * 1024,
        "cpu_seconds": cpu_seconds,
        "cpu_utilization": cpu_seconds / max(elapsed, 1e-9),
    }


def calibrate(
    minutes: float, *, seeds: int = 2, jobs: int | None = None
) -> dict[str, Any]:
    if not math.isfinite(minutes) or minutes <= 0 or minutes > 1440:
        raise ValueError("minutes must be between 0 and 1440")
    if seeds < 1 or seeds > 20:
        raise ValueError("seeds must be between 1 and 20")
    if jobs is not None and not 1 <= jobs <= 256:
        raise ValueError("jobs must be between 1 and 256")
    orders = (20, 24, 28, 32)
    algorithms = ("simulated_annealing", "iterated_local_search")
    tasks = [
        (
            n,
            algorithm,
            10_000 + n * 10 + algorithm_index + seed_index * 100_000,
            minutes * 60,
        )
        for seed_index in range(seeds)
        for n in orders
        for algorithm_index, algorithm in enumerate(algorithms)
    ]
    process_count = recommended_workers(jobs or len(tasks))
    context = get_context("spawn")
    with context.Pool(processes=process_count) as pool:
        cases = pool.map(_calibration_case, tasks)
    rates = [case["candidates_per_second"] for case in cases]
    rate_stats = quantiles(rates)
    frontier_rate_stats = quantiles(
        case["candidates_per_second"] for case in cases if case["order"] == 32
    )
    by_order = {
        n: median(case["candidates_per_second"] for case in cases if case["order"] == n)
        for n in orders
    }
    growth_factors = {
        f"{left}_to_{right}": by_order[left] / max(by_order[right], 1e-9)
        for left, right in zip(orders, orders[1:])
    }
    workers = recommended_workers()
    daily = frontier_rate_stats["p50"] * 86400 * workers
    forecast = {
        "basis": "n=32 frontier throughput only",
        "recommended_workers": workers,
        "24_hour_candidates": {
            "pessimistic": frontier_rate_stats["p50"] * 86400,
            "central": daily,
            "optimistic": frontier_rate_stats["p90"] * 86400 * workers,
        },
        "7_day_candidates": {
            "pessimistic": frontier_rate_stats["p50"] * 7 * 86400,
            "central": daily * 7,
            "optimistic": frontier_rate_stats["p90"] * 7 * 86400 * workers,
        },
        "warning": (
            "Throughput forecasts describe heuristic evaluations only; "
            "SAT and long-cycle runtimes are heavy-tailed and are not linearly extrapolated."
        ),
    }
    return {
        "benchmark_id": f"calibration-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created_at": utc_now(),
        "kind": "calibration",
        "requested_minutes": minutes,
        "seeds_per_case": seeds,
        "parallel_processes": process_count,
        "cases": cases,
        "throughput_quantiles": rate_stats,
        "frontier_n32_throughput_quantiles": frontier_rate_stats,
        "growth_factors": growth_factors,
        "forecast": forecast,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "peak_rss_source": "resource.getrusage fallback before CLI hardware audit",
    }


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = str(report["benchmark_id"])
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    atomic_write_json(json_path, report)
    lines = [
        f"# Benchmark {stem}",
        "",
        f"- Created: {report['created_at']}",
        f"- Kind: {report['kind']}",
        f"- Peak RSS: {report['peak_rss_bytes']} bytes",
        "",
    ]
    if report["kind"] == "calibration":
        lines.extend(
            [
                "## Forecast",
                "",
                "```json",
                json.dumps(report["forecast"], indent=2, sort_keys=True),
                "```",
                "",
                "These are engineering throughput estimates, not a mathematical result.",
            ]
        )
    elif report["kind"] == "soak":
        duration_label = (
            "full two-hour gate"
            if float(report["requested_hours"]) >= 2
            else "short functional soak"
        )
        lines.extend(
            [
                "## Soak checks",
                "",
                f"- Duration gate pass: {report['duration_gate_pass']}",
                f"- RSS plateau pass: {report['rss_plateau_pass']}",
                f"- Pause/resume observed: {report['pause_resume_observed']}",
                f"- Dashboard responsive: {report['dashboard_responsive']}",
                f"- Candidate counter monotonic: {report['candidate_counter_monotonic']}",
                f"- Queues bounded: {report['queues_bounded']}",
                f"- Worker recycling gate: {report['recycling_gate_pass']}",
                f"- Database growth bounded: {report['database_growth_bounded']}",
                f"- Worker failures: {report['worker_failures']}",
                f"- Final status: {report['final_status']}",
                f"- Overall soak pass: {report['soak_pass']}",
                "",
                f"This report is the {duration_label}.",
            ]
        )
    elif report["kind"] == "mutation_cache":
        acceptance = report["acceptance"]
        lines.extend(
            [
                "## Issue #14 mutation-cache gates",
                "",
                (
                    "- Targeted operator time reduction: "
                    f"{report['targeted_operator_time_reduction_fraction']:.2%}"
                ),
                (
                    "- Workload throughput increase: "
                    f"{report['workload_throughput_increase_fraction']:.2%}"
                ),
                (
                    "- Uniform operator regression: "
                    f"{report['uniform_operator_regression_fraction']:.2%}"
                ),
                (
                    "- Logical trajectories equal: "
                    f"{report['logical_trajectories_equal']}"
                ),
                (
                    "- All acceptance gates pass: "
                    f"{all(acceptance.values())}"
                ),
                "",
                "Raw paired runs and fixed-size subphase aggregates are "
                "preserved in the JSON report.",
            ]
        )
    else:
        lines.extend(
            [
                "Raw samples and p50/p90/p95/max values are preserved in the JSON report.",
                "",
                "The C++ subprocess is retained as an independent verifier; whether it is",
                "used in a ranking loop must be decided from the measured Python/C++ timings.",
            ]
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def soak(
    workspace: Path,
    *,
    hours: float,
    order: int,
    workers: int,
) -> dict[str, Any]:
    """Run a bounded search soak and exercise pause/resume through control files."""

    if not math.isfinite(hours) or hours <= 0 or hours > 24:
        raise ValueError("hours must be between 0 and 24")
    duration = hours * 3600
    if workspace.exists() and not workspace.is_dir():
        raise ValueError("soak workspace must be a directory")
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("soak workspace must be empty")
    workspace.mkdir(parents=True, exist_ok=True)
    config = SearchConfig(
        workspace=workspace,
        order=order,
        workers=workers,
        wall_seconds=duration,
        state_seconds=min(2.0, max(0.1, duration / 40)),
        checkpoint_seconds=min(30.0, max(0.2, duration / 20)),
        worker_recycle_candidates=20_000,
        min_free_disk_bytes=1,
    )
    config.validate()
    from .web import create_server

    dashboard = create_server(workspace, "127.0.0.1", 0)
    dashboard_thread = Thread(target=dashboard.serve_forever, daemon=True)
    dashboard_thread.start()
    context = get_context("spawn")
    process = context.Process(target=run_search, args=(config,))
    try:
        process.start()
    except BaseException:
        dashboard.shutdown()
        dashboard.server_close()
        dashboard_thread.join(timeout=5)
        raise
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    paused = resumed = False
    paused_observed = resumed_observed = False
    candidates_at_resume: int | None = None
    dashboard_checks: list[dict[str, Any]] = []
    interval = min(5.0, max(0.1, duration / 100))
    grace_seconds = max(120, config.exact_timeout_seconds * 2 + 30)
    try:
        while (
            process.is_alive() and time.monotonic() - started < duration + grace_seconds
        ):
            elapsed = time.monotonic() - started
            state = read_json(workspace / "state.json", default={})
            if state:
                sample = {
                    "elapsed_seconds": elapsed,
                    "status": state.get("status"),
                    "rss_bytes": (
                        int(state.get("resources", {}).get("master_rss_bytes", 0))
                        + int(state.get("resources", {}).get("worker_rss_bytes", 0))
                    ),
                    "database_bytes": int(
                        state.get("resources", {}).get("database_bytes", 0)
                    ),
                    "disk_free_bytes": int(
                        state.get("resources", {}).get("disk_free_bytes", 0)
                    ),
                    "candidates": int(state.get("throughput", {}).get("candidates", 0)),
                    "candidates_per_second": float(
                        state.get("throughput", {}).get("candidates_per_second", 0)
                    ),
                    "worker_restarts": int(state.get("workers", {}).get("restarts", 0)),
                    "worker_failures": int(state.get("workers", {}).get("failed", 0)),
                    "telemetry_queue": state.get("queues", {}).get("telemetry_current"),
                    "telemetry_queue_max": state.get("queues", {}).get("telemetry_max"),
                    "exact_queue": state.get("queues", {}).get("exact_current"),
                }
                samples.append(sample)
                if paused and sample["status"] in {
                    "PAUSED",
                    "PAUSED_MEMORY_HIGH",
                }:
                    paused_observed = True
                if resumed and paused_observed and sample["status"] == "RUNNING":
                    resumed_observed = True
                dashboard_checks.append(_probe_dashboard(dashboard.server_address))
            if not paused and elapsed >= duration * 0.25:
                action = _write_control(workspace, "PAUSE")
                actions.append(action)
                paused = True
            if paused and not resumed and elapsed >= duration * 0.35:
                action = _write_control(workspace, "RESUME")
                actions.append(action)
                resumed = True
                candidates_at_resume = int(
                    state.get("throughput", {}).get("candidates", 0)
                )
            time.sleep(interval)
    except BaseException:
        if process.is_alive():
            _write_control(workspace, "STOP")
            process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        raise
    finally:
        dashboard.shutdown()
        dashboard.server_close()
        dashboard_thread.join(timeout=5)
    process.join(timeout=10)
    if process.is_alive():
        _write_control(workspace, "STOP")
        process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join()
    rss = [sample["rss_bytes"] for sample in samples if sample["rss_bytes"] > 0]
    split = max(1, len(rss) // 3)
    middle = rss[split : 2 * split] or rss
    final = rss[2 * split :] or rss
    middle_median = median(middle) if middle else 0
    final_median = median(final) if final else 0
    plateau_bound = middle_median * 1.2 + 32 * 1024 * 1024
    state = read_json(workspace / "state.json", default={})
    actual_seconds = time.monotonic() - started
    candidate_samples = [sample["candidates"] for sample in samples]
    database_samples = [sample["database_bytes"] for sample in samples]
    database_growth_bytes = (
        max(database_samples) - min(database_samples) if database_samples else 0
    )
    duration_gate_pass = actual_seconds >= duration
    pause_resume_observed = paused_observed and resumed_observed
    candidate_counter_monotonic = all(
        left <= right for left, right in zip(candidate_samples, candidate_samples[1:])
    )
    worker_failures = max(
        (sample["worker_failures"] for sample in samples),
        default=0,
    )
    dashboard_responsive = bool(dashboard_checks) and all(
        check["status"] == 200 for check in dashboard_checks
    )
    progress_after_resume = (
        candidates_at_resume is not None
        and bool(candidate_samples)
        and candidate_samples[-1] > candidates_at_resume
    )
    queues_bounded = bool(samples) and all(
        (
            sample["telemetry_queue"] is None
            or sample["telemetry_queue_max"] is None
            or int(sample["telemetry_queue"]) <= int(sample["telemetry_queue_max"])
        )
        and (sample["exact_queue"] is None or int(sample["exact_queue"]) <= 1)
        for sample in samples
    )
    recycling_observed = (
        max((sample["worker_restarts"] for sample in samples), default=0) > 0
    )
    recycling_gate_pass = recycling_observed or hours < 2
    database_growth_bounded = database_growth_bytes <= 64 * 1024 * 1024
    final_status = state.get("status", "TOOL_FAILURE")
    soak_pass = all(
        (
            duration_gate_pass,
            pause_resume_observed,
            candidate_counter_monotonic,
            progress_after_resume,
            dashboard_responsive,
            queues_bounded,
            recycling_gate_pass,
            database_growth_bounded,
            worker_failures == 0,
            bool(rss) and final_median <= plateau_bound,
            process.exitcode == 0,
            final_status in {"NO_RESULT_WITHIN_BUDGET", "COUNTEREXAMPLE_VERIFIED"},
        )
    )
    return {
        "benchmark_id": f"soak-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created_at": utc_now(),
        "kind": "soak",
        "requested_hours": hours,
        "actual_seconds": actual_seconds,
        "duration_gate_pass": duration_gate_pass,
        "order": order,
        "workers": workers,
        "samples": samples,
        "actions": actions,
        "pause_observed": paused_observed,
        "resume_observed": resumed_observed,
        "pause_resume_observed": pause_resume_observed,
        "progress_after_resume": progress_after_resume,
        "rss_plateau_pass": bool(rss) and final_median <= plateau_bound,
        "candidate_counter_monotonic": candidate_counter_monotonic,
        "queues_bounded": queues_bounded,
        "recycling_observed": recycling_observed,
        "recycling_gate_pass": recycling_gate_pass,
        "database_growth_bytes": database_growth_bytes,
        "database_growth_bounded": database_growth_bounded,
        "worker_failures": worker_failures,
        "dashboard_checks": dashboard_checks,
        "dashboard_responsive": dashboard_responsive,
        "queue_capacity": config.queue_capacity,
        "worker_recycle_candidates": config.worker_recycle_candidates,
        "final_status": final_status,
        "peak_rss_bytes": max(rss, default=0),
        "process_exitcode": process.exitcode,
        "soak_pass": soak_pass,
    }


def _probe_dashboard(address: tuple[str, int]) -> dict[str, Any]:
    started = time.perf_counter()
    connection = HTTPConnection(*address, timeout=2)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        response.read()
        return {
            "status": response.status,
            "elapsed_seconds": time.perf_counter() - started,
        }
    except OSError as error:
        return {
            "status": 0,
            "elapsed_seconds": time.perf_counter() - started,
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        connection.close()


def _write_control(workspace: Path, action: str) -> dict[str, Any]:
    return next_control(workspace, action)

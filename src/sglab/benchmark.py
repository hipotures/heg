from __future__ import annotations

from pathlib import Path
from multiprocessing import get_context
from random import Random
from statistics import median
from typing import Any, Callable, Iterable
import json
import math
import os
import platform
import resource
import sqlite3
import tempfile
import time

from .certification import verify_cpp
from .model import BitGraph
from .resources import current_rss_bytes, disk_free_bytes, recommended_workers, run_bounded
from .sat import tiny_cegar
from .state import atomic_write_json, utc_now
from .state import read_json
from .search import SearchConfig, run_search
from .targets.erdos_gyarfas import PLUGIN, verify_reference


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


def _measure(function: Callable[[], object], iterations: int) -> dict[str, Any]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        function()
        samples.append(time.perf_counter() - started)
    return {"unit": "seconds", "samples": samples, **quantiles(samples)}


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
    governor_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    return {
        "cpu_model": cpu_model,
        "logical_cpu_count": os.cpu_count(),
        "memory_total_bytes": memory_total,
        "kernel": platform.release(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "compiler": compiler.stdout.decode("utf-8", errors="replace").splitlines()[:2],
        "cpu_governor": governor_path.read_text().strip() if governor_path.exists() else None,
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
        "filesystem_free_bytes": disk_free_bytes(path),
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
    for n in orders:
        graph = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
        operations[f"edge_degree_n{n}"] = _measure(
            lambda graph=graph: (graph.has_edge(0, 1), graph.degree_sequence()),
            iterations,
        )
        operations[f"mutation_n{n}"] = _measure(
            lambda graph=graph: PLUGIN.mutate(graph, rng, {"mode": "cubic_first"}),
            iterations,
        )
        operations[f"score_n{n}"] = _measure(
            lambda graph=graph: PLUGIN.cheap_score(graph, 16),
            iterations,
        )
        operations[f"graph6_n{n}"] = _measure(
            lambda graph=graph: BitGraph.from_graph6(graph.to_graph6()),
            iterations,
        )
        operations[f"canonical_fallback_n{n}"] = _measure(
            lambda graph=graph: graph.stable_hash(),
            iterations,
        )
    exact_graph = PLUGIN.generate_seed(
        Random(99), {"order": 20, "mode": "cubic_first"}
    )
    operations["exact_python_n20"] = _measure(
        lambda: verify_reference(exact_graph), iterations
    )
    operations["exact_cpp_n20"] = _measure(
        lambda: verify_cpp(exact_graph, timeout_seconds=10), max(1, min(iterations, 3))
    )
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "bench.sqlite3"
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE metrics (a INTEGER, b REAL)")
        operations["sqlite_batch_100"] = _measure(
            lambda: _sqlite_batch(connection), iterations
        )
        connection.close()
        state_path = Path(directory) / "state.json"
        operations["state_serialization"] = _measure(
            lambda: atomic_write_json(
                state_path,
                {"status": "BENCHMARK", "workers": {"alive": 1}, "values": list(range(32))},
            ),
            iterations,
        )
    operations["tiny_cegar_iteration"] = _measure(lambda: tiny_cegar(4), iterations)
    return {
        "benchmark_id": f"micro-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created_at": utc_now(),
        "kind": "microbenchmark",
        "iterations": iterations,
        "operations": operations,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
    }


def _sqlite_batch(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO metrics VALUES (?, ?)",
        [(index, index / 10) for index in range(100)],
    )
    connection.commit()
    connection.execute("DELETE FROM metrics")
    connection.commit()


def calibrate(minutes: float) -> dict[str, Any]:
    if minutes <= 0 or minutes > 1440:
        raise ValueError("minutes must be between 0 and 1440")
    orders = (20, 24, 28, 32)
    algorithms = ("simulated_annealing", "iterated_local_search")
    seconds_per_case = minutes * 60 / (len(orders) * len(algorithms))
    cases: list[dict[str, Any]] = []
    for n in orders:
        for algorithm_index, algorithm in enumerate(algorithms):
            rng = Random(10_000 + n * 10 + algorithm_index)
            graph = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
            score = PLUGIN.cheap_score(graph, 32)
            best = score.ordering_key
            evaluated = accepted = legal = improvements = 0
            started = time.perf_counter()
            while time.perf_counter() - started < seconds_per_case:
                candidate = PLUGIN.mutate(graph, rng, {"mode": "cubic_first"})
                evaluated += 1
                if candidate == graph:
                    continue
                legal += 1
                candidate_score = PLUGIN.cheap_score(candidate, 32)
                take = candidate_score.ordering_key <= score.ordering_key
                if algorithm == "simulated_annealing" and not take:
                    take = rng.random() < 0.01
                elif algorithm == "iterated_local_search" and evaluated % 64 == 0:
                    take = True
                if take:
                    graph, score = candidate, candidate_score
                    accepted += 1
                if candidate_score.ordering_key < best:
                    best = candidate_score.ordering_key
                    improvements += 1
            elapsed = time.perf_counter() - started
            cases.append(
                {
                    "order": n,
                    "algorithm": algorithm,
                    "seed": 10_000 + n * 10 + algorithm_index,
                    "elapsed_seconds": elapsed,
                    "candidates": evaluated,
                    "candidates_per_second": evaluated / max(elapsed, 1e-9),
                    "legal_move_rate": legal / max(evaluated, 1),
                    "accepted_move_rate": accepted / max(evaluated, 1),
                    "improvements": improvements,
                    "best_score": list(best),
                    "rss_bytes": current_rss_bytes(),
                }
            )
    rates = [case["candidates_per_second"] for case in cases]
    rate_stats = quantiles(rates)
    by_order = {
        n: median(
            case["candidates_per_second"] for case in cases if case["order"] == n
        )
        for n in orders
    }
    growth_factors = {
        f"{left}_to_{right}": by_order[left] / max(by_order[right], 1e-9)
        for left, right in zip(orders, orders[1:])
    }
    workers = recommended_workers()
    daily = rate_stats["p50"] * 86400 * workers
    forecast = {
        "recommended_workers": workers,
        "24_hour_candidates": {
            "pessimistic": rate_stats["p50"] * 86400,
            "central": daily,
            "optimistic": rate_stats["p90"] * 86400 * workers,
        },
        "7_day_candidates": {
            "pessimistic": rate_stats["p50"] * 7 * 86400,
            "central": daily * 7,
            "optimistic": rate_stats["p90"] * 7 * 86400 * workers,
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
        "cases": cases,
        "throughput_quantiles": rate_stats,
        "growth_factors": growth_factors,
        "forecast": forecast,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
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
        lines.extend(
            [
                "## Soak checks",
                "",
                f"- RSS plateau pass: {report['rss_plateau_pass']}",
                f"- Pause/resume observed: {report['pause_resume_observed']}",
                f"- Final status: {report['final_status']}",
                "",
                "A short smoke soak does not substitute for the documented two-hour gate.",
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

    if hours <= 0 or hours > 24:
        raise ValueError("hours must be between 0 and 24")
    duration = hours * 3600
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
    context = get_context("spawn")
    process = context.Process(target=run_search, args=(config,))
    process.start()
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    paused = resumed = False
    interval = min(5.0, max(0.1, duration / 100))
    while process.is_alive() and time.monotonic() - started < duration + 30:
        elapsed = time.monotonic() - started
        state = read_json(workspace / "state.json", default={})
        if state:
            samples.append(
                {
                    "elapsed_seconds": elapsed,
                    "status": state.get("status"),
                    "rss_bytes": (
                        int(state.get("resources", {}).get("master_rss_bytes", 0))
                        + int(state.get("resources", {}).get("worker_rss_bytes", 0))
                    ),
                    "database_bytes": int(
                        state.get("resources", {}).get("database_bytes", 0)
                    ),
                }
            )
        if not paused and elapsed >= duration * 0.25:
            action = _write_control(workspace, "PAUSE")
            actions.append(action)
            paused = True
        if paused and not resumed and elapsed >= duration * 0.35:
            action = _write_control(workspace, "RESUME")
            actions.append(action)
            resumed = True
        time.sleep(interval)
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
    return {
        "benchmark_id": f"soak-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created_at": utc_now(),
        "kind": "soak",
        "requested_hours": hours,
        "order": order,
        "workers": workers,
        "samples": samples,
        "actions": actions,
        "pause_resume_observed": any(sample["status"] == "PAUSED" for sample in samples),
        "rss_plateau_pass": bool(rss) and final_median <= plateau_bound,
        "queue_capacity": config.queue_capacity,
        "worker_recycle_candidates": config.worker_recycle_candidates,
        "final_status": state.get("status", "TOOL_FAILURE"),
        "peak_rss_bytes": max(rss, default=0),
        "process_exitcode": process.exitcode,
    }


def _write_control(workspace: Path, action: str) -> dict[str, Any]:
    current = read_json(workspace / "control.json", default={"version": 0})
    request = {
        "version": int(current.get("version", 0)) + 1,
        "requested_at": utc_now(),
        "action": action,
    }
    atomic_write_json(workspace / "control.json", request)
    return request

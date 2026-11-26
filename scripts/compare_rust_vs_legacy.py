#!/usr/bin/env python3
"""Head-to-head comparison: legacy Python + C++ engine vs native Rust engine."""
from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path
from random import Random
from threading import Event
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sglab.locations import score_worker_path
from sglab.research.lanes import LaneSpec, _LaneKernel
from sglab.score_worker import PersistentScoreWorker
from sglab.targets.erdos_gyarfas import PLUGIN, forbidden_lengths

RUST_BIN = ROOT / "_build" / "sglab-rust-engine"
CPP_BIN = score_worker_path()


def _legacy_lane(args: tuple[int, str, int, int]) -> dict[str, object]:
    order, algorithm, evals, seed = args
    params = {
        "order": order,
        "batch_candidates": evals,
        "witness_cap": 64,
        "mutation_weights": {
            "uniform_two_edge_switch": 0.5,
            "forbidden_cycle_break_switch": 0.5,
        },
    }
    if algorithm == "simulated_annealing":
        params.update(
            {"temperature": 8.0, "cooling": 0.9995, "restart_threshold": 50_000}
        )
    else:
        params.update({"tabu_tenure": 64, "perturbation_interval": 200})

    spec = LaneSpec(
        lane_id=f"cmp-{algorithm}-{order}-{seed}",
        campaign_id="cmp-rust-vs-legacy",
        target="erdos_gyarfas",
        algorithm=algorithm,
        graph_family="connected_cubic",
        seed=seed,
        parameters=params,
        resource_share=1.0,
    )
    kernel = _LaneKernel(spec, None, None)
    try:
        t0 = time.perf_counter()
        out = kernel.run_batch(Event(), max_evaluations=evals, max_wall_seconds=120.0)
        wall = time.perf_counter() - t0
        return {
            "evaluated": int(out["evaluated"]),
            "wall_s": wall,
            "best_wc": dict(kernel.best_score.witness_counts),
            "best_weighted": kernel.best_score.weighted_penalty,
        }
    finally:
        kernel.close()


def _rust_search(order: int, algorithm: str, evals: int, workers: int, seed: int) -> dict[str, object]:
    proc = subprocess.run(
        [
            str(RUST_BIN),
            "search",
            "--order",
            str(order),
            "--mode",
            "cubic_first",
            "--algorithm",
            algorithm,
            "--evals",
            str(evals),
            "--workers",
            str(workers),
            "--cap",
            "64",
            "--seed",
            str(seed),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def compare_scorer_ipc() -> None:
    print("=== 1. Direct Scorer Comparison (300 cubic graphs/order, cap=64, nb=50_000) ===")
    with (
        PersistentScoreWorker(binary=CPP_BIN) as cpp_w,
        PersistentScoreWorker(binary=RUST_BIN) as rust_w,
    ):
        for n in (32, 50, 56, 60, 62, 64):
            rng = Random(20261126 + n * 1009)
            g = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
            graphs = []
            for i in range(300):
                if i % 25 == 0:
                    g = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
                else:
                    g = PLUGIN.mutate(g, rng, {"mode": "cubic_first"})
                graphs.append(g)
            lengths = forbidden_lengths(n)
            for g in graphs[:10]:
                cpp_w.score(g, lengths=lengths, limit=65, node_budget=50_000)
                rust_w.score(g, lengths=lengths, limit=65, node_budget=50_000)

            t0 = time.perf_counter()
            for g in graphs:
                cpp_w.score(g, lengths=lengths, limit=65, node_budget=50_000)
            cpp_sps = len(graphs) / (time.perf_counter() - t0)

            t0 = time.perf_counter()
            for g in graphs:
                rust_w.score(g, lengths=lengths, limit=65, node_budget=50_000)
            rust_ipc_sps = len(graphs) / (time.perf_counter() - t0)

            print(
                f"  n={n:2d} | C++ --serve (IPC): {cpp_sps:8.1f} ev/s | Rust --serve (IPC): {rust_ipc_sps:8.1f} ev/s | ratio={rust_ipc_sps/cpp_sps:.2f}x"
            )

    print("\n--- Rust native bench-score (zero IPC) ---")
    subprocess.run(
        [str(RUST_BIN), "bench-score", "--orders", "32,50,56,60,62,64", "--count", "300"],
        check=True,
    )


def compare_single_lane() -> None:
    print("\n=== 2. Full Search Loop: 1 Lane (Legacy Python+C++ vs Native Rust) ===")
    for alg in ("simulated_annealing", "iterated_local_search_tabu"):
        print(f"\nAlgorithm: {alg}")
        for n in (32, 50, 56, 60, 62, 64):
            leg = _legacy_lane((n, alg, 2000, 20261126 + n))
            leg_sps = leg["evaluated"] / leg["wall_s"]
            rust_evals = 20_000 if n != 64 else 10_000
            rst = _rust_search(n, alg, rust_evals, 1, 20261126 + n)
            rst_sps = float(rst["evals_per_second"])
            print(
                f"  n={n:2d} | Legacy Py+C++: {leg_sps:7.1f} ev/s | Native Rust: {rst_sps:9.1f} ev/s | Speedup: {rst_sps/leg_sps:5.2f}x | rust_best={rst['best_witness_counts']}"
            )


def compare_parallel_16core() -> None:
    print("\n=== 3. Parallel Scaling: Legacy Py+C++ vs Native Rust (1 / 8 / 16 workers, ILS-tabu) ===")
    ctx = get_context("spawn")
    for n in (50, 60, 64):
        print(f"\nOrder n={n}:")
        for workers in (1, 8, 16):
            leg_tasks = [
                (n, "iterated_local_search_tabu", 4000, 20261126 + n * 100 + i)
                for i in range(workers)
            ]
            t0 = time.perf_counter()
            with ctx.Pool(processes=workers) as pool:
                outs = pool.map(_legacy_lane, leg_tasks)
            leg_wall = time.perf_counter() - t0
            leg_sps = sum(o["evaluated"] for o in outs) / leg_wall

            rust_evals = 40_000 if n != 64 else 15_000
            rst = _rust_search(n, "iterated_local_search_tabu", rust_evals, workers, 20261126 + n * 100)
            rst_sps = float(rst["evals_per_second"])
            print(
                f"  workers={workers:2d} | Legacy Py+C++: {leg_sps:8.1f} ev/s | Native Rust: {rst_sps:10.1f} ev/s ({rst['total_evaluations']} ev in {rst['wall_seconds']:.2f}s) | Speedup: {rst_sps/leg_sps:5.2f}x"
            )


if __name__ == "__main__":
    if not RUST_BIN.is_file() or not CPP_BIN.is_file():
        raise SystemExit("Build both binaries first: make score-worker rust-engine")
    compare_scorer_ipc()
    compare_single_lane()
    compare_parallel_16core()

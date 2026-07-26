from __future__ import annotations

from pathlib import Path
from random import Random
from unittest.mock import patch
import os
import unittest

from sglab.locations import score_worker_path
from sglab.model import (
    CycleCountWorkspace,
    count_cycles_of_length_bounded,
)
from sglab.research.lanes import (
    FAST_GRAPH_KEY_SCHEME,
    LEGACY_GRAPH_KEY_SCHEME,
    LaneSpec,
    _LaneKernel,
    _NeverStop,
    _zobrist_graph_key,
    _zobrist_update_key,
)
from sglab.score_worker import PersistentScoreWorker
from sglab.targets.erdos_gyarfas import PLUGIN, forbidden_lengths


def _spec(*, evaluations: int = 200) -> LaneSpec:
    return LaneSpec(
        lane_id="lane-score-worker",
        campaign_id="campaign-score-worker",
        target="erdos_gyarfas",
        algorithm="iterated_local_search_tabu",
        graph_family="unrestricted_min_degree_3",
        seed=987654,
        parameters={
            "order": 32,
            "batch_candidates": evaluations,
            "witness_cap": 64,
            "tabu_tenure": 128,
            "perturbation_interval": 64,
        },
        resource_share=1.0,
    )


def _logical_checkpoint(kernel: _LaneKernel) -> tuple[object, ...]:
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


@unittest.skipUnless(
    score_worker_path().is_file(), "C++ score worker has not been built"
)
class PersistentScoreWorkerTests(unittest.TestCase):
    def test_cpp_counts_match_python_count_workspace(self) -> None:
        rng = Random(20260726)
        with PersistentScoreWorker() as worker:
            for order in (4, 8, 16, 32, 64, 96, 128):
                graph = PLUGIN.generate_seed(
                    rng, {"order": order, "mode": "cubic_first"}
                )
                for limit, budget in ((2, 1), (17, 4096), (65, 50000)):
                    response = worker.score(
                        graph,
                        limit=limit,
                        node_budget=budget,
                    )
                    self.assertFalse(response.dominated)
                    workspace = CycleCountWorkspace.for_order(order)
                    expected = []
                    for length in forbidden_lengths(order):
                        count, complete, nodes = (
                            count_cycles_of_length_bounded(
                                graph,
                                length,
                                limit,
                                budget,
                                workspace,
                            )
                        )
                        expected.append(
                            (length, count, complete, nodes)
                        )
                    self.assertEqual(
                        [
                            (
                                result.length,
                                result.count,
                                result.complete,
                                result.nodes,
                            )
                            for result in response.results
                        ],
                        expected,
                    )

    def test_worker_is_reused_and_closes(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(8), {"order": 32, "mode": "cubic_first"}
        )
        worker = PersistentScoreWorker()
        worker.start()
        pid = worker.pid
        self.assertIsNotNone(pid)
        worker.score(graph, limit=17, node_budget=4096)
        worker.score(graph, limit=17, node_budget=4096)
        self.assertEqual(worker.pid, pid)
        worker.close()
        self.assertIsNone(worker.pid)
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_cpp_and_python_backends_keep_same_trajectory(self) -> None:
        results = {}
        for backend in ("python", "cpp"):
            with patch.dict(
                os.environ,
                {
                    "SGLAB_SCORE_BACKEND": backend,
                    "SGLAB_SCORE_EARLY_EXIT": "0",
                    "SGLAB_FAST_DUPLICATE_KEY": "0",
                },
            ):
                kernel = _LaneKernel(_spec(), None, None)
                try:
                    metrics = kernel.run_batch(
                        _NeverStop(), max_evaluations=200
                    )
                    results[backend] = (
                        _logical_checkpoint(kernel),
                        metrics["accepted"],
                        metrics["improvements"],
                    )
                    if backend == "cpp":
                        self.assertGreaterEqual(
                            metrics["score_backend"]["python_audits"],
                            metrics["improvements"],
                        )
                finally:
                    kernel.close()
        self.assertEqual(results["python"], results["cpp"])

    def test_early_exit_preserves_trajectory(self) -> None:
        results = {}
        for enabled in ("0", "1"):
            with patch.dict(
                os.environ,
                {
                    "SGLAB_SCORE_BACKEND": "cpp",
                    "SGLAB_SCORE_EARLY_EXIT": enabled,
                    "SGLAB_FAST_DUPLICATE_KEY": "0",
                },
            ):
                kernel = _LaneKernel(_spec(), None, None)
                try:
                    metrics = kernel.run_batch(
                        _NeverStop(), max_evaluations=200
                    )
                    results[enabled] = (
                        _logical_checkpoint(kernel),
                        metrics["accepted"],
                        metrics["improvements"],
                        metrics["early_rejected"],
                    )
                finally:
                    kernel.close()
        self.assertEqual(results["0"][:3], results["1"][:3])
        self.assertEqual(results["0"][3], 0)
        self.assertGreater(results["1"][3], 0)

    def test_worker_crash_is_restarted_before_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SGLAB_SCORE_BACKEND": "cpp",
                "SGLAB_SCORE_EARLY_EXIT": "0",
            },
        ):
            kernel = _LaneKernel(_spec(evaluations=10), None, None)
            try:
                assert kernel.score_worker is not None
                assert kernel.score_worker.process is not None
                kernel.score_worker.process.kill()
                kernel.score_worker.process.wait(timeout=1)
                metrics = kernel.run_batch(
                    _NeverStop(), max_evaluations=10
                )
                backend = metrics["score_backend"]
                self.assertEqual(backend["effective"], "cpp")
                self.assertEqual(backend["worker_restarts"], 1)
                self.assertEqual(backend["fallbacks"], 0)
            finally:
                kernel.close()


class FastDuplicateKeyTests(unittest.TestCase):
    def test_mutation_delta_matches_full_zobrist_recount(self) -> None:
        rng = Random(77)
        graph = PLUGIN.generate_seed(
            rng, {"order": 32, "mode": "cubic_first"}
        )
        key = _zobrist_graph_key(graph)
        for _ in range(200):
            mutation = PLUGIN.mutate_with_delta(
                graph,
                rng,
                {
                    "mode": "cubic_first",
                    "mutation_operator": "uniform_two_edge_switch",
                },
            )
            if mutation.graph == graph:
                continue
            key = _zobrist_update_key(
                key,
                removed_edges=mutation.removed_edges,
                added_edges=mutation.added_edges,
            )
            graph = mutation.graph
            self.assertEqual(key, _zobrist_graph_key(graph))

    def test_legacy_checkpoint_keeps_legacy_tabu_scheme(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SGLAB_SCORE_BACKEND": "python",
                "SGLAB_FAST_DUPLICATE_KEY": "0",
            },
        ):
            original = _LaneKernel(_spec(evaluations=10), None, None)
            try:
                checkpoint = original.checkpoint(0)
            finally:
                original.close()
        self.assertEqual(
            checkpoint["duplicate_key_scheme"],
            LEGACY_GRAPH_KEY_SCHEME,
        )
        self.assertEqual(
            checkpoint["tabu_key_scheme"], "sha256_graph6_v1"
        )
        checkpoint.pop("duplicate_key_scheme")
        with patch.dict(
            os.environ,
            {
                "SGLAB_SCORE_BACKEND": "python",
                "SGLAB_FAST_DUPLICATE_KEY": "1",
            },
        ):
            restored = _LaneKernel(_spec(evaluations=10), checkpoint, None)
            try:
                self.assertEqual(
                    restored.tabu_key_scheme,
                    LEGACY_GRAPH_KEY_SCHEME,
                )
                restored.restart(123)
                self.assertEqual(
                    restored.tabu_key_scheme,
                    FAST_GRAPH_KEY_SCHEME,
                )
            finally:
                restored.close()

    def test_fork_inherits_parent_scheme_and_explicit_restart_upgrades(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "SGLAB_SCORE_BACKEND": "python",
                "SGLAB_FAST_DUPLICATE_KEY": "0",
            },
        ):
            original = _LaneKernel(_spec(evaluations=10), None, None)
            try:
                checkpoint = original.checkpoint(0)
            finally:
                original.close()
        with patch.dict(
            os.environ,
            {
                "SGLAB_SCORE_BACKEND": "python",
                "SGLAB_FAST_DUPLICATE_KEY": "1",
            },
        ):
            forked = _LaneKernel(
                _spec(evaluations=10),
                checkpoint,
                fork_seed=909,
            )
            try:
                self.assertEqual(
                    forked.tabu_key_scheme,
                    LEGACY_GRAPH_KEY_SCHEME,
                )
                forked.restart_from_checkpoint(checkpoint, seed=910)
                self.assertEqual(
                    forked.tabu_key_scheme,
                    FAST_GRAPH_KEY_SCHEME,
                )
            finally:
                forked.close()


if __name__ == "__main__":
    unittest.main()

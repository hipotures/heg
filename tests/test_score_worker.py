from __future__ import annotations

from pathlib import Path
from random import Random
from unittest.mock import patch
import unittest

from sglab.locations import score_worker_path
from sglab.model import BitGraph, find_cycles_of_length_bounded
from sglab.research.lanes import (
    FAST_GRAPH_KEY_SCHEME,
    LEGACY_GRAPH_KEY_SCHEME,
    LaneSpec,
    _LaneKernel,
    _NeverStop,
    _zobrist_graph_key,
    _zobrist_update_key,
)
from sglab.score_worker import PersistentScoreWorker, ScoreWorkerError
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


def _targeted_spec(*, evaluations: int = 300) -> LaneSpec:
    return LaneSpec(
        lane_id="lane-targeted-mutation-cache",
        campaign_id="campaign-score-worker",
        target="erdos_gyarfas",
        algorithm="simulated_annealing",
        graph_family="connected_cubic",
        seed=20260726,
        parameters={
            "order": 32,
            "batch_candidates": evaluations,
            "witness_cap": 64,
            "temperature": 1.0,
            "cooling": 0.995,
            "restart_threshold": 50_000,
            "mutation_weights": {
                "uniform_two_edge_switch": 0.0,
                "forbidden_cycle_break_switch": 1.0,
            },
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
    def test_missing_worker_fails_before_scoring(self) -> None:
        worker = PersistentScoreWorker(
            binary=Path("/definitely/missing/sglab-score-worker")
        )
        with self.assertRaisesRegex(
            ScoreWorkerError, "score worker is unavailable"
        ):
            worker.start()

    def test_cpp_counts_match_independent_witness_enumerator(self) -> None:
        rng = Random(20260726)
        with PersistentScoreWorker() as worker:
            for order in (4, 8, 16, 32, 64, 96, 128):
                graph = PLUGIN.generate_seed(
                    rng, {"order": order, "mode": "cubic_first"}
                )
                for limit, budget in ((2, 1), (17, 4096), (65, 50000)):
                    response = worker.score(
                        graph,
                        lengths=forbidden_lengths(order),
                        limit=limit,
                        node_budget=budget,
                    )
                    self.assertFalse(response.dominated)
                    expected = []
                    for length in forbidden_lengths(order):
                        witnesses, complete = (
                            find_cycles_of_length_bounded(
                                graph, length, limit, budget
                            )
                        )
                        expected.append(
                            (length, len(witnesses), complete)
                        )
                    self.assertEqual(
                        [
                            (
                                result.length,
                                result.count,
                                result.complete,
                            )
                            for result in response.results
                        ],
                        expected,
                    )

    def test_worker_counts_target_supplied_triangle_length(self) -> None:
        graph = BitGraph.from_edges(
            4,
            (
                (u, v)
                for u in range(4)
                for v in range(u + 1, 4)
            ),
        )
        with PersistentScoreWorker() as worker:
            response = worker.score(
                graph,
                lengths=(3,),
                limit=17,
                node_budget=4096,
            )
        self.assertEqual(
            tuple(
                (result.length, result.count, result.complete)
                for result in response.results
            ),
            ((3, 4, True),),
        )

    def test_worker_is_reused_and_closes(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(8), {"order": 32, "mode": "cubic_first"}
        )
        worker = PersistentScoreWorker()
        worker.start()
        pid = worker.pid
        self.assertIsNotNone(pid)
        worker.score(
            graph,
            lengths=forbidden_lengths(graph.n),
            limit=17,
            node_budget=4096,
        )
        worker.score(
            graph,
            lengths=forbidden_lengths(graph.n),
            limit=17,
            node_budget=4096,
        )
        self.assertEqual(worker.pid, pid)
        worker.close()
        self.assertIsNone(worker.pid)
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_lane_kernel_has_one_optimized_cpp_score_contract(self) -> None:
        kernel = _LaneKernel(_spec(), None, None)
        try:
            metrics = kernel.run_batch(
                _NeverStop(), max_evaluations=200
            )
            backend = metrics["score_backend"]
            self.assertEqual(backend["implementation"], "cpp")
            self.assertTrue(backend["early_exit_enabled"])
            self.assertEqual(
                backend["duplicate_key_scheme"],
                FAST_GRAPH_KEY_SCHEME,
            )
            self.assertNotIn("requested", backend)
            self.assertNotIn("effective", backend)
            self.assertNotIn("python_audits", backend)
            self.assertNotIn("fallbacks", backend)
            self.assertNotIn("parity_mismatches", backend)
        finally:
            kernel.close()

    def test_mutation_witness_cache_preserves_trajectory(self) -> None:
        results = {}
        profiles = {}
        for enabled in (False, True):
            kernel = _LaneKernel(
                _targeted_spec(),
                None,
                None,
                mutation_witness_cache=enabled,
            )
            try:
                metrics = kernel.run_batch(
                    _NeverStop(), max_evaluations=300
                )
                results[enabled] = (
                    _logical_checkpoint(kernel),
                    metrics["accepted"],
                    metrics["improvements"],
                    metrics["operator_statistics"],
                )
                profiles[enabled] = metrics["timing"][
                    "mutation_profile"
                ]
            finally:
                kernel.close()

        self.assertEqual(results[False], results[True])
        self.assertEqual(profiles[False]["witness_cache_hits"], 0)
        self.assertEqual(
            profiles[False]["witness_searches"],
            profiles[False]["targeted_evaluations"],
        )
        self.assertGreater(profiles[True]["witness_cache_hits"], 0)
        self.assertLess(
            profiles[True]["witness_searches"],
            profiles[False]["witness_searches"],
        )
        self.assertTrue(
            all(
                not isinstance(value, (dict, list))
                for value in profiles[True].values()
            )
        )

    def test_mutation_profile_can_be_disabled(self) -> None:
        kernel = _LaneKernel(
            _targeted_spec(evaluations=10),
            None,
            None,
            instrumentation_enabled=True,
            score_profiling_enabled=False,
        )
        try:
            metrics = kernel.run_batch(
                _NeverStop(), max_evaluations=10
            )
        finally:
            kernel.close()
        self.assertNotIn("mutation_profile", metrics["timing"])
        self.assertTrue(
            metrics["score_backend"]["mutation_witness_cache_enabled"]
        )

    def test_worker_crash_is_restarted_without_fallback(self) -> None:
        kernel = _LaneKernel(_spec(evaluations=10), None, None)
        try:
            assert kernel.score_worker.process is not None
            kernel.score_worker.process.kill()
            kernel.score_worker.process.wait(timeout=1)
            metrics = kernel.run_batch(
                _NeverStop(), max_evaluations=10
            )
            backend = metrics["score_backend"]
            self.assertEqual(backend["implementation"], "cpp")
            self.assertEqual(backend["worker_restarts"], 1)
            self.assertNotIn("fallbacks", backend)
        finally:
            kernel.close()

    def test_repeated_worker_failure_is_fail_closed(self) -> None:
        kernel = _LaneKernel(_spec(evaluations=10), None, None)
        try:
            with patch.object(
                kernel.score_worker,
                "score",
                side_effect=ScoreWorkerError("synthetic failure"),
            ):
                with self.assertRaisesRegex(
                    ScoreWorkerError,
                    "mandatory C\\+\\+ score worker failed",
                ):
                    kernel.run_batch(
                        _NeverStop(), max_evaluations=10
                    )
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
        original = _LaneKernel(_spec(evaluations=10), None, None)
        try:
            checkpoint = original.checkpoint(0)
        finally:
            original.close()
        graph = PLUGIN.generate_seed(
            Random(987654),
            {"order": 32, "mode": "unrestricted_min_degree_3"},
        )
        checkpoint["duplicate_key_scheme"] = LEGACY_GRAPH_KEY_SCHEME
        checkpoint["tabu_key_scheme"] = "sha256_graph6_v1"
        checkpoint["tabu"] = [graph.stable_hash()]
        self.assertEqual(
            checkpoint["duplicate_key_scheme"],
            LEGACY_GRAPH_KEY_SCHEME,
        )
        self.assertEqual(
            checkpoint["tabu_key_scheme"], "sha256_graph6_v1"
        )
        checkpoint.pop("duplicate_key_scheme")
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
        original = _LaneKernel(_spec(evaluations=10), None, None)
        try:
            checkpoint = original.checkpoint(0)
        finally:
            original.close()
        checkpoint["duplicate_key_scheme"] = LEGACY_GRAPH_KEY_SCHEME
        checkpoint["tabu_key_scheme"] = "sha256_graph6_v1"
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

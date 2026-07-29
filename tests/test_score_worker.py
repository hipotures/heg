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
from sglab.score_worker import (
    CycleCountResult,
    PersistentScoreWorker,
    ScoreWorkerError,
)
from sglab.targets.base import GraphValidationContext
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


def _legacy_forbidden_witness_edge_choices(
    graph: BitGraph,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    witnesses = []
    for length in forbidden_lengths(graph.n):
        found, _complete = find_cycles_of_length_bounded(
            graph, length, 2, 4_096
        )
        witnesses.extend(found[:1])
    return tuple(
        tuple(
            tuple(
                sorted(
                    (
                        witness[index],
                        witness[(index + 1) % len(witness)],
                    )
                )
            )
            for index in range(len(witness))
        )
        for witness in witnesses
    )


class DirectMutationWitnessContextTests(unittest.TestCase):
    def test_direct_context_reuses_and_replaces_one_graph_entry(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(14), {"order": 30, "mode": "cubic_first"}
        )
        replacement = PLUGIN.generate_seed(
            Random(15), {"order": 30, "mode": "cubic_first"}
        )
        profile = PLUGIN.new_mutation_profile()
        context = PLUGIN.new_mutation_context()
        config = {
            "mode": "cubic_first",
            "mutation_operator": "forbidden_cycle_break_switch",
            "forbidden_witness_context": context,
            "mutation_profile": profile,
        }

        PLUGIN.mutate_with_delta(graph, Random(1), config)
        PLUGIN.mutate_with_delta(graph, Random(2), config)
        self.assertEqual(profile.witness_searches, 1)
        self.assertEqual(profile.witness_cache_lookups, 2)
        self.assertEqual(profile.witness_cache_hits, 1)
        self.assertEqual(profile.witness_cache_misses, 1)

        PLUGIN.mutate_with_delta(replacement, Random(3), config)
        PLUGIN.mutate_with_delta(replacement, Random(4), config)
        self.assertEqual(profile.witness_searches, 2)
        self.assertEqual(profile.witness_cache_lookups, 4)
        self.assertEqual(profile.witness_cache_hits, 2)
        self.assertEqual(profile.witness_cache_misses, 2)
        self.assertIs(context._graph, replacement)

        context.invalidate()
        self.assertIsNone(context._graph)
        self.assertEqual(context._choices, ())
        PLUGIN.mutate_with_delta(replacement, Random(5), config)
        self.assertEqual(profile.witness_searches, 3)
        self.assertEqual(profile.witness_cache_misses, 3)

    def test_direct_context_preserves_candidates_and_rng(self) -> None:
        initial = PLUGIN.generate_seed(
            Random(140), {"order": 30, "mode": "cubic_first"}
        )
        uncached_graph = initial
        cached_graph = initial
        uncached_rng = Random(141)
        cached_rng = Random(141)
        context = PLUGIN.new_mutation_context()
        uncached_candidates = []
        cached_candidates = []

        for evaluation in range(100):
            uncached = PLUGIN.mutate_with_delta(
                uncached_graph,
                uncached_rng,
                {
                    "mode": "cubic_first",
                    "mutation_operator": "forbidden_cycle_break_switch",
                },
            )
            cached = PLUGIN.mutate_with_delta(
                cached_graph,
                cached_rng,
                {
                    "mode": "cubic_first",
                    "mutation_operator": "forbidden_cycle_break_switch",
                    "forbidden_witness_context": context,
                },
            )
            uncached_candidates.append(uncached)
            cached_candidates.append(cached)
            self.assertEqual(uncached_rng.getstate(), cached_rng.getstate())
            if evaluation % 3 == 0:
                uncached_graph = uncached.graph
                cached_graph = cached.graph

        self.assertEqual(uncached_candidates, cached_candidates)
        self.assertEqual(uncached_graph, cached_graph)

    def test_limit_one_preserves_legacy_first_witness_choices(self) -> None:
        for order, seed in ((8, 81), (16, 161), (30, 301)):
            graph = PLUGIN.generate_seed(
                Random(seed),
                {"order": order, "mode": "cubic_first"},
            )
            self.assertEqual(
                PLUGIN.forbidden_witness_edge_choices(graph),
                _legacy_forbidden_witness_edge_choices(graph),
            )

    def test_empty_choices_are_cached_and_preserve_noop_rng(self) -> None:
        graph = BitGraph.from_edges(
            5, ((0, 1), (1, 2), (2, 3), (3, 4), (0, 4))
        )
        profile = PLUGIN.new_mutation_profile()
        context = PLUGIN.new_mutation_context()
        rng = Random(51)
        initial_rng_state = rng.getstate()
        config = {
            "mode": "cubic_first",
            "mutation_operator": "forbidden_cycle_break_switch",
            "forbidden_witness_context": context,
            "mutation_profile": profile,
        }

        first = PLUGIN.mutate_with_delta(graph, rng, config)
        second = PLUGIN.mutate_with_delta(graph, rng, config)

        self.assertIs(first.graph, graph)
        self.assertIs(second.graph, graph)
        self.assertEqual(rng.getstate(), initial_rng_state)
        self.assertEqual(profile.witness_searches, 1)
        self.assertEqual(profile.witness_cache_hits, 1)

    def test_subphase_profile_is_fixed_size_and_accounted(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(61), {"order": 30, "mode": "cubic_first"}
        )
        profile = PLUGIN.new_mutation_profile()
        context = PLUGIN.new_mutation_context()
        config = {
            "mode": "cubic_first",
            "mutation_operator": "forbidden_cycle_break_switch",
            "forbidden_witness_context": context,
            "mutation_profile": profile,
        }

        PLUGIN.mutate_with_delta(graph, Random(62), config)
        PLUGIN.mutate_with_delta(graph, Random(63), config)
        payload = profile.payload(cache_enabled=True)

        self.assertEqual(payload["witness_cache_lookups"], 2)
        self.assertEqual(payload["witness_cache_hits"], 1)
        self.assertEqual(payload["witness_cache_misses"], 1)
        self.assertEqual(payload["witness_searches"], 1)
        self.assertEqual(payload["witness_search_cycle_4_calls"], 1)
        self.assertEqual(payload["witness_search_cycle_8_calls"], 1)
        self.assertEqual(payload["witness_search_cycle_16_calls"], 1)
        self.assertEqual(payload["witness_search_cycle_32_calls"], 0)
        self.assertGreater(payload["witness_search_cycle_4_nodes"], 0)
        self.assertGreater(payload["switch_attempts"], 0)
        self.assertGreaterEqual(payload["partner_edge_sampling_ns"], 0)
        self.assertGreaterEqual(payload["candidate_construction_ns"], 0)
        self.assertGreaterEqual(payload["connectivity_validation_ns"], 0)
        self.assertTrue(
            all(
                not isinstance(value, (dict, list))
                for value in payload.values()
            )
        )


class ValidatedScoreAssemblyTests(unittest.TestCase):
    def test_bound_validation_context_preserves_score_and_rejects_other_graph(
        self,
    ) -> None:
        graph = PLUGIN.generate_seed(
            Random(71), {"order": 30, "mode": "cubic_first"}
        )
        other = PLUGIN.generate_seed(
            Random(72), {"order": 30, "mode": "cubic_first"}
        )
        results = tuple(
            CycleCountResult(
                length=length,
                count=0,
                complete=True,
                nodes=0,
                elapsed_ns=0,
            )
            for length in forbidden_lengths(graph.n)
        )
        context = GraphValidationContext(graph, PLUGIN.validate_graph(graph))

        ordinary = PLUGIN.score_from_cycle_counts(graph, 64, results, None)
        prepared = PLUGIN.score_from_cycle_counts(
            graph,
            64,
            results,
            None,
            validation_context=context,
        )

        self.assertEqual(prepared, ordinary)
        with self.assertRaisesRegex(ValueError, "different graph"):
            PLUGIN.score_from_cycle_counts(
                other,
                64,
                results,
                None,
                validation_context=context,
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

    def test_worker_cutoff_boundaries_and_python_timings(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(73), {"order": 30, "mode": "cubic_first"}
        )
        lengths = forbidden_lengths(graph.n)
        with PersistentScoreWorker() as worker:
            full = worker.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
                profile_timing=True,
            )
            score = PLUGIN.score_from_cycle_counts(
                graph, 64, full.results, None
            )
            cutoff = (
                sum(count for _, count in score.witness_counts),
                score.weighted_penalty,
                score.simplicity,
            )
            inclusive = worker.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
                cutoff=cutoff,
                cutoff_inclusive=True,
            )
            exclusive = worker.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
                cutoff=cutoff,
                cutoff_inclusive=False,
            )
            compact_exclusive = worker.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
                cutoff=cutoff,
                cutoff_inclusive=False,
                compact_dominated=True,
            )

        self.assertTrue(inclusive.dominated)
        self.assertFalse(exclusive.dominated)
        self.assertEqual(
            tuple(
                (result.length, result.count, result.complete, result.nodes)
                for result in exclusive.results
            ),
            tuple(
                (result.length, result.count, result.complete, result.nodes)
                for result in full.results
            ),
        )
        self.assertFalse(compact_exclusive.dominated)
        self.assertEqual(
            tuple(
                (result.length, result.count, result.complete, result.nodes)
                for result in compact_exclusive.results
            ),
            tuple(
                (result.length, result.count, result.complete, result.nodes)
                for result in exclusive.results
            ),
        )
        self.assertIsNotNone(full.timing)
        assert full.timing is not None
        self.assertGreaterEqual(full.timing.request_packing_ns, 0)
        self.assertGreaterEqual(full.timing.request_write_ns, 0)
        self.assertGreaterEqual(full.timing.response_read_ns, 0)
        self.assertGreaterEqual(full.timing.response_parsing_ns, 0)
        self.assertGreaterEqual(
            full.timing.worker_roundtrip_ns,
            full.timing.request_packing_ns
            + full.timing.request_write_ns
            + full.timing.response_read_ns
            + full.timing.response_parsing_ns,
        )

    def test_worker_can_prove_cutoff_from_longest_cycle_first(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(101), {"order": 30, "mode": "cubic_first"}
        )
        with (
            PersistentScoreWorker() as worker,
            PersistentScoreWorker(
                cutoff_longest_first=False
            ) as ascending_worker,
        ):
            full = worker.score(
                graph,
                lengths=forbidden_lengths(graph.n),
                limit=65,
                node_budget=50_000,
            )
            dominated = worker.score(
                graph,
                lengths=forbidden_lengths(graph.n),
                limit=65,
                node_budget=50_000,
                cutoff=(64, 256, graph.size()),
                cutoff_inclusive=True,
            )
            compact = worker.score(
                graph,
                lengths=forbidden_lengths(graph.n),
                limit=65,
                node_budget=50_000,
                cutoff=(64, 256, graph.size()),
                cutoff_inclusive=True,
                compact_dominated=True,
            )
            ascending = ascending_worker.score(
                graph,
                lengths=forbidden_lengths(graph.n),
                limit=65,
                node_budget=50_000,
                cutoff=(64, 256, graph.size()),
                cutoff_inclusive=True,
            )
        full_score = PLUGIN.score_from_cycle_counts(
            graph,
            64,
            full.results,
            None,
        )
        self.assertGreaterEqual(
            full_score.ordering_key,
            (0, 64, 256, 0, graph.size()),
        )
        self.assertTrue(dominated.dominated)
        self.assertEqual(
            tuple(result.length for result in dominated.results),
            (16,),
        )
        self.assertTrue(compact.dominated)
        self.assertEqual(compact.results, ())
        self.assertTrue(ascending.dominated)
        self.assertEqual(
            tuple(result.length for result in ascending.results),
            (4, 8, 16),
        )

    def test_worker_rejects_compact_response_without_cutoff(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(101), {"order": 30, "mode": "cubic_first"}
        )
        with PersistentScoreWorker() as worker:
            with self.assertRaisesRegex(
                ValueError,
                "compact dominated responses require a cutoff",
            ):
                worker.score(
                    graph,
                    lengths=forbidden_lengths(graph.n),
                    limit=65,
                    node_budget=50_000,
                    compact_dominated=True,
                )

    def test_worker_request_plan_cache_is_one_entry_and_optional(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(101), {"order": 30, "mode": "cubic_first"}
        )
        lengths = forbidden_lengths(graph.n)
        with (
            PersistentScoreWorker() as cached,
            PersistentScoreWorker(
                prepared_request_cache_enabled=False
            ) as uncached,
        ):
            cached.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
            )
            first_plan = cached._prepared_request_plan
            assert first_plan is not None
            cached.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
            )
            self.assertIs(cached._prepared_request_plan, first_plan)
            cached.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=49_999,
            )
            self.assertIsNot(cached._prepared_request_plan, first_plan)

            uncached.score(
                graph,
                lengths=lengths,
                limit=65,
                node_budget=50_000,
            )
            self.assertIsNone(uncached._prepared_request_plan)

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
        self.assertEqual(
            profiles[True]["witness_cache_lookups"],
            profiles[True]["witness_cache_hits"]
            + profiles[True]["witness_cache_misses"],
        )
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

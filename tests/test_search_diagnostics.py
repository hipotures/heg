from __future__ import annotations

from unittest.mock import patch
from random import Random
import unittest

from sglab.model import find_cycles_of_length_bounded
from sglab.research.lanes import (
    LaneSpec,
    _LaneKernel,
    _NeverStop,
    run_bounded_lane_batch,
)
from sglab.targets import TARGETS


def _spec(*, evaluations: int = 1_000) -> LaneSpec:
    return LaneSpec(
        lane_id="lane-diagnostics",
        campaign_id="diagnostic-tests",
        target="erdos_gyarfas",
        algorithm="iterated_local_search_tabu",
        graph_family="connected_cubic",
        seed=17,
        parameters={
            "order": 10,
            "batch_candidates": evaluations,
            "witness_cap": 16,
            "tabu_tenure": 32,
            "perturbation_interval": 50,
        },
        resource_share=1.0,
    )


def _random_restart_spec(*, evaluations: int = 400) -> LaneSpec:
    return LaneSpec(
        lane_id="lane-independent-samples",
        campaign_id="diagnostic-tests",
        target="erdos_gyarfas",
        algorithm="random_restart",
        graph_family="connected_cubic",
        seed=29,
        parameters={
            "order": 16,
            "batch_candidates": evaluations,
            "witness_cap": 16,
        },
        resource_share=1.0,
        seed_lineage=(29,),
    )


class SearchDiagnosticsTests(unittest.TestCase):
    def test_random_restart_uses_independent_sample_provenance(self) -> None:
        optimized = run_bounded_lane_batch(
            _random_restart_spec(),
            max_evaluations=400,
            max_wall_seconds=10,
            independent_sample_provenance=True,
        )
        legacy = run_bounded_lane_batch(
            _random_restart_spec(),
            max_evaluations=400,
            max_wall_seconds=10,
            independent_sample_provenance=False,
        )
        self.assertEqual(
            optimized["best_graph6"], legacy["best_graph6"]
        )
        self.assertEqual(
            optimized["best_score"], legacy["best_score"]
        )
        self.assertEqual(
            optimized["score_trajectory_summary"],
            legacy["score_trajectory_summary"],
        )
        self.assertEqual(
            optimized["checkpoint"]["rng_state"],
            legacy["checkpoint"]["rng_state"],
        )
        self.assertEqual(
            optimized["mutation_ancestry"][
                "global_record_improvements"
            ],
            [],
        )
        provenance = optimized["candidate_provenance"]
        self.assertEqual(
            provenance["provenance_kind"], "independent_sample"
        )
        self.assertEqual(provenance["seed_lineage"], [29])
        self.assertGreater(provenance["evaluation_index"], 0)
        self.assertEqual(
            optimized["checkpoint"]["current_provenance"][
                "provenance_kind"
            ],
            "independent_sample",
        )

    def test_independent_sample_checkpoint_resume_continuation_is_exact(
        self,
    ) -> None:
        spec = _random_restart_spec(evaluations=200)
        original = _LaneKernel(spec, None, None)
        try:
            initial = original.checkpoint(0)
            original.run_batch(
                _NeverStop(),
                max_evaluations=200,
                source_checkpoint_id=initial["checkpoint_id"],
            )
            midpoint = original.checkpoint(0)
            original.run_batch(
                _NeverStop(),
                max_evaluations=200,
                source_checkpoint_id=midpoint["checkpoint_id"],
            )
            expected = original.checkpoint(0)
        finally:
            original.close()
        restored = _LaneKernel(spec, midpoint, None)
        try:
            restored.run_batch(
                _NeverStop(),
                max_evaluations=200,
                source_checkpoint_id=midpoint["checkpoint_id"],
            )
            actual = restored.checkpoint(0)
        finally:
            restored.close()
        for field in (
            "graph6",
            "score",
            "best_graph6",
            "best_score",
            "rng_state",
            "algorithm_evaluated",
            "high_water",
            "current_candidate_id",
            "best_candidate_id",
            "current_provenance",
            "best_provenance",
        ):
            self.assertEqual(actual[field], expected[field], field)

    def test_ancestry_is_bounded_and_parent_child_ids_correlate(self) -> None:
        result = run_bounded_lane_batch(
            _spec(),
            max_evaluations=1_000,
            max_wall_seconds=10,
        )
        ancestry = result["mutation_ancestry"]
        lineage = ancestry["final_best_ancestry"]
        self.assertLessEqual(len(lineage), 64)
        self.assertEqual(ancestry["limit_per_retained_candidate"], 64)
        self.assertEqual(
            ancestry["rejected_non_record_candidates_stored"], 0
        )
        self.assertGreater(len(lineage), 0)
        for parent, child in zip(lineage, lineage[1:]):
            self.assertEqual(
                child["parent_candidate_id"], parent["candidate_id"]
            )
        self.assertEqual(
            lineage[-1]["candidate_id"],
            result["best_candidate_identifier"],
        )
        self.assertTrue(
            all(
                record["global_record"]
                for record in ancestry["global_record_improvements"]
            )
        )
        checkpoint = result["checkpoint"]
        accepted_tail = checkpoint["accepted_ancestry"]
        self.assertEqual(len(accepted_tail), 64)
        self.assertLessEqual(len(checkpoint["best_ancestry"]), 64)
        for parent, child in zip(accepted_tail, accepted_tail[1:]):
            self.assertEqual(
                child["parent_candidate_id"], parent["candidate_id"]
            )

    def test_timing_counters_are_non_overlapping_and_consistent(self) -> None:
        timing = run_bounded_lane_batch(
            _spec(evaluations=200),
            max_evaluations=200,
            max_wall_seconds=10,
        )["timing"]
        counters = timing["counters_seconds"]
        for name in (
            "mutation_generation",
            "graph_validation",
            "witness_counting",
            "score_calculation",
            "duplicate_detection",
            "tabu_bookkeeping",
            "telemetry_construction",
            "sqlite_persistence",
            "exact_final_verification",
        ):
            self.assertIn(name, counters)
            self.assertGreaterEqual(counters[name], 0)
        self.assertAlmostEqual(
            timing["accounted_search_seconds"]
            + timing["unattributed_search_seconds"],
            timing["search_loop_seconds"],
            places=9,
        )
        self.assertAlmostEqual(
            timing["measured_total_seconds"],
            timing["search_loop_seconds"]
            + counters["telemetry_construction"]
            + counters["sqlite_persistence"]
            + counters["exact_final_verification"],
            places=9,
        )
        profile = timing["score_profile"]
        self.assertEqual(
            sum(
                int(profile[f"cycle_{length}_ns"])
                for length in (4, 8)
            ),
            round(counters["witness_counting"] * 1_000_000_000),
        )
        self.assertGreater(profile["cycle_4_nodes"], 0)
        self.assertGreater(profile["cycle_8_nodes"], 0)

    def test_score_profiling_can_be_disabled_without_changing_search(
        self,
    ) -> None:
        enabled = run_bounded_lane_batch(
            _spec(evaluations=200),
            max_evaluations=200,
            max_wall_seconds=10,
            score_profiling_enabled=True,
        )
        with patch(
            "sglab.targets.erdos_gyarfas.perf_counter_ns",
            side_effect=AssertionError("score profiling entered disabled path"),
        ):
            disabled = run_bounded_lane_batch(
                _spec(evaluations=200),
                max_evaluations=200,
                max_wall_seconds=10,
                score_profiling_enabled=False,
            )
        self.assertNotIn("score_profile", disabled["timing"])
        self.assertEqual(enabled["best_graph6"], disabled["best_graph6"])
        self.assertEqual(enabled["best_score"], disabled["best_score"])
        self.assertEqual(
            enabled["score_trajectory_summary"],
            disabled["score_trajectory_summary"],
        )

    def test_disabled_instrumentation_preserves_result_and_hot_path(
        self,
    ) -> None:
        enabled = run_bounded_lane_batch(
            _spec(),
            max_evaluations=1_000,
            max_wall_seconds=10,
        )
        with (
            patch(
                "sglab.research.lanes.time.perf_counter_ns",
                side_effect=AssertionError("timing entered disabled hot path"),
            ),
            patch(
                "sglab.research.lanes._mutation_record",
                side_effect=AssertionError("ancestry entered disabled hot path"),
            ),
        ):
            disabled = run_bounded_lane_batch(
                _spec(),
                max_evaluations=1_000,
                max_wall_seconds=10,
                instrumentation_enabled=False,
            )
        self.assertFalse(disabled["timing"]["enabled"])
        self.assertEqual(enabled["best_graph6"], disabled["best_graph6"])
        self.assertEqual(enabled["best_score"], disabled["best_score"])
        self.assertEqual(
            enabled["score_trajectory_summary"],
            disabled["score_trajectory_summary"],
        )
        self.assertEqual(
            enabled["evaluation_count"], disabled["evaluation_count"]
        )
        self.assertGreater(
            disabled["throughput"],
            enabled["throughput"] * 0.5,
            "disabled diagnostics regressed throughput by more than 50%",
        )

    def test_operator_weights_are_applied_and_reported(self) -> None:
        uniform_spec = _spec(evaluations=200)
        uniform_spec.parameters["mutation_weights"] = {
            "uniform_two_edge_switch": 1.0,
            "forbidden_cycle_break_switch": 0.0,
        }
        targeted_spec = _spec(evaluations=200)
        targeted_spec.parameters["mutation_weights"] = {
            "uniform_two_edge_switch": 0.0,
            "forbidden_cycle_break_switch": 1.0,
        }
        uniform = run_bounded_lane_batch(
            uniform_spec, max_evaluations=200, max_wall_seconds=10
        )
        targeted = run_bounded_lane_batch(
            targeted_spec, max_evaluations=200, max_wall_seconds=10
        )
        self.assertEqual(
            set(uniform["operator_statistics"]["mutation_operators"]),
            {"uniform_two_edge_switch"},
        )
        self.assertEqual(
            set(targeted["operator_statistics"]["mutation_operators"]),
            {"forbidden_cycle_break_switch"},
        )
        self.assertEqual(
            uniform["operator_statistics"]["mutation_operators"][
                "uniform_two_edge_switch"
            ]["uses"],
            200,
        )
        self.assertEqual(
            targeted["operator_statistics"]["mutation_operators"][
                "forbidden_cycle_break_switch"
            ]["uses"],
            200,
        )

    def test_targeted_switch_removes_a_forbidden_witness_edge_safely(
        self,
    ) -> None:
        plugin = TARGETS["erdos_gyarfas"]
        graph = plugin.generate_seed(
            Random(17), {"order": 20, "mode": "cubic_first"}
        )
        witness_edges = set()
        for length in plugin.forbidden_lengths(graph.n):
            witnesses, _complete = find_cycles_of_length_bounded(
                graph, length, 64, 50_000
            )
            for witness in witnesses:
                witness_edges.update(
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
        candidate = graph
        for seed in range(64):
            candidate = plugin.mutate(
                graph,
                Random(seed),
                {
                    "mode": "cubic_first",
                    "mutation_operator": "forbidden_cycle_break_switch",
                },
            )
            if candidate != graph:
                break
        self.assertNotEqual(candidate, graph)
        removed = set(graph.edges()) - set(candidate.edges())
        self.assertEqual(len(removed), 2)
        self.assertTrue(removed & witness_edges)
        self.assertTrue(candidate.is_connected())
        self.assertTrue(
            all(candidate.degree(vertex) == 3 for vertex in range(candidate.n))
        )


if __name__ == "__main__":
    unittest.main()

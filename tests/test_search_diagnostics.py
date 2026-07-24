from __future__ import annotations

from unittest.mock import patch
import unittest

from sglab.research.lanes import LaneSpec, run_bounded_lane_batch


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
            "restart_threshold": 1_000,
            "promotion_penalty": 10,
        },
        resource_share=1.0,
    )


class SearchDiagnosticsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

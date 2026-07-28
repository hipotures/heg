from __future__ import annotations

from random import Random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy
import json
import sqlite3
import tempfile
import unittest

from sglab.research.diagnostics import ScientificActionDispatcher
from sglab.research.lanes import (
    SEED_ATTEMPT_BUCKET_UPPER_BOUNDS,
    SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS,
    LaneSpec,
    _LaneKernel,
    _NeverStop,
)
from sglab.targets.erdos_gyarfas import PLUGIN
from sglab.targets.base import SeedGenerationTrace


def _spec(
    *,
    algorithm: str = "random_restart",
    order: int = 10,
    seed: int = 17,
    restart_threshold: int = 100,
    graph_family: str = "connected_cubic",
) -> LaneSpec:
    parameters: dict[str, object] = {
        "order": order,
        "batch_candidates": 200,
        "witness_cap": 16,
    }
    if algorithm == "simulated_annealing":
        parameters.update(
            {
                "temperature": 1.0,
                "cooling": 0.99,
                "restart_threshold": restart_threshold,
            }
        )
    return LaneSpec(
        lane_id=f"lane-seed-{algorithm}-{order}",
        campaign_id="seed-telemetry-tests",
        target="erdos_gyarfas",
        algorithm=algorithm,
        graph_family=graph_family,
        seed=seed,
        parameters=parameters,
        resource_share=1.0,
        seed_lineage=(seed,),
    )


class _ExhaustingRandom:
    def shuffle(self, values: list[int]) -> None:
        return None

    def choice(self, values: list[int]) -> int:
        return values[0]


class _BrokenRandom:
    def shuffle(self, values: list[int]) -> None:
        raise RuntimeError("injected generator failure")


class SeedGenerationTraceTests(unittest.TestCase):
    def test_first_attempt_success_and_invalid_configuration(self) -> None:
        trace = SeedGenerationTrace()
        graph = PLUGIN.generate_seed(
            Random(0),
            {"order": 10, "mode": "cubic_first"},
            trace=trace,
        )
        self.assertEqual(graph.n, 10)
        self.assertEqual(trace.attempts, 1)
        self.assertEqual(trace.retry_budget, 200)
        self.assertIsNone(trace.failure_category)

        invalid = SeedGenerationTrace()
        with self.assertRaises(ValueError):
            PLUGIN.generate_seed(
                Random(1),
                {"order": 9, "mode": "cubic_first"},
                trace=invalid,
            )
        self.assertEqual(
            invalid.failure_category, "invalid_generator_configuration"
        )
        self.assertEqual(invalid.attempts, 0)

    def test_forced_retries_report_exact_attempt_count(self) -> None:
        cubic = SeedGenerationTrace()
        cubic_graph = PLUGIN.generate_seed(
            Random(3),
            {"order": 10, "mode": "cubic_first"},
            trace=cubic,
        )
        self.assertEqual(cubic_graph.n, 10)
        self.assertEqual(cubic.attempts, 2)

        mixed = SeedGenerationTrace()
        mixed_graph = PLUGIN.generate_seed(
            Random(0),
            {
                "order": 5,
                "mode": "minimal_structure_mixed_degree",
            },
            trace=mixed,
        )
        self.assertEqual(mixed_graph.n, 5)
        self.assertEqual(mixed.attempts, 2)

    def test_budget_exhaustion_and_other_failure_are_categorized(self) -> None:
        exhausted = SeedGenerationTrace()
        with self.assertRaises(RuntimeError):
            PLUGIN.generate_seed(
                _ExhaustingRandom(),  # type: ignore[arg-type]
                {"order": 6, "mode": "cubic_first"},
                trace=exhausted,
            )
        self.assertEqual(exhausted.attempts, 200)
        self.assertEqual(exhausted.retry_budget, 200)
        self.assertEqual(
            exhausted.failure_category,
            "cubic_matching_construction_exhaustion",
        )

        mixed_exhausted = SeedGenerationTrace()
        with (
            patch(
                "sglab.targets.erdos_gyarfas.BitGraph.is_connected",
                return_value=False,
            ),
            self.assertRaises(RuntimeError),
        ):
            PLUGIN.generate_seed(
                Random(0),
                {
                    "order": 5,
                    "mode": "minimal_structure_mixed_degree",
                },
                trace=mixed_exhausted,
            )
        self.assertEqual(mixed_exhausted.attempts, 2_000)
        self.assertEqual(
            mixed_exhausted.failure_category,
            "mixed_degree_stub_construction_exhaustion",
        )

        broken = SeedGenerationTrace()
        with self.assertRaisesRegex(RuntimeError, "injected"):
            PLUGIN.generate_seed(
                _BrokenRandom(),  # type: ignore[arg-type]
                {"order": 6, "mode": "cubic_first"},
                trace=broken,
            )
        self.assertEqual(
            broken.failure_category, "other_implementation_failure"
        )


class SeedGenerationLaneTests(unittest.TestCase):
    def test_sources_are_classified_and_checkpoint_restore_is_excluded(
        self,
    ) -> None:
        random_kernel = _LaneKernel(_spec(), None, None)
        try:
            initial = random_kernel.checkpoint(0)
            self.assertEqual(
                (
                    initial["seed_generation"]["graph_family"],
                    initial["seed_generation"]["graph_order"],
                    initial["seed_generation"]["generator_mode"],
                ),
                ("connected_cubic", 10, "cubic_first"),
            )
            self.assertEqual(
                initial["seed_generation"]["sources"][
                    "initial_lane_seed"
                ]["calls"],
                1,
            )
            metrics = random_kernel.run_batch(
                _NeverStop(), max_evaluations=5
            )
            self.assertEqual(
                metrics["seed_generation"]["batch"]["sources"][
                    "random_restart_candidate"
                ]["calls"],
                5,
            )
            random_kernel.restart(99)
            explicit = random_kernel.checkpoint(0)
            self.assertEqual(
                explicit["seed_generation"]["sources"][
                    "explicit_director_restart"
                ]["calls"],
                1,
            )
        finally:
            random_kernel.close()

        forked = _LaneKernel(_spec(), initial, fork_seed=123)
        try:
            self.assertEqual(
                forked.checkpoint(0)["seed_generation"]["total"]["calls"],
                0,
            )
        finally:
            forked.close()

        annealing = _LaneKernel(
            _spec(
                algorithm="simulated_annealing",
                restart_threshold=1,
            ),
            None,
            None,
        )
        try:
            annealing.run_batch(_NeverStop(), max_evaluations=2)
            checkpoint = annealing.checkpoint(0)
            self.assertEqual(
                checkpoint["seed_generation"]["sources"][
                    "automatic_algorithm_restart"
                ]["calls"],
                1,
            )
        finally:
            annealing.close()

        before_restore_calls = checkpoint["seed_generation"]["total"]["calls"]
        restored = _LaneKernel(
            _spec(algorithm="simulated_annealing"), checkpoint, None
        )
        try:
            restored_checkpoint = restored.checkpoint(0)
            self.assertEqual(
                restored_checkpoint["seed_generation"]["total"]["calls"],
                before_restore_calls,
            )
        finally:
            restored.close()

    def test_effective_generator_mode_is_reported_for_odd_unrestricted(
        self,
    ) -> None:
        kernel = _LaneKernel(
            _spec(
                order=5,
                graph_family="unrestricted_min_degree_3",
            ),
            None,
            None,
        )
        try:
            telemetry = kernel.checkpoint(0)["seed_generation"]
        finally:
            kernel.close()
        self.assertEqual(
            telemetry["generator_mode"],
            "minimal_structure_mixed_degree",
        )

    def test_aggregates_are_bounded_and_batch_cumulative_are_consistent(
        self,
    ) -> None:
        kernel = _LaneKernel(_spec(), None, None)
        try:
            first = kernel.run_batch(_NeverStop(), max_evaluations=100)
            second = kernel.run_batch(_NeverStop(), max_evaluations=100)
        finally:
            kernel.close()
        first_seed = first["seed_generation"]
        second_seed = second["seed_generation"]
        self.assertEqual(first_seed["batch"]["total"]["calls"], 101)
        self.assertEqual(first_seed["cumulative"]["total"]["calls"], 101)
        self.assertEqual(second_seed["batch"]["total"]["calls"], 100)
        self.assertEqual(second_seed["cumulative"]["total"]["calls"], 201)
        total = second_seed["cumulative"]["total"]
        self.assertEqual(
            len(total["attempt_histogram"]),
            len(SEED_ATTEMPT_BUCKET_UPPER_BOUNDS) + 1,
        )
        self.assertEqual(
            len(total["elapsed_ns_histogram"]),
            len(SEED_ELAPSED_NS_BUCKET_UPPER_BOUNDS) + 1,
        )
        self.assertEqual(sum(total["attempt_histogram"]), total["calls"])
        self.assertGreater(
            second_seed["cumulative"]["generator_time_share"], 0
        )

    def test_instrumentation_preserves_rng_trajectory_and_checkpoint_id(
        self,
    ) -> None:
        spec = _spec()
        enabled = _LaneKernel(spec, None, None, instrumentation_enabled=True)
        disabled = _LaneKernel(
            spec, None, None, instrumentation_enabled=False
        )
        try:
            enabled_metrics = enabled.run_batch(
                _NeverStop(), max_evaluations=50
            )
            disabled_metrics = disabled.run_batch(
                _NeverStop(), max_evaluations=50
            )
            enabled_checkpoint = enabled.checkpoint(0)
            disabled_checkpoint = disabled.checkpoint(0)
        finally:
            enabled.close()
            disabled.close()
        for field in (
            "graph6",
            "score",
            "best_graph6",
            "best_score",
            "rng_state",
            "current_candidate_id",
            "best_candidate_id",
            "checkpoint_id",
            "sha256",
        ):
            self.assertEqual(
                enabled_checkpoint[field],
                disabled_checkpoint[field],
                field,
            )
        self.assertEqual(
            enabled_metrics["score_trajectory_summary"],
            disabled_metrics["score_trajectory_summary"],
        )

    def test_resume_replay_preserves_scientific_identity(self) -> None:
        spec = _spec()
        uninterrupted = _LaneKernel(spec, None, None)
        try:
            uninterrupted.run_batch(_NeverStop(), max_evaluations=20)
            midpoint = uninterrupted.checkpoint(0)
            uninterrupted.run_batch(_NeverStop(), max_evaluations=20)
            expected = uninterrupted.checkpoint(0)
        finally:
            uninterrupted.close()
        restored = _LaneKernel(spec, copy.deepcopy(midpoint), None)
        try:
            restored.run_batch(_NeverStop(), max_evaluations=20)
            actual = restored.checkpoint(0)
        finally:
            restored.close()
        for field in (
            "graph6",
            "score",
            "best_graph6",
            "best_score",
            "rng_state",
            "checkpoint_id",
            "sha256",
        ):
            self.assertEqual(actual[field], expected[field], field)


class SeedGenerationDiagnosticTests(unittest.TestCase):
    def test_diagnostic_compares_lanes_and_orders(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE lane_metric_windows (
                lane_id TEXT NOT NULL,
                end_high_water INTEGER NOT NULL,
                metrics_json TEXT NOT NULL
            )
            """
        )
        lanes = []
        for order, p95, share in ((10, 4, 0.2), (20, 64, 0.7)):
            lane_id = f"lane-order-{order}"
            lanes.append(
                {
                    "lane_id": lane_id,
                    "graph_family": "connected_cubic",
                    "current_parameters_json": (
                        f'{{"order":{order}}}'
                    ),
                }
            )
            metrics = {
                "seed_generation": {
                    "cumulative": {
                        "generator_mode": "cubic_first",
                        "measured_search_loop_ns": 1_000,
                        "generator_time_share": share,
                        "total": {
                            "calls": 10,
                            "successes": 10,
                            "failures": 0,
                            "attempt_percentiles": {
                                "p95": p95,
                                "p99": p95,
                            },
                            "attempts_max": p95,
                            "retry_budget_max": 100,
                            "maximum_retry_budget_fraction": p95 / 100,
                            "retry_budget_exhaustions": 0,
                            "elapsed_ns_total": 500,
                            "failure_categories": {},
                        },
                        "sources": {
                            "random_restart_candidate": {
                                "search_loop_elapsed_ns": round(
                                    share * 1_000
                                )
                            }
                        },
                    }
                }
            }
            connection.execute(
                "INSERT INTO lane_metric_windows VALUES (?, ?, ?)",
                (lane_id, 10, json.dumps(metrics)),
            )
        with tempfile.TemporaryDirectory() as directory:
            dispatcher = ScientificActionDispatcher(
                store=SimpleNamespace(connection=connection),
                campaign_id="seed-telemetry-tests",
                campaign_dir=Path(directory),
            )
            result = dispatcher._seed_generation_efficiency(lanes)
        self.assertEqual(
            result["highest_p95_attempts"]["lane_id"], "lane-order-20"
        )
        self.assertEqual(
            result["highest_generator_time_share"]["graph_order"], 20
        )
        self.assertEqual(
            [
                lane["lane_id"]
                for lane in result[
                    "random_restart_seed_construction_dominated"
                ]
            ],
            ["lane-order-20"],
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()

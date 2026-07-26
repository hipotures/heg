import tempfile
import unittest
from pathlib import Path

from sglab.benchmark import (
    calibrate,
    microbenchmark,
    quantiles,
    score_kernel_benchmark,
    soak,
    write_report,
)


class BenchmarkTests(unittest.TestCase):
    def test_quantiles_preserve_tail(self) -> None:
        result = quantiles([1, 2, 3, 4, 100])
        self.assertEqual(result["p50"], 3)
        self.assertEqual(result["p90"], 100)
        self.assertEqual(result["maximum"], 100)

    def test_microbenchmark_separates_search_pipeline_stages(self) -> None:
        operations = microbenchmark(
            iterations=1, orders=(20,)
        )["operations"]
        self.assertTrue(
            {
                "candidate_evaluation_batch_10_n20",
                "checkpoint_serialization_n20",
                "sqlite_commit_100_rows",
                "telemetry_event_publication",
                "live_frontier_publication",
            }.issubset(operations)
        )

    def test_short_calibration_covers_frontier_gates_and_writes_reports(self) -> None:
        report = calibrate(0.002, seeds=1, jobs=2)
        self.assertEqual({case["order"] for case in report["cases"]}, {20, 24, 28, 32})
        self.assertIn("24_hour_candidates", report["forecast"])
        self.assertEqual(report["forecast"]["basis"], "n=32 frontier throughput only")
        self.assertIn("frontier_n32_throughput_quantiles", report)
        self.assertIn("peak_rss_source", report)
        with tempfile.TemporaryDirectory() as directory:
            paths = write_report(report, Path(directory))
            self.assertTrue(all(path.is_file() for path in paths))

    def test_score_kernel_benchmark_reports_all_acceptance_gates(self) -> None:
        report = score_kernel_benchmark(
            iterations=1,
            backend_evaluations=2,
            search_evaluations=2,
        )
        self.assertEqual(report["kind"], "score_kernel")
        self.assertEqual(set(report["backend_comparison"]), {"64", "96"})
        self.assertIn("overhead_gate_below_2_percent", report["profiling_comparison"])
        self.assertIn(
            "duplicate_time_reduction_fraction",
            report["legacy_key_comparison"],
        )
        self.assertIn(
            "ancestry_time_reduction_fraction",
            report["independent_provenance_comparison"],
        )
        self.assertIn(
            "witness_search_time_reduction_fraction",
            report["mutation_witness_cache_comparison"],
        )
        self.assertIn("decision", report["incremental_scoring_gate"])
        self.assertTrue(report["acceptance"]["backend_trajectories_equal"])
        self.assertTrue(
            report["acceptance"][
                "mutation_witness_cache_trajectory_equal"
            ]
        )

    def test_short_soak_exercises_controls_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = soak(
                Path(directory),
                hours=0.001,
                order=8,
                workers=1,
            )
        self.assertTrue(report["duration_gate_pass"])
        self.assertTrue(report["pause_resume_observed"])
        self.assertTrue(report["dashboard_responsive"])
        self.assertTrue(report["candidate_counter_monotonic"])
        self.assertTrue(report["progress_after_resume"])
        self.assertTrue(report["queues_bounded"])
        self.assertTrue(report["database_growth_bounded"])
        self.assertTrue(report["soak_pass"])

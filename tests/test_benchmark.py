import tempfile
import unittest
from pathlib import Path

from sglab.benchmark import (
    calibrate,
    microbenchmark,
    quantiles,
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

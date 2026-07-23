import tempfile
import unittest
from pathlib import Path

from sglab.benchmark import calibrate, quantiles, write_report


class BenchmarkTests(unittest.TestCase):
    def test_quantiles_preserve_tail(self) -> None:
        result = quantiles([1, 2, 3, 4, 100])
        self.assertEqual(result["p50"], 3)
        self.assertEqual(result["p90"], 100)
        self.assertEqual(result["maximum"], 100)

    def test_short_calibration_covers_frontier_gates_and_writes_reports(self) -> None:
        report = calibrate(0.002)
        self.assertEqual({case["order"] for case in report["cases"]}, {20, 24, 28, 32})
        self.assertIn("24_hour_candidates", report["forecast"])
        with tempfile.TemporaryDirectory() as directory:
            paths = write_report(report, Path(directory))
            self.assertTrue(all(path.is_file() for path in paths))

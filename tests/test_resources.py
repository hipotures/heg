import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sglab.resources import (
    current_rss_bytes,
    process_tree_rss_bytes,
    recommended_workers,
    run_bounded,
)


class ResourceSafetyTests(unittest.TestCase):
    def test_recommended_workers_uses_all_logical_cpus_by_default(self) -> None:
        with patch("os.cpu_count", return_value=16):
            self.assertEqual(recommended_workers(), 16)
            self.assertEqual(recommended_workers(16), 16)
            self.assertEqual(recommended_workers(32), 16)
            self.assertEqual(recommended_workers(8), 8)
            self.assertEqual(recommended_workers(None, reserve_threads=2), 14)

    def test_subprocess_timeout_is_unknown_and_kills_group(self) -> None:
        result = run_bounded(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout_seconds=0.05,
            output_limit_bytes=128,
        )
        self.assertEqual(result.status, "UNKNOWN_TIMEOUT")

    def test_subprocess_output_is_bounded(self) -> None:
        result = run_bounded(
            [sys.executable, "-c", "print('x' * 1000)"],
            timeout_seconds=2,
            output_limit_bytes=64,
        )
        self.assertEqual(result.status, "ERROR_OUTPUT_LIMIT")
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 64)
        missing = run_bounded(
            ["/definitely/missing/sglab-tool"],
            timeout_seconds=1,
            output_limit_bytes=64,
        )
        self.assertEqual(missing.status, "TOOL_FAILURE")

    def test_proc_rss_ignores_process_lookup_error_on_exiting_pid(self) -> None:
        with patch.object(
            Path,
            "read_text",
            side_effect=ProcessLookupError(3, "No such process"),
        ):
            self.assertEqual(current_rss_bytes(12345), 0)
            self.assertEqual(process_tree_rss_bytes(12345), 0)

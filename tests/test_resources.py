import sys
import unittest

from sglab.resources import run_bounded


class ResourceSafetyTests(unittest.TestCase):
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
        self.assertEqual(len(result.stdout), 64)

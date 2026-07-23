import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sglab.state import append_event, atomic_write_json, next_control, read_json


class StateTests(unittest.TestCase):
    def test_atomic_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, {"status": "RUNNING", "value": 7})
            self.assertEqual(read_json(path)["value"], 7)
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            with ThreadPoolExecutor(max_workers=4) as executor:
                versions = list(
                    executor.map(
                        lambda _: next_control(directory, "PAUSE")["version"],
                        range(8),
                    )
                )
            self.assertEqual(sorted(versions), list(range(1, 9)))

    def test_structured_log_rotates_at_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            append_event(path, "first", max_bytes=1, value=1)
            append_event(path, "second", max_bytes=1, value=2)
            self.assertTrue(path.with_suffix(".jsonl.1").exists())
            self.assertIn('"event":"second"', path.read_text(encoding="utf-8"))
            append_event(path, "large", max_bytes=1024, value="x" * 4096)
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertIn('"truncated":true', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

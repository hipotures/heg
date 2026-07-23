import tempfile
import unittest
from pathlib import Path

from sglab.state import atomic_write_json, read_json


class StateTests(unittest.TestCase):
    def test_atomic_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, {"status": "RUNNING", "value": 7})
            self.assertEqual(read_json(path)["value"], 7)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()

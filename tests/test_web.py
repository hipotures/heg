import unittest
from pathlib import Path


class WebAssetsTests(unittest.TestCase):
    def test_index_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "web" / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()

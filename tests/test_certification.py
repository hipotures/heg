import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from sglab.certification import certify, default_cyclecheck
from sglab.model import BitGraph


@unittest.skipUnless(default_cyclecheck().is_file(), "C++ helper has not been built")
class CertificationTests(unittest.TestCase):
    def test_k4_artifact_has_two_agreeing_verifiers_and_hashes(self) -> None:
        graph = BitGraph.from_edges(
            4, ((u, v) for u in range(4) for v in range(u + 1, 4))
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest = certify(graph, Path(directory), timeout_seconds=5)
            self.assertEqual(manifest["status"], "INVALID_CANDIDATE")
            self.assertEqual(len(manifest["verifiers"]), 2)
            restored = json.loads((Path(directory) / "candidate.json").read_text())
            self.assertEqual(restored["n"], 4)
            self.assertEqual(
                manifest["graph6_sha256"],
                hashlib.sha256(
                    (Path(directory) / "candidate.graph6").read_bytes()
                ).hexdigest(),
            )
            self.assertTrue((Path(directory) / "commands.txt").is_file())
        with tempfile.TemporaryDirectory() as directory:
            invalid = certify(
                BitGraph.empty(4),
                Path(directory),
                timeout_seconds=5,
            )
            self.assertEqual(invalid["status"], "INVALID_CANDIDATE")

import random
import unittest
from pathlib import Path

from sglab.certification import default_cyclecheck, verify_cpp
from sglab.targets.erdos_gyarfas import PLUGIN, verify_reference


@unittest.skipUnless(default_cyclecheck().is_file(), "C++ helper has not been built")
class CppVerifierTests(unittest.TestCase):
    def test_agrees_with_reference_on_small_random_cubic_graphs(self) -> None:
        rng = random.Random(1234)
        for n in (6, 8, 10):
            graph = PLUGIN.generate_seed(rng, {"order": n, "mode": "cubic_first"})
            reference = verify_reference(graph)
            independent = verify_cpp(graph, timeout_seconds=5)
            expected = "FOUND" if reference.status == "REJECTED" else "ABSENT"
            self.assertEqual(independent["status"], expected)

    def test_protocol_reports_witness(self) -> None:
        graph = PLUGIN.generate_seed(
            random.Random(2), {"order": 6, "mode": "cubic_first"}
        )
        result = verify_cpp(graph, Path(default_cyclecheck()), timeout_seconds=5)
        if result["status"] == "FOUND":
            self.assertEqual(len(result["witness"]), result["length"])

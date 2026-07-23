import random
import unittest

from sglab.model import BitGraph, find_cycle_of_length
from sglab.verification import find_cycle_dynamic, verify_dynamic
from sglab.targets.erdos_gyarfas import verify_reference


class IndependentVerificationTests(unittest.TestCase):
    def test_cycle_detectors_agree_on_small_random_graphs(self) -> None:
        rng = random.Random(20260723)
        for n in range(4, 9):
            for _ in range(8):
                edges = [
                    (u, v)
                    for u in range(n)
                    for v in range(u + 1, n)
                    if rng.random() < 0.4
                ]
                graph = BitGraph.from_edges(n, edges)
                for length in range(3, n + 1):
                    self.assertEqual(
                        find_cycle_of_length(graph, length) is not None,
                        find_cycle_dynamic(graph, length) is not None,
                    )

    def test_full_verifiers_agree_on_k4(self) -> None:
        graph = BitGraph.from_edges(
            4, ((u, v) for u in range(4) for v in range(u + 1, 4))
        )
        self.assertEqual(verify_reference(graph).status, verify_dynamic(graph).status)

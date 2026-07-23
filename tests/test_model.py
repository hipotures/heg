import unittest

from sglab.model import BitGraph, find_cycle_of_length
from sglab.targets.erdos_gyarfas import forbidden_lengths, verify_reference


class BitGraphTests(unittest.TestCase):
    def test_rejects_asymmetric_rows(self) -> None:
        with self.assertRaises(ValueError):
            BitGraph(2, (2, 0))

    def test_rejects_loop(self) -> None:
        with self.assertRaises(ValueError):
            BitGraph(1, (1,))

    def test_basic_invariants(self) -> None:
        graph = BitGraph.from_edges(4, [(0, 1), (1, 2), (2, 3), (3, 0)])
        self.assertEqual(graph.size(), 4)
        self.assertEqual(graph.minimum_degree(), 2)
        self.assertTrue(graph.is_connected())
        self.assertEqual(set(graph.edges()), {(0, 1), (0, 3), (1, 2), (2, 3)})

    def test_cycle_witness(self) -> None:
        graph = BitGraph.from_edges(4, [(0, 1), (1, 2), (2, 3), (3, 0)])
        cycle = find_cycle_of_length(graph, 4)
        self.assertIsNotNone(cycle)
        self.assertEqual(len(cycle or ()), 4)

    def test_k4_is_rejected(self) -> None:
        graph = BitGraph.from_edges(
            4,
            [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)],
        )
        result = verify_reference(graph)
        self.assertEqual(result.status, "REJECTED")
        self.assertTrue(result.complete)

    def test_forbidden_lengths(self) -> None:
        self.assertEqual(forbidden_lengths(31), (4, 8, 16))
        self.assertEqual(forbidden_lengths(32), (4, 8, 16, 32))

    def test_graph6_round_trip_small_and_extended_order(self) -> None:
        for n, edges in (
            (6, [(0, 1), (2, 5), (3, 4)]),
            (128, [(0, 127), (64, 65), (10, 11)]),
        ):
            graph = BitGraph.from_edges(n, edges)
            self.assertEqual(BitGraph.from_graph6(graph.to_graph6()), graph)

    def test_graph6_known_k4(self) -> None:
        graph = BitGraph.from_edges(4, ((u, v) for u in range(4) for v in range(u + 1, 4)))
        self.assertEqual(graph.to_graph6(), "C~")

    def test_stable_hash_is_deterministic(self) -> None:
        graph = BitGraph.from_edges(3, [(0, 1)])
        restored = BitGraph.from_graph6(graph.to_graph6())
        self.assertEqual(graph.stable_hash(), restored.stable_hash())


if __name__ == "__main__":
    unittest.main()

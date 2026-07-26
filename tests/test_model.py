import unittest
from random import Random

from sglab.model import (
    BitGraph,
    CycleCountWorkspace,
    count_cycles_of_length_bounded,
    find_cycle_of_length,
    find_cycles_of_length_bounded,
)
from sglab.targets.erdos_gyarfas import PLUGIN, forbidden_lengths, verify_reference


class BitGraphTests(unittest.TestCase):
    def test_rejects_asymmetric_rows(self) -> None:
        with self.assertRaises(ValueError):
            BitGraph(2, (2, 0))

    def test_rejects_loop(self) -> None:
        with self.assertRaises(ValueError):
            BitGraph(1, (1,))
        with self.assertRaises(ValueError):
            BitGraph.from_edges(2, [(0, 1), (1, 0)])

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
        witnesses, complete = find_cycles_of_length_bounded(graph, 4, 2, 1)
        self.assertEqual(witnesses, ())
        self.assertFalse(complete)

    def test_count_only_cycle_search_matches_witness_enumerator(self) -> None:
        rng = Random(20260726)
        workspace = CycleCountWorkspace.for_order(12)
        for n in range(4, 13):
            graph = BitGraph.from_edges(
                n,
                (
                    (u, v)
                    for u in range(n)
                    for v in range(u + 1, n)
                    if rng.random() < 0.3
                ),
            )
            for length in range(4, n + 1, 4):
                for limit, budget in ((1, 1), (3, 32), (16, 4096)):
                    witnesses, complete = find_cycles_of_length_bounded(
                        graph, length, limit, budget
                    )
                    count, counted_complete, nodes = (
                        count_cycles_of_length_bounded(
                            graph,
                            length,
                            limit,
                            budget,
                            workspace,
                        )
                    )
                    self.assertEqual(count, len(witnesses))
                    self.assertEqual(counted_complete, complete)
                    self.assertGreater(nodes, 0)

    def test_count_only_workspace_is_reusable(self) -> None:
        graph = BitGraph.from_edges(
            4, ((u, v) for u in range(4) for v in range(u + 1, 4))
        )
        workspace = CycleCountWorkspace.for_order(graph.n)
        first = count_cycles_of_length_bounded(
            graph, 4, 4, 4096, workspace
        )
        second = count_cycles_of_length_bounded(
            graph, 4, 2, 4096, workspace
        )
        self.assertEqual(first[:2], (3, True))
        self.assertEqual(second[:2], (2, False))

    def test_k4_is_rejected(self) -> None:
        graph = BitGraph.from_edges(
            4,
            [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)],
        )
        result = verify_reference(graph)
        self.assertEqual(result.status, "REJECTED")
        self.assertTrue(result.complete)
        score = PLUGIN.cheap_score(graph, cap=1)
        self.assertEqual(score.witness_counts, ((4, 1),))
        self.assertFalse(score.complete)

    def test_cheap_score_matches_bounded_witness_reference(self) -> None:
        graph = PLUGIN.generate_seed(
            Random(7262027), {"order": 64, "mode": "cubic_first"}
        )
        cap = 2000
        node_budget = 50_000
        counts = []
        weighted = 0
        complete = True
        for length in forbidden_lengths(graph.n):
            witnesses, search_complete = find_cycles_of_length_bounded(
                graph, length, cap + 1, node_budget
            )
            count = min(len(witnesses), cap)
            counts.append((length, count))
            weighted += count * max(1, 64 // length)
            complete = (
                complete
                and len(witnesses) <= cap
                and search_complete
            )
        score = PLUGIN.cheap_score(graph, cap)
        self.assertEqual(score.witness_counts, tuple(counts))
        self.assertEqual(score.weighted_penalty, weighted)
        self.assertEqual(score.complete, complete)

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
        graph = BitGraph.from_edges(
            4, ((u, v) for u in range(4) for v in range(u + 1, 4))
        )
        self.assertEqual(graph.to_graph6(), "C~")
        with self.assertRaisesRegex(ValueError, "trailing data"):
            BitGraph.from_graph6("C~?")
        with self.assertRaisesRegex(ValueError, "padding bits"):
            BitGraph.from_graph6("A@")

    def test_stable_hash_is_deterministic(self) -> None:
        graph = BitGraph.from_edges(3, [(0, 1)])
        restored = BitGraph.from_graph6(graph.to_graph6())
        self.assertEqual(graph.stable_hash(), restored.stable_hash())

    def test_graph6_reusable_buffer_matches_canonical_encoding(self) -> None:
        buffer = bytearray(b"stale")
        rng = Random(20260726)
        for n in (0, 1, 6, 62, 63, 96, 128):
            graph = BitGraph.from_edges(
                n,
                (
                    (u, v)
                    for u in range(n)
                    for v in range(u + 1, n)
                    if rng.random() < 0.08
                ),
            )
            expected = graph.to_graph6().encode("ascii")
            graph.encode_graph6_into(buffer)
            self.assertEqual(bytes(buffer), expected)
            self.assertEqual(
                graph.stable_hash(buffer),
                graph.stable_hash(),
            )


if __name__ == "__main__":
    unittest.main()

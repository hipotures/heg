import random
import unittest

from sglab.model import BitGraph, find_cycle_of_length
from sglab.verification import find_cycle_dynamic, verify_dynamic
from sglab.targets.erdos_gyarfas import verify_reference

try:
    import networkx as nx
except ImportError:
    nx = None


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
                networkx_lengths: set[int] | None = None
                if nx is not None:
                    reference_graph = nx.DiGraph()
                    reference_graph.add_nodes_from(range(n))
                    reference_graph.add_edges_from(
                        edge for u, v in edges for edge in ((u, v), (v, u))
                    )
                    networkx_lengths = {
                        len(cycle)
                        for cycle in nx.simple_cycles(reference_graph, length_bound=n)
                        if len(cycle) >= 3
                    }
                for length in range(3, n + 1):
                    found = find_cycle_of_length(graph, length) is not None
                    self.assertEqual(
                        found, find_cycle_dynamic(graph, length) is not None
                    )
                    if networkx_lengths is not None:
                        self.assertEqual(found, length in networkx_lengths)

    def test_full_verifiers_agree_on_k4(self) -> None:
        graph = BitGraph.from_edges(
            4, ((u, v) for u in range(4) for v in range(u + 1, 4))
        )
        self.assertEqual(verify_reference(graph).status, verify_dynamic(graph).status)

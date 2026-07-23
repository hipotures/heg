from __future__ import annotations

from random import Random
from time import perf_counter
from typing import Any
import math

from ..model import BitGraph, find_cycle_of_length, find_cycles_of_length
from .base import ScoreResult, ValidationResult, VerifyResult, Witness


def forbidden_lengths(n: int) -> tuple[int, ...]:
    values: list[int] = []
    current = 4
    while current <= n:
        values.append(current)
        current *= 2
    return tuple(values)


def verify_reference(graph: BitGraph) -> VerifyResult:
    """Slow exact reference verification for small graphs."""

    start = perf_counter()
    if graph.n == 0:
        return VerifyResult(
            "INVALID", True, "graph must be non-empty",
            elapsed_seconds=perf_counter() - start,
            implementation="python-reference-dfs",
        )
    if not graph.is_connected():
        return VerifyResult(
            "INVALID", True, "minimal-candidate mode requires connectedness",
            elapsed_seconds=perf_counter() - start,
            implementation="python-reference-dfs",
        )
    if graph.minimum_degree() < 3:
        return VerifyResult(
            "INVALID", True, "minimum degree is below 3",
            elapsed_seconds=perf_counter() - start,
            implementation="python-reference-dfs",
        )

    for length in forbidden_lengths(graph.n):
        cycle = find_cycle_of_length(graph, length)
        if cycle is not None:
            return VerifyResult(
                "REJECTED",
                True,
                f"found a forbidden cycle of length {length}",
                (Witness(kind=f"cycle_{length}", vertices=cycle),),
                elapsed_seconds=perf_counter() - start,
                implementation="python-reference-dfs",
            )

    return VerifyResult(
        "VERIFIED",
        True,
        "no power-of-two cycle was found by the complete reference verifier",
        elapsed_seconds=perf_counter() - start,
        implementation="python-reference-dfs",
    )


class ErdosGyarfasPlugin:
    id = "erdos_gyarfas"

    def validate_graph(self, graph: BitGraph) -> ValidationResult:
        if graph.n == 0:
            return ValidationResult(False, "graph must be non-empty")
        if not graph.is_connected():
            return ValidationResult(False, "graph must be connected")
        if graph.minimum_degree() < 3:
            return ValidationResult(False, "minimum degree is below 3")
        return ValidationResult(True, "valid structural candidate")

    def generate_seed(self, rng: Random, config: dict[str, Any]) -> BitGraph:
        n = int(config["order"])
        mode = str(config.get("mode", "cubic_first"))
        if n < 4:
            raise ValueError("order must be at least 4")
        if mode == "cubic_first" and n % 2:
            raise ValueError("cubic graphs require an even order")
        if mode == "minimal_structure_mixed_degree":
            high_count = 2 if n % 2 == 0 else 1
            high_count = min(high_count, max(1, math.floor(3 * n / 7)))
            degrees = [4] * high_count + [3] * (n - high_count)
            if sum(degrees) % 2:
                high_count += 1
                degrees = [4] * high_count + [3] * (n - high_count)
            high = set(range(high_count))
            for _ in range(2_000):
                stubs = [vertex for vertex, degree in enumerate(degrees) for _ in range(degree)]
                rng.shuffle(stubs)
                edges: set[tuple[int, int]] = set()
                valid = True
                while stubs:
                    u = stubs.pop()
                    choices = [
                        index
                        for index, v in enumerate(stubs)
                        if u != v
                        and tuple(sorted((u, v))) not in edges
                        and not (u in high and v in high)
                    ]
                    if not choices:
                        valid = False
                        break
                    v = stubs.pop(rng.choice(choices))
                    edges.add(tuple(sorted((u, v))))
                if valid:
                    graph = BitGraph.from_edges(n, edges)
                    if graph.is_connected() and all(
                        any(graph.degree(v) == 3 for v in graph.neighbors(u))
                        for u in range(n)
                    ):
                        return graph
            raise RuntimeError("failed to generate a mixed-degree seed within retry budget")
        # A cycle plus a random non-neighbour perfect matching is a connected
        # cubic seed. Retry is bounded and deterministic for a fixed RNG state.
        cycle = {(u, (u + 1) % n) for u in range(n)}
        cycle = {tuple(sorted(edge)) for edge in cycle}
        for _ in range(200):
            vertices = list(range(n))
            rng.shuffle(vertices)
            matching: set[tuple[int, int]] = set()
            while vertices:
                u = vertices.pop()
                choices = [
                    index
                    for index, v in enumerate(vertices)
                    if tuple(sorted((u, v))) not in cycle
                ]
                if not choices:
                    break
                index = rng.choice(choices)
                v = vertices.pop(index)
                matching.add(tuple(sorted((u, v))))
            if not vertices and len(matching) == n // 2:
                return BitGraph.from_edges(n, cycle | matching)
        raise RuntimeError("failed to generate a cubic seed within retry budget")

    def mutate(self, graph: BitGraph, rng: Random, config: dict[str, Any]) -> BitGraph:
        mode = str(config.get("mode", "cubic_first"))
        if mode == "unrestricted_min_degree_3":
            if rng.random() < 0.55:
                missing = [
                    (u, v)
                    for u in range(graph.n)
                    for v in range(u + 1, graph.n)
                    if not graph.has_edge(u, v)
                ]
                if missing:
                    return graph.with_edges(add=(rng.choice(missing),))
            removable = [
                edge
                for edge in graph.edges()
                if graph.degree(edge[0]) > 3 and graph.degree(edge[1]) > 3
            ]
            if removable:
                candidate = graph.with_edges(remove=(rng.choice(removable),))
                if candidate.is_connected():
                    return candidate
        edges = tuple(graph.edges())
        if len(edges) < 2:
            return graph
        for _ in range(64):
            (a, b), (c, d) = rng.sample(edges, 2)
            if len({a, b, c, d}) != 4:
                continue
            pairing = ((a, c), (b, d)) if rng.randrange(2) == 0 else ((a, d), (b, c))
            additions = tuple(tuple(sorted(edge)) for edge in pairing)
            if additions[0] == additions[1] or any(graph.has_edge(*edge) for edge in additions):
                continue
            candidate = graph.with_edges(add=additions, remove=((a, b), (c, d)))
            if candidate.is_connected() and (
                mode != "minimal_structure_mixed_degree"
                or self._minimal_structure_valid(candidate)
            ):
                return candidate
        return graph

    def cheap_score(self, graph: BitGraph, cap: int) -> ScoreResult:
        validation = self.validate_graph(graph)
        if not validation.valid:
            return ScoreResult(False, (), 10**9, True, simplicity=graph.size())
        counts: list[tuple[int, int]] = []
        weighted = 0
        complete = True
        remaining = cap
        for length in forbidden_lengths(graph.n):
            witnesses = find_cycles_of_length(graph, length, remaining)
            count = len(witnesses)
            counts.append((length, count))
            weighted += count * max(1, 64 // length)
            remaining -= count
            if remaining == 0:
                complete = False
                break
        return ScoreResult(
            True,
            tuple(counts),
            weighted,
            complete,
            simplicity=graph.size(),
        )

    def exact_verify(self, graph: BitGraph) -> VerifyResult:
        return verify_reference(graph)

    def canonical_key(self, graph: BitGraph) -> bytes:
        # Stable but explicitly non-authoritative without nauty.
        return graph.stable_hash().encode("ascii")

    @staticmethod
    def _minimal_structure_valid(graph: BitGraph) -> bool:
        degree_three = sum(graph.degree(u) == 3 for u in range(graph.n))
        if degree_three < math.ceil(4 * graph.n / 7):
            return False
        high = {u for u in range(graph.n) if graph.degree(u) >= 4}
        if any(u in high and v in high for u, v in graph.edges()):
            return False
        return all(
            any(graph.degree(v) == 3 for v in graph.neighbors(u))
            for u in range(graph.n)
        )


PLUGIN = ErdosGyarfasPlugin()

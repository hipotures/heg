from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from time import perf_counter, perf_counter_ns
from typing import Any
import math

from ..model import (
    BitGraph,
    CycleCountWorkspace,
    count_cycles_of_length_bounded_into,
    find_cycle_of_length,
    find_cycles_of_length_bounded,
)
from ..external import canonical_graph6
from .base import ScoreResult, ValidationResult, VerifyResult, Witness


def forbidden_lengths(n: int) -> tuple[int, ...]:
    values: list[int] = []
    current = 4
    while current <= n:
        values.append(current)
        current *= 2
    return tuple(values)


PROFILED_CYCLE_LENGTHS = (4, 8, 16, 32, 64, 128)


@dataclass(slots=True)
class ScoreProfileAccumulator:
    """One batch's in-memory score counters."""

    graph_validation_ns: int = 0
    witness_counting_ns: int = 0
    score_calculation_ns: int = 0
    cycle_ns: list[int] = field(
        default_factory=lambda: [0] * len(PROFILED_CYCLE_LENGTHS)
    )
    cycle_nodes: list[int] = field(
        default_factory=lambda: [0] * len(PROFILED_CYCLE_LENGTHS)
    )

    def reset(self) -> None:
        self.graph_validation_ns = 0
        self.witness_counting_ns = 0
        self.score_calculation_ns = 0
        for index in range(len(PROFILED_CYCLE_LENGTHS)):
            self.cycle_ns[index] = 0
            self.cycle_nodes[index] = 0

    def payload(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for index, length in enumerate(PROFILED_CYCLE_LENGTHS):
            result[f"cycle_{length}_ns"] = self.cycle_ns[index]
            result[f"cycle_{length}_nodes"] = self.cycle_nodes[index]
        return result


def verify_reference(graph: BitGraph) -> VerifyResult:
    """Slow exact reference verification for small graphs."""

    start = perf_counter()
    if graph.n == 0:
        return VerifyResult(
            "INVALID",
            True,
            "graph must be non-empty",
            elapsed_seconds=perf_counter() - start,
            implementation="python-reference-dfs",
        )
    if not graph.is_connected():
        return VerifyResult(
            "INVALID",
            True,
            "minimal-candidate mode requires connectedness",
            elapsed_seconds=perf_counter() - start,
            implementation="python-reference-dfs",
        )
    if graph.minimum_degree() < 3:
        return VerifyResult(
            "INVALID",
            True,
            "minimum degree is below 3",
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
    statement = (
        "Every graph of minimum degree at least three contains a cycle whose "
        "length is a power of two."
    )
    control_only = False

    def forbidden_lengths(self, order: int) -> tuple[int, ...]:
        return forbidden_lengths(order)

    def validate_graph(self, graph: BitGraph) -> ValidationResult:
        if graph.n == 0:
            return ValidationResult(False, "graph must be non-empty")
        if not graph.is_connected():
            return ValidationResult(False, "graph must be connected")
        if graph.minimum_degree() < 3:
            return ValidationResult(False, "minimum degree is below 3")
        return ValidationResult(True, "valid structural candidate")

    @staticmethod
    def new_score_workspace(order: int) -> CycleCountWorkspace:
        return CycleCountWorkspace.for_order(order)

    @staticmethod
    def new_score_profile() -> ScoreProfileAccumulator:
        return ScoreProfileAccumulator()

    def generate_seed(self, rng: Random, config: dict[str, Any]) -> BitGraph:
        n = int(config["order"])
        mode = str(config.get("mode", "cubic_first"))
        if n < 4:
            raise ValueError("order must be at least 4")
        if mode not in {
            "cubic_first",
            "minimal_structure_mixed_degree",
            "unrestricted_min_degree_3",
        }:
            raise ValueError(f"unsupported mode: {mode}")
        if mode == "cubic_first" and n % 2:
            raise ValueError("cubic graphs require an even order")
        if mode == "minimal_structure_mixed_degree" and n < 5:
            raise ValueError("minimal_structure_mixed_degree requires order at least 5")
        if mode == "unrestricted_min_degree_3" and n % 2:
            return self.generate_seed(
                rng,
                {**config, "mode": "minimal_structure_mixed_degree"},
            )
        if mode == "minimal_structure_mixed_degree":
            high_count = 2 if n % 2 == 0 else 1
            high_count = min(high_count, max(1, math.floor(3 * n / 7)))
            degrees = [4] * high_count + [3] * (n - high_count)
            if sum(degrees) % 2:
                high_count += 1
                degrees = [4] * high_count + [3] * (n - high_count)
            high = set(range(high_count))
            for _ in range(2_000):
                stubs = [
                    vertex
                    for vertex, degree in enumerate(degrees)
                    for _ in range(degree)
                ]
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
            raise RuntimeError(
                "failed to generate a mixed-degree seed within retry budget"
            )
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
        operator = str(
            config.get("mutation_operator", "uniform_two_edge_switch")
        )
        if operator not in {
            "uniform_two_edge_switch",
            "forbidden_cycle_break_switch",
        }:
            raise ValueError(f"unsupported mutation operator: {operator}")
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
        if operator == "forbidden_cycle_break_switch":
            witness_edges = self._forbidden_witness_edges(graph, rng)
            if not witness_edges:
                return graph
            for _ in range(64):
                first = rng.choice(witness_edges)
                remote = rng.choice(edges)
                candidate = self._two_edge_switch(
                    graph, first, remote, rng, mode
                )
                if candidate is not None:
                    return candidate
            return graph
        for _ in range(64):
            first, second = rng.sample(edges, 2)
            candidate = self._two_edge_switch(
                graph, first, second, rng, mode
            )
            if candidate is not None:
                return candidate
        return graph

    def _forbidden_witness_edges(
        self, graph: BitGraph, rng: Random
    ) -> tuple[tuple[int, int], ...]:
        witnesses: list[tuple[int, ...]] = []
        for length in self.forbidden_lengths(graph.n):
            found, _complete = find_cycles_of_length_bounded(
                graph, length, 2, 4_096
            )
            if found:
                witnesses.extend(found[:1])
        if not witnesses:
            return ()
        witness = rng.choice(witnesses)
        return tuple(
            tuple(sorted((witness[index], witness[(index + 1) % len(witness)])))
            for index in range(len(witness))
        )

    def _two_edge_switch(
        self,
        graph: BitGraph,
        first: tuple[int, int],
        second: tuple[int, int],
        rng: Random,
        mode: str,
    ) -> BitGraph | None:
        (a, b), (c, d) = first, second
        if len({a, b, c, d}) != 4:
            return None
        pairings = (
            (((a, c), (b, d)), ((a, d), (b, c)))
            if rng.randrange(2) == 0
            else (((a, d), (b, c)), ((a, c), (b, d)))
        )
        for pairing in pairings:
            additions = tuple(tuple(sorted(edge)) for edge in pairing)
            if additions[0] == additions[1] or any(
                graph.has_edge(*edge) for edge in additions
            ):
                continue
            candidate = graph.with_edges(
                add=additions, remove=(first, second)
            )
            if candidate.is_connected() and (
                mode != "minimal_structure_mixed_degree"
                or self._minimal_structure_valid(candidate)
            ):
                return candidate
        return None

    def cheap_score(self, graph: BitGraph, cap: int) -> ScoreResult:
        return self.cheap_score_with_workspace(
            graph,
            cap,
            CycleCountWorkspace.for_order(graph.n),
            None,
        )

    def cheap_score_profiled(
        self,
        graph: BitGraph,
        cap: int,
        workspace: CycleCountWorkspace,
        profile: ScoreProfileAccumulator,
    ) -> ScoreResult:
        """Accumulate one score into batch-local integer counters."""

        return self.cheap_score_with_workspace(graph, cap, workspace, profile)

    def cheap_score_with_workspace(
        self,
        graph: BitGraph,
        cap: int,
        workspace: CycleCountWorkspace,
        profile: ScoreProfileAccumulator | None,
    ) -> ScoreResult:
        if profile is None:
            validation = self.validate_graph(graph)
        else:
            started = perf_counter_ns()
            validation = self.validate_graph(graph)
            profile.graph_validation_ns += perf_counter_ns() - started
        if not validation.valid:
            score_started = perf_counter_ns() if profile is not None else 0
            score = ScoreResult(
                False, (), 10**9, True, simplicity=graph.size()
            )
            if profile is not None:
                profile.score_calculation_ns += (
                    perf_counter_ns() - score_started
                )
            return score

        counts: list[tuple[int, int]] = []
        weighted = 0
        complete = True
        node_budget = max(4_096, min(50_000, cap * 1_024))
        for index, length in enumerate(self.forbidden_lengths(graph.n)):
            if profile is None:
                count_cycles_of_length_bounded_into(
                    graph, length, cap + 1, node_budget, workspace
                )
            else:
                witness_started = perf_counter_ns()
                count_cycles_of_length_bounded_into(
                    graph, length, cap + 1, node_budget, workspace
                )
                elapsed = perf_counter_ns() - witness_started
                profile.witness_counting_ns += elapsed
                profile.cycle_ns[index] += elapsed
                profile.cycle_nodes[index] += workspace.visited_nodes

            score_started = perf_counter_ns() if profile is not None else 0
            count = min(workspace.count, cap)
            counts.append((length, count))
            weighted += count * max(1, 64 // length)
            if workspace.count > cap or not workspace.complete:
                complete = False
            if profile is not None:
                profile.score_calculation_ns += (
                    perf_counter_ns() - score_started
                )

        score_started = perf_counter_ns() if profile is not None else 0
        score = ScoreResult(
            True,
            tuple(counts),
            weighted,
            complete,
            simplicity=graph.size(),
        )
        if profile is not None:
            profile.score_calculation_ns += (
                perf_counter_ns() - score_started
            )
        return score

    def exact_verify(self, graph: BitGraph) -> VerifyResult:
        return verify_reference(graph)

    def canonical_key(self, graph: BitGraph) -> bytes:
        canonical, _authoritative = canonical_graph6(graph)
        # Without nauty this remains stable but explicitly non-authoritative.
        return canonical.encode("ascii")

    def explain(self, graph: BitGraph, result: VerifyResult) -> dict[str, Any]:
        return {
            "target": self.id,
            "order": graph.n,
            "size": graph.size(),
            "minimum_degree": graph.minimum_degree(),
            "status": result.status,
            "complete": result.complete,
            "message": result.message,
            "witnesses": [
                {
                    "kind": witness.kind,
                    "vertices": list(witness.vertices),
                }
                for witness in result.witnesses
            ],
        }

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

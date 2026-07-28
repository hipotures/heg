from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from time import perf_counter, perf_counter_ns
from typing import Any
import math

from ..model import (
    BitGraph,
    find_cycle_of_length,
    find_cycles_of_length_bounded,
)
from ..external import canonical_graph6
from ..score_worker import CycleCountResult
from .base import (
    MutationResult,
    ScoreResult,
    SeedGenerationTrace,
    ValidationResult,
    VerifyResult,
    Witness,
)


def forbidden_lengths(n: int) -> tuple[int, ...]:
    values: list[int] = []
    current = 4
    while current <= n:
        values.append(current)
        current *= 2
    return tuple(values)


PROFILED_CYCLE_LENGTHS = (3, 4, 8, 16, 32, 64, 128)


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
    cycle_evaluations: list[int] = field(
        default_factory=lambda: [0] * len(PROFILED_CYCLE_LENGTHS)
    )
    cycle_complete: list[int] = field(
        default_factory=lambda: [0] * len(PROFILED_CYCLE_LENGTHS)
    )
    cycle_cutoff: list[int] = field(
        default_factory=lambda: [0] * len(PROFILED_CYCLE_LENGTHS)
    )

    def reset(self) -> None:
        self.graph_validation_ns = 0
        self.witness_counting_ns = 0
        self.score_calculation_ns = 0
        for index in range(len(PROFILED_CYCLE_LENGTHS)):
            self.cycle_ns[index] = 0
            self.cycle_nodes[index] = 0
            self.cycle_evaluations[index] = 0
            self.cycle_complete[index] = 0
            self.cycle_cutoff[index] = 0

    def payload(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for index, length in enumerate(PROFILED_CYCLE_LENGTHS):
            result[f"cycle_{length}_ns"] = self.cycle_ns[index]
            result[f"cycle_{length}_nodes"] = self.cycle_nodes[index]
            result[f"cycle_{length}_evaluations"] = (
                self.cycle_evaluations[index]
            )
            result[f"cycle_{length}_complete"] = (
                self.cycle_complete[index]
            )
            result[f"cycle_{length}_cutoff"] = self.cycle_cutoff[index]
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
    def new_score_profile() -> ScoreProfileAccumulator:
        return ScoreProfileAccumulator()

    def generate_seed(
        self,
        rng: Random,
        config: dict[str, Any],
        *,
        trace: SeedGenerationTrace | None = None,
    ) -> BitGraph:
        try:
            n = int(config["order"])
            mode = str(config.get("mode", "cubic_first"))
            if trace is not None:
                trace.generator_mode = mode
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
                raise ValueError(
                    "minimal_structure_mixed_degree requires order at least 5"
                )
        except (KeyError, TypeError, ValueError):
            if trace is not None:
                trace.failure_category = "invalid_generator_configuration"
            raise

        if mode == "unrestricted_min_degree_3" and n % 2:
            mode = "minimal_structure_mixed_degree"
            if trace is not None:
                trace.generator_mode = mode

        try:
            if mode == "minimal_structure_mixed_degree":
                retry_budget = 2_000
                if trace is not None:
                    trace.retry_budget = retry_budget
                high_count = 2 if n % 2 == 0 else 1
                high_count = min(
                    high_count, max(1, math.floor(3 * n / 7))
                )
                degrees = [4] * high_count + [3] * (n - high_count)
                if sum(degrees) % 2:
                    high_count += 1
                    degrees = [4] * high_count + [3] * (n - high_count)
                high = set(range(high_count))
                for attempt in range(1, retry_budget + 1):
                    if trace is not None:
                        trace.attempts = attempt
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
                            any(
                                graph.degree(v) == 3
                                for v in graph.neighbors(u)
                            )
                            for u in range(n)
                        ):
                            return graph
                if trace is not None:
                    trace.failure_category = (
                        "mixed_degree_stub_construction_exhaustion"
                    )
                raise RuntimeError(
                    "failed to generate a mixed-degree seed within retry budget"
                )

            # A cycle plus a random non-neighbour perfect matching is a
            # connected cubic seed. Retry is bounded and deterministic.
            retry_budget = 200
            if trace is not None:
                trace.retry_budget = retry_budget
            cycle = {(u, (u + 1) % n) for u in range(n)}
            cycle = {tuple(sorted(edge)) for edge in cycle}
            for attempt in range(1, retry_budget + 1):
                if trace is not None:
                    trace.attempts = attempt
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
            if trace is not None:
                trace.failure_category = (
                    "cubic_matching_construction_exhaustion"
                )
            raise RuntimeError(
                "failed to generate a cubic seed within retry budget"
            )
        except BaseException:
            if trace is not None and trace.failure_category is None:
                trace.failure_category = "other_implementation_failure"
            raise

    def mutate(self, graph: BitGraph, rng: Random, config: dict[str, Any]) -> BitGraph:
        return self.mutate_with_delta(graph, rng, config).graph

    def mutate_with_delta(
        self,
        graph: BitGraph,
        rng: Random,
        config: dict[str, Any],
    ) -> MutationResult:
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
                    addition = rng.choice(missing)
                    return MutationResult(
                        graph.with_edges(add=(addition,)),
                        added_edges=(addition,),
                    )
            removable = [
                edge
                for edge in graph.edges()
                if graph.degree(edge[0]) > 3 and graph.degree(edge[1]) > 3
            ]
            if removable:
                candidate = graph.with_edges(remove=(rng.choice(removable),))
                if candidate.is_connected():
                    removed = tuple(
                        edge
                        for edge in graph.edges()
                        if not candidate.has_edge(*edge)
                    )
                    return MutationResult(
                        candidate,
                        removed_edges=removed,
                    )
        edges = tuple(graph.edges())
        if len(edges) < 2:
            return MutationResult(graph)
        if operator == "forbidden_cycle_break_switch":
            witness_choices = config.get(
                "forbidden_witness_edge_choices"
            )
            if witness_choices is None:
                witness_edges = self._forbidden_witness_edges(graph, rng)
            else:
                witness_edges = (
                    rng.choice(witness_choices) if witness_choices else ()
                )
            if not witness_edges:
                return MutationResult(graph)
            for _ in range(64):
                first = rng.choice(witness_edges)
                remote = rng.choice(edges)
                candidate = self._two_edge_switch(
                    graph, first, remote, rng, mode
                )
                if candidate is not None:
                    return candidate
            return MutationResult(graph)
        for _ in range(64):
            first, second = rng.sample(edges, 2)
            candidate = self._two_edge_switch(
                graph, first, second, rng, mode
            )
            if candidate is not None:
                return candidate
        return MutationResult(graph)

    def _forbidden_witness_edges(
        self, graph: BitGraph, rng: Random
    ) -> tuple[tuple[int, int], ...]:
        choices = self.forbidden_witness_edge_choices(graph)
        return rng.choice(choices) if choices else ()

    def forbidden_witness_edge_choices(
        self, graph: BitGraph
    ) -> tuple[tuple[tuple[int, int], ...], ...]:
        witnesses: list[tuple[int, ...]] = []
        for length in self.forbidden_lengths(graph.n):
            found, _complete = find_cycles_of_length_bounded(
                graph, length, 2, 4_096
            )
            if found:
                witnesses.extend(found[:1])
        if not witnesses:
            return ()
        return tuple(
            tuple(
                tuple(
                    sorted(
                        (
                            witness[index],
                            witness[(index + 1) % len(witness)],
                        )
                    )
                )
                for index in range(len(witness))
            )
            for witness in witnesses
        )

    def _two_edge_switch(
        self,
        graph: BitGraph,
        first: tuple[int, int],
        second: tuple[int, int],
        rng: Random,
        mode: str,
    ) -> MutationResult | None:
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
                return MutationResult(
                    candidate,
                    removed_edges=(first, second),
                    added_edges=additions,
                )
        return None

    def score_from_cycle_counts(
        self,
        graph: BitGraph,
        cap: int,
        results: tuple[CycleCountResult, ...],
        profile: ScoreProfileAccumulator | None,
    ) -> ScoreResult:
        """Assemble the ordinary score from a parity-checked count backend."""

        if profile is None:
            validation = self.validate_graph(graph)
        else:
            started = perf_counter_ns()
            validation = self.validate_graph(graph)
            profile.graph_validation_ns += perf_counter_ns() - started
        if not validation.valid:
            return ScoreResult(
                False, (), 10**9, True, simplicity=graph.size()
            )
        score_started = perf_counter_ns() if profile is not None else 0
        lengths = self.forbidden_lengths(graph.n)
        if tuple(result.length for result in results) != lengths:
            raise ValueError("cycle-count backend returned unexpected lengths")
        counts: list[tuple[int, int]] = []
        weighted = 0
        complete = True
        for result in results:
            count = min(result.count, cap)
            counts.append((result.length, count))
            weighted += count * max(1, 64 // result.length)
            complete = (
                complete
                and result.count <= cap
                and result.complete
            )
            if profile is not None:
                self.record_cycle_count_profile(
                    (result,), profile, cutoff=False
                )
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

    @staticmethod
    def record_cycle_count_profile(
        results: tuple[CycleCountResult, ...],
        profile: ScoreProfileAccumulator,
        *,
        cutoff: bool,
    ) -> None:
        for index_in_results, result in enumerate(results):
            index = PROFILED_CYCLE_LENGTHS.index(result.length)
            profile.witness_counting_ns += result.elapsed_ns
            profile.cycle_ns[index] += result.elapsed_ns
            profile.cycle_nodes[index] += result.nodes
            profile.cycle_evaluations[index] += 1
            is_cutoff = cutoff and index_in_results == len(results) - 1
            profile.cycle_cutoff[index] += int(is_cutoff)
            profile.cycle_complete[index] += int(
                not is_cutoff and result.complete
            )

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

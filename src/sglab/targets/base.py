from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Literal, Protocol

from ..model import BitGraph
from ..score_worker import CycleCountResult


@dataclass(frozen=True, slots=True)
class Witness:
    kind: str
    vertices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class VerifyResult:
    status: Literal["VERIFIED", "REJECTED", "UNKNOWN", "INVALID"]
    complete: bool
    message: str
    witnesses: tuple[Witness, ...] = ()
    elapsed_seconds: float = 0.0
    implementation: str = "unknown"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    message: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    graph: BitGraph
    removed_edges: tuple[tuple[int, int], ...] = ()
    added_edges: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class SeedGenerationTrace:
    generator_mode: str = ""
    attempts: int = 0
    retry_budget: int = 0
    failure_category: str | None = None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    valid: bool
    witness_counts: tuple[tuple[int, int], ...]
    weighted_penalty: int
    complete: bool
    novelty: float = 0.0
    simplicity: int = 0

    @property
    def ordering_key(self) -> tuple[int, int, int, int, int]:
        total = sum(count for _, count in self.witness_counts)
        return (
            0 if self.valid else 1,
            total,
            self.weighted_penalty,
            -round(self.novelty * 1_000_000),
            self.simplicity,
        )


class TargetPlugin(Protocol):
    id: str
    statement: str
    control_only: bool

    def forbidden_lengths(self, order: int) -> tuple[int, ...]: ...
    def validate_graph(self, graph: BitGraph) -> ValidationResult: ...
    def generate_seed(
        self,
        rng: Random,
        config: dict[str, Any],
        *,
        trace: SeedGenerationTrace | None = None,
    ) -> BitGraph: ...
    def mutate(
        self, graph: BitGraph, rng: Random, config: dict[str, Any]
    ) -> BitGraph: ...
    def score_from_cycle_counts(
        self,
        graph: BitGraph,
        cap: int,
        results: tuple[CycleCountResult, ...],
        profile: object | None,
    ) -> ScoreResult: ...
    def exact_verify(self, graph: BitGraph) -> VerifyResult: ...
    def canonical_key(self, graph: BitGraph) -> bytes: ...
    def explain(self, graph: BitGraph, result: VerifyResult) -> dict[str, Any]: ...

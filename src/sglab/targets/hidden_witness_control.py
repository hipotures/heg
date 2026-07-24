from __future__ import annotations

from time import perf_counter

from ..model import BitGraph, find_cycle_of_length
from .base import ScoreResult, ValidationResult, VerifyResult, Witness
from .erdos_gyarfas import ErdosGyarfasPlugin


class HiddenWitnessControlPlugin(ErdosGyarfasPlugin):
    """Deliberately false acceptance target; never a research claim."""

    id = "m6_hidden_witness_control_v1"
    statement = (
        "Control-only false statement: every connected cubic graph on ten "
        "vertices contains a triangle. The finite witness is withheld from "
        "the Director prompt."
    )
    control_only = True

    def forbidden_lengths(self, order: int) -> tuple[int, ...]:
        return (3,) if order == 10 else ()

    def validate_graph(self, graph: BitGraph) -> ValidationResult:
        if graph.n != 10:
            return ValidationResult(False, "control target requires order ten")
        if not graph.is_connected():
            return ValidationResult(False, "control graph must be connected")
        if any(graph.degree(vertex) != 3 for vertex in range(graph.n)):
            return ValidationResult(False, "control graph must be cubic")
        return ValidationResult(True, "valid hidden-witness control candidate")

    def cheap_score(self, graph: BitGraph, cap: int) -> ScoreResult:
        validation = self.validate_graph(graph)
        if not validation.valid:
            return ScoreResult(False, (), 10**9, True, simplicity=graph.size())
        triangle = find_cycle_of_length(graph, 3)
        count = int(triangle is not None)
        return ScoreResult(
            True,
            ((3, count),),
            count,
            True,
            simplicity=graph.size(),
        )

    def exact_verify(self, graph: BitGraph) -> VerifyResult:
        started = perf_counter()
        validation = self.validate_graph(graph)
        if not validation.valid:
            return VerifyResult(
                "INVALID",
                True,
                validation.message,
                elapsed_seconds=perf_counter() - started,
                implementation="python-reference-dfs",
            )
        triangle = find_cycle_of_length(graph, 3)
        if triangle is not None:
            return VerifyResult(
                "REJECTED",
                True,
                "found the required triangle",
                (Witness("cycle_3", triangle),),
                elapsed_seconds=perf_counter() - started,
                implementation="python-reference-dfs",
            )
        return VerifyResult(
            "VERIFIED",
            True,
            "no triangle exists in the complete reference search",
            elapsed_seconds=perf_counter() - started,
            implementation="python-reference-dfs",
        )

    def explain(self, graph: BitGraph, result: VerifyResult) -> dict[str, object]:
        return {
            **super().explain(graph, result),
            "target": self.id,
            "control_only": True,
        }


PLUGIN = HiddenWitnessControlPlugin()

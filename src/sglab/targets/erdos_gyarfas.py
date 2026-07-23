from __future__ import annotations

from ..model import BitGraph, find_cycle_of_length
from .base import VerifyResult, Witness


def forbidden_lengths(n: int) -> tuple[int, ...]:
    values: list[int] = []
    current = 4
    while current <= n:
        values.append(current)
        current *= 2
    return tuple(values)


def verify_reference(graph: BitGraph) -> VerifyResult:
    """Slow exact reference verification for small graphs."""

    if graph.n == 0:
        return VerifyResult("INVALID", True, "graph must be non-empty")
    if not graph.is_connected():
        return VerifyResult("INVALID", True, "minimal-candidate mode requires connectedness")
    if graph.minimum_degree() < 3:
        return VerifyResult("INVALID", True, "minimum degree is below 3")

    for length in forbidden_lengths(graph.n):
        cycle = find_cycle_of_length(graph, length)
        if cycle is not None:
            return VerifyResult(
                "REJECTED",
                True,
                f"found a forbidden cycle of length {length}",
                (Witness(kind=f"cycle_{length}", vertices=cycle),),
            )

    return VerifyResult(
        "VERIFIED",
        True,
        "no power-of-two cycle was found by the complete reference verifier",
    )

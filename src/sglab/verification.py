from __future__ import annotations

from time import perf_counter

from .model import BitGraph
from .targets.base import VerifyResult, Witness
from .targets.erdos_gyarfas import forbidden_lengths


def find_cycle_dynamic(graph: BitGraph, length: int) -> tuple[int, ...] | None:
    """Independent exact-length cycle detector using subset dynamic programming."""

    if length < 3 or length > graph.n:
        return None
    for start in range(graph.n):
        states: dict[tuple[int, int], tuple[int, ...]] = {}
        for neighbour in graph.neighbors(start):
            if neighbour > start:
                mask = (1 << start) | (1 << neighbour)
                states[(mask, neighbour)] = (start, neighbour)
        for _ in range(2, length):
            following: dict[tuple[int, int], tuple[int, ...]] = {}
            for (mask, last), path in states.items():
                available = graph.rows[last] & ~mask
                available &= ~((1 << (start + 1)) - 1)
                while available:
                    bit = available & -available
                    vertex = bit.bit_length() - 1
                    following.setdefault((mask | bit, vertex), path + (vertex,))
                    available ^= bit
            states = following
            if not states:
                break
        for (_, last), path in states.items():
            if graph.has_edge(last, start):
                return path
    return None


def verify_dynamic(graph: BitGraph) -> VerifyResult:
    started = perf_counter()
    if graph.n == 0:
        return _result("INVALID", "graph must be non-empty", started)
    if not graph.is_connected():
        return _result(
            "INVALID", "minimal-candidate mode requires connectedness", started
        )
    if graph.minimum_degree() < 3:
        return _result("INVALID", "minimum degree is below 3", started)
    for length in forbidden_lengths(graph.n):
        witness = find_cycle_dynamic(graph, length)
        if witness is not None:
            return VerifyResult(
                "REJECTED",
                True,
                f"found a forbidden cycle of length {length}",
                (Witness(f"cycle_{length}", witness),),
                perf_counter() - started,
                "python-subset-dp",
            )
    return _result(
        "VERIFIED",
        "no power-of-two cycle was found by the complete subset-DP verifier",
        started,
    )


def _result(status: str, message: str, started: float) -> VerifyResult:
    return VerifyResult(
        status,  # type: ignore[arg-type]
        True,
        message,
        elapsed_seconds=perf_counter() - started,
        implementation="python-subset-dp",
    )

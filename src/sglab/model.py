from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Iterable, Iterator


@dataclass(frozen=True, slots=True)
class BitGraph:
    """Immutable simple undirected graph backed by Python integer bitsets."""

    n: int
    rows: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError("n must be non-negative")
        if len(self.rows) != self.n:
            raise ValueError("rows length must equal n")
        mask = (1 << self.n) - 1 if self.n else 0
        for u, row in enumerate(self.rows):
            if row & ~mask:
                raise ValueError("adjacency row contains an out-of-range vertex")
            if row & (1 << u):
                raise ValueError("loops are not allowed")
        for u, row in enumerate(self.rows):
            bits = row
            while bits:
                lsb = bits & -bits
                v = lsb.bit_length() - 1
                if not (self.rows[v] & (1 << u)):
                    raise ValueError("adjacency must be symmetric")
                bits ^= lsb

    @classmethod
    def empty(cls, n: int) -> "BitGraph":
        return cls(n=n, rows=(0,) * n)

    @classmethod
    def from_edges(cls, n: int, edges: Iterable[tuple[int, int]]) -> "BitGraph":
        rows = [0] * n
        for u, v in edges:
            if not (0 <= u < n and 0 <= v < n):
                raise ValueError("edge endpoint out of range")
            if u == v:
                raise ValueError("loops are not allowed")
            rows[u] |= 1 << v
            rows[v] |= 1 << u
        return cls(n=n, rows=tuple(rows))

    def has_edge(self, u: int, v: int) -> bool:
        return bool(self.rows[u] & (1 << v))

    def degree(self, u: int) -> int:
        return self.rows[u].bit_count()

    def minimum_degree(self) -> int:
        return min((row.bit_count() for row in self.rows), default=0)

    def size(self) -> int:
        return sum(row.bit_count() for row in self.rows) // 2

    def neighbors(self, u: int) -> Iterator[int]:
        bits = self.rows[u]
        while bits:
            lsb = bits & -bits
            yield lsb.bit_length() - 1
            bits ^= lsb

    def edges(self) -> Iterator[tuple[int, int]]:
        for u in range(self.n):
            bits = self.rows[u] & ~((1 << (u + 1)) - 1)
            while bits:
                lsb = bits & -bits
                v = lsb.bit_length() - 1
                yield u, v
                bits ^= lsb

    def is_connected(self) -> bool:
        if self.n == 0:
            return True
        seen = 1
        queue: deque[int] = deque([0])
        while queue:
            u = queue.popleft()
            unseen = self.rows[u] & ~seen
            while unseen:
                lsb = unseen & -unseen
                v = lsb.bit_length() - 1
                seen |= lsb
                queue.append(v)
                unseen ^= lsb
        return seen.bit_count() == self.n


def find_cycle_of_length(graph: BitGraph, length: int) -> tuple[int, ...] | None:
    """Return one simple cycle of exactly ``length`` or ``None``.

    This is a deliberately slow reference implementation. The smallest vertex
    in a cycle is forced to be the DFS start, which removes many duplicates.
    """

    if length < 3 or length > graph.n:
        return None

    for start in range(graph.n):
        path = [start]
        visited = [1 << start]

        def dfs(last: int) -> tuple[int, ...] | None:
            if len(path) == length:
                return tuple(path) if graph.has_edge(last, start) else None

            bits = graph.rows[last] & ~visited[0]
            # All non-start cycle vertices are greater than the chosen minimum.
            bits &= ~((1 << (start + 1)) - 1)
            while bits:
                lsb = bits & -bits
                nxt = lsb.bit_length() - 1
                path.append(nxt)
                visited[0] |= lsb
                result = dfs(nxt)
                visited[0] ^= lsb
                path.pop()
                if result is not None:
                    return result
                bits ^= lsb
            return None

        result = dfs(start)
        if result is not None:
            return result
    return None

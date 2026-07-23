from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Iterable, Iterator
import hashlib


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
            if rows[u] & (1 << v):
                raise ValueError("duplicate edges are not allowed")
            rows[u] |= 1 << v
            rows[v] |= 1 << u
        return cls(n=n, rows=tuple(rows))

    def has_edge(self, u: int, v: int) -> bool:
        return bool(self.rows[u] & (1 << v))

    def degree(self, u: int) -> int:
        return self.rows[u].bit_count()

    def degree_sequence(self) -> tuple[int, ...]:
        return tuple(row.bit_count() for row in self.rows)

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

    def with_edges(
        self,
        *,
        add: Iterable[tuple[int, int]] = (),
        remove: Iterable[tuple[int, int]] = (),
    ) -> "BitGraph":
        rows = list(self.rows)
        for u, v in remove:
            if not self.has_edge(u, v):
                raise ValueError("cannot remove a missing edge")
            rows[u] &= ~(1 << v)
            rows[v] &= ~(1 << u)
        for u, v in add:
            if u == v or not (0 <= u < self.n and 0 <= v < self.n):
                raise ValueError("invalid edge")
            if rows[u] & (1 << v):
                raise ValueError("cannot add an existing edge")
            rows[u] |= 1 << v
            rows[v] |= 1 << u
        return BitGraph(self.n, tuple(rows))

    def to_graph6(self) -> str:
        if self.n <= 62:
            prefix = bytes((self.n + 63,))
        elif self.n <= 258047:
            prefix = bytes(
                (
                    126,
                    ((self.n >> 12) & 63) + 63,
                    ((self.n >> 6) & 63) + 63,
                    (self.n & 63) + 63,
                )
            )
        else:
            raise ValueError("graph6 export supports at most 258047 vertices")
        bits = [int(self.has_edge(u, v)) for v in range(1, self.n) for u in range(v)]
        bits.extend([0] * ((-len(bits)) % 6))
        data = bytes(
            sum(bits[offset + bit] << (5 - bit) for bit in range(6)) + 63
            for offset in range(0, len(bits), 6)
        )
        return (prefix + data).decode("ascii")

    @classmethod
    def from_graph6(cls, value: str | bytes) -> "BitGraph":
        raw = value.encode("ascii") if isinstance(value, str) else value
        raw = raw.strip()
        if raw.startswith(b">>graph6<<"):
            raw = raw[10:]
        if not raw:
            raise ValueError("empty graph6 input")
        if raw[0] != 126:
            n, offset = raw[0] - 63, 1
        elif len(raw) >= 4 and raw[1] != 126:
            n = ((raw[1] - 63) << 12) | ((raw[2] - 63) << 6) | (raw[3] - 63)
            offset = 4
        else:
            raise ValueError("large graph6 order encoding is unsupported")
        if n < 0:
            raise ValueError("invalid graph6 order")
        encoded = raw[offset:]
        if any(byte < 63 or byte > 126 for byte in encoded):
            raise ValueError("invalid graph6 byte")
        required = n * (n - 1) // 2
        required_bytes = (required + 5) // 6
        if len(encoded) < required_bytes:
            raise ValueError("truncated graph6 input")
        if len(encoded) > required_bytes:
            raise ValueError("graph6 input contains trailing data")
        if required % 6 and encoded:
            unused_mask = (1 << (6 - required % 6)) - 1
            if (encoded[-1] - 63) & unused_mask:
                raise ValueError("graph6 padding bits must be zero")
        edges: list[tuple[int, int]] = []
        position = 0
        for v in range(1, n):
            for u in range(v):
                byte = encoded[position // 6] - 63
                if byte & (1 << (5 - position % 6)):
                    edges.append((u, v))
                position += 1
        return cls.from_edges(n, edges)

    def stable_hash(self) -> str:
        return hashlib.sha256(self.to_graph6().encode("ascii")).hexdigest()


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


def find_cycles_of_length(
    graph: BitGraph, length: int, limit: int
) -> tuple[tuple[int, ...], ...]:
    """Enumerate at most ``limit`` cycles, without rotations or reversals."""

    return find_cycles_of_length_bounded(graph, length, limit, None)[0]


def find_cycles_of_length_bounded(
    graph: BitGraph,
    length: int,
    limit: int,
    node_budget: int | None,
) -> tuple[tuple[tuple[int, ...], ...], bool]:
    """Enumerate cycles under an optional DFS-node budget.

    The boolean is true only when enumeration was exhaustive before reaching
    either the witness limit or the work budget.
    """

    if limit <= 0 or length < 3 or length > graph.n:
        return (), True
    if node_budget is not None and node_budget < 1:
        raise ValueError("node_budget must be positive")
    found: list[tuple[int, ...]] = []
    visited_nodes = 0
    budget_exhausted = False
    for start in range(graph.n):
        path = [start]
        visited = 1 << start

        def dfs(last: int, seen: int) -> None:
            nonlocal visited_nodes, budget_exhausted
            if len(found) >= limit or budget_exhausted:
                return
            visited_nodes += 1
            if node_budget is not None and visited_nodes > node_budget:
                budget_exhausted = True
                return
            if len(path) == length:
                if graph.has_edge(last, start) and path[1] < path[-1]:
                    found.append(tuple(path))
                return
            bits = graph.rows[last] & ~seen
            bits &= ~((1 << (start + 1)) - 1)
            while bits and len(found) < limit and not budget_exhausted:
                bit = bits & -bits
                path.append(bit.bit_length() - 1)
                dfs(path[-1], seen | bit)
                path.pop()
                bits ^= bit

        dfs(start, visited)
        if len(found) >= limit:
            break
        if budget_exhausted:
            break
    return tuple(found), not budget_exhausted and len(found) < limit

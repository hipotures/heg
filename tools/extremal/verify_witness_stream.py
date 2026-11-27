#!/usr/bin/env python3
"""Independent Python witness-stream verifier for `sglab-rust-engine scan-batch`.

Reads the original raw dataset (`g6`, `s6`, `psv-tsv`, or `conder-edges`, plain or `.gz`)
together with the witness stream (`<id>\t<n>\t<L>\t<v0,v1,...>`, plain or `.gz`), and
independently certifies for 100% of records:
  1. Graph ID and order match 1-to-1 (no missing or extra graphs).
  2. Optional 3-regularity check (--expect-cubic).
  3. Every non-NONE witness is a valid simple cycle of power-of-two length L >= 4
     whose edges all exist in the independently decoded graph.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
from pathlib import Path
from typing import Iterator

csv.field_size_limit(10 * 1024 * 1024)


def open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def decode_graph6(raw: str) -> tuple[int, list[set[int]]]:
    s = raw.strip()
    if s.startswith(">>graph6<<"):
        s = s[10:]
    b = [ord(c) - 63 for c in s]
    if b[0] != 63:
        n, pos = b[0], 1
    else:
        n = (b[1] << 12) | (b[2] << 6) | b[3]
        pos = 4
    adj: list[set[int]] = [set() for _ in range(n)]
    bit_buf = 0
    bits_left = 0
    for v in range(1, n):
        for u in range(v):
            if bits_left == 0:
                bit_buf = b[pos]
                pos += 1
                bits_left = 6
            bits_left -= 1
            if (bit_buf >> bits_left) & 1:
                adj[u].add(v)
                adj[v].add(u)
    return n, adj


def decode_sparse6(raw: str) -> tuple[int, list[set[int]]]:
    s = raw.strip()
    if s.startswith(">>sparse6<<"):
        s = s[11:]
    assert s[0] == ":", f"bad sparse6 prefix: {s[:10]}"
    b = [ord(c) - 63 for c in s[1:]]
    if b[0] != 63:
        n, pos = b[0], 1
    else:
        n = (b[1] << 12) | (b[2] << 6) | b[3]
        pos = 4
    adj: list[set[int]] = [set() for _ in range(n)]
    if n <= 1:
        return n, adj
    k = (n - 1).bit_length()
    bits = []
    for val in b[pos:]:
        for sh in (5, 4, 3, 2, 1, 0):
            bits.append((val >> sh) & 1)
    v = 0
    i = 0
    tb = len(bits)
    while i + 1 + k <= tb:
        bf = bits[i]
        i += 1
        x = 0
        for _ in range(k):
            x = (x << 1) | bits[i]
            i += 1
        if bf == 1:
            v += 1
        if v >= n or x >= n:
            break
        if x > v:
            v = x
        elif x < v:
            adj[x].add(v)
            adj[v].add(x)
    return n, adj


def iter_graphs(path: Path, fmt: str, max_order: int | None) -> Iterator[tuple[str, int, list[set[int]]]]:
    if fmt in ("g6", "s6"):
        seq = 0
        dec = decode_graph6 if fmt == "g6" else decode_sparse6
        with open_text(path) as f:
            for line in f:
                t = line.strip()
                if not t:
                    continue
                seq += 1
                n, adj = dec(t)
                if max_order is not None and n > max_order:
                    continue
                yield str(seq), n, adj
    elif fmt == "psv-tsv":
        with open_text(path) as f:
            reader = csv.reader(f, delimiter="|", quotechar='"')
            for cols in reader:
                if not cols or cols[0] == "id":
                    continue
                gid = f"psv:{cols[0]}"
                order = int(cols[2])
                if max_order is not None and order > max_order:
                    continue
                n, adj = decode_sparse6(cols[3])
                assert n == order, f"{gid}: order mismatch {n} != {order}"
                yield gid, n, adj
    elif fmt == "conder-edges":
        cur_id = ""
        in_graph = False
        n = 0
        adj: list[set[int]] = []
        skip = False
        with open_text(path) as f:
            for line in f:
                t = line.strip()
                if not t:
                    continue
                if t.startswith("//"):
                    tok = t.lstrip("/").strip().split()[0]
                    if tok.startswith("C"):
                        cur_id = tok
                    continue
                if not in_graph:
                    if "Graph<" in t:
                        after = t.split("Graph<", 1)[1]
                        ord_part, rest = after.split("|", 1)
                        n = int(ord_part.strip())
                        in_graph = True
                        skip = max_order is not None and n > max_order
                        adj = [] if skip else [set() for _ in range(n)]
                        if not skip:
                            _parse_edges(rest, adj)
                        if ">;" in t:
                            in_graph = False
                            if not skip:
                                yield cur_id, n, adj
                else:
                    if not skip:
                        _parse_edges(t, adj)
                    if ">;" in t:
                        in_graph = False
                        if not skip:
                            yield cur_id, n, adj
    else:
        raise ValueError(f"unknown format: {fmt}")


def _parse_edges(text: str, adj: list[set[int]]) -> None:
    i = 0
    L = len(text)
    while i < L:
        if text[i] == "{":
            j = i + 1
            while j < L and text[j].isspace():
                j += 1
            if j < L and text[j].isdigit():
                close = text.index("}", j)
                u_s, v_s = text[j:close].split(",")
                u, v = int(u_s) - 1, int(v_s) - 1
                adj[u].add(v)
                adj[v].add(u)
                i = close + 1
                continue
        i += 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Independent witness-stream verifier")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--format", choices=["g6", "s6", "psv-tsv", "conder-edges"], required=True)
    ap.add_argument("--witnesses", type=Path, required=True)
    ap.add_argument("--expect-cubic", action="store_true")
    ap.add_argument("--max-order", type=int, default=None)
    ap.add_argument("--require-power-of-two", action="store_true", default=True)
    args = ap.parse_args()

    t0 = time.time()
    checked = 0
    none_count = 0
    by_len: dict[str, int] = {}

    with open_text(args.witnesses) as wf:
        w_iter = (line.rstrip("\n") for line in wf if line.strip())
        for gid, n, adj in iter_graphs(args.input, args.format, args.max_order):
            try:
                wline = next(w_iter)
            except StopIteration:
                raise SystemExit(f"ERROR: witness file ended early before graph {gid}")
            parts = wline.split("\t")
            assert len(parts) >= 3, f"bad witness line: {wline!r}"
            wid, wn_s, wlen_s = parts[0], parts[1], parts[2]
            assert wid == gid, f"ID mismatch: witness={wid} vs input={gid}"
            assert int(wn_s) == n, f"{gid}: order mismatch {wn_s} != {n}"
            if args.expect_cubic:
                for u, nbrs in enumerate(adj):
                    assert len(nbrs) == 3, f"{gid}: vertex {u} has deg {len(nbrs)} != 3"
            if wlen_s == "NONE":
                none_count += 1
                by_len["NONE"] = by_len.get("NONE", 0) + 1
            else:
                L = int(wlen_s)
                if args.require_power_of_two:
                    assert L >= 4 and (L & (L - 1)) == 0, f"{gid}: length {L} is not power of two"
                verts = [int(x) for x in parts[3].split(",")]
                assert len(verts) == L, f"{gid}: witness len {len(verts)} != {L}"
                assert len(set(verts)) == L, f"{gid}: duplicate vertex in witness"
                for idx in range(L):
                    u, v = verts[idx], verts[(idx + 1) % L]
                    assert 0 <= u < n and v in adj[u], f"{gid}: missing edge ({u}, {v})"
                by_len[str(L)] = by_len.get(str(L), 0) + 1
            checked += 1

        leftover = next(w_iter, None)
        if leftover is not None:
            raise SystemExit(f"ERROR: extra witness line after input EOF: {leftover[:80]}")

    elapsed = time.time() - t0
    print(json.dumps({
        "status": "VERIFIED",
        "checked_graphs": checked,
        "none_count": none_count,
        "counts_by_len": dict(sorted(by_len.items(), key=lambda kv: (kv[0] == "NONE", int(kv[0]) if kv[0] != "NONE" else 0))),
        "elapsed_seconds": round(elapsed, 3),
    }))


if __name__ == "__main__":
    main()

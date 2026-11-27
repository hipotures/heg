#!/usr/bin/env python3
"""INSTANT TEST OF OUR BRAND-NEW 8-VERTEX {C4,C8,C16}-FREE GADGET H8* (mins=(2,3,3)!)
Plugged into Petersen (10) + H7 for n = 72, 73, 74, 75, 76 (delta >= 3, {C4, C8, C16}-free)!
With IMMEDIATE TRIPLE INDEPENDENT CERTIFICATION (M4 C++17 + Rust verify-exact + Pure Python DFS)!
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from collections import Counter, deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from sglab.certification import verify_cpp
from sglab.model import BitGraph

RUST_BIN = REPO / "_build" / "sglab-rust-engine"
OUT_DIR = Path(os.environ.get("SGLAB_OUT_DIR", "."))

H7_EDGES = [(0, 3), (0, 4), (1, 3), (1, 5), (2, 4), (2, 6), (3, 5), (4, 6), (5, 6)]
# H8* discovered by 16-core C++17 gadget hunter!
# Ports 0,1,2 (deg 2); internals 3,4,5,6 (deg 3), 7 (deg 4):
H8_EDGES = [(0, 3), (0, 4), (1, 3), (1, 6), (2, 5), (2, 7), (3, 5), (4, 6), (4, 7), (5, 7), (6, 7)]
# Note: in H8*, port 0-1 has dist 2 (via 3), while 0-2 and 1-2 BOTH have dist >= 3!!
# So port 2 is the distinguished "good" port (any path using port 2 has length >= 3!),
# and ONLY the pair (0, 1) has length 2!

def adj_from_edges(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    adj: list[list[int]] = [[] for _ in range(n)]
    for u, v in edges:
        adj[u].append(v); adj[v].append(u)
    return [sorted(x) for x in adj]

def port_windows(adj: list[list[int]], ports: tuple[int, int, int]) -> dict[tuple[int, int], list[int]]:
    out = {}
    for i in range(3):
        for j in range(i + 1, 3):
            s, t = ports[i], ports[j]
            lens: set[int] = set()
            def dfs(u: int, d: int, vis: int) -> None:
                if u == t:
                    lens.add(d); return
                for w in adj[u]:
                    if not (vis & (1 << w)):
                        dfs(w, d + 1, vis | (1 << w))
            dfs(s, 0, 1 << s)
            out[(i, j)] = sorted(lens)
    return out

# Verify H8* windows!
h8_adj = adj_from_edges(8, H8_EDGES)
print("H8* exact port windows:", port_windows(h8_adj, (0, 1, 2)))
# Re-index H8* ports so distinguished port (the one whose incident pairs BOTH have min>=3) is slot 0!
# Here port 2 has S(2,0)>=3 and S(2,1)>=3, while S(0,1) has 2!
# So in our port convention:
#   - For H7:  p0=0 -> pairs using p0 have min=2, pair AVOIDING p0 has min=3 (bonus when p0 is OFF cycle!)
#   - For H8*: p_good=2 -> pairs USING p_good have min=3, pair AVOIDING p_good has min=2 (bonus when p_good is ON cycle!)

def build_petersen() -> list[list[int]]:
    edges = []
    for i in range(5):
        edges += [(i, (i + 1) % 5), (i, i + 5), (i + 5, 5 + (i + 2) % 5)]
    return adj_from_edges(10, edges)

pet = build_petersen()
# Enumerate all 12 five-cycles of Petersen
five_cycles = []
for s in range(10):
    def dfs5(u: int, path: list[int]) -> None:
        if len(path) == 5:
            if s in pet[u] and path[1] < u:
                five_cycles.append(tuple(path))
            return
        for w in pet[u]:
            if w > s and w not in path:
                dfs5(w, path + [w])
    dfs5(s, [s])
print(f"Petersen 5-cycles: {len(five_cycles)}")

# Precompute for each 5-cycle: list of (v, off_cycle_nbr_idx)
cyc_off = []
for cyc in five_cycles:
    items = []
    for i in range(5):
        v = cyc[i]
        ia = pet[v].index(cyc[(i - 1) % 5])
        ib = pet[v].index(cyc[(i + 1) % 5])
        items.append((v, 3 - ia - ib))
    cyc_off.append(items)

def solve_petersen_h8_h7(h8_verts: set[int]) -> list[int] | None:
    """Exact backtracking over choice[v] in {0, 1, 2}:
      - if v in h8_verts: choice[v] is the neighbor mapped to port 2 (good port: gives +1 iff choice[v] != off_idx)
      - if v not in h8_verts (H7): choice[v] is the neighbor mapped to port 0 (gives +1 iff choice[v] == off_idx)
    Need total +1 bonus >= 2 on EVERY 5-cycle of Petersen!"""
    choice = [-1] * 10

    def bt(v: int) -> list[int] | None:
        if v == 10:
            return list(choice)
        for c in range(3):
            choice[v] = c
            # Check all 5-cycles that are fully assigned (or prune early!)
            ok = True
            for items in cyc_off:
                bonus = 0
                unassigned = 0
                for u, off_idx in items:
                    if choice[u] == -1:
                        unassigned += 1
                    elif u in h8_verts:
                        if choice[u] != off_idx:
                            bonus += 1
                    else:
                        if choice[u] == off_idx:
                            bonus += 1
                if bonus + unassigned < 2:
                    ok = False
                    break
            if ok:
                res = bt(v + 1)
                if res is not None:
                    return res
        choice[v] = -1
        return None

    return bt(0)

def build_graph(h8_verts: set[int], choice: list[int]) -> BitGraph:
    offsets = []
    cur = 0
    for v in range(10):
        offsets.append(cur)
        cur += 8 if v in h8_verts else 7
    edges = []
    for v in range(10):
        off = offsets[v]
        gedges = H8_EDGES if v in h8_verts else H7_EDGES
        for a, b in gedges:
            edges.append((off + a, off + b))
    def port_of(v: int, nbr_idx: int) -> int:
        c = choice[v]
        if v in h8_verts:
            # nbr_idx == c maps to port 2 (good port); others map to 0, 1
            if nbr_idx == c:
                return offsets[v] + 2
            others = [x for x in (0, 1, 2) if x != c]
            return offsets[v] + (0 if nbr_idx == others[0] else 1)
        else:
            # nbr_idx == c maps to port 0 (bad port); others map to 1, 2
            if nbr_idx == c:
                return offsets[v] + 0
            others = [x for x in (0, 1, 2) if x != c]
            return offsets[v] + (1 if nbr_idx == others[0] else 2)
    for u in range(10):
        for iu, v in enumerate(pet[u]):
            if u < v:
                iv = pet[v].index(u)
                edges.append((port_of(u, iu), port_of(v, iv)))
    rows = [0] * cur
    for a, b in edges:
        rows[a] |= 1 << b
        rows[b] |= 1 << a
    return BitGraph(cur, tuple(rows))

def find_exact_cycle_py(adj: list[list[int]], target: int) -> list[int] | None:
    n = len(adj)
    for s in range(n - target + 1):
        nbrs_s = [v for v in adj[s] if v > s]
        if len(nbrs_s) < 2:
            continue
        dist = [-1] * n; dist[s] = 0; q = deque([s])
        while q:
            u = q.popleft()
            if dist[u] >= target - 1: continue
            for w in adj[u]:
                if w > s and dist[w] == -1:
                    dist[w] = dist[u] + 1; q.append(w)
        def dfs(u: int, depth: int, vis: int, path: list[int], first: int) -> list[int] | None:
            if depth == target:
                return list(path) if (s in adj[u] and first < u) else None
            rem = target - depth
            for w in adj[u]:
                if w > s and not (vis & (1 << w)) and 0 <= dist[w] <= rem:
                    path.append(w)
                    r = dfs(w, depth + 1, vis | (1 << w), path, first)
                    if r is not None: return r
                    path.pop()
            return None
        for v in nbrs_s:
            r = dfs(v, 2, (1 << s) | (1 << v), [s, v], v)
            if r is not None: return r
    return None

def is_biconnected(adj: list[list[int]]) -> bool:
    n = len(adj)
    disc = [-1]*n; low = [0]*n; par = [-1]*n; rc = 0; ap = False; t = 1
    st = [(0, 0)]; disc[0] = low[0] = 0
    while st:
        u, idx = st[-1]
        if idx < len(adj[u]):
            st[-1] = (u, idx + 1)
            v = adj[u][idx]
            if disc[v] == -1:
                par[v] = u
                if u == 0: rc += 1
                disc[v] = low[v] = t; t += 1
                st.append((v, 0))
            elif v != par[u]:
                low[u] = min(low[u], disc[v])
        else:
            st.pop()
            p = par[u]
            if p != -1:
                low[p] = min(low[p], low[u])
                if p != 0 and low[u] >= disc[p]: ap = True
    return all(d != -1 for d in disc) and rc <= 1 and not ap

records = []
for r in [2, 3, 4, 5]:
    target_n = 70 + r
    found_sol = None
    # Try subsets of size r in Petersen
    for comb in itertools.combinations(range(10), r):
        sol = solve_petersen_h8_h7(set(comb))
        if sol is not None:
            found_sol = (set(comb), sol)
            break
    if found_sol is None:
        print(f"r={r} (n={target_n}): NO zero-bad-5cycle solution on Petersen.", flush=True)
    else:
        h8s, sol = found_sol
        bg = build_graph(h8s, sol)
        g6 = bg.to_graph6()
        adj = [[v for v in range(bg.n) if bg.has_edge(u, v)] for u in range(bg.n)]
        degs = dict(sorted(Counter(len(x) for x in adj).items()))
        biconn = is_biconnected(adj)
        ve = json.loads(subprocess.check_output([str(RUST_BIN), "verify-exact", "--graph6", g6], text=True))
        m4 = verify_cpp(bg, timeout_seconds=60, lengths=(4, 8, 16))
        py4 = find_exact_cycle_py(adj, 4)
        py8 = find_exact_cycle_py(adj, 8)
        py16 = find_exact_cycle_py(adj, 16)
        ok = (
            biconn and min(degs) >= 3
            and ve["c16_exact_count"] == 0
            and ve["lengths"]["4"] == "ABSENT" and ve["lengths"]["8"] == "ABSENT" and ve["lengths"]["16"] == "ABSENT"
            and m4["status"] == "ABSENT" and m4["complete"] is True
            and py4 is None and py8 is None and py16 is None
        )
        print(f"\n{'!'*78}")
        print(f"!!! TRIPLE-CERTIFIED f_{{delta>=3}}(4) <= {target_n} RECORD (Petersen + {r}*H8* + {10-r}*H7) OK={ok} !!!")
        print(f"  n={bg.n} m={bg.size()} degs={degs} biconn={biconn} h8_verts={sorted(h8s)}")
        print(f"  [1] Rust verify-exact : c16={ve['c16_exact_count']} lengths={ve['lengths']} ({ve['elapsed_ms']:.2f}ms)")
        print(f"  [2] M4 C++17 (4,8,16) : status={m4['status']} complete={m4['complete']} ({m4['elapsed_seconds']*1000:.2f}ms)")
        print(f"  [3] Python exact DFS  : C4={py4} C8={py8} C16={py16}")
        print(f"  graph6: {g6}")
        print(f"{'!'*78}\n", flush=True)
        records.append({
            "n": bg.n, "m": bg.size(), "degs": degs, "biconn": biconn,
            "h8_verts": sorted(h8s), "choice": sol, "ok": ok,
            "ve": ve, "m4": m4, "g6": g6,
        })
        if ok:
            break

(OUT_DIR / "h8star_f4_records.json").write_text(json.dumps(records, indent=2))

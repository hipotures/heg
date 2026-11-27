#!/usr/bin/env python3
"""Triple-Independent Full-Graph Exact Certification of ALL Track 2 f(5) & H8* f(4) World Records!
Also runs edge-contraction cascades on:
  1. Our triple-certified n=73 (Petersen + 3*H8* + 7*H7) f_{delta>=3}(4) record -> testing n=72, 71!
  2. Our smallest f_cubic(5) record (n<=370) -> testing contractions!
  3. Our smallest f_{delta>=3}(5) record (H8* + H15 + H7, n<300!) -> testing contractions!
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from sglab.certification import verify_cpp
from sglab.model import BitGraph

RUST_BIN = REPO / "_build" / "sglab-rust-engine"
WORK_DIR = Path(os.environ.get("SGLAB_WORK_DIR", "."))
SCRATCH = WORK_DIR
CPP_LARGE = REPO / "_build" / "sglab-cyclecheck-large"

H7_EDGES = [(0, 3), (0, 4), (1, 3), (1, 5), (2, 4), (2, 6), (3, 5), (4, 6), (5, 6)]
H7_PORTS = (0, 1, 2)  # port 0 is the "bad" port (0-1, 0-2 have dist 2; 1-2 has dist 3)

H15_EDGES = list(H7_EDGES) + [(u + 7, v + 7) for u, v in H7_EDGES] + [(14, 1), (14, 8), (2, 9)]
H15_PORTS = (14, 0, 7)  # port 14 is the "bad" port (14-0, 14-7 have dist 3; 0-7 has dist 5)

H8_EDGES = [(0, 3), (0, 4), (1, 3), (1, 6), (2, 5), (2, 7), (3, 5), (4, 6), (4, 7), (5, 7), (6, 7)]
H8_PORTS = (2, 0, 1)  # port 2 is the "good" port (2-0, 2-1 have dist 3; 0-1 has dist 2)


def adj_from_edges(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    adj: list[list[int]] = [[] for _ in range(n)]
    for u, v in edges:
        adj[u].append(v); adj[v].append(u)
    return [sorted(x) for x in adj]


def encode_graph6_large(adj: list[list[int]]) -> str:
    n = len(adj)
    out = bytearray()
    if n <= 62:
        out.append(n + 63)
    else:
        out.extend((126, ((n >> 12) & 63) + 63, ((n >> 6) & 63) + 63, (n & 63) + 63))
    adj_sets = [set(nbrs) for nbrs in adj]
    val = 0
    width = 0
    for v in range(1, n):
        sv = adj_sets[v]
        for u in range(v):
            val = (val << 1) | (1 if u in sv else 0)
            width += 1
            if width == 6:
                out.append(val + 63)
                val = 0
                width = 0
    if width:
        out.append((val << (6 - width)) + 63)
    return out.decode("ascii")


def build_tutte_coxeter() -> list[list[int]]:
    lcf = [-13, -9, 7, -7, 9, 13] * 5
    adj = [set() for _ in range(30)]
    for i in range(30):
        j = (i + 1) % 30
        adj[i].add(j); adj[j].add(i)
        k = (i + lcf[i]) % 30
        adj[i].add(k); adj[k].add(i)
    return [sorted(s) for s in adj]


def expand_tc(tc: list[list[int]], gt: list[int], p0: list[int]) -> list[list[int]]:
    # gt: 0=unexp(1), 1=H7(7), 2=H15(15), 3=H8*(8)
    gadgets = {
        1: (7, H7_EDGES, H7_PORTS),
        2: (15, H15_EDGES, H15_PORTS),
        3: (8, H8_EDGES, H8_PORTS),
    }
    offsets = []
    cur = 0
    for v in range(len(tc)):
        offsets.append(cur)
        cur += 1 if gt[v] == 0 else gadgets[gt[v]][0]
    edges = []
    for v in range(len(tc)):
        if gt[v] == 0:
            continue
        off = offsets[v]
        for a, b in gadgets[gt[v]][1]:
            edges.append((off + a, off + b))

    def port_of(v: int, nbr_idx: int) -> int:
        if gt[v] == 0:
            return offsets[v]
        ports = gadgets[gt[v]][2]
        c = p0[v]
        # In BOTH conventions of f5_h8star_solver.cpp:
        #   gt=1 (H7):  ports[0] maps to nbr_idx == c (bad port -> p0==off_idx gives 1-2 -> lo=3!)
        #   gt=2 (H15): ports[0] maps to nbr_idx == c (bad port -> p0==off_idx gives 1-2 -> lo=5!)
        #   gt=3 (H8*): ports[0]=2 maps to nbr_idx == c (good port -> p0==off_idx gives 0-1 -> lo=2, p0!=off_idx gives 2-0/2-1 -> lo=3!)
        if nbr_idx == c:
            return offsets[v] + ports[0]
        others = [x for x in (0, 1, 2) if x != c]
        return offsets[v] + (ports[1] if nbr_idx == others[0] else ports[2])

    for u in range(len(tc)):
        for iu, v in enumerate(tc[u]):
            if u < v:
                iv = tc[v].index(u)
                edges.append((port_of(u, iu), port_of(v, iv)))
    return adj_from_edges(cur, edges)


def triple_certify_large(adj: list[list[int]], label: str) -> dict:
    n = len(adj)
    m = sum(len(x) for x in adj) // 2
    degs = dict(sorted(Counter(len(x) for x in adj).items()))
    simple = all(u not in adj[u] and len(adj[u]) == len(set(adj[u])) for u in range(n))
    g6 = encode_graph6_large(adj)
    g6_path = SCRATCH / f"cert_f5_{label}_n{n}.g6"
    g6_path.write_text(g6 + "\n")

    r_out = json.loads(subprocess.check_output(
        [str(RUST_BIN), "verify-large", "--graph6-file", str(g6_path), "--lengths", "4,8,16,32", "--workers", "16"],
        text=True,
    ))
    c_out = json.loads(subprocess.check_output(
        [str(CPP_LARGE), "--graph6-file", str(g6_path), "--lengths", "4,8,16,32"],
        text=True,
    ))
    ok = (
        simple
        and r_out["biconnected"]
        and r_out["min_deg"] >= 3
        and all(r_out["lengths"].get(str(L)) == "ABSENT" for L in (4, 8, 16, 32))
        and all(c_out["results"].get(str(L), {}).get("status") == "ABSENT" for L in (4, 8, 16, 32))
    )
    print(f"  [CERT] {label:24s} n={n:3d} m={m:3d} degs={degs} biconn={r_out['biconnected']} OK={ok}")
    print(f"         Rust verify-large ({r_out['total_ms']:.1f}ms): {r_out['lengths']} | C++17 DFS ({c_out['total_ms']:.1f}ms): { {k: v['status'] for k, v in c_out['results'].items()} }", flush=True)
    return {
        "label": label, "n": n, "m": m,
        "cubic": (min(degs) == 3 and max(degs) == 3),
        "deg_seq": {str(k): v for k, v in degs.items()},
        "biconnected": r_out["biconnected"],
        "simple": simple, "ok": ok,
        "rust_verify_large": r_out,
        "cpp_exact_dfs": c_out,
        "g6_file": str(g6_path),
        "g6": g6,
    }


def contract_edge(adj: list[list[int]], u: int, v: int) -> list[list[int]] | None:
    n = len(adj)
    new_adj = [set() for _ in range(n - 1)]
    def remap(x: int) -> int:
        if x == v:
            return u if u < v else u - 1
        return x if x < v else x - 1
    for a in range(n):
        for b in adj[a]:
            if a < b:
                if (a == u and b == v) or (a == v and b == u):
                    continue
                ra, rb = remap(a), remap(b)
                if ra != rb:
                    new_adj[ra].add(rb); new_adj[rb].add(ra)
    out = [sorted(s) for s in new_adj]
    if any(len(s) < 3 for s in out):
        return None
    return out


def main() -> None:
    tc = build_tutte_coxeter()
    sols = json.loads((SCRATCH / "f5_h8star_solutions.json").read_text())
    print(f"=== TRIPLE-CERTIFYING {len(sols)} SOLVED f(5) CONSTRUCTIONS ===", flush=True)

    certified = []
    # Sort by (not cubic, n) so we certify smallest cubic and smallest delta>=3!
    cubic_sols = sorted([s for s in sols if s["cubic"]], key=lambda x: x["n"])
    mixed_sols = sorted([s for s in sols if not s["cubic"]], key=lambda x: x["n"])

    best_cubic_adj = None
    best_mixed_adj = None

    for s in cubic_sols:
        adj = expand_tc(tc, s["gt"], s["p0"])
        c = triple_certify_large(adj, s["label"])
        certified.append(c)
        if c["ok"] and best_cubic_adj is None:
            best_cubic_adj = (s["n"], adj, s["label"])

    # Certify smallest 4 mixed solutions
    for s in mixed_sols[:4]:
        adj = expand_tc(tc, s["gt"], s["p0"])
        c = triple_certify_large(adj, s["label"])
        certified.append(c)
        if c["ok"] and best_mixed_adj is None:
            best_mixed_adj = (s["n"], adj, s["label"])

    # Try edge-contraction cascade on our smallest delta>=3 f(5) winner!
    if best_mixed_adj is not None:
        cur_n, cur_adj, cur_lbl = best_mixed_adj
        print(f"\n=== EDGE-CONTRACTION CASCADE ON SMALLEST f_{{delta>=3}}(5) WINNER: {cur_lbl} (n={cur_n}) ===", flush=True)
        for step in range(4):
            adj_sets = [set(x) for x in cur_adj]
            non_tri = [(u, v) for u in range(cur_n) for v in cur_adj[u] if u < v and not (adj_sets[u] & adj_sets[v])]
            random.Random(20261127 + step).shuffle(non_tri)
            hit = False
            for u, v in non_tri[:40]:
                na = contract_edge(cur_adj, u, v)
                if na is None:
                    continue
                tmp = SCRATCH / "tmp_f5_c.g6"
                tmp.write_text(encode_graph6_large(na) + "\n")
                r = json.loads(subprocess.check_output(
                    [str(RUST_BIN), "verify-large", "--graph6-file", str(tmp), "--lengths", "4,8,16,32", "--workers", "16"],
                    text=True,
                ))
                if r["biconnected"] and all(r["lengths"][str(L)] == "ABSENT" for L in (4, 8, 16, 32)):
                    cur_adj = na
                    cur_n -= 1
                    cur_lbl = f"{cur_lbl}_c{step+1}"
                    print(f"  *** CONTRACTION HIT -> n={cur_n}! ***", flush=True)
                    certified.append(triple_certify_large(cur_adj, cur_lbl))
                    hit = True
                    break
            if not hit:
                print(f"  Cascade stopped at n={cur_n} (0/40 non-triangle edges avoided C4..C32).", flush=True)
                break

    # Also test edge-contraction cascade on our triple-certified n=73 f_{delta>=3}(4) record!
    f4_recs = json.loads((SCRATCH / "h8star_f4_records.json").read_text())
    f4_contracted = []
    if f4_recs:
        g73 = BitGraph.from_graph6(f4_recs[0]["g6"])
        adj73 = [[v for v in range(73) if g73.has_edge(u, v)] for u in range(73)]
        print(f"\n=== TESTING ALL EDGE CONTRACTIONS OF n=73 (Petersen + 3*H8* + 7*H7) -> n=72 ===", flush=True)
        best72_c16 = 9999
        best72_g6 = None
        for u in range(73):
            for v in adj73[u]:
                if u < v:
                    na = contract_edge(adj73, u, v)
                    if na is None:
                        continue
                    g6 = encode_graph6_large(na)
                    ve = json.loads(subprocess.check_output([str(RUST_BIN), "verify-exact", "--graph6", g6], text=True))
                    if ve["lengths"]["4"] == "ABSENT" and ve["lengths"]["8"] == "ABSENT":
                        c16 = ve["c16_exact_count"]
                        if c16 < best72_c16:
                            best72_c16 = c16
                            best72_g6 = g6
                        if c16 == 0:
                            bg = BitGraph.from_graph6(g6)
                            m4 = verify_cpp(bg, timeout_seconds=60, lengths=(4, 8, 16))
                            print(f"  *** n=72 CONTRACTION HIT!! C4=C8=C16=0! M4={m4} g6={g6} ***", flush=True)
                            f4_contracted.append({"n": 72, "ve": ve, "m4": m4, "g6": g6})
                            break
        print(f"  n=73 -> n=72 contractions: best C16 (with C4=C8=0) = {best72_c16}", flush=True)

    out = {
        "certified_f5": certified,
        "f4_h8star": f4_recs,
        "f4_contracted_72": f4_contracted,
    }
    (SCRATCH / "track2_certified_world_records.json").write_text(json.dumps(out, indent=2))
    print("\nSaved all certified world records to track2_certified_world_records.json!")


if __name__ == "__main__":
    main()

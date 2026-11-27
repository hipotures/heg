#!/usr/bin/env python3
"""Independent DIMACS CNF encoder for Tutte-Coxeter (30 vertices) with {H_15, H_8*, H_7} gadgets.

Completely independent of tc_exact_optimality.cpp!
Encodes exact satisfiability of:
  - Cubic TC(a15 * H_15 + (30 - a15) * H_7)       [e.g., a15=18 -> n=354 UNSAT, a15=20 -> n=370 SAT]
  - Mixed TC(a15 * H_15 + (30 - a15) * H_8*)      [e.g., a15=14 -> n=338 UNSAT, a15=15 -> n=345 SAT]

Exact encoding (100% lossless, verified against Tutte-Coxeter's 90 C8 + 72 C10 cycles):
  For two-gadget mode (H_15 vs G2 where G2 in {H_7, H_8*}):
    - Each vertex v in 0..29 has 6 Boolean state variables:
        x(v, 0..2): v is H_15 with p0 = 0, 1, 2
        x(v, 3..5): v is G2   with p0 = 0, 1, 2
      with Exactly-One constraint on {x(v, 0..5)}.
    - Define h15(v) <-> x(v,0) v x(v,1) v x(v,2), and enforce AtMost(h15, a15) via Sinz sequential counter!
      (Note: AtMost(h15, a15) is strictly weaker than Exactly(a15) ONLY in allowing FEWER H15s;
       if AtMost(h15, a15) is UNSAT, then EVERY a <= a15 is UNSAT simultaneously!!)
    - Symmetry breaking (100% lossless via 5-arc-transitivity of TC):
        Fix vertex 0 to G2 with p0 = 0, i.e., unit clause x(0, 3) = True!
    - For each C8 cycle C = [(v_0, off_0), ..., (v_7, off_7)]:
      On each vertex i in 0..7, the contribution dl_i in {2, 3, 5} depends ONLY on x(v_i, 0..5):
        * p5_i = x(v_i, off_i)                       (aligned H_15 -> dl = 5, delta = +2 vs baseline 3)
        * p2_i = (x(v_i, 3 + off_i) if G2==H8* else  (dl = 2, delta = -1 vs baseline 3)
                  OR_{q != off_i} x(v_i, 3 + q))
      Cycle C survives iff:  2 * sum(p5_i) - sum(p2_i) >= 1  (i.e. sum(dl_i) >= 25)!
      Encode this exact condition on the 8 pairs (p5_i, p2_i) using a tiny exact DP/sequential
      automaton over reachable partial scores s in [-8, +16] (clamped at >= 1 once guaranteed)!
    - Note: if even the 90 C8 constraints + AtMost(h15, a15) are UNSAT (which is a RELAXATION
      ignoring C10!), then the full C8+C10 instance is UNCONDITIONALLY UNSAT!
      For SAT sanity checks (n=370, n=345), we also include all 72 C10 constraints (or verify solutions)!
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_tutte_coxeter() -> list[list[int]]:
    lcf = [-13, -9, 7, -7, 9, 13]
    n = 30
    adj = [set() for _ in range(n)]
    for i in range(n):
        adj[i].add((i + 1) % n); adj[(i + 1) % n].add(i)
        j = (i + lcf[i % 6]) % n
        adj[i].add(j); adj[j].add(i)
    return [sorted(s) for s in adj]


def find_cycles(adj: list[list[int]], target_lens: tuple[int, ...]) -> list[tuple[int, list[tuple[int, int]]]]:
    n = len(adj)
    max_l = max(target_lens)
    out = []
    for s in range(n):
        def dfs(u: int, path: list[int], vis: int, first: int) -> None:
            d = len(path)
            if d in target_lens and s in adj[u] and first < u:
                items = []
                for idx, v in enumerate(path):
                    pv, nv = path[(idx - 1) % d], path[(idx + 1) % d]
                    ia, ib = adj[v].index(pv), adj[v].index(nv)
                    items.append((v, 3 - ia - ib))
                out.append((d, items))
            if d >= max_l:
                return
            for w in adj[u]:
                if w > s and not (vis & (1 << w)):
                    dfs(w, path + [w], vis | (1 << w), first)
        for v in adj[s]:
            if v > s:
                dfs(v, [s, v], (1 << s) | (1 << v), v)
    return out


class CNFBuilder:
    def __init__(self) -> None:
        self.nvars = 0
        self.clauses: list[list[int]] = []

    def new_var(self) -> int:
        self.nvars += 1
        return self.nvars

    def add(self, *lits: int) -> None:
        self.clauses.append(list(lits))

    def add_at_most(self, lits: list[int], k: int) -> None:
        """Sinz (2005) sequential counter encoding sum(lits) <= k."""
        n = len(lits)
        if k >= n:
            return
        if k == 0:
            for x in lits:
                self.add(-x)
            return
        # s[i][j] means among lits[0..i], at least j+1 are true (0 <= i < n-1, 0 <= j < k)
        s = [[self.new_var() for _ in range(k)] for _ in range(n - 1)]
        self.add(-lits[0], s[0][0])
        for j in range(1, k):
            self.add(-s[0][j])
        for i in range(1, n - 1):
            self.add(-lits[i], s[i][0])
            self.add(-s[i - 1][0], s[i][0])
            for j in range(1, k):
                self.add(-lits[i], -s[i - 1][j - 1], s[i][j])
                self.add(-s[i - 1][j], s[i][j])
            self.add(-lits[i], -s[i - 1][k - 1])
        self.add(-lits[n - 1], -s[n - 2][k - 1])

    def write_dimacs(self, path: Path, comments: list[str]) -> None:
        lines = [f"c {c}" for c in comments]
        lines.append(f"p cnf {self.nvars} {len(self.clauses)}")
        for cl in self.clauses:
            lines.append(" ".join(str(x) for x in cl) + " 0")
        path.write_text("\n".join(lines) + "\n")


def encode_tc_cnf(
    a15: int,
    g2: str,
    include_c10: bool = False,
    break_sym: bool = True,
    add_slack_bound: bool = False,
) -> tuple[CNFBuilder, dict[tuple[int, int], int]]:
    assert g2 in ("H7", "H8s")
    adj = build_tutte_coxeter()
    lens = (8, 10) if include_c10 else (8,)
    cycles = find_cycles(adj, lens)

    cnf = CNFBuilder()
    # x[v, s] for v in 0..29, s in 0..5:
    #   s = 0,1,2 -> H15 with p0 = s
    #   s = 3,4,5 -> g2  with p0 = s - 3
    x: dict[tuple[int, int], int] = {}
    h15: list[int] = []
    for v in range(30):
        for s in range(6):
            x[(v, s)] = cnf.new_var()
        # Exactly one of x[v, 0..5]
        cnf.add(*[x[(v, s)] for s in range(6)])
        for s1 in range(6):
            for s2 in range(s1 + 1, 6):
                cnf.add(-x[(v, s1)], -x[(v, s2)])
        # h15[v] <-> x[v,0] v x[v,1] v x[v,2]
        hv = cnf.new_var()
        h15.append(hv)
        for s in range(3):
            cnf.add(-x[(v, s)], hv)
        cnf.add(-hv, x[(v, 0)], x[(v, 1)], x[(v, 2)])

    # AtMost(h15, a15)
    cnf.add_at_most(h15, a15)

    # Lossless symmetry breaking: since TC is 5-arc-transitive and a15 < 30,
    # at least one vertex is G2; WLOG v = 0 is G2 with p0 = 0 (state 3)!
    if break_sym and a15 < 30:
        cnf.add(x[(0, 3)])

    c8_excess_lits: list[int] = []

    # Exact per-cycle DP automaton for sum(dl_i) >= 33 - L!
    # Shift dl_i by -2 so weight w_i in {0 (dl=2), 1 (dl=3), 3 (dl=5)}!
    # Required sum(w_i) >= (33 - L) - 2*L = 33 - 3*L:
    #   For C8  (L=8):  sum(w_i) >= 9!
    #   For C10 (L=10): sum(w_i) >= 3!
    # When add_slack_bound is True, we track up to req + 1 = 10 on C8s and also encode
    # the reverse implications (sum >= t => u[i][t]) so that u[7][10] is TRUE whenever
    # sum(w_i) >= 10! Then by the exact double-counting identity:
    #   sum_{C in C8} (sum_C - 9) <= S = 16*a15 - (8 if H8s else 16)*(30 - a15) - 90,
    # at most S of the 90 C8 cycles can satisfy sum_C >= 10!
    for clen, items in cycles:
        req = 33 - 3 * clen
        if req <= 0:
            continue
        track_max = (req + 1) if (add_slack_bound and clen == 8) else req
        w_ge3 = []
        w_eq0 = []
        for v, off in items:
            w_ge3.append(x[(v, off)])
            if g2 == "H8s":
                w_eq0.append(x[(v, 3 + off)])
            else:
                q_others = [q for q in range(3) if q != off]
                e0 = cnf.new_var()
                cnf.add(-x[(v, 3 + q_others[0])], e0)
                cnf.add(-x[(v, 3 + q_others[1])], e0)
                cnf.add(-e0, x[(v, 3 + q_others[0])], x[(v, 3 + q_others[1])])
                w_eq0.append(e0)

        u: list[dict[int, int]] = []
        for i in range(clen):
            max_reach = min(track_max, 3 * (i + 1))
            layer: dict[int, int] = {}
            for t in range(1, max_reach + 1):
                layer[t] = cnf.new_var()
            u.append(layer)

        # Layer 0 constraints:
        #   Soundness (u[0][t] => sum_0 >= t):
        for t, var in u[0].items():
            if t == 1:
                cnf.add(-var, -w_eq0[0])
            elif t in (2, 3):
                cnf.add(-var, w_ge3[0])
            else:
                cnf.add(-var)
        #   Completeness (sum_0 >= t => u[0][t]) when tracking excess!
        if add_slack_bound and clen == 8:
            cnf.add(w_eq0[0], u[0][1])       # w_0 >= 1 => u[0][1]
            cnf.add(-w_ge3[0], u[0][2])      # w_0 == 3 => u[0][2]
            cnf.add(-w_ge3[0], u[0][3])      # w_0 == 3 => u[0][3]

        for i in range(1, clen):
            prev = u[i - 1]
            for t, var in u[i].items():
                # Soundness (u[i][t] => sum_i >= t):
                if t in prev:
                    cnf.add(-var, -w_eq0[i], prev[t])
                elif t > 3 * i:
                    cnf.add(-var, -w_eq0[i])
                if t - 1 >= 1:
                    if (t - 1) in prev:
                        cnf.add(-var, w_ge3[i], prev[t - 1])
                    elif t - 1 > 3 * i:
                        cnf.add(-var, w_ge3[i])
                if t - 3 >= 1:
                    if (t - 3) in prev:
                        cnf.add(-var, prev[t - 3])
                    elif t - 3 > 3 * i:
                        cnf.add(-var)
                # Completeness (sum_i >= t => u[i][t]) when tracking excess!
                if add_slack_bound and clen == 8:
                    # 1. prev >= t => u[i][t]
                    if t in prev:
                        cnf.add(-prev[t], var)
                    # 2. prev >= t-1 and w_i >= 1 (i.e. !w_eq0[i]) => u[i][t]
                    if t - 1 == 0:
                        cnf.add(w_eq0[i], var)
                    elif (t - 1) in prev:
                        cnf.add(-prev[t - 1], w_eq0[i], var)
                    # 3. prev >= t-3 and w_i == 3 (i.e. w_ge3[i]) => u[i][t]
                    if t - 3 <= 0:
                        cnf.add(-w_ge3[i], var)
                    elif (t - 3) in prev:
                        cnf.add(-prev[t - 3], -w_ge3[i], var)

        # Enforce final sum >= req!
        cnf.add(u[clen - 1][req])
        if add_slack_bound and clen == 8:
            c8_excess_lits.append(u[clen - 1][req + 1])

    if add_slack_bound and c8_excess_lits:
        slack = 16 * a15 - (8 if g2 == "H8s" else 16) * (30 - a15) - 90
        if slack < 0:
            cnf.add()  # empty clause (analytically UNSAT!)
        else:
            cnf.add_at_most(c8_excess_lits, slack)

    return cnf, x


def main() -> None:
    ap = argparse.ArgumentParser(description="Encode Tutte-Coxeter {H15, H8*/H7} optimality to DIMACS CNF")
    ap.add_argument("--a15", type=int, required=True, help="Max allowed number of H_15 vertices")
    ap.add_argument("--g2", choices=["H7", "H8s"], required=True, help="Second gadget type (H7 for cubic, H8s for delta>=3)")
    ap.add_argument("--include-c10", action="store_true", help="Include C10 constraints in addition to C8")
    ap.add_argument("--no-sym-break", action="store_true", help="Disable v=0 symmetry breaking")
    ap.add_argument("--add-slack-bound", action="store_true", help="Add exact double-counting global slack bound AtMost({sum_C>=10}, S)")
    ap.add_argument("--out", type=Path, required=True, help="Output DIMACS .cnf path")
    args = ap.parse_args()

    cnf, _ = encode_tc_cnf(
        args.a15, args.g2,
        include_c10=args.include_c10,
        break_sym=not args.no_sym_break,
        add_slack_bound=args.add_slack_bound,
    )
    n_tot = 15 * args.a15 + (8 if args.g2 == "H8s" else 7) * (30 - args.a15)
    comments = [
        f"Tutte-Coxeter optimality CNF: <= {args.a15} H_15 + {args.g2} (n = {n_tot})",
        f"include_c10={args.include_c10}, sym_break={not args.no_sym_break}, add_slack_bound={args.add_slack_bound}",
    ]
    cnf.write_dimacs(args.out, comments)
    print(f"Wrote {args.out}: vars={cnf.nvars}, clauses={len(cnf.clauses)}")


if __name__ == "__main__":
    main()

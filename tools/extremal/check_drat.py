#!/usr/bin/env python3
"""Independent RUP/DRAT proof checker for DIMACS CNF UNSAT certificates!

Verifies that every added clause C in a DRAT proof is a Reverse Unit Propagation
(RUP) consequence of the current formula F (i.e., F U {~l : l in C} derives a
contradiction via pure unit propagation), and that the proof concludes with the
empty clause 0.

Completely independent of mini_cdcl_drat.cpp and tc_exact_optimality.cpp!
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


def parse_cnf(path: Path) -> tuple[int, list[list[int]]]:
    nvars = 0
    clauses: list[list[int]] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("c"):
            continue
        if s.startswith("p"):
            parts = s.split()
            nvars = int(parts[2])
            continue
        lits = [int(x) for x in s.split()]
        if lits and lits[-1] == 0:
            lits.pop()
        if lits:
            clauses.append(lits)
    return nvars, clauses


class RupChecker:
    def __init__(self, nvars: int, init_clauses: list[list[int]]) -> None:
        self.nvars = nvars
        self.clauses: list[list[int]] = []
        self.watches: list[list[int]] = [[] for _ in range(2 * nvars)]
        self.units: list[int] = []
        self.val: list[int] = [-1] * nvars
        self.trail: list[int] = []
        self.contradiction = False
        for cl in init_clauses:
            self.add_clause(cl)

    @staticmethod
    def to_lit(x: int) -> int:
        v = abs(x) - 1
        return (2 * v) if x > 0 else (2 * v + 1)

    def add_clause(self, dimacs_cl: list[int]) -> None:
        lits = sorted(set(self.to_lit(x) for x in dimacs_cl))
        for i in range(len(lits) - 1):
            if lits[i] == (lits[i + 1] ^ 1):
                return  # tautology
        if not lits:
            self.contradiction = True
            return
        if len(lits) == 1:
            self.units.append(lits[0])
            return
        cid = len(self.clauses)
        self.clauses.append(lits)
        self.watches[lits[0] ^ 1].append(cid)
        self.watches[lits[1] ^ 1].append(cid)

    def _assign(self, lit: int) -> bool:
        v = lit >> 1
        want = 0 if (lit & 1) else 1
        cur = self.val[v]
        if cur != -1:
            return cur == want
        self.val[v] = want
        self.trail.append(lit)
        return True

    def _lit_val(self, lit: int) -> int:
        v = self.val[lit >> 1]
        if v == -1:
            return -1
        return (1 - v) if (lit & 1) else v

    def is_rup(self, dimacs_cl: list[int]) -> bool:
        if self.contradiction:
            return True
        self.trail.clear()
        ok = True
        # Assign all known unit clauses
        for u in self.units:
            if not self._assign(u):
                ok = False
                break
        # Negate every literal in candidate clause
        if ok:
            for x in dimacs_cl:
                if not self._assign(self.to_lit(x) ^ 1):
                    ok = False
                    break
        # Unit propagation
        qhead = 0
        while ok and qhead < len(self.trail):
            p = self.trail[qhead]
            qhead += 1
            ws = self.watches[p]
            false_lit = p ^ 1
            i = 0
            while i < len(ws):
                cid = ws[i]
                lits = self.clauses[cid]
                if lits[0] == false_lit:
                    lits[0], lits[1] = lits[1], lits[0]
                if self._lit_val(lits[0]) == 1:
                    i += 1
                    continue
                found = False
                for k in range(2, len(lits)):
                    if self._lit_val(lits[k]) != 0:
                        lits[1], lits[k] = lits[k], lits[1]
                        self.watches[lits[1] ^ 1].append(cid)
                        ws[i] = ws[-1]
                        ws.pop()
                        found = True
                        break
                if found:
                    continue
                if self._lit_val(lits[0]) == 0:
                    ok = False
                    break
                if not self._assign(lits[0]):
                    ok = False
                    break
                i += 1
        # Unwind trail
        for lit in self.trail:
            self.val[lit >> 1] = -1
        return not ok


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.cnf> <proof.drat>", file=sys.stderr)
        sys.exit(2)
    t0 = time.time()
    nvars, init_clauses = parse_cnf(Path(sys.argv[1]))
    checker = RupChecker(nvars, init_clauses)

    checked = 0
    derived_empty = False
    for lineno, raw in enumerate(Path(sys.argv[2]).read_text().splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("c"):
            continue
        if s.startswith("d "):
            continue  # deletion hints are safe to ignore in soundness checking
        lits = [int(x) for x in s.split()]
        if not lits or lits[-1] != 0:
            raise ValueError(f"Malformed DRAT line {lineno}: {raw}")
        lits.pop()
        if not checker.is_rup(lits):
            print(f"FAIL: clause at line {lineno} is NOT RUP: {lits}", file=sys.stderr)
            sys.exit(1)
        checked += 1
        if not lits:
            derived_empty = True
            break
        checker.add_clause(lits)

    el = time.time() - t0
    if derived_empty:
        print(f"VERIFIED UNSAT (RUP/DRAT): {checked} proof steps checked in {el:.2f}s")
        sys.exit(0)
    else:
        print("FAIL: DRAT proof did not derive empty clause 0", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

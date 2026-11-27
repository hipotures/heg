#!/usr/bin/env python3
"""Reproducible 56-leaf cube-and-conquer CaDiCaL + drat-trim UNSAT prover for
Tutte-Coxeter cubic TC(<=19 * H_15 + H_7) at n = 362.

Exhaustive disjoint partition (100% lossless):
  - Base CNF fixes v=0 to H_7 with p0=0 (state 3) via 5-arc-transitivity of TC.
  - Partition all 6 * 6 = 36 mutually exclusive states of neighbors (v=1, v=29).
  - For the 4 hardest cubes (s1 in {1,2}, s2 in {1,2}), partition further across all
    6 mutually exclusive states of the 3rd neighbor v=17 -> 32 + 24 = 56 disjoint leaves.
  - Every leaf is solved by CaDiCaL with binary DRAT proof and independently verified
    by `drat-trim` (`s VERIFIED`).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tc_to_cnf import encode_tc_cnf


def build_leaf_cubes() -> list[tuple[str, list[tuple[int, int]]]]:
    leaves: list[tuple[str, list[tuple[int, int]]]] = []
    for s1 in range(6):
        for s2 in range(6):
            if s1 in (1, 2) and s2 in (1, 2):
                for s3 in range(6):
                    leaves.append((f"c_{s1}_{s2}_{s3}", [(1, s1), (29, s2), (17, s3)]))
            else:
                leaves.append((f"c_{s1}_{s2}", [(1, s1), (29, s2)]))
    assert len(leaves) == 56
    return leaves


def main() -> None:
    ap = argparse.ArgumentParser(description="56-leaf cube-and-conquer DRAT prover for TC n=362 cubic")
    ap.add_argument("--cadical", type=Path, default=Path("_build/solvers/cadical"))
    ap.add_argument("--drat-trim", type=Path, default=Path("_build/solvers/drat-trim"))
    ap.add_argument("--work-dir", type=Path, default=Path("_build/datasets/tc_sat/n362_56leaves"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--keep-drat", action="store_true")
    args = ap.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    base_cnf, xmap = encode_tc_cnf(19, "H7", include_c10=True, break_sym=True, add_slack_bound=True)
    base_clauses = [" ".join(map(str, cl)) + " 0" for cl in base_cnf.clauses]
    leaves = build_leaf_cubes()

    def run_leaf(item: tuple[str, list[tuple[int, int]]]) -> dict[str, object]:
        tag, fixes = item
        cnf_p = args.work_dir / f"{tag}.cnf"
        drat_p = args.work_dir / f"{tag}.drat"
        header = f"p cnf {base_cnf.nvars} {len(base_clauses) + len(fixes)}"
        extra = [f"{xmap[pair]} 0" for pair in fixes]
        cnf_p.write_text("\n".join([header] + base_clauses + extra) + "\n")

        t0 = time.time()
        r = subprocess.run([str(args.cadical), str(cnf_p), str(drat_p)], capture_output=True, text=True)
        solve_s = round(time.time() - t0, 3)
        if r.returncode != 20:
            return {"tag": tag, "status": f"NON_UNSAT_RC_{r.returncode}", "solve_s": solve_s}
        t1 = time.time()
        rv = subprocess.run([str(args.drat_trim), str(cnf_p), str(drat_p)], capture_output=True, text=True)
        verify_s = round(time.time() - t1, 3)
        ok = rv.returncode == 0 and "s VERIFIED" in rv.stdout
        drat_bytes = drat_p.stat().st_size if drat_p.exists() else 0
        if ok and not args.keep_drat:
            drat_p.unlink(missing_ok=True)
        return {
            "tag": tag,
            "status": "VERIFIED_UNSAT" if ok else "DRAT_FAIL",
            "solve_s": solve_s,
            "verify_s": verify_s,
            "drat_bytes": drat_bytes,
        }

    t_all = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(run_leaf, leaves):
            results.append(res)
            print(f"[{len(results):2d}/56] {res['tag']}: {res['status']} (solve={res['solve_s']}s, verify={res.get('verify_s')}s)", flush=True)

    verified = sum(1 for r in results if r["status"] == "VERIFIED_UNSAT")
    summary = {
        "instance": "TC(<=19*H_15 + H_7) n=362 cubic",
        "leaves_total": len(leaves),
        "leaves_verified_unsat": verified,
        "wall_seconds": round(time.time() - t_all, 3),
        "results": results,
    }
    (args.work_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"leaves_verified_unsat": verified, "leaves_total": len(leaves), "wall_seconds": summary["wall_seconds"]}))
    if verified != len(leaves):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

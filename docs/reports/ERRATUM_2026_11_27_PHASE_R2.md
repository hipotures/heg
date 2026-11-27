# Erratum & Follow-Up Remediation: Phase R2 and Residual Review Items (`REVIEW_FOLLOWUP_2026_11_27.md`)

**Date:** 2026-11-27 UTC  
**Scope:** Resolves every open item in `docs/reports/REVIEW_FOLLOWUP_2026_11_27.md` (commit `cda4904`) without rewriting historical reports.

---

## 1. Corrections to `M6_GOAL_PHASE_R2_EXACT_GADGETS_TC_OPTIMALITY_2026_11_27.md`

### 1.1 4-Port Hidden-`C8` Pruning Gap Fixed & Re-Verified (`exhaustive_gadget_enum_deep.cpp`)
- **Issue**: In commit `ebddd39`, `exhaustive_gadget_enum_deep.cpp` guarded `creates_c8` with `if (u >= np)` and omitted a leaf `C8` check. While harmless for 3 ports (6 port-incident edges cannot form a `C8`), 4 ports (8 port-incident edges) could close a port-only `C8` at `u = 3 < 4`.
- **Fix**: Removed the `u >= np` guard so `creates_c8` runs unconditionally on every edge insertion, and added an unconditional leaf check `all_cycle_lengths(n, st.rows)` rejecting any graph containing `C4`, `C8`, or `C16`.
- **Re-run results** (`4p n = 11..14`): Hidden port-only `C8` search branches were indeed pruned (`tasks`: `7709 -> 7589` at `n=11`, `5071 -> 5007` at `n=12`, `23497 -> 23217` at `n=13`, `18601 -> 18505` at `n=14`), and **all** previously reported valid leaf counts and distinct window types (`177/6`, `108/2`, `492/11`, `1208/13`) survived the full leaf `C4/C8/C16` check unchanged (zero false positives had entered the final table).

### 1.2 Odd-Parity Signature Removed & Missing `2×deg4` / `3×deg4` Signatures Exhaustively Enumerated
- **Issue**: Row `"3p n=14 2xdeg4 (2,2,2 + 9x3 + 4,4)"` had odd degree sum `6 + 27 + 8 = 41` and therefore proved nothing. Meanwhile `n=13 (2×deg4)` (sum 38) and `n=17 (2×deg4)` (sum 50) had not been run, making the statement *"among all cubic, 1×deg4, and 2×deg4 ... up to n = 17, only three orders exist"* too broad.
- **Fix**: Added an explicit even-degree-sum assertion to `exhaustive_gadget_enum_deep.cpp`, removed the impossible odd-sum signature, and exhaustively ran all missing even-sum signatures (noPE):

| Signature (3-port, noPE) | Degree Sum | `{C4,C8}`-free Leaves | Connected `{C4,C8,C16}`-free | Distinct Types | Time (16c) |
|---|---:|---:|---:|---:|---:|
| `3p n=13 2×deg4 (2,2,2 + 8×3 + 4,4)` | 38 | 0 | **0** | 0 | 68.8 ms |
| `3p n=14 3×deg4 (2,2,2 + 8×3 + 4,4,4)` | 42 | 0 | **0** | 0 | 2.54 s |
| `3p n=15 2×deg4 (2,2,2 + 10×3 + 4,4)` | 44 | 0 | **0** | 0 | 3.33 s |
| `3p n=17 2×deg4 (2,2,2 + 12×3 + 4,4)` | 50 | 960 | **0** (all hit `C16`/disc.) | 0 | 24.62 s |

- **Clarification of scope & leaf metric**:
  - The exhaustive non-existence theorem for `n <= 17` (noPE) now rigorously covers **all even-sum cubic, `1×deg4`, and `2×deg4` signatures** (plus `3×deg4` at `n = 8, 14` and `1×deg5` at `n = 7, 9`). Signatures with higher max degree (`>= 5` at `n >= 10`) or `>= 3` degree-4 vertices (other than `n = 8, 14`) were not enumerated.
  - Note on the "Leaves" column of Table 2.1 in Phase R2: rows `n <= 11` (from `exhaustive_gadget_enum.cpp`, which prunes `C4` incrementally and checks `C8` at the leaf) reported **`C4`-free leaves**, whereas rows `n >= 12` (from `exhaustive_gadget_enum_deep.cpp`, which prunes both `C4` and `C8` incrementally) reported **`{C4, C8}`-free leaves**.
- **Reproducible symmetry-breaking check**: Imported `tools/extremal/verify_symmetry_breaking.cpp`, reproducing `creates_c8` `0/5000` mismatches and `SB == NO_SB` identical window sets at `n = 7` cubic (`10` vs `96` valid, `2` types), `n = 8 1×deg4` (`9` vs `144` valid, `2` types), and `n = 9` cubic (`0` vs `0` valid across `18,360` `C4`-free leaves).

### 1.3 Independent SAT + Machine-Checked RUP/DRAT Certification of Tutte–Coxeter `UNSAT` (`n = 354` & `n = 338`)
- **Fixed latent fragility in `tc_exact_optimality.cpp`**: `assign_v` now updates every incident cycle in `inst.v2c[v]` unconditionally before returning `ok`, ensuring `unassign_to` is always an exact inverse even on early-failing branches.
- **Independent SAT + DRAT Verification**: Built three completely independent tools under `tools/extremal/`:
  - `tc_to_cnf.py`: independent Python DIMACS CNF encoder (verified SAT by our certified `n = 370` and `n = 345` solutions with `0` unsatisfied clauses; `n = 345` also solved from scratch by our CDCL solver in `13.18 s`). With `--add-slack-bound`, appends the exact 2-line double-counting consequence `AtMost({sum_C >= 10}, S)` where `S = 16 a_15 - (8 or 16)(30 - a_15) - 90` (holds for all `<= a_15` since replacing `H_15` by `H_8*`/`H_7` strictly decreases `sum_C`).
  - `mini_cdcl_drat.cpp`: self-contained C++17 CDCL SAT solver emitting standard DRAT proofs.
  - `check_drat.cpp` (and `check_drat.py`): independent RUP/DRAT proof checker verifying every single proof step and final empty clause `0`.

| Instance (within `TC + {H_15, H_8*, H_7}`) | CNF Vars / Clauses | CDCL Result & Time | Independent RUP/DRAT Verification (`check_drat.cpp`) | CNF SHA-256 |
|---|---:|---|---|---|
| `TC(<=18·H_15 + H_7)` (`n <= 354`, cubic) | `8,106 / 37,187` | `UNSATISFIABLE` (`24.39 s`, `179,809` conflicts) | **`VERIFIED UNSAT`**: `179,809` steps checked in `35.83 s` | `d42e49c4...45e44e` |
| `TC(<=14·H_15 + H_8*)` (`n <= 338`, $\delta \ge 3$) | `7,270 / 34,799` | `UNSATISFIABLE` (`43.67 s`, `232,503` conflicts) | **`VERIFIED UNSAT`**: `232,503` steps checked in `57.62 s` | `a966119e...bcccb64f` |

Exact commands reproducing those two CNFs (C8-only relaxation — omitting `--include-c10` is sound for `UNSAT` — plus `--add-slack-bound`):

```bash
python3 tools/extremal/tc_to_cnf.py --a15 18 --g2 H7  --add-slack-bound --out tc_n354_slack.cnf
python3 tools/extremal/tc_to_cnf.py --a15 14 --g2 H8s --add-slack-bound --out tc_n338_slack.cnf
g++ -O3 -std=c++17 tools/extremal/mini_cdcl_drat.cpp -o _build/mini-cdcl-drat
g++ -O3 -std=c++17 tools/extremal/check_drat.cpp     -o _build/check-drat
_build/mini-cdcl-drat tc_n354_slack.cnf tc_n354_slack.drat
_build/check-drat     tc_n354_slack.cnf tc_n354_slack.drat
_build/mini-cdcl-drat tc_n338_slack.cnf tc_n338_slack.drat
_build/check-drat     tc_n338_slack.cnf tc_n338_slack.drat
```

**Scope of the DRAT certificate**: DRAT certifies unsatisfiability of the generated CNF *including* the `--add-slack-bound` lemma `AtMost({sum_C >= 10}, S)`; it does not formally derive that counting lemma itself. The counting lemma (`sum_{C in C8} (sum_C - 9) <= 16 a_15 - (8 or 16)(30 - a_15) - 90` under `AtMost(#H_15 <= a_15)`) is verified directly by hand from the exact incidence count (every `(vertex, off-edge)` of Tutte–Coxeter lies on exactly `8` of its `90` `C8` cycles) and was independently confirmed by `REVIEW_FOLLOWUP2_2026_11_27.md` using a separate Levi-graph / PySAT / CaDiCaL 1.5.3 encoding.

- **Scope & wording precision**:
  - The bounds `[342, 345]` ($\delta \ge 3$) and `{362, 370}` (cubic) apply **strictly within the Tutte–Coxeter base + `{H_15, H_8*, H_7}` replacement family** (excluding unexpanded vertices, 4-port gadgets, or other base graphs).
  - For bipartite girth-8 bases `B_{34}..B_{48}` (§4 of R2), our solver is heuristic; the accurate statement is that **no** `n < 370` (cubic) or `n < 345` ($\delta \ge 3$) solution was found (not a proof of impossibility).

---

## 2. Residual Engineering, Reproducibility & Documentation Fixes

1. **Zero hardcoded `~/.gemini/.../scratch` paths in `tools/extremal/`**: Replaced hardcoded paths in `f5_h8star_solver.cpp`, `f5_girth8_bipartite_assault.cpp`, `test_h8star_petersen_f4.py`, and `track2_certify_all_f5.py` with CLI arguments / repo-relative paths (`grep -rn '\.gemini' tools/extremal/` returns empty).
2. **Raw campaign JSON data imported into repo**: Added compact JSON summaries for Wave D2, Wave E, 1h, 2h, Track 2, and Phase R3 under `docs/reports/data/` with `docs/reports/data/SHA256SUMS.txt`.
3. **Hardened `large_verify.rs` tests**: Corrected inaccurate comments (`C_300` with 2 planted chords; `C_512` with 1 planted chord touching bit 511) and added a dense `n = 370` `ABSENT` test directly loading `docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6` (`17/17` Rust release tests passing in `0.82 s`).
4. **Reference documentation & ADR**: Added `docs/reference/cli-rust-engine.md` (linked from `docs/reference/README.md`) documenting `verify-exact`, `verify-large`, `lns-polish`, `voltage-search`, `bjorklund-c32`, `search`, `score`, and `--serve`, and added `docs/adr/0019-large-order-exact-cycle-verification.md` (linked from `docs/adr/README.md`) formally separating M4 (`n <= 128`, ADR 0004) from the dual-verifier `128 < n <= 512` path.

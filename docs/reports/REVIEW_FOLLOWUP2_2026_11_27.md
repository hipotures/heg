# Follow-Up Review No. 2: Commit `e7acb38` (R2 Erratum, DRAT, Phase R3)

> Polish original: [`REVIEW_FOLLOWUP2_2026_11_27_pl.md`](REVIEW_FOLLOWUP2_2026_11_27_pl.md). This English version is a translation with identical content.

- **Concerns**: `REVIEW_FOLLOWUP_2026_11_27.md` → `e7acb38` (`ERRATUM_2026_11_27_PHASE_R2.md`, `M6_GOAL_PHASE_R3_F4_DELTA3_LT73_2026_11_27.md`).
- **Limitations**: the machine was busy. Neither `cargo test` nor the 16-thread gadget enumerator was run. The only heavier computation was single-threaded CaDiCaL at `nice 19`, about 8 CPU minutes in total.
- **New script**: `docs/reports/assets/review-2026-11-26/tc_indep_lemma.py`.

## 1. Status of the findings from `REVIEW_FOLLOWUP_2026_11_27.md`

| Finding | Status |
|---|---|
| No C8 test for port edges and at the leaf (4 ports) | ✅ Fixed in code. According to the erratum, the 4-port results did not change after the rerun. **I did not reproduce the rerun** (requires 16 cores) |
| Odd-sum signature, missing 2×deg4 for n=13/17 | ✅ Parity assertion. New signatures: n=13 and n=17 with 2×deg4, n=14 with 3×deg4 (noPE variants). Scope of the claim made precise in the erratum |
| Mixed "leaves" metric | ✅ Explained in the erratum |
| Missing `NO_SB` code | ✅ `verify_symmetry_breaking.cpp` added |
| `assign_v` fragility | ✅ Fixed |
| UNSAT from a single solver | ✅ SAT and DRAT with in-house tools, plus **my independent verification** (§2) |
| `~/.gemini` paths | ✅ Removed (`grep` returns nothing) |
| Raw JSON data | ✅ `docs/reports/data/` with `SHA256SUMS.txt` (sums match) |
| CLI documentation and ADR | ✅ `docs/reference/cli-rust-engine.md`, `docs/adr/0019-…` |
| `verify-large` test | ✅ Comments fixed, ABSENT test on `n=370` added (I did not run the test) |

## 2. Independent verification of UNSAT for the TC family

My encoding, `tc_indep_lemma.py`, is independent of `tc_to_cnf.py`, `mini_cdcl_drat.cpp` and `tc_exact_optimality.cpp`:
- TC built differently (Levi graph of GQ(2,2), not LCF);
- own enumeration of C8/C10 cycles;
- own PB→CNF encoding (monotone prefix-sum DP);
- cardinality constraints from PySAT, solved with the established **CaDiCaL 1.5.3** solver;
- every SAT model checked separately against all 162 cycles.

| Instance | Result | Time (nice 19) |
|---|---|---:|
| ≤18·H15 + H7 (cubic, `n ≤ 354`) | **UNSAT** ✅ | 305 s |
| ≤14·H15 + H8* (δ≥3, `n ≤ 338`) | **UNSAT** ✅ | 21 s |
| ≤20·H15 + H7 (control) | SAT, model checked, `n = 370` ✅ | 142 s |
| ≤15·H15 + H8* (control) | SAT, model checked, `n = 345` ✅ | 22 s |

Notes:
- Without the counting lemma, CaDiCaL did not decide `n ≤ 354` in ~16 CPU minutes, so that run was stopped. Both UNSAT results (the project's and mine) therefore depend on the lemma `Σ_{C8}(Σw_C − 9) = 16a − 8b − 16c − 90`. I checked the lemma by hand: every (vertex, edge pair) of TC lies on exactly 8 of the 90 eight-cycles. Under `AtMost(#H15 ≤ a)` the left-hand side is ≤ S(a). DRAT certifies only the CNF with the lemma added, not the lemma itself — this is worth stating in the erratum.
- The hash `d42e49c4…` in the erratum is reproduced by `tc_to_cnf.py --a15 18 --g2 H7 --add-slack-bound`. That instance covers only C8 (a relaxation, which is valid for UNSAT), but **the flags are not documented**.
- The conclusion "TC + {H15, H8*, H7}: δ≥3 minimum in [342, 345], cubic ∈ {362, 370}" is now independently confirmed. It still holds only within this family.

## 3. Phase R3 (`f_{δ≥3}(4) < 73`)

- The direction follows the recommendation: 0% of compute on cubic `n < 78`.
- I independently checked all 6 "best" graphs from `phase_r3_f4_delta3_lt73_results.json` (`cyc.c`): degrees, 2-connectivity, C4 = C8 = 0, C16 counts = 1, 2, 2, 10, 16, 12 — **consistent** with the report.
- The language still over-interprets heuristic results: "rock-solid C16 = 1 floor", "Sharp empirical transition at n = 73 vs n = 72". These are LNS results with no evidential value. It should say "no C16 = 0 found in N leaves".

## 4. Remaining minor items

1. Document the exact commands that generate the CNFs whose hashes are given (`--add-slack-bound`, without `--include-c10`), and state that DRAT does not cover the lemma.
2. Tone down the "floor/transition" wording in R3.

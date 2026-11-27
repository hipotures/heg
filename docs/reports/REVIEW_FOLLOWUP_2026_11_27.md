# Follow-Up Review: Verification of Post-Review Fixes and the Phase R2 Report (2026-11-27)

> Polish original: [`REVIEW_FOLLOWUP_2026_11_27_pl.md`](REVIEW_FOLLOWUP_2026_11_27_pl.md). This English version is a translation with identical content.

- **Concerns**: `REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md` → commits `6f67c6c` (remediation + erratum) and `ebddd39` (Phase R2).
- **Limitations**: the machine was still busy, so `cargo test`, `make test` and the 16-thread solvers in `tools/extremal/` were not run. Only light single-threaded checks were performed (`nice`).
- **New scripts**: `docs/reports/assets/review-2026-11-26/hc.c` (independent local gadget search) and `enum_n7_gadgets.py` (exhaustive n=7 enumeration).

## 1. Status of the review findings

| § | Finding | Status |
|---|---|---|
| 3.1 | Ripatti 2017: cubic `n < 78` | ✅ Fixed: `00_RESEARCH_STATUS.md` (such campaigns are now prohibited), erratum §2.1 |
| 3.2 | Tools outside the repo | 🟡 Partially. Sources are in `tools/extremal/`, the `n=77` certificate was added and independently confirmed (`cyc.c`: no C4/C8/C16). **However**: `f5_h8star_solver.cpp:366`, `f5_girth8_bipartite_assault.cpp:350`, `test_h8star_petersen_f4.py:22` and `track2_certify_all_f5.py:25` hardcode paths into `~/.gemini/.../scratch`. Raw JSON files of the 1h/2h/Wave E campaigns are still not in the repo. |
| 3.3 | "Unique/0 found" from sampling | ✅ Fixed in erratum §2.3. Phase R2 added exhaustive enumeration (remarks in §2) |
| 3.4 | Wrong pigeonhole in Wave E | ✅ Retracted in erratum §2.2 |
| 3.5 | `f(6)` attribution | ✅ Fixed in erratum §2.4 and in the status (32 640, arXiv:2511.07247 from Nov 2025, conditional bound) |
| 3.6 | Overstated wording, heuristics instead of an exact solver | ✅ Erratum §2.5. Phase R2 decides `n=338` and `n=354` with an exact solver |
| 3.7.1 | Dead BFS and misleading comment | ✅ Removed and fixed |
| 3.7.2 | Witness only in `debug_assert` | ✅ `verify_witness_runtime` also runs in release |
| 3.7.3 | `--lengths` and graph6 | ✅ Checked on the built binary: `--lengths 4,8,1x` gives an error message and exit 2. graph6 length is validated |
| 3.7.4 | Tests for `n > 64` | 🟡 Tests cover mask words 1–7 and bit 511. However, the test comments are inaccurate ("cubic graph", "chords every 10th vertex", "n = 100"): the graphs are the cycle `C_300`/`C_512` with 1–2 chords, and `n=100` is not tested. There is no ABSENT test on a dense graph with `n > 128` (e.g. on the `n=370` certificate itself) |
| 3.8 | D2 table, Monte Carlo sieve | ✅ Erratum §2.6 |
| 3.9 | Reference/architecture documentation, ADR | ❌ **Not done**: the new subcommands (`verify-large`, `lns-polish`, `voltage-search`, `bjorklund-c32`) are still described only in the ledger and reports |

## 2. Phase R2: what was confirmed and what raises doubts

### 2.1 Independently confirmed

- **Second `n=73` witness** (`Petersen_1U_9H8star`): `m=114`, `{3:64, 4:9}`, no articulation points, no C4/C8/C16 (`cyc.c`) ✅
- **n=7: exactly two window types** (my enumeration of all labeled graphs, `enum_n7_gadgets.py`): `(2,2,2)` and `(2,2,3)`. **All H7 windows are contiguous**: `[2..6], [2..6], [3..6]`. This matters for §2.3: for the `{H15, H8*, H7}` family the window-minimum model is an exact model, not merely a relaxation.
- **"0 {C4,C8}-free gadgets for n=11–14"**: independent local search (`hc.c`, 400 restarts × 4000 switches) found no gadget for `(2,2,2,3⁸)`, `(2,2,2,3⁸,4)`, `(2,2,2,3¹⁰)` or `(2,2,2,3¹⁰,4)` noPE. Positive control: the same program finds an `n=7` gadget and an `n=15` gadget of type H15 (windows 3/3/5) in a fraction of a second. The result agrees with R2, though it is only empirical evidence.
- **The analytic theorem** `8a₁₅ − 4b₈ − 8c₇ ≥ 45` and its consequences (`a ≥ 18` cubic, `a ≥ 14` for δ≥3, `c ≤ 3` at `a = 15`, giving `n ≥ 342`) were recomputed by hand. They are correct.

### 2.2 Remarks on `exhaustive_gadget_enum_deep.cpp` (the "100% exhaustive" classification)

1. **C8 pruning is disabled for edges added from ports** (`if (u >= np && creates_c8(...))`), and the leaf has **no final C8 test** (only C16 is tested, and only for `n ≥ 16`). For 3 ports this is harmless: 6 port edges cannot close a C8. **For 4 ports**, the cycle `p0–i–p1–j–p2–k–p3–l` consists solely of 8 port edges and is closed by an edge added at `u = 3 < np`, which nobody checks. The 4-port classification (`Q₁₁…Q₁₄`) may therefore contain false "{C4,C8}-free" gadgets. Adding `has_cycle_len(n, rows, 8)` at the leaf is enough.
2. **Vacuous signature**: `"3p n=14 2xdeg4 (2,2,2 + 9x3 + 4,4)"` has degree sum 6+27+8 = **41 (odd)**, so its "0" proves nothing.
3. **Missing signatures** relative to the claim "among all cubic, 1×deg4, and 2×deg4 … up to n = 17, ONLY THREE ORDERS EXIST": `n=13, 2×deg4` (`2,2,2,3⁸,4,4`, sum 38) and `n=17, 2×deg4` (`2,2,2,3¹²,4,4`, sum 50) were not run. Vertices of degree ≥ 5 appear only for `n ≤ 9`. The claim is too broad.
4. **The "{C4,C8}-free Leaves" column** in the R2 table mixes two metrics. For `n ≤ 11` (part A, `exhaustive_gadget_enum.cpp`) these are merely C4-free leaves (e.g. 1170 for `n=11`), while for `n ≥ 12` (deep) they are {C4,C8}-free leaves. Hence the apparent anomaly 1170 → 0 → 96.
5. **The "against brute-force NO_SB at n = 7, 8, 9" check** has no code in the repo, so it cannot be reproduced. My enumeration confirms only `n=7`. I consider the losslessness argument for the symmetry breaking (isolated vertices of the same class are interchangeable; a "prefix" is chosen) to be correct.

### 2.3 Remarks on `tc_exact_optimality.cpp` (`PROVEN_UNSAT` for `n=338` and `n=354`)

The logic is correct:
- slack bounding: the sum of independent lower bounds on non-negative terms of the identity `Σ_C(sum_C − 25) = 16a − 8b − 16c − 90`;
- `cycle_max_sum` as an upper bound;
- symmetry breaking (`v=0`, `p0=0`) is lossless because TC is 5-arc-transitive and the vertex stabilizer acts on the neighbors as S₃;
- all 162 cycles (lengths 8 and 10) are included, and for `L ≥ 12` the condition always holds.

Caveats:
1. **Latent fragility**: `assign_v` aborts the update halfway through the cycle list, while `unassign_to` reverts all cycles of the vertex. A failed assignment inside `dfs` would corrupt the state (possible false UNSAT). This path is not currently executed, because the domain is filtered by the same test and states are copied during task generation. It is still a trap for any modification. Either update all cycles before returning `false`, or record how many were updated.
2. **No independent confirmation**: UNSAT comes from a single in-house solver without a proof certificate. The "Complete & Independently Verified" status in the R2 header applies to the graph certificates, not to the UNSAT proofs. Recommendation: encode the instance as SAT/ILP and decide it independently (e.g. CaDiCaL with DRAT); the instance has 30 × 9 variables and 162 constraints.
3. **Scope**: "exact TC minimum [342, 345]" and "{362, 370}" hold only for the TC base and gadgets `{H15, H8*, H7}`. They do not cover unexpanded vertices (`U`, as in `Pet_1U`), 4-port gadgets or other bases. The report says so in one sentence, but the title ("Exact Optimality Theorems") is broader.

### 2.4 Other R2 wording

- §4 "larger bases cannot compensate" (bases B₃₄…B₄₈) rests on minimum violation counts from a heuristic solver, not on a proof. It should say "not found".
- The ledger (`IMPLEMENTATION_STATUS.md`, Track 2 entry) still says "unique … H8*". The erratum corrects this, and the ledger is chronological, so this is acceptable.

## 3. Recommendations (short)

1. Add a final C8 test at the leaf in `exhaustive_gadget_enum_deep.cpp`, rerun the 4-port part and the missing 3-port signatures (`n=13`/`n=17` with 2×deg4), and remove the vacuous `n=14 2×deg4` signature.
2. Replace the hardcoded `~/.gemini/...` paths with CLI arguments or repo-relative paths. Import the raw campaign JSON files or give their hashes and location.
3. Independently verify UNSAT for `n=338`/`n=354` (SAT + DRAT) and remove the `assign_v` fragility.
4. Add reference documentation for the new CLI subcommands. Consider an ADR for the `n ≤ 512` verification path.
5. Fix the comments in the `large_verify.rs` test and add an ABSENT test on the `n=370` certificate.

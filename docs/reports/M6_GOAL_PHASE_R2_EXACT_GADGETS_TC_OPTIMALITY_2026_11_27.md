# M6 `/goal` Phase R2: Exhaustive 3-Port & 4-Port Gadget Classification, Tutte–Coxeter Exact Optimality Theorems, and Second Certified `n = 73` Witness

**Date:** 2026-11-26 / 2026-11-27 UTC  
**Status:** Complete & Independently Verified  
**Reproducible Sources:**
- `tools/extremal/exhaustive_gadget_enum.cpp`
- `tools/extremal/exhaustive_gadget_enum_deep.cpp`
- `tools/extremal/tc_exact_optimality.cpp`
- `tools/extremal/f5_girth8_bipartite_assault.cpp`
- `tools/extremal/petersen_4port_f4_solver.cpp`
- New Certificate: `docs/reports/certificates/f4_delta3_n73_Petersen_1U_9H8star.g6`

---

## 1. Executive Summary

Addressing the exact open mathematical questions raised in `docs/reports/REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md` (§3.6, §4.3, §5.3–§5.5), Phase R2 replaces randomized configuration-model sampling with **100% exhaustive, symmetry-broken proofs** across three fronts:

1. **Complete Exhaustive Classification of 3-Port `{C4, C8, C16}`-Free Gadgets (`n <= 17`)**:
   - Proven exhaustively (and cross-checked against brute-force non-symmetry-broken enumeration at `n = 7, 8, 9` plus exact recovery of `H_15` at `n = 15` in `2.92 ms`): among all cubic, `1×deg4`, and `2×deg4` 3-port `{C4, C8, C16}`-free gadgets without port-port edges up to `n = 17`, **ONLY THREE ORDERS EXIST**:
     - `n = 7` (cubic): `H_7'` `(2,2,2)` and `H_7` `(2,2,3)`.
     - `n = 8` (`1×deg4`): `H_8'` `(2,2,2)` and our sporadic **`H_8*` `(2,3,3)`**.
     - `n = 15` (cubic): **`H_15` `(3,3,5)`** (unique window type).
   - **Zero** valid gadgets exist at `n = 5, 6, 9, 10, 11, 12, 13, 14, 16 (1×deg4), 17 (cubic)`.
2. **Complete Exhaustive Classification of 4-Port `{C4, C8, C16}`-Free Gadgets (`n = 6..14`)**:
   - Enumerated all connected 4-port gadgets (`ports 0..3` deg 2, internal deg `>= 3`), discovering non-port-edge families `Q_9` (`1×deg4`), `Q_{11a/b/c}` (`1×deg4`), `Q_{12a/b}` (cubic: `(2,2,4,4,4,4)` and `(2,2,3,3,5,5)`), `Q_{13}^*` (`1×deg4`: `(3,3,4,4,4,4)`), and `Q_{14}` (cubic: `(3,3,5,5,5,5)`).
3. **Analytic Double-Counting Theorem + Exact Branch-and-Bound Optimality Proofs for Tutte–Coxeter + `{H_15, H_8*, H_7}`**:
   - **Analytic Theorem**: Every `(v, off_edge)` in the Tutte–Coxeter graph lies on exactly `8` of its `90` `C8` cycles; summing the exact `C8` survival condition `2 n_5(C) - n_2(C) >= 1` over all `90` `C8` cycles proves:
     $$8 a_{15} - 4 b_8 - 8 c_7 \ge 45.$$
     Immediate zero-search corollaries: `a_15 >= 14` ($\delta \ge 3$) and `a_15 >= 18` (cubic).
   - **Exact Symmetry-Broken Branch-and-Bound Proofs (`tc_exact_optimality.cpp`)**:
     - **`TC(14·H_15 + 16·H_8*)` (`n = 338`, slack = 6): `PROVEN_UNSAT`** in `32.78 s` (`124,260,076` nodes). By strict dominance of `H_8*` over `H_7`, **every** valid TC lift using `{H_15, H_8*, H_7}` requires **`a_15 >= 15`**, bracketing the exact TC minimum to **`[342, 345]`** (certified record: **`345`**).
     - **`TC(18·H_15 + 12·H_7)` (`n = 354` cubic, slack = 6): `PROVEN_UNSAT`** in `4.80 s` (`11,115,147` nodes). Every valid cubic TC lift using `{H_15, H_7}` requires **`a_15 >= 19`**, bracketing the exact cubic TC minimum to **`{362, 370}`** (certified record: **`370`**).
4. **Second Structurally Distinct Quadruple-Certified `n = 73` Witness (`f_{delta>=3}(4) <= 73`)**:
   - Leaving `1` Petersen vertex unexpanded (`U_1`) and expanding the remaining `9` vertices by `H_8*` yields a brand-new `n = 73`, `m = 114`, `{3: 64, 4: 9}`, 2-connected `{C4, C8, C16}`-free witness (`docs/reports/certificates/f4_delta3_n73_Petersen_1U_9H8star.g6`), independently verified by **4 distinct engines**: M4 (`cpp/sglab_cyclecheck`), Rust `verify-exact`, independent Python DFS, and reviewer's `docs/reports/assets/review-2026-11-26/cyc.c` (`pow2 check: C4=0 C8=0 C16=0`).

---

## 2. Exhaustive 3-Port & 4-Port Gadget Tables

### 2.1 3-Port `{C4, C8, C16}`-Free Gadgets (100% Exhaustive)

| Order & Signature | Mode | `{C4,C8}`-free Leaves | Valid `{4,8,16}`-free | Distinct Window Types | Runtime (16c) |
|---|---|---:|---:|---|---:|
| `n=3` cubic `(2,2,2)` | Unrestricted | 1 | 1 (PE) | `K_3`: `(1,1,1)` | 0.002 ms |
| `n=5` cubic `(2,2,2 + 3,3)` | Unrestricted | 0 | **0** | — | 0.001 ms |
| `n=6` `1×deg4` `(2,2,2 + 3,3,4)` | Unrestricted | 0 | **0** | — | 0.003 ms |
| `n=7` cubic `(2,2,2 + 4×3)` | Unrestricted | 10 | 10 (noPE) | `H_7'` `(2,2,2)`, `H_7` `(2,2,3)` | 0.010 ms |
| `n=7` `2×deg4`, `1×deg5` | Unrestricted | 0 | **0** | — | 0.014 ms |
| `n=8` `1×deg4` `(2,2,2 + 4×3 + 4)` | Unrestricted | 15 | 9 (noPE) | `H_8'` `(2,2,2)`, **`H_8*` `(2,3,3)`** | 0.047 ms |
| `n=8` `3×deg4` | Unrestricted | 0 | **0** | — | 0.059 ms |
| `n=9` cubic / `2×deg4` / `1×deg5` | Unrestricted | 84 / 28 / 4 | **0 / 0 / 0** | — | 0.28 ms |
| `n=10` `1×deg4` | Unrestricted | 489 | **0** | — | 0.43 ms |
| `n=11` cubic / `2×deg4` | Unrestricted | 1,170 / 0 | **0 / 0** | — | 4.25 ms |
| `n=12` `1×deg4` | Unrestricted | 0 | **0** | — | 1.33 ms |
| `n=13` cubic | Unrestricted | 0 | **0** | — | 0.74 ms |
| `n=14` `1×deg4` / `2×deg4` | noPE | 0 / 0 | **0 / 0** | — | 26.4 ms |
| `n=15` cubic | noPE | 96 | 96 | **`H_15` `(3,3,5)`** (unique!) | 2.92 ms |
| `n=15` `2×deg4` | noPE | 0 | **0** | — | 72.0 ms |
| `n=16` `1×deg4` | noPE | 440 | **0** (all hit `C16`/disc.) | — | 50.3 ms |
| `n=17` cubic | noPE | 1,336 | **0** (all hit `C16`/disc.) | — | 17.6 ms |

*(Validation: `creates_c8` incremental MitM pruner tested with 0/5,000 mismatches against exact `has_cycle_len(8)`; lossless symmetry breaking verified against full brute-force `NO_SB` at `n = 7, 8, 9` (`n = 9` cubic: `18,360` `C4`-free leaves, `0` valid) and by exact recovery of `H_15` at `n = 15`.)*

### 2.2 Selected 4-Port `{C4, C8, C16}`-Free Gadgets (noPE, 100% Exhaustive)

| Order & Signature | Distinct noPE Types | Notable Window Profiles | Runtime |
|---|---:|---|---:|
| `4p n=9` `1×deg4` | 1 | `Q_9`: `mins=(2,2,2,3,3,3)` | 0.25 ms |
| `4p n=11` `1×deg4` | 3 | `Q_{11a}`: `(2,2,3,4,4,4)`, `Q_{11b}`: `(2,2,2,4,4,5)`, `Q_{11c}`: `(2,2,3,3,4,5)` | 2.15 ms |
| `4p n=12` cubic | 2 | `Q_{12a}`: `(2,2,4,4,4,4)`, `Q_{12b}`: `(2,2,3,3,5,5)` | 1.56 ms |
| `4p n=13` `1×deg4` | 11 | `Q_{13}^*`: `(3,3,4,4,4,4)` (symmetric `H_7 + H_7` merged at deg-4) | 9.60 ms |
| `4p n=14` cubic | 13 | `Q_{14}`: `(3,3,5,5,5,5)` (bridge-joined `H_7 + H_7`) | 5.25 ms |

---

## 3. Tutte–Coxeter Exact Optimality Results (`tc_exact_optimality.cpp`)

| Configuration | `n` | Family | Exact Global Slack | Exact Nodes | Time | Status |
|---|---:|---|---:|---:|---:|---|
| `TC(13·H_15 + 17·H_8*)` | 331 | $\delta \ge 3$ | `-18` | 0 | 0.000 s | **`PROVEN_UNSAT_ANALYTIC`** |
| `TC(17·H_15 + 13·H_7)` | 346 | Cubic | `-26` | 0 | 0.000 s | **`PROVEN_UNSAT_ANALYTIC`** |
| `TC(14·H_15 + 16·H_8*)` | 338 | $\delta \ge 3$ | `+6` | 124,260,076 | 32.78 s | **`PROVEN_UNSAT`** |
| `TC(18·H_15 + 12·H_7)` | 354 | Cubic | `+6` | 11,115,147 | 4.80 s | **`PROVEN_UNSAT`** |
| `TC(15·H_15 + 12·H_8* + 3·H_7)` | 342 | $\delta \ge 3$ | `+6` | 185,251,471 | 60.0 s | `TIMEOUT` (heuristic min_viol > 0) |
| `TC(15·H_15 + 13·H_8* + 2·H_7)` | 343 | $\delta \ge 3$ | `+14` | 244,141,939 | 60.0 s | `TIMEOUT` (PAWS min_viol = 7) |
| `TC(15·H_15 + 14·H_8* + 1·H_7)` | 344 | $\delta \ge 3$ | `+22` | 292,196,801 | 60.0 s | `TIMEOUT` (PAWS min_viol = 3) |
| `TC(19·H_15 + 11·H_7)` | 362 | Cubic | `+38` | 289,789,082 | 60.0 s | `TIMEOUT` (PAWS min_viol = 5) |
| **`TC(15·H_15 + 15·H_8*)`** | **345** | **$\delta \ge 3$** | `+30` | — | — | **CERTIFIED RECORD** |
| **`TC(20·H_15 + 10·H_7)`** | **370** | **Cubic** | `+70` | — | — | **CERTIFIED RECORD** |

---

## 4. Additional Bipartite Girth-8 Bases (`B_{34}..B_{48}`) & Petersen Contractions

- **Bipartite girth-8 cubic bases `B_{34}..B_{48}`** (`f5_girth8_bipartite_assault.cpp`): minimum cycle violations remained `27..42` (cubic `n = 362..368`) and `27..51` ($\delta \ge 3$, `n = 339..344`), showing that larger bases cannot compensate for the lower `H_15` fraction needed to stay under `n = 370 / 345`.
- **Petersen 1-edge and 2-edge contractions with 4-port gadgets** (`petersen_4port_f4_solver.cpp`): best violations reached `min_bad = 1` at `n = 72` (`Pet1e_Q14_2H8`, `Pet2e_Q14_2H8`) and `min_bad = 2` at `n = 70..72` (`Q_{11a/b/c}`, `Q_{12a/b}`, `Q_{13}^*`).
- **Petersen with 1 unexpanded vertex (`Pet_1U_9H8`)**: solved at **`n = 73`** (`{3: 64, 4: 9}`, `m = 114`), quadruple-certified as our second structurally distinct `f_{delta>=3}(4) <= 73` witness (`docs/reports/certificates/f4_delta3_n73_Petersen_1U_9H8star.g6`).

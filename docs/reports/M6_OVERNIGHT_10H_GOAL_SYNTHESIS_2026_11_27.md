# M6 Autonomous Overnight `/goal` Master Synthesis Report (2026-11-26 → 2026-11-27)

**Window:** `2026-11-26T21:04Z` → `2026-11-27T05:10Z` (~8.1 hours, with 3 peer-review integration cycles)  
**Hardware:** 16-core AMD Ryzen 9 7950X3D (`x86-64`, `PCLMULQDQ`, `AVX-512`)  
**Scope:** Extremal bounds for power-of-two-cycle-free graphs ($f(4), f(5), f(6)$), exhaustive 3-port/4-port gadget classification, Tutte–Coxeter exact optimality proofs (analytic + branch-and-bound + independent DRAT + independent CaDiCaL), general $\delta \ge 3$ $f(4) < 73$ assault, open bipartite cubic frontier ($n = 84..120$), and Ducoffe–Dumitru Conjecture 4.1 (`single_block_41`, $k = 23..37$).

---

## 1. Headline Certified Mathematical Results

All five explicit graph certificates under `docs/reports/certificates/` are simple, 2-connected, $\delta \ge 3$, and verified independently by multiple exact implementations (and cross-checked by the external peer reviews `REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md`, `REVIEW_FOLLOWUP_2026_11_27.md`, and `REVIEW_FOLLOWUP2_2026_11_27.md`):

| Result | Previous Benchmark | Construction | Order `n` / Size `m` / Degrees | Independent Verification | Certificate |
|---|---|---|---:|---|---|
| **$f_{\mathrm{cubic}}(5) \le 370$** | `450` (Exoo / García 2026, `-80`) | `Tutte–Coxeter(30) + 20·H_15 + 10·H_7` | `370 / 555 / 3-regular` | Rust `verify-large` (`9.12 ms`), C++17 `sglab-cyclecheck-large` (`33.79 ms`), reviewer `cyc.c` | [`f5_cubic_n370_TC_20H15_10H7.g6`](certificates/f5_cubic_n370_TC_20H15_10H7.g6) |
| **$f_{\delta \ge 3}(5) \le 345$** | `450` cubic (`-105`) | `Tutte–Coxeter(30) + 15·H_15 + 15·H_8*` | `345 / 525 / {3:330, 4:15}` | Rust `verify-large` (`17.11 ms`), C++17 `sglab-cyclecheck-large` (`38.68 ms`), reviewer `cyc.c` | [`f5_delta3_n345_TC_15H15_15H8star.g6`](certificates/f5_delta3_n345_TC_15H15_15H8star.g6) |
| **$f_{\delta \ge 3}(4) \le 73$** (Witness 1) | `78` cubic (Ripatti 2017, `-5`) | `Petersen(10) + 3·H_8* + 7·H_7` | `73 / 111 / {3:70, 4:3}` | **M4** (`sglab-cyclecheck` `9.30 ms`), Rust `verify-exact`, Python DFS, reviewer `cyc.c` | [`f4_delta3_n73_Petersen_3H8star_7H7.g6`](certificates/f4_delta3_n73_Petersen_3H8star_7H7.g6) |
| **$f_{\delta \ge 3}(4) \le 73$** (Witness 2) | `78` cubic (`-5`) | `Petersen(10) + 1·U_1 + 9·H_8*` | `73 / 114 / {3:64, 4:9}` | **M4** (`sglab-cyclecheck`), Rust `verify-exact`, Python DFS, reviewer `cyc.c` | [`f4_delta3_n73_Petersen_1U_9H8star.g6`](certificates/f4_delta3_n73_Petersen_1U_9H8star.g6) |
| **$f_{\delta \ge 3}(4) \le 77$** (Wave E) | `78` cubic (`-1`) | Exoo $G_{78}$ edge contraction | `77 / 116 / {3:76, 4:1}` | **M4** (`sglab-cyclecheck` `8.37 ms`), Rust `verify-exact`, Python DFS, reviewer `cyc.c` | [`f4_delta3_n77_G78_contract.g6`](certificates/f4_delta3_n77_G78_contract.g6) |

*(Verification authority boundary per [ADR 0004](../adr/0004-m4-certification-authority.md) and [ADR 0019](../adr/0019-large-order-exact-cycle-verification.md): all `n <= 128` certificates are certified by M4 `sglab-cyclecheck`; `n = 345, 370` (`128 < n <= 512`) are certified by dual independent exact verifiers `verify-large` + `sglab-cyclecheck-large` + reviewer `cyc.c`.)*

---

## 2. Proven Structural & Optimality Theorems

### 2.1 Sporadic 8-Vertex Gadget $H_8^*$ & Exhaustive 3-Port / 4-Port Classification (`n <= 17`)
- Discovered the sporadic 8-vertex `{C4, C8, C16}`-free 3-port gadget **$H_8^*$** (`ports 0,1,2` deg 2; `4×deg3 + 1×deg4`; windows `S(0,1)=[2..7]`, `S(0,2)=S(1,2)=[3..7]`), which strictly dominates $H_7$ (`(2,2,3)`) on two of three port pairs and drives both $f_{\delta \ge 3}(4) \le 73$ and $f_{\delta \ge 3}(5) \le 345$.
- **100% exhaustive symmetry-broken enumeration** (`tools/extremal/exhaustive_gadget_enum.cpp`, `exhaustive_gadget_enum_deep.cpp`, cross-checked against brute-force non-symmetry-broken enumeration at `n = 7, 8, 9` in `verify_symmetry_breaking.cpp` and unique recovery of `H_15` at `n = 15`):
  - Among **all even-sum cubic, `1×deg4`, and `2×deg4` 3-port `{C4, C8, C16}`-free gadgets without port-port edges up to `n = 17`** (plus `3×deg4` at `n = 8, 14` and `1×deg5` at `n = 7, 9`), **only three orders exist**: `n = 7` cubic (`H_7'`, `H_7`), `n = 8` `1×deg4` (`H_8'`, **`H_8*`**), and `n = 15` cubic (**`H_15`**).
  - Exhaustively classified 4-port `{C4, C8, C16}`-free gadgets `n = 6..14` with unconditional incremental `C8` pruning and full leaf `C4/C8/C16` checks (`Q_9`, `Q_{11a/b/c}`, `Q_{12a/b}`, `Q_{13}^*`, `Q_{14}`).

### 2.2 Tutte–Coxeter Exact Optimality (Within `TC + {H_15, H_8*, H_7}`)
- **Analytic Double-Counting Lemma** (manually verified independently by reviewer): every `(vertex, off-edge)` in Tutte–Coxeter lies on exactly `8` of its `90` `C8` cycles, proving:
  $$8 a_{15} - 4 b_8 - 8 c_7 \ge 45 \implies a_{15} \ge 14 \;(\delta \ge 3), \quad a_{15} \ge 18 \;(\text{cubic}), \quad c_7 \le 3 \text{ when } a_{15} = 15.$$
- **Triple-Independent Exact `UNSAT` Certification** (custom symmetry-broken branch-and-bound `tc_exact_optimality.cpp` + independent CNF/CDCL/RUP-DRAT `tc_to_cnf.py --add-slack-bound` + `mini_cdcl_drat.cpp` + `check_drat.cpp` + reviewer's independent Levi-graph/PySAT/CaDiCaL 1.5.3 encoding `tc_indep_lemma.py`):
  - **`TC(<=18·H_15 + H_7)` (`n <= 354`, cubic)**: `UNSAT` (`179,809` RUP/DRAT steps checked in `35.83 s`; CaDiCaL `305 s`). Exact cubic minimum within `TC + {H_15, H_7}` lies in **`{362, 370}`**.
  - **`TC(<=14·H_15 + H_8*)` (`n <= 338`, $\delta \ge 3$)**: `UNSAT` (`232,503` RUP/DRAT steps checked in `57.62 s`; CaDiCaL `21 s`). Exact $\delta \ge 3$ minimum within `TC + {H_15, H_8*, H_7}` lies in **`[342, 345]`**.
  - *(Precision note: the DRAT proofs certify unsatisfiability of the CNF with the hand-verified double-counting lemma `AtMost({sum_C >= 10}, S)` added; `TC(19·H_15 + 11·H_7)` at `n = 362` timed out at 120 s under `mini_cdcl_drat`.)*

### 2.3 Conditional Analytic Upper Bound for $f_{\mathrm{cubic}}(6)$
- Conditional on the 2,048-vertex girth-17 cubic graph reported by Exoo, Jajcay, Mačaj, and Širáň (`arXiv:2511.07247`), replacing any maximal 4-packing ($|P| \ge 45$) by $H_7$ and the rest by $H_{15}$ yields $f_{\mathrm{cubic}}(6) \le 30,360$ (`-360` vs uniform $H_{15}$ replacement `30,720`, `-2,280` vs `32,640`).

---

## 3. Large-Scale Exact LNS-RRT & Voltage-Lift Campaigns Executed Overnight

Across Phases R3, R4, and R5 (after halting all cubic `n < 78` hunts in accordance with Ripatti 2017), we evaluated **`61,779,576,335` (`61.78 BILLION`)** exact `C4 = C8 = 0` LNS-RRT repair leaves and **`1,813,576`** bipartite voltage lifts with zero crashes:

| Phase | Target Family | Compute / Leaves | Key Outcome (Strictly Heuristic for LNS) | Report & Data |
|---|---|---:|---|---|
| **Phase R3** | General $\delta \ge 3$ at `n = 72, 71, 70` (6 seeds) | `86.0 min` / `30.52B` `u128` leaves | Best `C16 = 1` at `n = 72` (`{3:70,4:2}`, `9.09B` leaves; `13.04B` cum.), `C16 = 2` at `n = 72` (`{3:68,4:4}`) & `n = 71` (`{3:70,4:1}`), `C16 = 12` at `n = 70`; **no `C16 = 0` graph found at `n < 73`** | [`M6_GOAL_PHASE_R3_F4_DELTA3_LT73_2026_11_27.md`](M6_GOAL_PHASE_R3_F4_DELTA3_LT73_2026_11_27.md), [`phase_r3_f4_delta3_lt73_results.json`](data/phase_r3_f4_delta3_lt73_results.json) |
| **Phase R4** | Bipartite cubic `n = 72..120` (`23` non-abelian non-nilpotent voltage families + `n = 84..120` bipartite LNS-RRT) | `104.2 min` / `1.81M` lifts + `3.30B` `u128` leaves | **16 additional exhaustive voltage families ruled out** (`0` `C16=0`, incl. simple `theta2 × A_5` at `n = 120` & `theta4 × SL(2,3)` at `n = 96`; `30` exhaustive families total with Wave D2); bipartite LNS-RRT reduced `C16` by `43%–65%` (`Ljubljana-112: 3948 -> 1378`, `n = 120: 3300 -> 1218`), all `M4(4,8)=ABSENT` & `PCLMULQDQ` Björklund `C32 = True` (present); **no `C16 = 0` found** | [`M6_GOAL_PHASE_R4_BIPARTITE_FRONTIER_2026_11_27.md`](M6_GOAL_PHASE_R4_BIPARTITE_FRONTIER_2026_11_27.md), [`track3_bipartite_results.json`](data/track3_bipartite_results.json) |
| **Phase R5** | Ducoffe–Dumitru Conjecture 4.1 (`single_block_41`, `k = 23..37`, glued odd `n = 45..73`) | `110.1 min` / `27.96B` `u64` leaves | Inside Theorem 4.2 auto-`C32=C64=0` window (`k = 23..31`, `17.43B` leaves), no block dropped below `C16 = 111..138`; above `k = 31`, `k = 33` dropped `142 -> 122` and `k = 37` reached **`C16 = 97`**; **0 counterexamples found** | [`M6_GOAL_PHASE_R5_CONJECTURE_41_LNS_RRT_2026_11_27.md`](M6_GOAL_PHASE_R5_CONJECTURE_41_LNS_RRT_2026_11_27.md), [`track4_conj41_n64_results.json`](data/track4_conj41_n64_results.json) |

---

## 4. Engineering, Reproducibility, Documentation & Verification Gates

- **Peer-Review Remediation Complete**: All items from `REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md`, `REVIEW_FOLLOWUP_2026_11_27.md`, and `REVIEW_FOLLOWUP2_2026_11_27.md` addressed and documented in [`ERRATUM_2026_11_26_WAVES_D_F_TRACK2.md`](ERRATUM_2026_11_26_WAVES_D_F_TRACK2.md) and [`ERRATUM_2026_11_27_PHASE_R2.md`](ERRATUM_2026_11_27_PHASE_R2.md).
- **New Reference Documentation & ADR**: [`docs/reference/cli-rust-engine.md`](../reference/cli-rust-engine.md) and [`docs/adr/0019-large-order-exact-cycle-verification.md`](../adr/0019-large-order-exact-cycle-verification.md).
- **Reproducible Tools & Data**: Zero hardcoded external scratch paths in `tools/extremal/`; 12 raw campaign JSONs archived in `docs/reports/data/` with verified `SHA256SUMS.txt`.
- **Final Verification Gate Status (`2026-11-27T05:06Z`)**:
  - `make rust-engine` + `cargo test --release`: **17/17 passed** (`0.81 s`, `0` warnings, incl. dense `n = 370` `ABSENT` test).
  - `tests/test_rust_engine.py`: **7/7 passed** (`3.04 s`).
  - `make doctor`: **PASS** (`cyclecheck`, `score_worker`, `rust_engine` available).
  - `make check`: **PASS** (`compileall` clean).
  - `make benchmark-smoke`: **PASS**.
  - `make dashboard-smoke`: **PASS** (`dashboard smoke: ok`).
  - `docs/reports/data/SHA256SUMS.txt`: **12/12 `OK`**.
  - Live re-verification of all 5 `.g6` certificates (`verify-large`, `sglab-cyclecheck-large`, M4 `sglab-cyclecheck`): **5/5 `ABSENT`**.
  - `make test` (full 401-test Python suite): `391 passed, 8 failed, 1 error, 1 skipped` — all failures are pre-existing Director protocol/context tests (`test_director_context.py`, `test_research_artifacts.py`, `test_research_protocol.py`); `git diff --stat c23522a~1..HEAD -- src/ tests/` confirms **0 files touched in `src/` or `tests/`**.
  - Zero orphan background processes; worktree clean and pushed to `origin/main`.

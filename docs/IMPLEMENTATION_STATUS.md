# Implementation Status

Last implementation audit: **2026-11-27**.

## Stage 2C: Certified 80-Vertex Lower Bound for Cubic Bipartite Counterexamples ($n \le 78$)

- **Complete Two-Branch Zero-Oracle Certified Proof (`docs/reports/M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md`, `docs/reports/data/stage2c_cubic_bipartite_n78_summary.json`)**: Proved that **every finite simple cubic bipartite graph on $n \le 78$ vertices contains a simple cycle of length $4$, $8$, or $16$**, advancing the cubic bipartite lower bound to **$n \ge 80$** (`+10` vertices over Zhuge `zenodo.21981786`, `+20` over Tranquilli `arXiv:2608.02675`) and establishing the strict three-way separation $f_{\delta \ge 3}(4) \le 73 < 78 = f_{\mathrm{cubic}}(4) < 80 \le f_{\mathrm{cubic,bip}}(4)$:
  - **$C_6$ branch (`SIDE = 35..39`, `tools/extremal/cubic_bipartite_cert_gen.cpp`, `cubic_bipartite_cert_verify.cpp`)**: Byte-identical reproduction of immutable upstream Tranquilli commit `67adc92d` at `SIDE = 29, 34` and exact new runs through `SIDE = 39` ($n \le 78$: `6,292,996` states, `1,213,994,934` proposals, `completions = 0`), with 64-bit-safe zero-oracle static certificates verified `VERIFIED_OK` (`8.28 s` Orbit 1 + `43.18 s` Orbit 2).
  - **Girth-$\ge 10$ branch (`V = 35..40`, `tools/extremal/cubic_bipartite_girth10_cert_gen.cpp`, `cubic_bipartite_girth10_cert_verify.cpp`, `cubic_bipartite_girth10_search.cpp`)**: Lossless 15-block / 31-point Moore-tree normalization (positive cage discovery verified at `V = 35` and exact embedding verified for all 3 $(3,10)$-cages) with zero-oracle static certificates `G10_VERIFIED_OK` through `V = 40` ($n \le 80$; `V = 39`: `83,749` states, `16,916,906` proposals, `0.464 s` verify).

## Stage 1 Certified Censuses, Unconditional $f_{\mathrm{cubic}}(6) \le 10{,}498$, and Exact Tutte–Coxeter DRAT Closure

- **Batch Census Scanner (`rust/sglab-engine/src/batch_scan.rs`, `scan-batch` CLI) & Independent Python Witness Verifier (`tools/extremal/verify_witness_stream.py`)**: Zero-dependency Rust parallel scanner supporting `graph6`, `sparse6`, `psv-tsv` (quoted `|` CSV), and `conder-edges` up to `n <= 16,384` in `general` and `vertex-transitive` modes with mandatory release-mode cycle witness verification (`21/21` Rust release tests passing in `0.82 s`).
- **Track 1A — Cubic Girth $\ge 9$ ($n = 58..64$, House of Graphs)**: All **`1,436,474 / 1,436,474`** graphs (`18 + 474 + 27,169 + 1,408,813`) scanned in `6.81 s` (`210.8k g/s`) and 100% independently verified by Python: `0` $C_4$, `0` $C_8$, **`100.000%` contain a certified simple $C_{16}$**.
- **Track 1B — PSV Cubic VT ($n \le 1280$) & Conder Cubic Symmetric ($n \le 2048$ and FULL $n \le 10\,000$)**: All **`111,705 / 111,705`** PSV rows (`111,391` with $n \le 1280$ + `314` Conder $n \le 2048$) and all **`3,815 / 3,815`** Conder symmetric cubic graphs ($n \le 10\,000$; `796` with $n \le 2048$) scanned (`6.75 s` PSV, `4.11 s` Conder) and 100% verified by Python: **every single graph contains a certified simple cycle of length $\in \{4, 8, 16, 32\}$** (`0` exceptions; smallest VT avoiding $\{C_4, C_8, C_{16}\}$ is `psv:2027` at `n = 180`, independently confirmed in general mode via `verify-large`; smallest symmetric is `C1050.1` at `n = 1050`).
- **Track 1C — Three $(3,10)$-Cages ($n = 70$) & Zhuge Calibration**: All 3 $(3,10)$-cages (`docs/reports/data/cagesk3g10.g6`) certified as containing $C_{16}$ by M4 (`sglab-cyclecheck`), Rust `verify-exact`, and Python DFS; Zhuge/Tranquilli scaling measured (`SIDE=33: 5.73 s` on 1 core, `~1.85×` per `+2` vertices).
- **Track 1D — K. Henry (`zenodo.23886386`) Audit & Unconditional $f_{\mathrm{cubic}}(6) \le 10{,}498$**: Verified Henry's `graph370.g6` directly for `C4..C32 = ABSENT` (`9.97 ms` Rust, `26.84 ms` C++) and credited Henry (`2026-11-03`) for priority on `f_cubic(5) <= 370`. Retrieved and verified House of Graphs `k3_g17_n2048.g6` (exact girth `17`, greedy 4-packing `|P| = 124` $\implies$ **unconditional $f_{\mathrm{cubic}}(6) \le 29{,}728$**) and `k3_g16_n702.g6` (exact girth `16`, BFS source 8-packing `|S_8| = 4` $\implies$ **unconditional $f_{\mathrm{cubic}}(6) \le 10{,}498$**, beating Henry's conditional `10,522`).
- **Track 1E — Complete `drat-trim` Closure of Tutte–Coxeter Exact Optimality (`tools/extremal/build_solvers.sh`, `tc_to_cnf.py --mode mixed3`, `tc_n362_cube_prove.py`)**: Closed **both** gaps in `TC + {H_15, H_8*, H_7}` to exact equality using CaDiCaL 2.1.3 + official `drat-trim`: exact **$\delta \ge 3$ minimum `= 345`** (`n = 342, 343, 344` all `s VERIFIED`, `190.06M` resolution steps) and exact **cubic minimum `= 370`** (`n = 362` all **`56 / 56`** exhaustive disjoint leaves `s VERIFIED`). Report: `docs/reports/M6_STAGE1_CERTIFIED_CENSUSES_AND_TC_CLOSURE_2026_11_27.md`.

## Pure Lean 4 Kernel-Checked Formalization (`lean/Sglab/`)

- **Zero-dependency Lean 4 (`v4.36.0`) formalization (`lean/README.md`, `lean/Sglab/`)**: Built cleanly via `lake build` (`14/14` jobs, `0` errors, `0` warnings, `0` `sorry`, `0` custom axioms, `0` `native_decide`; only standard Lean foundational axioms `propext`, `Classical.choice`, `Quot.sound` verified by `#print axioms` across all 25 headline theorems):
  - `lean/Sglab/Graph.lean`: Finite simple graphs (`FinGraph n`), `SimplePath`, `SimpleCycle`, BFS distance potential lower bound (`dist_lower_of_potential`), provably sound canonical bitmask cycle DFS (`not_hasCycle_of_dfs`), and provably sound weighted short-cycle DFS (`weighted_cycle_lower_of_check`).
  - `lean/Sglab/GadgetLift.lean`: General 3-port vertex-replacement lift (`liftGraph`), degree preservation (`liftGraph_minDeg3`, `liftGraph_isCubic`), and the Master 3-Port Cycle Projection & Length Lower Bound Theorem (`liftGraph_cycle_dichotomy`, `liftGraph_no_cycle`).
  - `lean/Sglab/Gadgets.lean`: Kernel-verified gadgets `H7` (`n=7`, cubic-internal, `(2,2,3)`), `H8star` (`n=8`, `δ≥3`, `(3,3,2)`), and `H15` (`n=15`, cubic-internal, `(3,3,5)`), with `{C4, C8}`-freeness and explicit BFS distance potentials checked inside the kernel.
  - `lean/Sglab/Records.lean`: Kernel-checked proofs of `f_delta3_4_le_73` (`3·H_8* + 7·H_7`), `f_delta3_4_le_73_alt` (`1·U_1 + 9·H_8*`), `f_cubic_5_le_370` (`20·H_15 + 10·H_7`), `f_delta3_5_le_345` (`15·H_15 + 15·H_8*`), and the general 4-packing theorem `f_cubic_6_4packing` / `f_cubic_6_4packing_N2048` (`≤ 30,360` on any `N=2048` cubic girth-`≥ 17` base).
  - `lean/Sglab/TutteCoxeterLowerBound.lean`: Kernel-checked verification of all 90 Tutte–Coxeter 8-cycles and exact 8-fold incidence of every `(v, off_port)` (`tc_incidence_eq_8`), exact double-counting identity (`tc_double_counting_eq`), `8 a_15 - 4 b_8 - 8 c_7 ≥ 45` (`tc_double_counting_bound`, `tc_cubic_a15_ge_18`, `tc_delta3_a15_ge_14`, `tc_delta3_a15_15_c7_le_3`), and formal soundness of the SAT/DRAT `--add-slack-bound` cardinality constraint (`tc_slack_card_sound`, `tc_slack_card_n354_cubic`, `tc_slack_card_n338_delta3`).

## Overnight `/goal` Master Synthesis & Final Verification Gates

- **Master Synthesis (`docs/reports/M6_OVERNIGHT_10H_GOAL_SYNTHESIS_2026_11_27.md`)**: Consolidates all certified upper bounds ($f_{\mathrm{cubic}}(5) \le 370$, $f_{\delta \ge 3}(5) \le 345$, $f_{\delta \ge 3}(4) \le 73$ via two distinct witnesses, $f_{\delta \ge 3}(4) \le 77$), exhaustive 3-port/4-port gadget classifications (`n <= 17` / `n <= 14`), Tutte–Coxeter exact optimality proofs (analytic + branch-and-bound + independent RUP/DRAT + reviewer CaDiCaL 1.5.3), `61.78B` exact LNS-RRT leaves across Phases R3–R5, and all three peer-review remediation cycles (including exact CNF reproduction commands and DRAT lemma-scope disclosure in `ERRATUM_2026_11_27_PHASE_R2.md`).
- **Final Gates (`2026-11-27T05:06Z`)**: `cargo test --release` `17/17` (`0.81 s`), `test_rust_engine.py` `7/7` (`3.04 s`), `make doctor`, `make check`, `make benchmark-smoke`, `make dashboard-smoke`, `SHA256SUMS.txt` `12/12`, and live verification of all 5 certificates (`verify-large` + `sglab-cyclecheck-large` + M4 `sglab-cyclecheck`) all green; `0` files modified in `src/` or `tests/`.

## Overnight `/goal` Phase R5: Ducoffe–Dumitru Conjecture 4.1 (`single_block_41`, `27.96B` Exact `u64` LNS-RRT Leaves)

- **110.1-minute 16-core `u64` LNS-RRT Campaign (`docs/reports/M6_GOAL_PHASE_R5_CONJECTURE_41_LNS_RRT_2026_11_27.md`, raw data `docs/reports/data/track4_conj41_n64_results.json`)**: Evaluated **`27,958,747,565`** (`27.96B`) exact `C4 = C8 = 0` LNS-RRT leaves across `k = 23..37` (glued odd orders `n = 45..73`). Inside the automatic-`C32=C64=0` Theorem 4.2 window (`k = 23..31`, `17.43B` leaves), blocks held a rigid `C16 = 111..138` floor; above `k = 31`, `k = 33` improved `142 -> 122` and `k = 37` reached **`C16 = 97`** (first sub-100 `single_block_41` block). Zero counterexamples found.

## Overnight `/goal` Phase R4: Bipartite Cubic `n = 78..126` Frontier (`23` Voltage Families + `3.30B` Bipartite `u128` LNS-RRT Leaves)

- **Expanded Voltage-Lift Scan (`docs/reports/M6_GOAL_PHASE_R4_BIPARTITE_FRONTIER_2026_11_27.md`, raw data `docs/reports/data/track3_bipartite_results.json`)**: Scanned `1,813,576` lifts (`1,661,449` valid cubic bipartite graphs, `100,055` `C4 = C8 = 0` hits, `0.35 s`) across `23` non-abelian, non-nilpotent families (`16` exhaustive, including simple non-solvable `theta2 × A_5` at `n = 120` and `theta4 × SL(2,3)` at `n = 96`), finding `0` `{C4, C8, C16}`-free lifts.
- **Bipartite-Preserving `u128` LNS-RRT (`--bipartite --rrt-slack`, `104.2` min, `3,299,149,485` exact leaves)**: Slashed `C16` by `43%–65%` across `n = 84, 96, 108, 112 (Ljubljana), 120` (`Ljubljana-112`: `3,948 -> 1,378`; `n = 120`: `3,300 -> 1,218`), all strictly bipartite with `M4(4, 8) = ABSENT (True)` and `PCLMULQDQ` Björklund `C32 = True` (zero-FP witness present), exposing a massive `C16 >= 1,218` bipartite wall compared to non-bipartite `H_7`-based constructions.

## Follow-Up Review Remediation (`REVIEW_FOLLOWUP_2026_11_27.md`) & Overnight `/goal` Phase R3 (`f_{\delta \ge 3}(4) < 73`)

- **Complete Follow-Up Remediation (`docs/reports/ERRATUM_2026_11_27_PHASE_R2.md`)**:
  - **Independent SAT + DRAT `UNSAT` Certification (`tools/extremal/tc_to_cnf.py`, `mini_cdcl_drat.cpp`, `check_drat.cpp`, `check_drat.py`)**: Independently verified `TC(<=18·H_15 + H_7)` (`n = 354`, cubic) as `UNSAT` (`24.39 s`, `179,809` RUP/DRAT proof steps checked in `35.83 s`) and `TC(<=14·H_15 + H_8*)` (`n = 338`, $\delta \ge 3$) as `UNSAT` (`43.67 s`, `232,503` RUP/DRAT proof steps checked in `57.62 s`). Also fixed the latent early-return fragility in `tc_exact_optimality.cpp::assign_v`.
  - **Fixed 4-Port `C8` Pruning & Completed Missing `2×deg4` / `3×deg4` Enumerations (`tools/extremal/exhaustive_gadget_enum_deep.cpp`, `verify_symmetry_breaking.cpp`)**: Enabled unconditional `creates_c8` + full leaf `C4/C8/C16` checking (confirming `0` false positives in `Q_{11}..Q_{14}`), removed the odd-sum `n = 14 2×deg4` row with a parity assertion, and exhaustively proved `0` valid noPE gadgets for `n = 13 (2×deg4)`, `n = 14 (3×deg4)`, `n = 15 (2×deg4)`, and `n = 17 (2×deg4)`.
  - **Reproducibility, Tests & Documentation**: Removed all hardcoded `~/.gemini/.../scratch` paths from `tools/extremal/`, imported compact campaign JSONs + `SHA256SUMS.txt` into `docs/reports/data/`, fixed `large_verify.rs` test comments and added a dense `n = 370` `ABSENT` certificate test (`17/17` Rust release tests passing in `0.82 s`), added `docs/reference/cli-rust-engine.md`, and added `docs/adr/0019-large-order-exact-cycle-verification.md`.
- **Phase R3 (`docs/reports/M6_GOAL_PHASE_R3_F4_DELTA3_LT73_2026_11_27.md`)**: Evaluated **`30,521,679,285`** (`30.52B`) exact `u128` LNS-RRT leaves (`86.0` min, 16 cores, `unrestricted_min_degree_3`) across 6 general $\delta \ge 3$ seeds at `n = 72, 71, 70`: held rock-solid `C16 = 1` at `n = 72` (`{3:70, 4:2}`, `9.09B` leaves, `13.04B` cumulative), drove contracted `n = 72` (`{3:68, 4:4}`) from `6 -> 2`, held `C16 = 2` at `n = 71` (`{3:70, 4:1}`, `8.04B` leaves), and drove `n = 70` from `31 -> 12`. Zero witnesses `< 73` found; certified $f_{\delta \ge 3}(4) \le 73$ stands.

## Overnight `/goal` Phase R2: Exhaustive 3-Port/4-Port Gadget Classification, Tutte–Coxeter Exact Optimality Proofs & Second `n = 73` Witness

- **100% Exhaustive Gadget Classification (`tools/extremal/exhaustive_gadget_enum.cpp`, `exhaustive_gadget_enum_deep.cpp`)**: Proved exhaustively (verified against brute-force non-symmetry-broken search at `n = 7, 8, 9` and exact unique recovery of `H_15` at `n = 15` in `2.92 ms`) that among all cubic, `1×deg4`, and `2×deg4` 3-port `{C4, C8, C16}`-free gadgets without port-port edges up to `n = 17`, **only three orders exist**: `n = 7` cubic (`H_7'`, `H_7`), `n = 8` `1×deg4` (`H_8'`, **`H_8*`**), and `n = 15` cubic (**`H_15`**); zero exist at `n = 5, 6, 9, 10, 11, 12, 13, 14, 16 (1×deg4), 17 (cubic)`. Also exhaustively classified 4-port `{C4, C8, C16}`-free gadgets `n = 6..14` (`Q_9`, `Q_{11a/b/c}`, `Q_{12a/b}`, `Q_{13}^*`, `Q_{14}`).
- **Tutte–Coxeter Analytic Double-Counting + Exact Branch-and-Bound Optimality (`tools/extremal/tc_exact_optimality.cpp`)**: Proved analytically that $8 a_{15} - 4 b_8 - 8 c_7 \ge 45$ over TC's 90 `C8` cycles (`a_15 >= 14` general, `a_15 >= 18` cubic), and proved via exact symmetry-broken branch-and-bound with global slack pruning that **`TC(14·H_15 + 16·H_8*)` (`n = 338`) is `PROVEN_UNSAT`** (`32.78 s`, `124.26M` nodes — forcing `a_15 >= 15` and bracketing the exact TC minimum to `[342, 345]`) and **`TC(18·H_15 + 12·H_7)` (`n = 354` cubic) is `PROVEN_UNSAT`** (`4.80 s`, `11.12M` nodes — bracketing cubic TC to `{362, 370}`).
- **Second Quadruple-Certified `n = 73` Witness (`docs/reports/certificates/f4_delta3_n73_Petersen_1U_9H8star.g6`)**: `Petersen + 1 unexpanded vertex + 9·H_8*` (`m = 114`, `{3: 64, 4: 9}`, 2-connected), independently verified by M4 (`cpp/sglab_cyclecheck`), Rust `verify-exact`, Python DFS, and reviewer's `cyc.c` (`pow2 check: C4=0 C8=0 C16=0`). Report: `docs/reports/M6_GOAL_PHASE_R2_EXACT_GADGETS_TC_OPTIMALITY_2026_11_27.md`.

## Peer-Review Remediation (`REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md` & Erratum)

- **Hardened `verify-large` (`rust/sglab-engine/src/large_verify.rs`, `main.rs`)**: Removed dead BFS `dist`/`queue` code and updated comments accurately, added release-mode runtime witness verification (`verify_witness_runtime`), enforced strict CLI validation on `--lengths` (rejecting malformed/odd tokens with exit code 2) and strict `graph6` byte-length validation, and expanded unit tests to cover multi-word `[u64; 8]` graphs (`n = 24, 300, 512`, touching bit 511) cross-checked against an independent canonical DFS.
- **Reproducibility & Research Status (`tools/extremal/`, `docs/00_RESEARCH_STATUS.md`, `docs/reports/ERRATUM_2026_11_26_WAVES_D_F_TRACK2.md`)**: Imported Track 2 C++17/Python tools (`sglab_cyclecheck_large.cpp`, `f5_gadget_hunter.cpp`, `f5_multideg4_gadgets.cpp`, `f5_h8star_solver.cpp`, `test_h8star_petersen_f4.py`, `track2_certify_all_f5.py`) and missing `docs/reports/certificates/f4_delta3_n77_G78_contract.g6` into the repo; updated `docs/00_RESEARCH_STATUS.md` with Ripatti (2017, BAIKAL: computational `f_cubic(4) = 78`), García (`arXiv:2609.04686`), and Exoo et al. (`arXiv:2511.07247`); published a formal Erratum correcting Wave E's pigeonhole proof, gadget sampling vs. exhaustiveness wording, `30,720`/`30,360` attribution, and Wave D2 table wording. Terminated cubic `n < 78` LNS hunts.

## Overnight `/goal` Track 2 & Wave F: Triple-Certified $f_{\mathrm{cubic}}(5) \le 370$, $f_{\delta \ge 3}(5) \le 345$, $f_{\delta \ge 3}(4) \le 73$, and Sporadic Gadget $H_8^*$

- **Wave F Engine Upgrades (`cc568bd`, `lns.rs`, `large_verify.rs`, `voltage_bipartite.rs`, `main.rs`)**: Added Record-to-Record Travel (`--rrt-slack <u32>`) and bipartition-preserving matching pruning (`--bipartite`) to `lns-polish` (`u64` + `u128`), added general-order (`n <= 512`) 16-core exact canonical MitM verifier (`verify-large`), and expanded `voltage-search` with `theta2`/`mobius10` bases and 12 additional non-abelian non-nilpotent groups ($A_5, SL(2,3), F_{42}, A_4 \times C_2, S_3 \times C_4, S_3 \times C_6, D_{12}, D_{18}, D_{20}, D_{21}, D_{24}, D_{30}$). `17/17` Rust release tests (`0` warnings) + `11/11` Python parity tests green.
- **Track 2 World-Record Upper Bounds (`docs/reports/M6_GOAL_TRACK2_F5_H8STAR_WORLD_RECORDS_2026_11_27.md`, certificates under `docs/reports/certificates/`)**:
  - **Sporadic 8-vertex gadget $H_8^*$ (`mins = (2, 3, 3)`)**: Discovered across `180.7M` C++17 gadget trials (`n = 6..15`): unique `{C4, C8, C16}`-free 8-vertex 3-port gadget (1 internal deg-4) achieving distance $\ge 3$ on 2 of 3 port pairs.
  - **$f_{\mathrm{cubic}}(5) \le 370$ (`-80` vertices vs Exoo/García 2026 `450`)**: Strictly 3-regular, simple, 2-connected `Tutte–Coxeter(30) + 20·H_15 + 10·H_7` (`m = 555`), triple-certified (`Rust verify-large 9.5 ms`, independent C++17 exact DFS `35.8 ms`, exact window calculus `L <= 10`).
  - **$f_{\delta \ge 3}(5) \le 345$ (`-105` vertices vs `450`)**: Simple, 2-connected `Tutte–Coxeter(30) + 15·H_15 + 15·H_8*` (`m = 525`, `{3: 330, 4: 15}`), triple-certified (`Rust verify-large 14.6 ms`, C++17 exact DFS `39.0 ms`).
  - **$f_{\delta \ge 3}(4) \le 73$ (`-5` vs `78`, `-4` vs Wave E `77`)**: Simple, 2-connected `Petersen(10) + 3·H_8* + 7·H_7` (`m = 111`, `{3: 70, 4: 3}`), triple-certified (`M4 C++17 9.30 ms`, Rust `verify-exact 2.26 ms`, Pure Python exact DFS `None`).
  - **Analytic bound $f_{\mathrm{cubic}}(6) \le 30,360$ (`-360` vs `30,720`)**: Replacing any maximal 4-packing ($|P| \ge \lceil 2048/46 \rceil = 45$) of the 2048-vertex girth-17 cubic graph by $H_7$ and the rest by $H_{15}$ guarantees $\min \text{len} \ge 4L - \lfloor L/5 \rfloor \ge 65 > 64$ unconditionally.

## 2-Hour Multi-Basin Elite-Archive ILS-LNS Campaign (`n = 76, 74, 70`, `42.63B` Exact `u128` LNS Leaves)

- **119.84-minute 16-core `u128` ILS-LNS campaign (`docs/reports/M6_CAMPAIGN_2H_ILS_LNS_CUBIC_F4_2026_11_26.md`)**: Evaluated **`42,627,141,833`** exact `C4 = C8 = 0` `u128` LNS leaves (`5.93M` leaves/s across `308` rounds, `0` errors) using 3-regime `C4 = C8 = 0` perturbations (`defect_ball`, `medium_hop`, `deep_ruin`) and automatic 45s `k = 5..8` deep polish:
  - **New strictly cubic record at `n = 74`**: cut exact `C16` in half from `6` down to **`3`** (`m = 111`, 3-regular, strictly 2-connected, `bridges = 0`, `M4(4,8) = ABSENT`, Rust `verify-exact = 0.89 ms`, Python exact `C16 = 3`; `15` distinct `C16 = 3` basins across `8.44B` leaves).
  - **Deep floor confirmation**: `n = 76` cubic (`30.77B` leaves, `43` distinct `C16 = 3` basins), `n = 70` cubic (`2.17B` leaves, `6` distinct `C16 = 4, C64 = 0` basins), and `n = 76` mixed `{3:74, 4:2}` (`1.24B` leaves, `4` distinct `C16 = 4` basins). No strictly cubic `f_cubic(4) < 78` witness was found; cumulative exact LNS evaluations across Wave D1/E + 1h + 2h campaigns now reach `83.26B` leaves.

## Wave E: `u128` Exact-Matching Micro-LNS (`n <= 128`) & `f(4) < 78` Hunt (`f_{\delta \ge 3}(4) \le 77` Certified)

- **`u128` Exact Bitset MitM `C16` & `u128` Exact-Matching Micro-LNS (`rust/sglab-engine/src/cycles.rs`, `lns.rs`, `main.rs`)**: Added `count_c16_mitm_u128` (wired into `count_cycles_fast_u128`, `verify-exact`, and `lns-polish` for `64 < n <= 128`) and full `u128` Exact-Matching Micro-LNS (`lns_destroy_and_repair_u128`, `run_parallel_lns_polish_u128` with instant `AtomicBool` stop on `best_c16 == 0`). Verified with `16/16` Rust release tests (`0` warnings, including `u128` MitM parity vs exact DFS on `n = 70` and `u128` LNS on `n = 70`) and `11/11` Python parity/resource tests (`--serve` v2 intact).
- **4-Stage `f(4) < 78` Campaign (`docs/reports/M6_WAVE_E_U128_LNS_F4_HUNT_2026_11_26.md`, `5,852,915,825` exact `u128` LNS leaves)**:
  - **Triple-certified explicit upper bound $f_{\delta \ge 3}(4) \le 77$**: Contracting an edge incident to the unexpanded $K_3$ vertex in Exoo $G_{78}$ yields strictly 2-connected (`bridges = 0`), simple 77-vertex graphs (`m = 116`, `76 × deg-3 + 1 × deg-4`, $\delta(G) = 3$) avoiding $\{C_4, C_8, C_{16}\}$ — independently certified by **M4 C++17 (`_build/sglab-cyclecheck`: `ABSENT, complete=true` on `[4, 8, 16]` in `8.37 ms`)**, **Rust `verify-exact` (`0.89 ms`)**, and **pure Python exact DFS** (`24` distinct witnesses generated on the `C4 = C8 = C16 = 0` manifold).
  - **Strictly cubic `n = 66..76` frontier (`C4 = C8 = 0`, `bridges = 0`)**: Drove strictly 3-regular **`n = 76` down to `C16 = 3`** via double-contraction cubicization + ILS-LNS (`435 -> 3` in 15s), alongside `n = 74 -> C16 = 6`, `n = 72 -> C16 = 9`, `n = 70 -> C16 = 4` (`C64 = 0`, matching exact Petersen+$10\cdot H_7$ pigeonhole bound $40/12 > 3$), `n = 68 -> C16 = 9`, `n = 66 -> C16 = 12`, and exhaustive proof that no 9-vertex `{C4, C8}`-free 3-port gadget has all pairwise port distances $\ge 3$.

## 1-Hour Multi-Basin LNS Campaign (`n = 60, 62, 64`, 34.78B exact leaves)

- **60.69-minute 16-core campaign (`docs/reports/M6_CAMPAIGN_1H_LNS_F4_60_62_64_2026_11_26.md`)**: Evaluated **`34,775,945,720`** exact `C4 = C8 = 0` LNS repair leaves (`+ 54.06M` SA evals) across 4 independent basins per order, establishing new strictly 2-connected (`bridges = 0`, `C4 = C8 = 0`) cubic records: **`n = 62 -> C16 = 12`** (`108×` below random), **`n = 64 -> C16 = 18`** (`78×` below random), and a 4-basin floor **`n = 60 -> C16 = 23`**, all certified by M4 + `verify-exact` (`0.5–0.9 ms`). No counterexample or `f(4) <= 64` witness was found.

## Wave D2: Bipartite `n ∈ [70, 128]` Voltage-Lift Search & x86-64 `PCLMULQDQ` Björklund $\mathrm{GF}(2^{16})$ Narrow Sieve

- **Hardware `PCLMULQDQ` Bipartite Björklund Narrow Sieve (`rust/sglab-engine/src/voltage_bipartite.rs`, `main.rs`)**: Implemented `_mm_clmulepi64_si128`-accelerated $\mathrm{GF}(2^{16})$ arithmetic, Gray-code Ryser inclusion-exclusion over $2^{h-1}$ subsets on the smaller bipartition with exact characteristic-2 non-backtracking 2-step transitions (`C32` detection in `32.3–57.1 ms` on 16 cores at $n = 72..120$, zero false positives, 2-round error $< 5.2 \times 10^{-7}$), exposed via `sglab-rust-engine bjorklund-c32`.
- **Bipartite Cubic Voltage-Lift Search (`voltage-search`)**: Supports 9 non-abelian, non-nilpotent even-order finite groups ($D_6, A_4, D_7, D_9, D_{10}, F_{20}, S_4, D_{14}, D_{15}$) over 4 bipartite cubic bases (`theta4`, `k33`, `theta6`, `cube8`) with orbit-reduced exact `C4`/`C8`/`C16` MitM + Björklund `C32` verification.
- **Verification & Experiment 10 (`docs/reports/M6_WAVE_D2_VOLTAGE_BJORKLUND_2026_11_26.md`)**: `16/16` Rust release tests (`0` warnings, `0.37 s`), `7/7` Python parity tests; scanned `746,472` lifts (`671,660` valid cubic bipartite graphs, `14` exhaustive families across $n = 72..120$) in `0.11 s`, ruling out `{C4, C8, C16}`-free lifts in all 14 exhaustive families.

## Wave D1: Native Rust Exact-Matching Micro-LNS Destroy-and-Repair (`C4 = C8 = 0`)

- **Exact-Matching Micro-LNS (`rust/sglab-engine/src/lns.rs`, `search.rs`, `main.rs`)**: Computes exact `C16` edge-participation heat `w_16(e)` via Bitset MitM, destroys `k in [4, 8]` pairwise-disjoint hot/cluster edges (`2k <= 16` ports), precomputes external path-length bitmasks `L_ext(p, q) <= 7` in frozen `G_rest`, and exhaustively solves legal `C4 = C8 = 0` strictly 2-connected perfect matchings via MRV branch-and-bound with incremental `C4`/`C8` pruning and exact early-aborting MitM `C16`. Exposed via `sglab-rust-engine lns-polish` (16-core shared-champion parallel polish) and opt-in `search --lns-interval`.
- **Verification & Experiment 9 (`docs/reports/M6_WAVE_D1_EXACT_LNS_2026_11_26.md`)**: `14/14` Rust release tests (`0` warnings), `7/7` Python parity tests; evaluated `689M` exact `C4 = C8 = 0` repair leaves across 16 cores in ~100 s, smashing strictly 2-connected cubic `C16` records down to **`17`** (`n = 62`, `-61.4%`), **`23`** (`n = 60`, `-64.6%`), **`24`** (`n = 64`, `-25.0%`), **`44`** (`n = 58`, `-52.7%`), and **`77`** (`n = 50`, `-43.4%`).

## Deep `/goal` Research Campaign (Wave A + B + C + `LexCutoff`, 1.97B evaluations)

- **Exact `LexCutoff` & ILS return-to-best (`rust/sglab-engine/src/cycles.rs`, `search.rs`, commit `2436da2`)**: Added exact ascending-length short-cycle early pruning under `--objective lex_short` (aborting in ~10–60 ns when `C4 > 0` or `C8 > 0`, yielding `11×` speedup on `n = 64` and `16.68M ev/s` peak on `single_block_41`) plus classic ILS return-to-best intensification after `10 × perturbation_interval` stagnant steps.
- **1.97-billion-evaluation 4-phase campaign (`docs/reports/M6_DEEP_CAMPAIGN_WAVE_ABC_2026_11_26.md`)**: Executed `1,965,629,664` evaluations in `579.5 s` across 16 cores with full dual M4 + `verify-exact` certification and 2-connectivity structural audit:
  - Strictly 2-connected cubic (`bridges = 0`, `C4 = C8 = 0`): drove exact `C16` down to **`71`** (`n=54`), **`65`** (`n=60`), **`44`** (`n=62`), **`32`** (`n=64`, `43.8×` below random), **`4` with `C64 = 0`** (`n=70`), and **`0`** (`n=78`, autonomous Exoo $G_{78}$), each verified in `0.4–0.8 ms`.
  - Strictly legal `single_block_41` (`k = 21..37`, odd `n = 41..73`, `biconn = True, bridges = 0`): M4-certified **`C8 = C16 = C32 = C64 = 0`** (`total = 3` per block) at `n = 65` and `n = 69`, and down to `C16 = 111..126` inside `C4 = C8 = 0`. No counterexample was found.

## Wave C: Exact Bitset MitM `C16`, Forced-Edge Branch-and-Reduce `C_n`, and Single-Pass Frontier DP

- **Exact Bitset Meet-in-the-Middle for `C16` (`rust/sglab-engine/src/cycles.rs`)**: Added `count_c16_mitm_u64` (canonical min-vertex 8-edge half-paths, `<= 384`/vertex in cubic graphs, disjoint bitmask pairing `(m1 & m2) == 0`) wired into `count_cycles_fast_u64`, eliminating `node_budget` exhaustion on `C16` while keeping `--serve` protocol v2 untouched and bit-for-bit parity-tested.
- **Deterministic Forced-Edge Branch-and-Reduce & Frontier DP (`rust/sglab-engine/src/exact_verify.rs`, `main.rs`)**: Added Eppstein/Xiao–Nagamochi `exact_cubic_hamiltonian_bnr_u64` (wired as 2nd line after Pósa+Thomason in `count_hamiltonian_u64` for `n >= 32` cubic graphs) and single-pass Simpath mate-array `exact_spectrum_frontier_dp` (`u128` cycle-length spectrum) plus CLI `sglab-rust-engine verify-exact --graph6 <g6>`.
- **Verification & Experiment 8 (`docs/reports/M6_WAVE_C_MITM16_BNR_FRONTIER_DP_2026_11_26.md`)**: `13/13` Rust release tests (`0` warnings, `0.13s`), `11/11` Python parity/resource tests; resolved all four Experiment 7 `n = 64` M4 10-second `C64` timeouts in `0.50–39.60 ms` (`0.72 ms` for `H7` `n = 64`), and cut true `C16` inside `C4 = C8 = 0` on 1-block cubic `n = 52..62` by `65%–91%` (down to `C16 = 93` at `n = 54, 62` and `C16 = 54, C64 = 0` at `n = 64`).

## Wave B: H7 gadget expansions, 3-edge switches, hot-edge heat, multi-objective & Hashimoto macro-gradient

- **Hashimoto non-backtracking trace $\operatorname{Tr}(B^k)$ via Ihara–Bass (`rust/sglab-engine/src/spectral.rs`)**: Implemented pure-Rust cyclic-Jacobi eigensolver, exact cubic Ihara–Bass trace formula + algebraic connectivity $\lambda_2(L)$, and exact general-degree directed-edge walk-power trace (verified against McGee cage reference integers $\operatorname{Tr}(B^{16}) = 66\,336$ and $\operatorname{Tr}(B^{32}) = 4\,296\,496\,672$), wired as opt-in `--hashimoto-guide` plateau tie-breaker.
- **$H_7$ gadget expansion seeds, 3-edge switches, hot-edge heat & objectives (`bank.rs`, `cycles.rs`, `mutation.rs`, `search.rs`, `main.rs`)**: Added `--seed-style h7_expansion` (Petersen / Petersen+$K_3$ / Heawood / Heawood+$K_3$ + $r\cdot H_7$ with port-orientation coordinate descent), `CycleBank64::edge_heat` (`O(1)` POPCNT), cyclic 3-edge switch (`--three-edge-prob`), and `--objective {total,weighted,lex_short}`.
- **Verification & M4-certified Experiment 7 (`docs/reports/M6_WAVE_B_H7_HASHIMOTO_3EDGE_2026_11_26.md`)**: `10/10` Rust release tests (0 warnings), `7/7` Python parity tests; broke 1-block cubic `n = 64` inside `C4 = C8 = 0` down to `C16 = 54` (`C16 = 2` under `total`), and drove Markström-25 (`k = 25`, `n = 49`) from `C16 = 187` to `C16 = 126` strictly inside `C4 = C8 = 0` (`1.33M ev/s`).

## Wave A: Closed Ducoffe–Dumitru filter, Conjecture 4.1 single-block mode, and Markström-24 seeding

- **Closed Ducoffe–Dumitru structural filter (`rust/sglab-engine/src/graph.rs`)**: Implemented full arXiv:2609.28594 constraints on both `BitGraph64` and `BitGraph`: strict 2-connectivity (`is_biconnected()`) for even orders (Theorem 2.3 / Corollary 2.4), zero bridges (Corollary 2.2), symmetric equal-order equal-edge 2-degenerate 1-clique-sums with cut-vertex degree `4` for odd orders, doubling-reduction auxiliary graph `M` check (`auxiliary_m_valid()`, Lemma 3.5: simple, `|L_2| <= max(0, 2h - 3)`, 2-degenerate), and Theorem 3.7 global bounds (`h <= floor(n/3) - 1`, `m <= 2n - 2` for `n >= 13`).
- **Conjecture 4.1 / Theorem 4.2 single-block search mode (`--mode single_block_41`, `mutation.rs`, `search.rs`, `main.rs`)**: Searches a single 2-connected, 2-degenerate block `B` of order `k` (vertex `0` of degree `2` with degree-3 neighbors; all other vertices `>= 3`), where `B +_0 B` is a legal odd candidate of order `n = 2k - 1` with automatic `C32 = C64 = 0` for `k in [21, 31]`. Added exact Markström-24 (`K4 -> K3 + 3·H7`, `C4 = C8 = 0, C16 = 228`) and optimal 1-edge subdivision seed (`--seed-style markstrom`, `k = 25`, `C4 = C8 = 0, C16 = 187`).
- **Verification & M4-certified Experiment 6 (`docs/reports/M6_WAVE_A_DUCOFFE_SINGLE_BLOCK_2026_11_26.md`)**: `8/8` Rust release tests, `11/11` Python parity/resource tests (`--serve` v2 parity intact), and 16-core M4-certified scan across `k = 21..31` (`n = 41..61`) sustaining `2.95–4.85M ev/s`, driving `C16 = C32 = 0` on every odd order `41..61` (`total = 2` at `n = 41`, `total = 3` at `n = 43..61`; M4 refuted all 13 glued candidates).

## Rust 2-block Ducoffe–Dumitru seeding, exact Tarjan block scoring, adaptive cap, and `/proc` RSS fix

- **Fixed `/proc` RSS race condition (`src/sglab/resources.py`, `tests/test_resources.py`)**: `current_rss_bytes()` and `process_tree_rss_bytes()` now handle `ProcessLookupError` when short-lived worker subprocesses exit mid-read. Verified with unit tests (`4/4`) and a 20-second 16-lane Rust `sglab research-campaign` (11.73M evaluations, clean `paused_by_operator`, `last_error: null`, zero orphan processes).
- **Exact Tarjan biconnected-block cycle scoring (`rust/sglab-engine/src/graph.rs`, `cycles.rs`)**: `count_cycles_fast_u64` now decomposes `length >= 16` queries by biconnected blocks (`BitGraph64::biconnected_blocks`), returning exact `count = 0, complete = true` in ~100 ns whenever `max_block_size < length` (eliminating false `node_budget` exhaustion penalties on 2-block graphs) and restricting multi-block DFS to individual blocks of size `>= length`. `--serve` protocol v2 parity remains untouched and 100% tested.
- **2-block Ducoffe–Dumitru seeding & adaptive cap (`mutation.rs`, `search.rs`, `main.rs`)**: Added opt-in `--seed-style {random,two_block,mixed}` (default `random`) with `O(1)` within-block 2-edge switch preservation and `--adaptive-cap-max <u32>` (default `0`, disabled). Verified across 7/7 Rust release tests, 11/11 Python tests, and M4-certified Experiment 5 (`docs/reports/M6_RUST_TWOBLOCK_AND_RESOURCE_FIX_2026_11_26.md`), breaking the `n = 38..60` `total = 128` plateau down to `total = 4..12` inside the legal Ducoffe–Dumitru class.

## Rust engine optimization waves 1–13 (L1 `BitGraph64`, delta `C4`/`C8`/`C16`, `CycleBank64`, Pósa+Thomason)

Completed 13 verified optimization waves inside `rust/sglab-engine/` without modifying the legacy Python or C++ stack or relaxing exactness/soundness invariants (`--serve` protocol v2 remains bit-for-bit parity-tested against `sglab-score-worker` in `tests/test_rust_engine.py`, M4 remains the sole counterexample certification authority, and all 5 Rust release unit tests prove exactness/soundness of every accelerated path):

- **Compact representation & zero-allocation hot loop**: 512-byte L1-resident `BitGraph64` (`[u64; 64]`), `Copy` `ScoreResult` with per-length `complete_mask`, stack-only `StackWitnesses`, `O(1)` edge-index patching (`removed_idx`), bidirectional `are_connected`, and 64-bit backward-shift `TabuRing64`.
- **Exact analytic, MitM, and incremental delta counters**: bitwise analytic `C4` (~0.15 µs) + exact `O(1)` delta `C4` (~10 ns) and exact delta `C8` (~50 ns) on 2-edge switches, zero-minus exact delta `C16` for `n <= 40`, register-resident recursive `count_cycles_pruned_u64` with `closing_set`-seeded `dist_mask`, `adj_to_closing`, and 3-level `rem == 3` leaf collapse, and `[C4, C8, C16, C32]` evaluation order when delta `C4`/`C8` are exact.
- **Hamiltonian acceleration (`n=32`, `n=64`)**: 2-bit register-only `(hi, lo)` cubic Hamiltonian DFS (`count_hamiltonian_cubic_u64`) plus sound Pósa extension + cubic branchless Thomason lollipop harvester with zero-copy reverse reopen, 4-seed Phase-1 skip, fused swap+`pos_of` updates, `edge_mix64`, and open-addressed dedup (`n=64` direct scorer `p50=56.3 µs`, `p95=69.0 µs`).
- **Orientation-aware transposed bitset `CycleBank64` (`rust/sglab-engine/src/bank.rs`)**: proves surviving and orientation-matched reconnected cycles across 2-edge switches in ~10 ns using interleaved `edge_bits`, `u8` 4 KB `edge_id`, branchless zero-division `insert_cycle`, 4-root MitM `C16` bank harvesting (~15 µs), 2-closing-vertex full-graph `C32` harvesting with lazy leaf hashing, 384-slot `C64` bank with `dir_valid` incremental retention, and zero-count-skip `WitnessCache` with `O(m)` bank witness extraction.
- **Verified 16-core throughput (`Ryzen 9 7950X3D`, `cubic_first` ILS-tabu, 2 s runs)**: `n=32`: **3.50M ev/s** (`138.5×` 1-core vs legacy Py+C++), `n=50`: **3.28M ev/s** (`58×`), `n=60`: **3.96M ev/s** (`81.5×`), `n=64`: **668k ev/s** (`35.9×`); `minimal_structure_mixed_degree` 16-core ILS-tabu: `n=50` **3.11M**, `n=60` **3.64M**, `n=64` **645k ev/s**; 16-core SA (`cubic_first`): `n=50` **2.79M**, `n=60` **3.08M**, `n=64` **417k ev/s**.

## Native Rust search engine, campaign wiring, and Ducoffe–Dumitru filter

Added an optional zero-dependency Rust crate (`rust/sglab-engine/`, built via
`make rust-engine` into `_build/sglab-rust-engine`) while preserving the entire
legacy Python + C++ stack (`src/sglab/`, `cpp/sglab_score_worker.cpp`,
`cpp/sglab_cyclecheck.cpp`) intact for direct comparison and parity checks.
The Rust binary implements both the exact binary protocol v2 `--serve` scorer
(bit-for-bit parity-tested against `sglab-score-worker` across orders 4..128,
including budget-exhaustion cutoffs) and a native multi-threaded inner search
loop (`simulated_annealing`, `iterated_local_search_tabu`, `random_restart`)
with stack-allocated `[u128; 128]` graphs, native witness caching, checkpoint
continuation (`--initial-graph6`), and `graph6` export compatible with M4
verification.

Campaigns and lanes can now opt into the Rust backend via
`--engine-backend rust|rust_scorer` on `research-campaign prepare`,
`[search].engine_backend = "rust"` in `experiment.toml`, or
`SGLAB_ENGINE_BACKEND=rust`, while keeping `cpp` as the unchanged default.
Missing binaries or unknown backends fail closed. `sglab doctor` reports
`rust_engine` availability alongside `cyclecheck` and `score_worker`.

The `minimal_structure_mixed_degree` (`predominantly_cubic`) structural prior
in both Python and Rust now enforces the sharpened Ducoffe–Dumitru
(`arXiv:2609.28594`) necessary conditions for minimal counterexamples: strictly
more than `2n/3` vertices of degree 3 (`3 * degree_three > 2 * n`), independent
high-degree vertices, every vertex adjacent to a degree-3 vertex, and at most
two biconnected blocks (biconnected or a 1-clique-sum of two biconnected graphs).

## Conservative budget-exhaustion scoring and 16-core concurrency

Bounded C++ cycle-count evaluations that exhaust `node_budget` without
completing (`complete=false`) now charge the conservative cap penalty
(`witness_cap`) in both `sglab-score-worker` cutoff accounting and
`ErdosGyarfasPlugin.score_from_cycle_counts`, rather than scoring truncated
traversals as false zeros. Raw C++ `(length, count, complete)` responses remain
exact and parity-checked against `find_cycles_of_length_bounded`, and M4 remains
the sole certification authority.

Production lane concurrency (`PRODUCTION_MAX_ACTIVE_LANES`) and default
`LaneManager`/`DecisionContext`/fallback limits are raised from 8 to 16, and
`recommended_workers()` defaults to all available logical CPUs (`reserve_threads=0`
by default, while still honoring an explicit `reserve_threads` argument). On
16-core hosts, prepared campaigns and multi-worker search runs now utilize up to
16 concurrent lanes/workers.

## Mandatory C++ scorer contract re-audit

Production scoring paths in campaign lanes and the legacy runner use only the
persistent C++ worker. A bounded failure permits one restart; a repeated
failure raises `ScoreWorkerError` and terminates the lane. The repository has
no Python heuristic-scoring fallback. Python cycle enumeration remains
independent M4 verification and diagnostic code, never a production scoring
substitute.

## Issue #21 — bounded Director prompts and source-first retention

Director prompt construction now separates the complete host-side continuity
and validation registries from a deterministic, section-bounded model
projection.  Target aliases remain exact and host-resolved; the model receives
only current target/budget, active-lane telemetry, relevant candidate and
checkpoint summaries, verifier counts, hypotheses, and recent interventions,
with omitted-count and section-byte reports.  Legacy histories are copied and
compacted without passing through the 256 KiB prompt serializer, so expected
candidate/checkpoint/turn growth cannot cause a terminal JSON-size error.

Director request, response, and wire payloads use a content-addressed raw
object with compatibility hard-links.  Failed, invalid, repair, interrupted,
and timed-out diagnostics are protected from rolling retention; only
successful transport aliases are eligible for a bounded window.  Candidate
and source artifacts remain append-only.  Capsules reference one raw object
instead of copying the same payload twice, and each workspace migration emits
the non-destructive `artifacts/workspace-artifact-manifest.json` with paths,
sizes, allocation, hashes, and artifact classes.  Credential homes and active
SQLite/WAL files are excluded from that public inventory.  Existing
`heg-ranked-001` files and scientific records are preserved in place.
`artifacts/source-index.json` gives direct program/source-ID to source-path
and SHA-256 mappings for generated Python candidates discovered in a
workspace.

The operator shortcut now handles a repaired `paused_fault` safely: it passes
an explicit recovery acknowledgement only when the repository commit differs
from the failed attempt and refuses repeated blind retries under unchanged
code. Director ranking guidance also states that `random_restart` must omit
`proposal_ranking` entirely, while validation remains fail-closed.

Long-running ranked lanes now renew a healthy isolated policy worker between
proposal batches before its bounded per-process wall lifetime expires. The
renewal repeats the frozen identity handshake and never falls back to an
unranked or in-process policy; protocol, timeout, crash, or renewal failures
remain fail-closed.

The model-facing Director schema now discriminates `start_lane` parameters by
algorithm. Ranked mutation branches require the reviewed catalog ID only when
the immutable plan enables it, and `random_restart` has no ranking field or
unrelated nullable parameters. Semantic validation remains authoritative and
still rejects any malformed response without dispatching work.

## Issue #19 — zero-lane Director bootstrap

Fresh ranked snapshots now recompute a constructive action space before every
Director request. With capacity and no active lanes, `start_lane` is explicit;
candidate-dependent and lane-targeting actions remain absent. The prompt,
algorithm-discriminated strict Structured Outputs schema, transport-null
normalization, and semantic validator share that projection, including the
exact reviewed ranking ID for mutation starts and the unranked random-restart
rule. Invalid initial and repair turns persist bounded validation paths and
messages in schema v19 and expose them through status. A deterministic
provider regression starts a ranked lane and records positive evaluations
without a paid model turn. The existing experiment identity and workspace
remain unchanged; no scoring, verifier authority, or ranking policy bytes were
changed.

The model-facing projection assigns deterministic per-turn `S1`, `L1`, `C1`,
`K1`, `H1`, and `E1` aliases. A bounded private alias registry is persisted
with each Director request; the host resolves aliases before durable
validation, while unknown, stale, and role-mismatched aliases fail closed.
Current snapshot continuity overrides stale scientific-memory target lists, and
the model receives only bounded candidate/checkpoint subsets with omitted-count
summaries and verifier status counts. Durable IDs remain in SQLite and private
artifacts, never in the model prompt.

## Issue #20 — AI candidate archive and Director turn capsules

The exact Mutation Forge Stage 4R recovery archive is now imported under
`artifacts/proposal-ranking/mutation_forge_stage4r_v1/`. Its 288 original
files (10,574,800 bytes), including valid, invalid, repaired, and failed
slots, raw protocol records, readable requests/responses, recovery lineage,
and selection reports, are byte-preserved and listed in
`import-manifest.json`. The manifest verifier detects missing, changed,
duplicate, or extra paths; the champion proof records the exact
source/AST/behavior identities and byte identity with HEG's frozen policy
source. The import was scanned for credential payloads without altering the
read-only Mutation Forge repository.

Every retained HEG App Server turn is projected into an idempotent bounded
capsule under `workspace/<experiment-id>/artifacts/director-turns/`, with
readable request/response views, exact validation issues, usage, provenance,
events, and raw references. `artifacts/README.md` indexes the imported
archive and turn capsules, including the latest turn. `sglab experiment run`
and experiment-aware status migrate the existing `heg-ranked-001` workspace
without model calls; projection failures cannot change SQLite or turn
dispatch. The ranking policy remains opt-in/default-disabled and no graph,
scorer, verifier, or experiment-identity semantics changed.

## Issue #17 — operator activation path

The integrated ranker now has an explicit operator boundary. `research-campaign
prepare` accepts only `--proposal-ranking mutation_forge_stage4r_v1`; the
nullable value is persisted and fingerprinted in the immutable campaign plan,
inherited by Resume/restart/fork/checkpoint recovery, and projected through
status, export, the API, and dashboard. The operator-facing activation is
LLM-Director-only: Director state names the plan-bound requirement and
semantic validation rejects omission, changes, random-restart use, and patch
activation. Passive mode remains unchanged. `sglab proposal-ranking doctor`
performs one bounded worker call and verifies clean shutdown without running a
benchmark. Omission remains default-disabled.
Fresh generic workspaces can be upgraded safely with
`sglab init --kind first-real-graph-campaign`, and `prepare` performs the same
atomic upgrade only when the workspace is empty. The persistent one-command
operator path is `sglab experiment run --config experiment.toml` with a single
required `[experiment].id`; it imports the authorized Codex home, revalidates
the plan fingerprint, and starts or resumes the matching attempt.

## Issue #15 — reviewed Mutation Forge Stage 4R ranking seam

Implemented on the opt-in branch `agent/mutation-forge-ranking-seam` from the
required HEG pin. The packaged policy bytes, source/AST/behavior identities,
Stage 2A worker protocol, Stage 2B context/proposal/pool schemas, deterministic
host-owned k-switch pool, fail-closed process boundary, checkpoint identity,
replay/red-team helpers, and additive schema-018 identity ledger are now
available. Existing lanes omit `proposal_ranking` and retain their prior
trajectory; the Director cannot patch the parameter. See
`docs/reports/MUTATION_FORGE_RANKING_SEAM_REPORT.md` for the preregistered
gates and terminal result. The authoritative faithful HEG end-to-end gate is
`NO_GO`; rollout remains disabled and no Stage 7R issue is created.

## Issue #16 — exact proposal-ranking performance seam

The opt-in ranking path now reuses immutable graph-local Stage 2B facts,
matching shapes, and copy-on-write local-risk adjacency, and sends each
bounded proposal pool through one reviewed worker batch frame. The base worker
protocol remains `stage2a.worker.v1`; the bounded extension is
`stage2a.worker.batch.v1` and is part of the exact checkpoint identity. A
fixed-width `stage7.heg.profile.v1` aggregate is available only when explicitly
requested; it contains no per-proposal history. Missing score witness lengths
are completed from the bounded host context rather than coerced to zero.

The policy remains disabled by default. The frozen serial order-18/24/30,
seed-801..805, three-repetition matrix completed all 45 paired rows but
measured a pooled median ranked/baseline ratio of 0.03790645 (all order and
paired-seed medians were below threshold). Replay, red-team, migration,
checkpoint/resume, process-safety, M4-isolation, worker, and repository gates
passed. The authoritative issue-16 decision is `NO_GO`; see the performance
report and byte-manifested evidence root. No rollout or future Stage 7R issue
is created by this work.

## Reusable direct-mutation witness context

The forbidden-cycle-break optimization is no longer private to `_LaneKernel`.
The target plugin now provides one reusable caller-owned context containing
only the ordered witness-edge choices for one immutable current graph. The
lane kernel uses that component, while direct `mutate_with_delta()` consumers
can supply the same context or pass its choices through the existing explicit
configuration field. Replacement/invalidation, empty-choice caching and the
uncached fallback preserve the previous first-witness bias, no-op semantics,
RNG draws and logical trajectories.

Fixed batch-local profiling now separates cache activity, whole and
per-length witness DFS calls/nodes/time, witness-edge materialization, partner
sampling/switch attempts, candidate construction, connectivity and
graph-family validation. The redundant bounded enumeration limit is one;
controlled regression graphs prove the ordered choices match the former
`limit=2`/`found[:1]` result.

The paired order-30 issue-14 workload (16 episodes and 80,000 evaluations per
cache mode, split evenly between operators) reduced targeted mutation time by
92.47%, increased workload throughput by 224.45%, and showed no uniform
regression. All paired logical trajectories matched, and witness searches
equaled the number of successive targeted current-graph states. See
`docs/reports/M6_MUTATION_WITNESS_CACHE.md`.

## Missing-checkpoint executability and terminal runner cleanup

Resume and snapshot publication now distinguish immutable checkpoint history
from current executability. Only the latest integrity-checked checkpoint of
each active lane is exposed as a current executable target; older and
non-current candidate-referenced checkpoints remain evidence. An explicit
retained candidate target is included only when its object is present in the
current `LaneManager` registry. Missing historical artifacts remain in the
continuity ledger and cannot reach the orchestrator pin boundary or trigger
`KeyError`.

The orchestrator now validates and pins its complete executable checkpoint set
in one atomic manager operation. The batch is kept ahead of older unrelated
pins during retention eviction, preventing a capacity-sized review from
deleting a not-yet-visited target according to set iteration order.

`LaneManager.shutdown()` now preserves final queued events for the dispatcher,
reaps lane processes, and idempotently closes every owned multiprocessing
command/event queue. A detached campaign runner can therefore exit after a
terminal fault instead of remaining in the dashboard service cgroup and
blocking the next Resume.

Focused regressions cover the missing-checkpoint evidence/executable split,
capacity-sized batch self-eviction, queue closure, repeated shutdown, and live
lane shutdown.

## Seed-generation retry and latency telemetry

Every campaign seed construction now records its source, graph family/order,
effective generator mode, success/failure, internal attempts, fixed retry
budget, elapsed time, and categorized failure. Fixed-size attempt/time
histograms provide bounded p50/p95/p99 estimates with batch and cumulative
lane totals; random-restart seed time is now separable from generic mutation
generation. Checkpoint graph restores are explicitly excluded.

Cumulative aggregates survive Resume in a separately hashed checkpoint
telemetry envelope, leaving graph/RNG/search checkpoint identity deterministic.
The reviewed `seed_generation_efficiency` diagnostic compares lanes, families,
and orders for high p95 attempts, retry-budget pressure, generator runtime
share, and seed-dominated random-restart throughput. No generator, retry
budget, graph-family semantics, search trajectory, archive, or M4 behavior
changed. See ADR 0015 and `docs/reports/SEED_GENERATION_TELEMETRY.md`.

## Passive snapshot-to-commit boundary

Passive review no longer runs as a background task while the same orchestrator
pumps and dispatches lane events. The coordinator drains those events before a
due snapshot, then performs the deterministic host review and action-batch
commit without another event pump between them. This closes the observed
multi-lane race in which unrelated accepted outcomes advanced the global
campaign version from 493 to 495 and invalidated a restart whose target lane
version was still current.

The global snapshot-version check and existing one-fresh-review recovery remain
unchanged for genuine external conflicts. Focused orchestration regressions
prove the passive boundary does not pump events and that an explicitly injected
first conflict still retries while a second injected conflict still faults
without dispatch or scheduler-state advancement.

## Passive stale-campaign concurrency recovery

The no-LLM passive scheduler now treats a commit-time
`rejected_stale_campaign` as a bounded optimistic-concurrency conflict rather
than immediately pausing the campaign. The rejected decision and batch remain
immutable evidence and dispatch nothing; the coordinator publishes one fresh
snapshot and performs one fresh deterministic review. A second stale campaign
conflict, or any other passive batch rejection, still stops fail-closed.
Rejected reviews do not advance committed scheduler state, and a durable
per-state decision-attempt ordinal prevents regenerated action IDs from
colliding with preserved rejected actions after retry or Resume.

Focused orchestration regressions cover both successful recovery after one
race, failure after a repeated race without an accepted action, and a later
restart from the last committed scheduler state. See
`docs/reports/PASSIVE_STALE_CAMPAIGN_RECOVERY.md`.

## Resume compaction of duplicated continuity summaries

The long-running first graph campaign reached a 32,760-byte durable scientific
memory and then failed Resume when new source rows produced a 34,371-byte
projection. Existing reduction exhausted rich candidate/lane fields but kept
their duplicated historical summary objects.

The deterministic secondary bound now drops oldest duplicated candidate and
lane summaries after rich-field reduction. Exact-verifier outcomes, current
executable candidate/checkpoint IDs, applicable action-space IDs, and all raw
SQLite history remain unchanged. A focused regression forces this final
reduction and verifies the exact/current ledgers byte-for-byte.

## No-LLM passive scheduler

Campaigns now support explicit `director_mode=llm|passive`. The versioned
`balanced_v1` passive policy uses persisted evaluation boundaries, bounded
telemetry, deterministic reason codes, checkpoint-aware stagnation restarts,
an exploration floor, and SHA-256 counter RNG lineage. Its decisions pass
through the existing schema/semantic validation, action tables, dispatcher,
resource controls, checkpoints, candidate pinning, and M4 broker.

Schema 17 records campaign/attempt modes, immutable transition provenance,
mode-specific contract fingerprints, passive decisions, and resumable
scheduler state. Passive startup creates no App Server session/turn or private
Codex home and does not perform token accounting. CLI and dashboard creation,
Resume preview/start, status, attempt history, and export provenance are
mode-aware; switching modes is explicit and restricted to a new attempt.

Focused deterministic and bounded live-smoke evidence is documented in
`docs/reports/PASSIVE_SCHEDULER_ACCEPTANCE.md`; the architectural choice is
ADR 0014.

## Mandatory optimized C++ heuristic scorer

Heuristic search now has one production scoring implementation: the
persistent optimized C++ worker. The Python count-only scorer, workspace,
plugin API, shadow/audit mode, backend environment switches and automatic
fallback have been removed. Campaign lanes and the legacy search runner both
start the worker before evaluation, retry it once after a bounded failure and
then fail closed.

New work always uses conservative early exit and `delta_local_v2`. Runtime
provenance and batch metrics describe the fixed implementation rather than a
requested/effective backend pair. M4 exact verification and its independent
reference implementation remain unchanged. See ADR 0013 and
`docs/reports/M6_MANDATORY_CPP_SCORER.md`.

## Deterministic cycle-overlay readability

The scientific observatory now assigns each displayed cycle length one stable
color reused by highlighted edges, vertex membership fills, layer controls,
and the graph legend. Shared highlighted edges render repeating equal colored
segments in ascending cycle-length order from the lower endpoint ID to the
higher endpoint ID. Toggling a layer recomputes the pattern from the remaining
visible cycles.

Vertices remain above all edges and now render hollow for no displayed-cycle
membership, solid for one membership, and as equal clockwise sectors for
multiple memberships. Exact M4 witnesses retain their double authority outline
while using the same length color in the core and vertex ring. Ordinary graph
edges, bounded visualization payloads, search, scoring, mutation, and M4
semantics are unchanged. See
`docs/reports/M6_CYCLE_OVERLAY_READABILITY.md`.

## Director evidence-reference schema

The dynamic Director output schema now restricts
`hypothesis_updates[].evidence_for`,
`hypothesis_updates[].evidence_against`, and `actions[].evidence_ids` to the
exact evidence registry submitted for that turn. The enum is stored once in
`$defs` and reused by reference, avoiding per-action duplication in the
client-owned request. An empty evidence registry forces all three arrays to
remain empty, while semantic validation retains the same independent
membership check.

This closes the attempt-21 repair failure in which the first response was
rejected for stale lane versions, then the otherwise reduced repair invented a
historical candidate-summary evidence ID absent from the committed snapshot.
Both rejected turns remain immutable evidence and no action from either turn
was executed.

## Attempt-scoped throughput after Resume

Current per-lane and aggregate throughput now ignore metric windows completed
before the active execution attempt's `started_at`. Resume therefore starts at
`0/s` until a lane completes its first new measurement window; historical
windows remain available for rolling telemetry and evidence.

## Bounded continuity ledgers across Resume

Scientific-memory merge now preserves the same fixed windows used by snapshot
construction: 32 exact-verifier outcomes, 64 hypotheses, candidates, and
lane/checkpoint entries, and four validation-feedback entries. Previously,
each merge appended older unique entries after the bounded current window, so
the exact-verifier ledger grew from 32 to 36 and then 41 entries and caused a
33,197-byte `ScientificStateOverflow`. Full rows and verifier artifacts remain
durable; only the model-facing projection is bounded. Repeated verifier
manifest paths and lane checkpoint paths/hashes are also omitted from the
projection while their logical IDs and exact results remain present, providing
headroom below the hard limit.

## Zero current throughput outside running state

The live-frontier aggregate and per-lane cards now show `0/s` whenever the
campaign is paused or otherwise not running. Completed metric windows remain
available for trends and evidence, but are no longer presented as current
work after Pause.

## Consistent per-lane and aggregate throughput

The main campaign lane cards now use each lane's latest completed metric
window, matching the live-frontier aggregate throughput contract. The existing
rolling telemetry summary remains unchanged for diversity, duplicate rate,
yield, and trends. The main lane panel displays up to eight cards instead of
the generic six-card bound, so a fully allocated eight-lane campaign is visible
without expansion.

## Current-graph witness cache for targeted mutations

After the persistent C++ scorer removed the original DFS bottleneck,
production order-96 windows showed mutation generation at 64–85% of accounted
search time. The forbidden-cycle-break operator was independently rerunning
the bounded Python witness traversal on the unchanged current graph after
rejected candidates.

Each lane now retains exactly one ephemeral ordered witness-choice tuple for
its current immutable graph. Accepted moves and restarts invalidate it; the
cache is not checkpointed or persisted. Cache on/off tests preserve graph,
score, best graph, RNG state, accepted count, improvements and operator
statistics. Mutation profiling adds only fixed batch-local integer counters
and emits one aggregate payload when profiling is enabled.

A clean seven-pair benchmark at order 96 with 30% targeted mutations improved
median throughput from 186.8/s to 261.6/s (1.40×), reduced mutation time by
72.7%, reduced witness searches from 301 to 67 and preserved the full logical
trajectory. Profiling on/off measured −0.03% overhead (noise) against the 2%
gate. The larger persistent-worker witness protocol extension is therefore
deferred until a new profile proves the remaining cache misses dominant. See
`docs/reports/M6_MUTATION_WITNESS_CACHE.md`.

## Director turn model and effort provenance

Persistent App Server turn cards now show a compact `model:effort` badge next
to their validity and thread-lifecycle badges. Values come from the immutable
App Server session joined to that specific turn, rather than from current
campaign settings, so historical turns retain their actual requested contract.
The badge wraps with the existing status row on narrow screens.

## Browser-local timestamps across the UI

Every primary timestamp on the dashboard, scientific observatory, and
comparison pages now uses one browser-local formatter with Polish/European
day-month-year order, a 24-hour clock, and the browser's configured timezone.
Attempts, actions, events, hypotheses, revisions, runs, live-frontier
publication, retained-candidate history, and comparison creation no longer
show raw `...Z` values as their main text.

The original UTC timestamp remains in each semantic `time` element and tooltip,
and raw technical JSON, APIs, SQLite values, and ordering are unchanged.
Static renderer regressions and desktop/mobile browser checks cover the shared
formatter and the observatory integration. See
`docs/reports/M6_BROWSER_LOCAL_TIMESTAMPS.md`.

## Director client-context hard gate raised to 32,000

The complete client-owned Director request now fails closed at 32,000 estimated
tokens instead of 16,000. Deterministic compaction still targets 15,000 tokens,
so ordinary requests keep the previous cost and context discipline; the larger
hard gate only supplies recovery margin when non-droppable exact-verifier facts
or executable IDs prevent further safe reduction.

A regression constructs a complete request above 16,000 and below 32,000
tokens and verifies that it is admitted, while the existing oversized-context
test still fails before inference above the new boundary. The App Server
protocol audit passed without authentication or a model turn. See
`docs/reports/M6_DIRECTOR_CONTEXT_HARD_LIMIT_32K.md`.

## Recurring Director context-budget repair

The fifth production `DirectorContextBudgetExceeded` recurrence was reproduced
from its persisted snapshot and context-budget artifact. The request reached
67,350 bytes / 16,838 estimated tokens. Its calculated state target was below
the irreducible safe-state floor, so the previous one-shot reduction discarded
all available compaction and failed at the hard gate.

Complete-request compaction now targets 15,000 tokens, then deterministically
searches for the tightest feasible state when the ideal target cannot preserve
all non-droppable facts. The prompt also stops duplicating the action space and
the complete list of durable reserved action IDs; durable SQLite collision
validation remains authoritative. The same production snapshot now preflights
at 59,076 bytes / 14,769 estimated tokens while retaining current executable
IDs and exact-verifier facts. No model turn or campaign Resume was used for
this verification. See
`docs/reports/M6_RECURRING_CONTEXT_BUDGET_REPAIR.md`.

## Selection-safe dashboard refresh

Periodic dashboard and live-frontier refresh no longer replaces the specific
DOM container intersecting an active text selection. A selection that crosses
a polling boundary therefore remains available for copying while polling,
unrelated telemetry, and the live graph drawing continue normally. The
selected container catches up after the selection is cleared. The change is
browser-only and does not alter campaign execution, scoring, persistence, or
API payloads.

Dashboard metric and semantic value tiles now share independent single-click
copy with card-local confirmation and keyboard activation. Clipboard text
includes the tile label and full value, so abbreviated IDs, hashes, and
SHA-256 values copy without truncation or layout changes. Standalone
abbreviated identifiers use the same mechanism, replacing separate `Copy ID`
buttons.

Persistent App Server turn cards now state that their order is newest first
and show each persisted `started_at` timestamp in the browser's local
timezone with European day-month-year order and a 24-hour clock. The raw UTC
value remains available in the timestamp tooltip and is unchanged in the
database and API.

The dashboard section navigation now exposes one-word anchors for every main
section. Comparison, visualization, and legacy-only links share the
visibility of their target section, preventing dead navigation entries.

## Aggregate live-frontier throughput

The live-frontier inspector now labels throughput as a campaign aggregate and
sums the latest completed measurement for every running lane. A lane that has
not yet completed its first batch no longer makes the whole value unavailable:
the available running-lane measurements remain visible, with measured/running
coverage in the tooltip. The lane visualization continues to report
lane-specific throughput. This is a read-only projection over existing
batch-level telemetry; it adds no scoring, checkpoint, SQLite, event, or
per-candidate work.

## Director verification-target schema

The dynamic Director output schema now restricts every
`schedule_verification.candidate_ids` item to the exact submitted candidate
target list. The semantic validator retains the same membership check; no
unknown ID is repaired, normalized or executed.

This closes the production attempt-15 gap in which the repair response used a
truncated candidate ID that was structurally valid as an arbitrary string but
semantically inadmissible. Replaying that attempt's 12-candidate action space
excluded the truncated ID and increased the complete schema by 453 bytes. The
full request remained within budget at 53,359 bytes / 13,340 estimated tokens
against the 16,000-token gate. See
`docs/reports/M6_DIRECTOR_VERIFICATION_TARGET_SCHEMA.md`.

Production attempt 16 then submitted the repaired live schema at 13,914 bytes
and the complete request at 53,373 bytes / 13,344 estimated tokens. Its first
two Director turns were `completed_valid`; verification used only exact enum
members, four reviewed M4 jobs completed, and four new order-96 lanes ran five
durable windows totaling 591,338 evaluations. All windows used the persistent
C++ backend, early exit and `delta_local_v2`, with zero scorer fallbacks or
parity mismatches. A third independent Director turn reached its 300-second
App Server timeout, so the campaign paused fail-closed with the four new lanes
paused and no worker processes left. This timeout is separate from the
accepted verification-target repair; no automatic further Resume was started.

## Director repair-turn state identity

Production attempt 11 completed four valid Director turns, then received one
semantically invalid response. Its first request had safely reduced
`DirectorStateV2` to 31,077 bytes under a 31,099-byte derived target. The
repair path incorrectly rebuilt the same source snapshot at the default
32 KiB limit and stopped fail-closed before starting the repair inference with
`prompt DirectorStateV2 does not match the committed snapshot`.

Repair recursion now carries the exact prepared state and all three reference
registries used by the invalid turn. The repair prompt therefore preserves
byte-for-byte scientific-state identity instead of performing another
projection. A request-budget regression exercises invalid→repair after
client-limit compaction and verifies that both submitted repair states are
equal. The paused production database was captured with SQLite Online Backup;
schema v16 passed integrity and foreign-key checks.

Production attempt 15 exercised the exact failed boundary: its first response
was `completed_invalid`, then a fresh repair turn started and completed
without the former snapshot mismatch. The repair response remained invalid
for one inadmissible verification candidate, so the whole action batch was
correctly rejected and the campaign stopped after its single allowed repair.
This later model-output fault executed no action and is separate from the
repaired state-identity protocol.

## Versioned duplicate keys and independent sample provenance

Lane checkpoints now record canonical `duplicate_key_scheme` values while
remaining compatible with historical aliases. Resume and
trajectory-preserving forks keep their existing visited/tabu semantics; only
new lanes and explicit algorithmic restarts may switch to the delta-local key.
The exact legacy SHA/graph6 key uses a reusable allocation-light encoder and
reuses the digest for candidate identity.

Random-restart lanes no longer construct fictitious mutation ancestry for
every accepted graph. Global records, retained candidates and periodic
checkpoints instead use schema-v2 `independent_sample` provenance. SQLite
schema v16 adds this provenance to retained candidates and copies it into
immutable M4 snapshots; historical rows remain `{}`.

Production Resume exposed one legacy boundary after this change: an
independent-sample lane correctly stopped constructing new mutation records
but restored 64 old ancestry entries from its pre-migration checkpoint and
re-serialized them in every telemetry window. Resume now treats those fields
as non-executable historical evidence and starts the live random-restart
ancestry tracker empty. Deterministic continuation tests preserve graph, score,
RNG, high-water counters and provenance while asserting empty mutation
ancestry.

Seven alternating benchmark pairs preserved every logical trajectory. The
legacy encoder reduced duplicate time by 48.1% and improved total throughput
14.6%; independent provenance reduced ancestry time by 99.68% and improved
random-restart throughput 33.4%. Profiling overhead remained below 2%. See
`docs/reports/M6_DUPLICATE_KEYS_AND_PROVENANCE.md`.

## Persistent scorer, conservative cutoff and fast duplicate key

The superseded ADR 0009 rollout allowed Erdős–Gyárfás lanes to use one bounded
persistent C++17 count-only worker. At that milestone, worker timeout, crash,
malformed output, or parity mismatch retried once and then fell back to
Python; shadow mode audited results. ADR 0013 later removed the Python scorer,
shadow mode, backend selection, and runtime fallback. M4 remained unchanged.

ILS/tabu scoring can stop when a monotone partial score is already dominated.
A deterministic mutation-delta key removes full graph6/SHA-256 construction
from local duplicate/tabu checks while legacy checkpoints retain their key
scheme. All controls and worker provenance are reported per attempt/batch.

On seven alternating pairs, C++ improved median backend throughput by 8.64× at
order 64 and 12.38× at order 96. Early exit added 9.3%, the fast key added
28.9%, and profiling overhead was 0.71%; every compared logical trajectory
matched. The incremental-witness gate failed at 0% complete dominant-length
stages, so that riskier optimization is not implemented. See
`docs/reports/M6_SCORE_PIPELINE_OPTIMIZATION.md`.

## Complete Director request-budget repair

The repeated production `DirectorContextBudgetExceeded` fault was reproduced
from attempt 8. Its state was valid at 32,722 bytes, so state-only compaction
did not run, while base instructions, prompt, and output schema together
reached 64,250 bytes / 16,063 estimated tokens.

The action space no longer repeats 43 verbose reference objects. Compact
lane/candidate/checkpoint lists now reconstruct identical evidence, advisory,
and executable registries. A second deterministic pass also derives a lower
state target from any remaining complete-request excess plus 1 KiB headroom
before inference. Exact-verifier facts and current executable IDs remain
non-droppable.

An SQLite Online Backup of the faulted campaign passed
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Rebuilding its latest
snapshot reduced the complete request to 57,843 bytes / 14,461 estimated
tokens. Registry parity was exact: evidence 60/60, advisory 43/43, executable
37/37, with no missing or added IDs. See
`docs/reports/M6_CLIENT_CONTEXT_BUDGET_REPAIR.md`.

## Transient live-frontier publication

Search workers now publish the already accepted graph and score at most once
per second during long batches. Publication does not call `cheap_score()` or
build a full checkpoint. The coordinator atomically overwrites one
SHA-256-protected, 64 KiB-bounded preview file per lane; no preview history,
SQLite row, log line, or scientific event is created. The visualization reader
prefers a valid preview and falls back to the latest valid durable checkpoint.

The standard microbenchmark now reports candidate evaluation, checkpoint
serialization, SQLite commit, telemetry/event enqueue, and live-frontier
publication separately. A 10-sample `n=20` run measured medians of 5.672 ms per
10-candidate evaluation batch, 0.818 ms checkpoint serialization, 0.066 ms per
100-row SQLite commit, 0.001 ms telemetry/event enqueue, and 0.097 ms
live-frontier publication. See
`docs/reports/M6_LIVE_FRONTIER_PUBLICATION.md`.

## Count-only hot-loop scorer and batch-local profiling

The Erdős–Gyárfás ranking path now uses a reusable lane-local iterative
integer-bitset DFS workspace. It preserves the bounded reference traversal's
counts, completeness flags and deterministic search trajectory without
constructing witness tuples in the candidate hot loop. Witness-returning
diagnostics and both M4 paths remain unchanged.

Per-length nanoseconds and DFS-node counts accumulate only in memory and are
serialized once per completed batch. Profiling can be switched off
independently; an alternating five-pair `n=64`, cap-2000 comparison measured
0.27% median overhead and identical graph, score and trajectory. Against
commit `11a2903`, median unprofiled throughput increased from 18.53 to 24.41
candidates/s (31.7%). See
`docs/reports/M6_SCORE_KERNEL_OPTIMIZATION.md`.

## Director scientific-memory compaction ordering repair

The first real graph campaign reached a 31,593-byte scientific-memory snapshot,
then added another search lane and stopped fail-closed with
`DirectorContextBudgetExceeded: DirectorStateV2 remains oversized after
deterministic compaction`. The state was reducible, but `SnapshotBuilder`
enforced the 32,768-byte Director limit before invoking the secondary
`ScientificMemoryCompactor`.

Snapshot construction now builds a section-bounded intermediate Director state,
runs deterministic scientific-memory reduction, and only then enforces the
final Director limit and constructs executable registries. A focused regression
test proves that reducible continuity is compacted while exact-verifier facts
remain present. An SQLite Online Backup of the affected production database
reconstructed 12 lanes, 11 candidates, 11 hypotheses, and 25 executable
checkpoint IDs into a 32,699-byte projection; `PRAGMA integrity_check` passed
and `PRAGMA foreign_key_check` returned no violations. No original campaign
data or model turn was used during the repair test.

## Audience-oriented documentation migration

The repository documentation now has user, operator, architecture, reference,
Codex, ADR, and evidence-report entry points based on commit
`a25579d0a6cd088d2c0687664312e9c3b07404b7`. The migration preserves historical
reports, benchmark evidence, and the chronological implementation ledger while
replacing six superseded mixed-purpose manuals with focused current guides.
All local Markdown link targets resolve, and the 18 screenshot markers remain
as an explicit capture plan under `docs/user/screenshot-plan.md`.

## Scientific observatory

The live campaign dashboard now includes a bounded read-only scientific
observatory. It renders the global-best graph, a live search-frontier sample
with a browser-session 1–5 second refresh selector, a lane-best graph, the
immutable candidate currently consumed by M4, or a retained historical
candidate.
Server-side `graph6` decoding keeps raw encodings and artifact paths out of the
browser contract. Distinct overlays show bounded non-certifying cycle examples
and hash-checked persisted M4 witnesses without conflating heuristic evidence
with certification. Live frontier checkpoints are size-bounded, opened without
following symlinks, integrity-checked, and explicitly labelled transient
heuristic telemetry.

Supporting tabs show weighted-penalty history, cycle profiles, lane telemetry,
verification state, and retained-candidate history. SQLite reads and browser
lists are bounded. Desktop and phone Playwright-CDP checks confirm responsive
layout, no page-wide horizontal overflow, and preservation of the selected
tab, graph viewport, and scroll position across repeated dashboard polls. The
observatory is read-only and creates no model, search, action, or verifier side
effect. See `docs/SCIENTIFIC_OBSERVATORY.md`.

## Campaign execution attempts, candidate lifetime, and scientific memory

SQLite schema v15 separates a durable scientific campaign from immutable
execution attempts. Start and Resume record attempt reason, code commit,
requested/effective application resources, incremental wall time, starting
memory/checkpoints, inherited and local counters, provenance, and terminal
outcome. The campaign ID and scientific contract remain stable while CPU
worker slots, active lanes, lane/verifier memory, verifier concurrency, and
queue bounds may change per attempt. Resume supports operator, budget,
repaired-infrastructure, interrupted-process, and host-restart continuity and
rejects live, certified, or scientifically invalidated campaigns.

Candidate-target actions now validate against the current executable registry,
transactionally create an immutable graph snapshot and durable pin, and make
M4 consume that snapshot. Pinned candidates cannot be pruned or deleted.
Pins release only after all references are terminal. A stale target is
persisted specifically, never executed, and permits one fresh stateless replan
with the current valid registry. Historical stale actions are excluded from
Resume execution.

Deterministic scientific-memory snapshots bound the canonical Director state
at 32,768 bytes, compact at a 24,576-byte soft threshold, and snapshot every
five valid cycles plus every terminal/Resume boundary. Exact-verifier facts
and current executable IDs are non-droppable; full raw history remains in
SQLite/artifacts. Every Director turn and execution attempt records the
snapshot it used.

The production state machine completed a model-free 65+65 second continuation:
the same campaign advanced from 69,995 to 140,918 cumulative evaluations,
reused two verified checkpoints and its terminal memory snapshot, preserved
four prior M4 outcomes and its hypothesis, and changed application worker
slots from 2 to 16 without duplicate actions. Protected HTTP controls and
Playwright CDP verify attempt history, cumulative/local metrics, repair
acknowledgement, resource differences, and desktop/mobile Resume preview.
The real paused campaign produces a read-only Resume preview with the current
set of hash-valid reusable checkpoints and its historical missing-candidate
action excluded. No real model or auth access occurred. See
`docs/user/resume.md`,
`docs/architecture/scientific-memory.md`, and
`docs/reports/CAMPAIGN_RESUME_AND_MEMORY_PHASE_A.md`.

The first production Resume exposed a legacy-shape boundary missed by the
fake/replay demonstrations: raw stored lane mutation ancestry made the
pre-Resume snapshot 368,573 bytes, above its 256 KiB artifact contract.
Snapshot construction now derives the same bounded telemetry summary used for
live lanes while leaving every raw metric row unchanged. The exact preserved
campaign shape now produces a 69,803-byte snapshot and a 15,861-byte
scientific-memory projection. The dashboard now waits for the immutable
execution-attempt row before claiming that Resume started and reports a
pre-attempt subprocess exit instead of returning a misleading PID. Resume
previews continue to report historical stale actions after they are already
terminalized.

The first attempt-scoped production Resume then exposed a second compatibility
boundary: expected App Server wrappers were accepted below the legacy
`runtime-groups` tree but not below the new immutable attempt
`application-data` tree. The same strict four-name, `codex-arg0-*`,
trusted-executable policy now recognizes both private layouts. Targets remain
non-followed for accounting, wrong-directory/untrusted links remain rejected,
and the failed execution attempt remains immutable historical evidence.

A later production attempt completed a valid Director turn but the stateless
response reused four descriptive `action_id` values from an earlier batch
with new idempotency keys. SQLite therefore raised the workspace-wide primary
key constraint before any of those returned actions executed. The Director
contract now supplies a deterministic per-snapshot action-ID namespace, the
semantic context rejects every durable workspace collision, and decision
persistence performs an atomic collision preflight. A race discovered only at
commit time is recorded as `rejected_action_id_collision` and receives at most
one fresh stateless replan; it is no longer surfaced as a raw
`IntegrityError`. The historical failed attempt and its records remain
unchanged.

The next production Resume exercised that action-ID fix successfully: the
Director used the recommended namespace, but supplied prose rather than
registry IDs in hypothesis evidence fields. The invalid response was correctly
persisted and not executed. Its stateless repair prompt then exceeded the
16,000-token client-owned limit because it redundantly embedded the complete
10 KiB rejected response alongside the unchanged scientific state. Repair
prompts now retain the response by artifact/SHA-256 and submit only the exact
validation errors plus the same state. Offline reconstruction of the preserved
turn reduces the estimate from 16,743 to 13,989 tokens without increasing any
limit. The prompt and generated schema also state explicitly that hypothesis
evidence arrays contain registry IDs, never prose. The failed attempt remains
immutable historical evidence.

## First real graph campaign authorization gate

The production campaign CLI now has a deterministic `prepare` boundary for a
fresh non-synthetic workspace. It creates a durable `prepared` campaign row,
an exact plan artifact, campaign ID, and canonical fingerprint before any
credential access. Campaign-specific auth import and start both require that
exact fingerprint. The fixed one-hour contract binds Luna/high/stateless,
twelve scientific cycles, at most twenty-four App Server turns including one
possible replan per state, eight bounded search lanes, M4 verifier limits, and
App Server diagnostic/runtime quotas. Per-lane and aggregate CPU-share bounds
are explicit in the fingerprinted search contract.

The existing production orchestrator and action space remain authoritative;
there is no scripted experiment sequence. Valid Director actions are
dispatched. Invalid responses are persisted and never executed. One invalid
response may be replanned only on a fresh stateless thread with the identical
DirectorStateV2 and validation errors; a second invalid response stops the
runtime fail-closed. Prepared campaigns disable App Server retries and provider
recovery.

The campaign's private App Server tree now uses the reviewed no-follow
resource-accounting and expected-wrapper policy. Scratch and single-file
limits, bounded wire/stderr/stdout, safe peak telemetry, strict model/effort
matching, and graceful shutdown are part of the fingerprinted contract.
Preparation and installed protocol compliance perform no model turn and do
not access authentication.

## M7 hypothesis and independent-arm contracts

SQLite schema v14 adds a nullable, fingerprinted arm-failure policy. Historical
suite rows remain null, retain plan schema 2.1, and recompute to their original
fingerprints. New measurement-only comparison plans use schema 2.2 and
`independent_invalid_continue_v1`: a schema-invalid or semantic-invalid
independent result is retained and the next independent arm runs, while
infrastructure, security, protocol, resource, and model-contract failures
still stop later arms. A persistent dependent arm still requires a completed
predecessor. All returned actions remain unexecuted.

The Director prompt, generated schema, and semantic validator now share an
operation-specific hypothesis-update contract. `create` requires a new,
response-unique ID. `confirm`, `weaken`, `reject`, `retain`, and `revise`
require an ID from the submitted hypothesis registry. The preserved Luna-high
response used `revise` for unknown `H0`; it therefore remains semantically
invalid and the new generated schema rejects that shape structurally.

Focused production-worker tests cover both invalid-result classes continuing
to a second independent arm, infrastructure fail-closed behavior, dependent
persistent blocking, and zero action execution. The complete 236-test safe
suite, doctor, compile checks, benchmark/dashboard smoke, schema-v14 Online
Backup migration, SQLite integrity, and foreign-key checks pass. No model,
auth, graph-search, or action-dispatch path was used. See
`docs/reports/M7_HYPOTHESIS_CONTRACT_FIX.md`.

## M7 comparison symlink policy and worker reaping

Schema v13 separates byte inequalities, single-file and log caps, filesystem
policy, accounting errors, process lifecycle, and App Server protocol
failures. The four reviewed App Server `arg0` wrapper names are accepted only
at the exact private runtime location and only when their target is a stable,
regular, executable, non-world-writable file below the server-discovered
Codex installation root and outside the research workspace. Accounting never
follows a target or charges its bytes, and persists only safe relative labels
and trust classes.

Deterministic production-worker tests cover the exact four wrappers, unexpected
external and wrong-directory links, untrusted and broken targets, link inode
races, genuine aggregate and single-file crossings, two successful arms, and
a ten-run wrapper soak. Filesystem failures no longer carry scratch limits or
false `current > limit` messages. The historical second suite remains
terminal and unchanged; its UI derives the corrected legacy explanation from
the v12 crossing sample.

The dashboard now polls only its owned comparison `Popen` handles, persists
the reaping result, removes completed registrations, and treats Linux zombie
state as non-live. HTTP tests prove successful and failed workers are reaped
while the dashboard remains responsive and terminal detail remains readable.

The installed no-auth lifecycle smoke starts, initializes, accounts, shuts
down, and reaps Codex without `thread/start` or `turn/start`. The installed
build creates no `arg0` wrapper symlinks in that bounded phase, so direct
classification of real installed wrappers remains unproven without crossing
the explicitly forbidden thread boundary. Consequently a fresh authenticated
comparison is not yet declared ready.

## M7 second real comparison failed before inference

Fresh authorization bound the schema-2.1/accounting-v2 Luna high-versus-xhigh
suite to its unchanged fingerprint and exact two-start contract. The plan
verification passed, a private runtime was prepared, and the App Server
process started. The worker then failed closed at
`after_app_server_start`, before thread creation, inference reservation, or
model inference. Luna high is an infrastructure failure and Luna xhigh is
blocked/not started. No authoritative tokens, search batches, actions, model
tools, or ratings exist.

Persisted telemetry proves that no byte quota was exceeded: scratch peaked at
2,274,115 apparent bytes against 536,870,912, while preserved artifacts peaked
at 4,878 against 67,108,864. Instead, the App Server created four transient
executable-wrapper symlinks in its private `arg0` directory. Accounting
correctly did not follow them, but worker enforcement converted any escaping
symlink into an aggregate `runtime_scratch` quota violation. The terminal
message and UI therefore show the false numeric comparison
`2,274,115 > 536,870,912`.

The diagnostic was persisted before shutdown, the lease was released, SQLite
integrity and foreign keys remain clean, and final process checks show no
worker, App Server, dashboard, or zombie. The suite is terminal and must not
be reused. A deterministic fix for normal App Server transient symlinks and
the misleading failure classification is required before another authorized
comparison. See
`docs/reports/M7_SECOND_REAL_COMPARISON_RUNTIME.md`.

## M7 comparison resource accounting repaired deterministically

SQLite schema v12 and the comparison worker now separate preserved artifacts,
private runtime scratch, credential material, and logs. New plans fingerprint
independent 64 MiB preserved, 512 MiB scratch, 32 MiB single-preserved-file,
256 MiB single-runtime-file, wire, stderr, stdout, and wall-time limits. The
deprecated artifact-directory limit maps only to preserved artifacts. Legacy
plans remain hash-stable and cannot be executed again.

One bounded `lstat` traversal supplies enforcement and telemetry, does not
follow symlinks, rejects escape, deduplicates hard links by device/inode,
reports apparent and allocated bytes, identifies sparse files, redacts
credential paths, and fails closed on inaccessible or over-bound traversal.
The worker persists bounded latest/peak/crossing/terminal summaries and a
private threshold diagnostic before interruption or cleanup. A valid completed
arm remains valid when later shutdown infrastructure fails.

The fake App Server proves 80 MiB transient scratch no longer consumes the
preserved quota; scratch/WAL crossings retain exact attribution after cleanup;
large preserved writes fail before creation; single-file and log bounds work;
two valid arms complete sequentially; the lease is released and no fake
process remains. The closest original-shape reproduction proves the old code
incorrectly combined runtime scratch with artifacts. The exact historical
transient contributor is unresolved because only the 6,083,415-byte
post-shutdown non-auth tree remains.

The failed Luna suite is unchanged: one consumed inference, high completed
valid, xhigh never started, and the original fingerprint recomputes exactly.
The UI now renders that history as an incomplete legacy infrastructure
failure and shows separated resource controls for future suites. See
`docs/reports/M7_COMPARISON_RESOURCE_ACCOUNTING_PHASE_A.md`.

## M7 first real comparison runtime failed closed

Fresh explicit authorization bound the prepared Luna high-versus-xhigh suite
to its unchanged fingerprint, two stateless contracts, and at most two
inference starts. The randomized high arm ran first and completed with a final
answer, matching effective model/effort/context, schema and semantic validity,
9,755 authoritative tokens, and 73.64 seconds total latency. Its returned
actions remained measurement-only and unexecuted.

The worker then failed closed on the 64 MiB comparison artifact-directory
limit before starting xhigh. Exactly one inference start was consumed; there
was no retry, replacement, second/third inference, search batch, lane, action
dispatch, candidate evaluation, compaction, or model tool call. The App Server
closed gracefully, the lease was released, and no worker/App Server orphan
remains. Because only one valid response exists, blind pairwise rating is not
available and no user rating was recorded.

The terminal UI exposed and then received a focused fix for rendering a
structured action-space object; the corrected page renders the completed turn
and disables all terminal controls. The complete 194-test suite, doctor,
compile checks, benchmark/dashboard smoke, SQLite integrity, and foreign-key
checks pass. See `docs/reports/M7_FIRST_REAL_COMPARISON_RUNTIME.md`.

## M7 first real comparison deterministic preparation complete

The dedicated non-synthetic `model_comparison_live` workspace now contains a
complete executable preserved-A4 fixture and one immutable prepared suite for
`gpt-5.6-luna` high versus xhigh in fresh `stateless_turns`. The schema-v11
workspace was built with SQLite Online Backup and a safe scientific-artifact
import; it contains no auth, sessions, Codex homes, rollouts, or wire logs.
All arm-input hashes match and the fixture's conservative client-owned input
estimate is 6,516 tokens under the 12,000-token limit.

The exact plan permits at most two 300-second inference starts and 40,000
authoritative server tokens, with measurement-only, no decision execution,
fail-closed sequencing, seed 20260725, zero search batches, zero action
dispatches, zero model tools, zero compactions, and zero retries reaching
inference. Playwright CDP created and prepared the suite through the rendered
UI and verified the safe API response. The plan remains unauthorized with zero
turns, reservations, attempts, leases, lanes, batches, and actions.

The complete 194-test suite, doctor, compile checks, benchmark/dashboard smoke,
schema-v11 integrity, and foreign-key checks pass. No auth content was read or
copied and no model inference occurred. Phase B remains stopped at the fresh
explicit authorization boundary. See
`docs/reports/M7_FIRST_REAL_COMPARISON_PREP.md`.

## M7 preserved A4 comparison import complete

The `sglab comparisons import-campaign-snapshot` administrative command now
creates a dedicated `model_comparison_live` workspace from one hash-verified
preserved campaign snapshot. It validates a read-only SQLite Online Backup,
copies only the scientific snapshot artifact, derives the complete executable
Director fixture, creates a fresh schema-v11 database, and records a
non-synthetic marker without credential hashes or private runtime paths.
Synthetic/demo sources, absolute paths, auth references, Codex homes,
sessions, rollouts, and wire references are rejected.

The redesigned comparison form and detail view retain every bounded-worker
resource limit, persistent-thread dependency field, fixed Start/Stop controls,
and bounded live progress polling while keeping semantic cards and responsive
layouts. Focused importer, worker, persistence, and UI tests cover the merged
behavior.

## M7 browser UI redesign complete

The research dashboard and controlled-comparison pages now use semantic
decision, effect, lane, candidate, plan, usage, and cost views. Raw protocol
JSON remains available as secondary technical evidence. Primary lists are
bounded, long identifiers are abbreviated without losing the complete value,
tables are locally contained, and narrow viewports use responsive card
layouts.

All pages now provide light and dark themes through shared design tokens. The
header toggle persists the browser preference in `localStorage` and falls back
to the operating-system color-scheme preference when unset. Typography,
focus visibility, field grouping, empty/error states, and status labelling
were normalized without adding a frontend framework or build step.

The user-started port-8787 demo server was inspected through Playwright-CDP at
1920×1080, 1440×900, 1280×720, 1024×768, and 390×844. All route shapes,
comparison lifecycle states, empty/error states, both themes, technical
disclosures, and deterministic forms were exercised. The phone layout has no
page-wide overflow and its primary controls provide 44-pixel touch targets.
Normal routes produced no console or network failures; the intentional unknown
route produced the expected styled 404.

The complete 175-test safe suite passes twice, as do focused HTTP/UI tests,
doctor, compile checks, benchmark/dashboard smoke, and SQLite v10 integrity.
See `docs/reports/M7_UI_PLAYWRIGHT_AUDIT_BEFORE.md` and
`docs/reports/M7_UI_PLAYWRIGHT_AUDIT_AFTER.md`.

## M7 deterministic UI-review fixture complete

The `sglab ui-fixture create` command now creates a rich, isolated and
reproducible `ui_demo` workspace for browser review. Fixed IDs, timestamps and
seeded content cover campaign, Director action/effect, lane, candidate,
hypothesis, telemetry, App Server lifecycle, event, comparison, rating and
cost-profile states without model calls, auth access, external network or a
production search campaign. Replacement is allowed only for a workspace with
the exact synthetic demo marker.

The generated review workspace contains 8 campaigns, 24 decisions, 12 lanes,
40 campaign candidates, 110 metric windows, 12 hypotheses, 12 App Server
turns and 9 comparison suites, including the unchanged read-only M6 S2/P1/P2
result. Two same-seed generations produce byte-identical SQLite databases and
the same logical SHA-256. The fixture is 0.72 MiB, schema v10 integrity is
`ok`, and view-data construction remains below 20 ms maximum in the recorded
local sample.

Focused fixture tests pass 5/5, the complete safe suite passes 158/158, and
doctor, check, benchmark/dashboard smoke and SQLite foreign-key checks pass.
Phase A deliberately stops before starting the port-8787 server or any
Playwright-CDP inspection. See
`docs/reports/M7_UI_REVIEW_FIXTURE.md`.

## M7 bounded comparison worker complete

SQLite schema v11 now persists comparison execution attempts, exclusive worker
leases and heartbeats, stop requests, inference reservations, explicit
persistent-conversation dependencies, and append-only arm transitions. The
worker consumes one immutable authorized plan, verifies its fingerprint before
auth access, reserves each inference transactionally, and never exceeds the
authorized cap. It supports fresh stateless arms and explicit persistent
sequences; compacted execution remains disabled pending a future exact plan.

The bearer-protected Start endpoint launches only the fixed
`sys.executable -m sglab comparisons worker` argv in a separate process group,
without a shell or browser-controlled executable, auth path, command, or
environment. The detail page polls bounded progress APIs for lease, heartbeat,
stop, lifecycle, contracts, usage, latency, and validity. Stop is a durable
request observed by the worker, which interrupts and drains an active turn
before bounded shutdown.

The real worker state machine was tested through the hardened App Server client
and a synthetic stdio server, including persistent resume, stateless fresh
threads, invalid output, timeout and late abort, nullable usage, tool/retry
rejection, protocol errors, crashes, forced shutdown, lease loss, and
fail-closed dependency blocking. The replay HTTP demonstration planned four
arms, reached three fake inference starts, completed two, timed out one, and
blocked the last; it also preserved manual and blind ratings.

Focused tests pass 16/16, two complete safe-suite runs and final `make test`
pass 169/169, explicit loopback tests pass 8/8, and doctor, check,
benchmark/dashboard smoke, SQLite
v10→v11 Online Backup migration, integrity and foreign-key checks pass. The
demonstration made zero real model calls or auth accesses and the comparison
worker created zero search batches, lanes, evaluations, action dispatches,
compactions, or tool executions. See
`docs/reports/M7_COMPARISON_WORKER_PHASE_A.md`,
`docs/architecture/comparison-system.md`, and
`docs/reference/cli-comparisons.md`.

## M7 controlled comparison UI and persistence complete

SQLite schema v10 now provides a comparison subsystem separate from research
campaigns: immutable fixtures and plans, bounded arms and turns, exact-plan
authorizations, append-only manual and blind pairwise ratings, and immutable
cost-profile snapshots. The standard-library dashboard exposes suite list,
creation, preflight/authorization, detail, blind comparison, and cost-profile
pages with bearer-protected POST endpoints.

The production Director default is now `stateless_turns`, based on the single
controlled S2/P2 pair. Explicit `persistent_thread` and `compacted_thread`
remain available; persistent selection emits a token-growth warning. Context
mode and fresh/resumed thread provenance are persisted without rewriting
historical rows.

The deterministic M6 importer renders the real S2/P1/P2 results without
private paths or another model call. Usage accounting does not double-count
cached input or reasoning output, missing usage remains null, and human,
automatic-validity, and downstream-science metrics stay separate.

The deterministic replay dry run made zero model calls, auth accesses, search
batches, lanes, or action dispatches. Focused tests, two complete 153-test
runs, doctor, compile checks, benchmark/dashboard smoke, loopback HTTP, and
SQLite v10 migration/integrity checks pass. See
`docs/reports/M7_COMPARISON_UI_PHASE_A.md` and
`docs/user/comparisons.md`.

## Fresh reduced context-mode screen completed

The corrected three-slot authenticated screen completed S2, P1 and P2 with
exactly three successful `gpt-5.6-luna:xhigh` inference starts. S2 used a
fresh stateless A4 thread; P1 and P2 used one separate persistent thread. All
three decisions were schema-valid, semantically valid, measurement-only and
unexecuted.

The A4 scientific state, prompt, schema, evidence registry and applicable
action space were identical for S2 and P2. S2 used 9,591 input tokens versus
12,754 for P2, a measured stateless reduction of 24.800062725419476%. Both
completed reliably; the predefined single-pair decision rule therefore
recommends `stateless_turns`, without claiming statistical superiority.

The run used exactly three inference starts and zero retries, search batches,
lanes, action dispatches, candidate evaluations, compactions or tool calls.
Both App Server processes shut down gracefully, all skill reload gates ended
with zero active skills, and both SQLite databases and Online Backups passed
schema-v9 integrity checks. See
`docs/reports/M6_REDUCED_CONTEXT_SCREEN_RERUN.md`.

## Action-applicability contract repaired deterministically

DirectorStateV2 now separates visible evidence, advisory targets, and
executable targets into independently hashed registries derived from the final
submitted state. The same dynamic applicable-action space drives the prompt,
structured output schema, and semantic validator. Lane-bound actions and lane
ID enums appear only when an active executable lane exists; historical lanes
remain explicitly visible as non-executable evidence.

The fresh offline reduced-screen plan retains exactly S2 → P1 → P2. A1 offers
`start_lane`, `request_diagnostic`, and `set_review_trigger`; A4 additionally
offers candidate promotion and M4 verification, but no lane-bound action.
S2/P2 remain byte-identical across state, prompt, schema, all three registries,
and applicable action space. Context limits pass, and no inference, auth
access, authenticated App Server turn, or graph-search batch occurred.

The preserved S2 result is now correctly classified as
`indeterminate_due_to_action_applicability_contract_mismatch`. Its raw
`stop_lane` output is not valid under the corrected space because that action
should not have been offered; it is not classified as an independent
model-quality failure.

Focused tests, SQLite v9 migration/integrity tests, and two 128-test
non-network safe-suite runs pass. Doctor, compile checks, benchmark smoke, all
five previously blocked HTTP/dashboard tests, `make dashboard-smoke`, and the
complete 133-test Phase-A-safe suite pass. See
`docs/reports/M6_ACTION_APPLICABILITY_PHASE_A.md`.

## Reduced context-mode screen — deterministic Phase A complete

The replacement measurement screen now has exactly three fail-closed slots in
the fixed order S2 (fresh stateless A4), P1 (fresh persistent A1), and P2
(persistent A4 on the P1 thread). It has no fourth slot, compaction operation,
search lane, batch, candidate evaluation, or action dispatch. Decisions remain
`measurement_only` and are never executed. A 300-second per-turn hard timeout
persists incomplete correlation, uses `turn/interrupt`, drains late events, and
prevents every later slot after a failure.

The authorized runtime contract is now exactly `gpt-5.6-luna` with reasoning
effort `xhigh`. Before each arm's first inference, the client persists the
expected and server-reported effective values and refuses `turn/start` unless
both match. A deterministic mismatch test proves S2 is not submitted when the
server reports another model.

S2 and P2 use byte-identical A4 scientific state, prompt, output schema,
canonical evidence registry, action space, target, budget, artifact references,
and complete request template. Their only intended difference is P1 history
retained by the P2 thread. The A4 state is 16,709 bytes, ancestry is 5,611
bytes, historical outcomes are 3,593 bytes, and the conservative complete
client-input estimate is 9,771 tokens; all hard context gates pass.

Focused evidence/lifecycle/timeout tests and two complete 125-test safe-suite
runs pass. The one installed-app-server compliance test was deliberately
excluded because this phase prohibits starting the installed server.
`make doctor`, `make check`, `make benchmark-smoke`, `make dashboard-smoke`,
and v8-to-v9 migration/integrity checks on an SQLite Online Backup pass.
Historical failure artifacts and the P1 response retain their recorded hashes,
and offline P1 revalidation remains schema-valid and semantically valid. No
auth access, model inference, installed App Server start, or graph-search batch
occurred. See `docs/reports/M6_REDUCED_CONTEXT_SCREEN_PHASE_A.md`.

## Reduced context-mode screen — authenticated run stopped at S2

With explicit authorization, the runtime imported only `auth.json` into two
separate private homes and started the strict stateless arm first. The
server-reported model contract matched `gpt-5.6-luna:xhigh` before inference.
S2 completed with a final structured response and authoritative usage. Its
original semantic result is classified as
`indeterminate_due_to_action_applicability_contract_mismatch`: the submitted
schema exposed `stop_lane` even though its only referenced lane was historical
and non-executable. The preserved output is not valid under the corrected
action space, but this is a client-contract defect rather than an independent
model-quality failure.

Fail-closed sequencing then stopped before P1 and P2. The run therefore used
exactly one inference start, no retries, and zero search batches, lanes,
dispatches, candidate evaluations, compactions, or tool calls. Shutdown was
graceful and SQLite integrity was `ok`. The S2/P2 token comparison is
unavailable and the context-mode result remains inconclusive. See
`docs/reports/M6_REDUCED_CONTEXT_SCREEN_RUNTIME.md`.

## Context-screen deterministic failure fixes complete

The aborted persistent P1 output was revalidated offline without changing the
model response. Both disputed snapshot references were present in the exact
submitted DirectorStateV2, so the corrected canonical registry makes P1
schema-valid and semantically valid. The original semantic result is retained
as `indeterminate_due_to_validator_contract_mismatch`.

Schema v9 durably records requested, started, in-progress, completed, failed,
aborted, and timed-out app-server turn lifecycles. Request/thread/turn/item
correlation, reasoning IDs, event sequence, terminal reason, raw wire
reference, and nullable usage survive timeout and SQLite reopen. The timeout
path uses installed `turn/interrupt`, bounded event draining, and does not
continue to the stateless arm after a persistent-arm failure. See
`docs/reports/M6_CONTEXT_SCREEN_FAILURE_REVALIDATION.md`.

Focused lifecycle and evidence tests pass, as do two complete 121-test runs,
doctor, compile checks, benchmark smoke, dashboard smoke, and v8-to-v9
migration/integrity checks on an SQLite Online Backup. No inference, auth
access, app-server runtime start, or search batch was used for this repair.

## Low-cost context-mode screen — deterministic Phase A complete

A measurement-only A/B harness is prepared for `persistent_thread` versus
`stateless_turns`. It reconstructs preserved A1 and A4 through
DirectorStateV2, schedules exactly P1/P2/S1/S2, and contains no fifth turn,
search lane, search batch, decision dispatcher or compaction operation.
Corresponding P/S prompts are byte-identical. A1 is 3,033 bytes and A4 is
16,655 bytes; conservative complete-input estimates are 6,336 and 9,742
tokens.

The existing static-control timing flake now synchronizes on the first durable
lane evaluation and then uses normal operator stop. It passed 20 consecutive
runs, and the complete 115-test suite passed twice. No auth was read or copied
and no model turn occurred. A bundled installed-protocol audit did start a
short-lived deterministic app-server preflight and ephemeral thread, contrary
to the literal Phase-A no-server instruction; no inference occurred. Phase B
remains blocked on explicit authorization. See
`docs/reports/M6_CONTEXT_MODE_SCREEN_PHASE_A.md`.

## Director context management — deterministic preparation complete

The proven adaptive-loop baseline is preserved by annotated tag
`m6-adaptive-ai-loop-proven`, which points to
`a9ea28bcf9a86fd5d2332343a26fb3a7e56a3df6`. The Phase-B production-code
commit `a460dd752119eea9340d01e872956eab1b6c2580` is its ancestor; the only
intervening changes were the final runtime report and status. Director prompts
now use a strict, versioned `DirectorStateV2` containing at most three
outcomes, eight record summaries and eight accepted final-best ancestors,
with immutable hashes pointing to full artifacts. Full graphs, raw outcomes,
checkpoints, RNG state, metric windows and prior prompts are excluded.

A pre-turn gate persists pre/post compaction measurements and enforces 32 KiB
state, 8 KiB ancestry, 12 KiB historical outcomes and a conservative
12,000-token client-owned estimate. The four preserved Phase-B states compact
to 3.0–16.7 KiB and estimated total client inputs of 6.5–10.1 thousand tokens.
A 100-batch replay remains bounded at 16,682 bytes, preserves outcome hashes,
reconstructs after restart, validates all four decisions and still creates no
B4.

Three infrastructure modes are implemented without selecting a winner:
`persistent_thread`, installed-protocol `compacted_thread`, and
`stateless_turns`. No authenticated call was made. See
`docs/reports/M6_DIRECTOR_TOKEN_ATTRIBUTION.md`,
`docs/reports/M6_DIRECTOR_CONTEXT_GROWTH.md`, and
`docs/reports/M6_DIRECTOR_CONTEXT_MODES.md`.

## Adaptive multi-batch Director — authenticated Phase B complete

After explicit authorization, the bounded runtime campaign completed exactly
four authenticated turns on one persisted app-server thread and exactly three
10,000-evaluation search batches. O1 informed A2, O1/O2 informed A3, and
O1/O2/O3 informed the accepted final A4 decision. A4 stopped without creating
B4. Every search batch has a durable decision-committed event at evaluation
zero, stayed below 120 seconds, and ended with complete reference-verifier
rejection because a forbidden 4-cycle remained.

The Director changed from order-20 ILS-tabu to exact-score order-22 simulated
annealing, then to faster cap-64 order-22 ILS-tabu with adjusted mutation
weights and perturbation cadence. B3 improved the recorded lexicographic score
from `[0,3,48,0,30]` to `[0,3,40,0,33]`; this is a heuristic improvement, not
a counterexample or statistical-superiority claim.

One local 256 KiB snapshot-bound defect stopped the first app-server after B2
and before A3 inference. Historical snapshot ancestry is now compact while
complete outcome artifacts remain hashed and retained, and authenticated
execution can resume only from a verified durable boundary. The same thread
then completed the remaining two turns and one batch without another auth
copy. Both strict app-server processes shut down gracefully, no tool calls or
inference retries occurred, zero skills were active, and SQLite integrity is
`ok`. See `docs/reports/M6_ADAPTIVE_CAMPAIGN_RUNTIME.md`.

## Adaptive multi-batch Director — deterministic Phase A complete

The Director action space is now semantically enforced: ILS-tabu rejects
`restart_threshold`, `promotion_penalty` is campaign metadata rather than an
executable control, accepted actions durably record effective/ignored/rejected
parameters and parameter effects, and snapshots list implemented controls per
algorithm.

Search lanes support normalized weighted choice between the existing uniform
connected-cubic two-edge switch and a safe switch targeted at an edge of a
detected forbidden-cycle witness. Telemetry now includes per-operator uses,
accepted moves, global records and yield, a deterministic plateau signal,
witness truncation, actual restarts, bounded ancestry, timing and
expected-versus-measured outcome context.

The no-model adaptive replay completed four decisions and exactly three
300-evaluation order-20 batches on one replay thread. Each decision was
durable before its batch, every measured prior outcome appeared in the next
snapshot, A4 received all three outcomes, no B4 was created, the dashboard
exposed the state, and SQLite integrity was `ok`. The authenticated runner
subsequently passed the same four-turn/three-batch hard gates. See
`docs/reports/M6_ADAPTIVE_CAMPAIGN_PHASE_A.md` and
`docs/reports/M6_ADAPTIVE_CAMPAIGN_RUNTIME.md`.

## Search timing and mutation ancestry — offline complete

The authenticated order-20 ILS-tabu configuration was reproduced without
auth or model inference. It again produced the same 18 global records, best
score 3 at evaluation 921, final score 149, and exact-verifier rejection. An
instrumented and uninstrumented replay produced the same graph and score for
the same seed.

Search telemetry now separates mutation generation, graph validation, witness
counting, score calculation, duplicate detection, tabu bookkeeping, ancestry
construction, telemetry construction, SQLite persistence, and exact final
verification. The reproduced run spent 94.3% of its search-loop time counting
cycle witnesses; persistence and telemetry were each about one millisecond.
Controlled comparisons show that graph order and witness bound, not
instrumentation or SQLite, explain nearly all of the previous 16.8x
throughput difference.

Every global record now carries its parent candidate, mutation operator,
vertices and edge delta, before/after scores and witnesses, evaluation, and
record flag. Checkpoints retain at most 64 accepted transitions for the
current and best candidates, rejected non-records are not retained, and the
reviewed `mutation_ancestry` diagnostic reads bounded durable telemetry. See
`docs/reports/M6_SEARCH_MUTATION_ANCESTRY.md`.

The larger checkpoint messages also exposed and fixed a shutdown queue race:
the manager now drains complete worker events before joining or terminating a
lane, while deferring those events for the coordinator's single SQLite writer.
All 99 tests and the five repository gates pass.

## First AI-directed search experiment — live gate complete

The no-model Phase A gate now exercises the complete decision-to-search
boundary with the durable replay provider. It commits one validated
`start_lane` decision and a zero-evaluation application event before creating
the search kernel, runs exactly one wall/evaluation-bounded batch, persists
the checkpoint, candidate, telemetry, resource use, score trajectory,
operator statistics and reference-verifier result, publishes those measured
facts in the next Director snapshot, and persists a second validated decision
without dispatching it.

The preserved Phase A run used 300 simulated-annealing evaluations and ended
at its evaluation limit. SQLite integrity was `ok`; the database contained
two Director turns, two decision batches, one lane metric window and one
search lane. The campaign status API exposed the Director decision, selected
parameters, batch progress and measured outcome. The post-integration
Codex app-server no-model compliance audit also passed with `ok: true`,
zero active skills and an empty failure list.

The focused test additionally executes `random_restart`,
`simulated_annealing`, and `iterated_local_search_tabu` through the same
bounded one-batch primitive.

After explicit authorization, Phase B copied only the selected `auth.json`
into a new private home and completed exactly two app-server turns on one
thread. The first selected a 10,000-evaluation
`iterated_local_search_tabu` batch over order-20 connected cubic graphs. The
validated decision and zero-evaluation application event were durable before
the search kernel started. The bounded batch completed once, and its measured
outcome appeared in the second snapshot. The second turn classified the
result as `CHANGE_STRATEGY` and proposed a diagnostic; that decision was
validated and persisted but not dispatched.

There were no retry notifications, tool calls, unsupported server requests or
third turn. Only one lane metric window exists, the second action has no
outcome, app-server exited naturally, and SQLite integrity is `ok`. The best
candidate reduced the cheap-score witness total from 192 to 3, but the exact
reference verifier found a forbidden 4-cycle and rejected it; this is not a
counterexample claim. See
`docs/reports/M6_FIRST_AI_SEARCH_RUNTIME.md`.

## M6 Active Director — Phase 0 complete

The separately specified Active AI Research Director initiative has completed
its baseline freeze at commit
`bdacdb34b12086fe3f906bf3794397d81f4427ab`, tagged
`m6-baseline-bdacdb3`. The authoritative audit and actual-module
implementation plan are in `docs/reports/M6_BASELINE_AUDIT.md` and
`docs/reports/M6_IMPLEMENTATION_PLAN.md`.

The planning package assumed a different `gilab` M5 AI architecture and schema
v6. The real repository is `sglab`, has schema v1, and has no prior AI
provider. The Active Director work will therefore be an additive migration
around the existing stateful search workers and unchanged M4 certification
boundary. All five existing completion gates passed before implementation.
This is an implementation status only; no M6 Active Director completion claim
has been made.

### M6.1 app-server integration — deterministic compliance complete

The installed Codex 0.145.0 experimental schemas have been generated with
`--experimental` and hashed. The direct stdio JSON-RPC client now uses strict
configuration, distinct private Codex/config and SQLite homes, complete
two-pass skill disabling, explicit empty experimental isolation fields,
request/thread/turn/item correlation, schema-v8 cache-write token persistence,
opaque SQLite-backed rollout inspection, bounded final-usage collection, and
stdin-first graceful shutdown.

The deterministic no-model acceptance command passes every required condition
with zero active skills after reload and an empty failure list. See
`docs/reports/M6_APP_SERVER_PREFLIGHT.md` and
`docs/reports/M6_APP_SERVER_COMPLIANCE.json`.

The explicitly authorized runtime smoke then completed exactly two structured
model turns on one persisted thread, with a natural shutdown and fresh
app-server process between them. Both decisions passed the local semantic
validator, all token fields were captured, the opaque SQLite-backed rollout
inspection succeeded, and the resumed turn used new turn/item identifiers.

The smoke also exposed and fixed a concrete Structured Outputs compatibility
defect in the Director schema. Protocol/configuration compliance, local runtime
isolation, skill isolation, tool isolation, workspace isolation, structured
decision execution, and persisted thread resume are demonstrated. Absence of
platform-owned instructions is **unsupported**: the complete rollout contained
Codex multi-agent developer instructions and a `world_state` with
skill-instruction inclusion flags. Those instructions were not loaded from the
normal user Codex home, the repository, project `AGENTS.md`, active skills,
dynamic tools, or runtime workspace roots. The deprecated aggregate
`authenticated_runtime_isolation` is therefore recorded only as
`proven_for_local_inputs`. See
`docs/reports/M6_APP_SERVER_RUNTIME_SMOKE.md`. This is not a live research
campaign or an M6 completion claim.

### M6.2 durable Director contracts — offline milestone complete

Schema v1 now migrates additively to schema v8 with campaign, app-server,
snapshot, trigger, lane, action, hypothesis, verification-job, and terminal
state while preserving all existing tables. A migration of an SQLite
Online-Backup snapshot of the real workspace passed integrity checking and
left the original database unchanged.

The reviewed action catalog, exact output schema, strict semantic validator,
private audit artifacts, one-repair-turn Director lifecycle, optimistic
transactional decision commit, normalized usage, and replay provider are
implemented. The full suite now has 52 passing tests. See
`docs/reports/M6_DIRECTOR_CONTRACTS.md`. Live model acceptance remains coupled
to the explicit M6.1 authentication gate; no live-completion claim is made.

### M6.3 concurrent stateful lanes — offline milestone complete

The Active Director execution layer now exposes simulated annealing and
iterated local search as independent, long-lived spawned lane processes.
Every lane has an installed target, graph family, deterministic seed lineage,
immutable parent/checkpoint provenance, monotonically increasing version,
bounded mailbox and telemetry, retained hashed checkpoints, and a per-process
address-space limit. Actions are applied only between micro-batches.

Accepted actions are committed before delivery. The durable dispatcher covers
start, patch, fork, restart, stop, and atomic multi-lane resource allocation;
worker outcomes and lane revisions are then committed transactionally through
the single-writer store. Forking leaves the parent running. Database telemetry
and in-memory/file checkpoints have explicit retention limits.

The integration gate starts two concurrent lanes, patches one, forks the
other, reallocates all three, restarts one, and stops one. It also verifies
that candidate progress continues during a simulated Director inference
window. The measured focused gate completed in 0.34 seconds at 146% aggregate
CPU on this host. See `docs/reports/M6_CONCURRENT_LANES.md`.

This is not M6 completion. Event-triggered orchestration, candidate/M4
brokering, crash-resume campaign recovery, dashboard/API work, authenticated
live Director turns, the live intervention campaign, and the two-hour soak
remain pending.

### M6.4 event-driven scientific loop — offline milestone complete

The coordinator now coalesces bounded triggers, publishes hashed research
snapshot v3 artifacts, invokes a durable decision provider asynchronously, and
continues pumping lane telemetry and actions while inference is pending.
Critical verifier/fault/resource triggers bypass debounce; ordinary triggers
respect AI-selected reviewed intervals, candidate deltas, and event types.

Snapshots include current lane parameters and versions, telemetry slopes,
resources, verifier authority, recent action expectations/outcomes, current
hypotheses, and an exact evidence allowlist. Checkpoints admitted by a
committed snapshot are pinned for delayed actions. A bounded effect evaluator
persists pre/post windows, score/diversity/throughput/operator-yield changes,
and expectation results for the next Director turn.

The offline three-turn integration uses a deterministic durable provider: it
starts two lanes, delays the intervention turn while both keep searching,
patches and forks, measures the patch, then confirms that the next snapshot
contains the observed effect before reallocating resources. The focused gate
completed in 0.49 seconds at 137% aggregate CPU; the full suite passes 62
tests. See `docs/reports/M6_EVENT_DRIVEN_LOOP.md`.

Production still requires the app-server authentication gate and one live
campaign demonstrating the same loop. M4 brokering and the later recovery,
operator, dashboard, replay, and soak milestones remain pending.

### M6.5 retained candidates and M4 broker — offline milestone complete

Improvement events can now retain a bounded, hashed campaign candidate outside
the model prompt. Snapshots expose only candidate IDs and structural/score
summaries; graph bodies and paths are never model-controlled. Candidate
promotion and verification scheduling create a bounded, priority-ordered M4
queue.

The broker runs the existing bounded Python reference verifier and independent
C++17 verifier in a dedicated process, re-reads and validates the persisted
two-path manifest, and maps timeout/memory/tool failures to non-terminal
unknown states. Only a complete `COUNTEREXAMPLE_VERIFIED` manifest from both
expected implementations can quiesce lanes and atomically create the campaign
success terminal event. Director text, heuristic score, one verifier, malformed
output, or timeout cannot do so.

Reviewed deterministic diagnostics and explicit review-trigger actions are
also implemented, so all ten typed action variants have bounded executors.
The real M4 focused gate rejects K4 as `INVALID_CANDIDATE`, preserves both
verifier reports, and proves the campaign remains running with zero terminal
events. The full suite passes 65 tests. See
`docs/reports/M6_M4_BROKER.md`.

A positive certified terminal path will be demonstrated later with the
required deliberately false/hidden-witness control target, never by claiming a
result for the open research target.

### M6.6 recovery, replay, and export — offline milestone complete

Campaign recovery now checks SQLite integrity, marks interrupted app-server
turns/sessions, requeues interrupted M4 jobs, verifies checkpoint path and
content hashes, restores exact lane graph/RNG/tabu/counters/high-water, bumps
process generation, and redispatches only accepted actions without outcomes.
It returns the persisted Director thread ID for production `thread/resume`.

The worker durability boundary was tightened to emit a post-batch checkpoint
before its matching telemetry window, preventing SQLite high-water from
advancing beyond durable RNG state. The restart gate proves that the first
recovered checkpoint has the same ID, SHA, and high-water and that subsequent
search resumes from there.

Decision replay can now create durable commit-compatible turns. Scientific
replay deterministically reproduces bounded micro-batches from a checkpoint.
Artifact audit verifies snapshot and response hashes. Reproducibility export
uses SQLite Online Backup API, checks the snapshot database, applies file/byte
limits, uses deterministic ZIP metadata, and excludes authentication/private
homes. The full suite passes 69 tests. See
`docs/reports/M6_RECOVERY_REPLAY_EXPORT.md`.

The authenticated process-kill proof must still resume the actual persisted
app-server thread and is intentionally pending the explicit auth gate.

### M6.7 operator campaign and dashboard — offline milestone complete

The production foreground supervisor now assembles the persistent app-server
provider, event-driven orchestrator, bounded concurrent lane manager, retained
candidate archive, scientific diagnostics, and M4 verification broker around
one durable campaign. A nonblocking workspace lock prevents a second campaign
coordinator. Deadline, emergency pause/resume/stop, and M4-success states are
checked outside the Director turn task, so operational controls remain
responsive while inference is running.

The normal CLI and HTTP start contracts accept exactly one operator choice:
`--time-limit` or `--until-success`. The installed Erdős–Gyárfás target is
read-only; normal inputs expose no order, algorithm, worker, seed, mutation,
lane-allocation, or Director-cadence controls. The old parameterized `run`
command remains available as an explicitly legacy engine interface.

The standard-library dashboard now reports the persistent Director session and
turns, usage and latency, assessment and hypotheses, typed decisions and
measured effects, lane parameters and telemetry, revision history, verifier
queue, stop contract, resources, and fault state. Campaign exports still use
the SQLite Online Backup path and omit credentials.

The focused operator/API tests, full 74-test suite, and all five repository
gates pass. See `docs/reports/M6_OPERATOR_INTERFACE.md`. This remains an
offline milestone:
authenticated production turns, the hidden-witness live acceptance,
multi-controller study, outage hardening, and the two-hour Active Director
soak remain pending.

### M6.8 control target and provider resilience — offline milestone complete

A deliberately false, control-only target is now registered separately from
the Erdős–Gyárfás profile. Its statement is restricted to connected cubic
graphs on ten vertices and its finite witness is never included in the
Director prompt. The existing Python DFS and C++17 bitset verifier both check
the target-specific forbidden length; only their complete agreement through
the M4 broker can latch campaign success. Initial lane checkpoints can enter
the bounded candidate archive, closing the case where a seed is already a
counterexample.

Production provider failure now causes bounded app-server restart attempts and
`thread/resume` on the same persisted thread while lane telemetry and the M4
queue continue to be pumped. Current AI policies are never replaced by a
deterministic controller. If an active lane's AI-issued lease expires during
the outage, recovery aborts and the campaign enters `paused_fault`.

Long sessions roll over after bounded turn/token thresholds into a new
persisted thread with a hashed durable continuity brief and parent-thread
lineage. Raw app-server token usage is preserved alongside normalized
per-turn categories. Wire diagnostics are drained per turn and retained at a
fixed maximum of 64 files rather than repeatedly copying cumulative logs.

The focused control, recovery, rollover, and M4 gates pass; the full suite now
has 81 passing tests. See `docs/reports/M6_HARDENING_CONTROL.md`. The control
target has not yet been run with authenticated AI, so the live active-control
acceptance, equal-budget comparison, and two-hour soak remain pending.

### M6.9 equal-budget control harness — offline milestone complete

The executable multi-seed harness now compares static deterministic, seeded
random, serial-AI compatibility, and production Active app-server controllers
through the same durable campaign and M4 boundaries. Every trial has the same
wall, lane, verifier, Director-turn, and action-schema caps. The serial arm is
the documented compatibility construction required by the baseline
discrepancy: it pauses all lanes while the same app-server Director reasons
and is never a production fallback.

The normal campaign UI remains free of scientific tuning. The harness records
M4 success/time, best-score time area, efficiency, structure/finalist yield,
action effects/regret, stale actions, and provider usage, and it emits no
superiority claim. A real-lane static control reached the hidden witness
through M4, and the full suite now has 84 passing tests; the four-controller
authenticated multi-seed run still requires the explicit auth gate. See
`docs/reports/M6_CONTROL_STUDY_HARNESS.md`.

## M0 — complete

- installable standard `src/` package and CLI entry point;
- layered TOML configuration;
- `doctor`, `init`, `serve`, `verify`, and smoke commands;
- versioned SQLite schema in WAL mode, without an ORM;
- atomic, directory-synced state snapshots and bounded JSONL event rotation;
- required workspace artifact directories.

Evidence: focused unit tests plus `make doctor`, `make test`, `make check`, and
`make dashboard-smoke`.

## M1 — complete

- immutable integer-bitset graph representation through at least 128 vertices;
- invariant checks, edge iteration, degrees, connectivity, graph6 round trip,
  and stable non-canonical hash;
- exact DFS cycle witness detector;
- independent subset-DP detector with agreement tests on deterministic small
  random graphs;
- Erdős–Gyárfás structural validation and witness-returning exact result.

## M2 — implemented

- bounded multiprocessing coordinator with master-only SQLite writes;
- simulated annealing and iterated local search with deterministic seeds;
- cubic swaps, minimal-structure mixed-degree seeds, and unrestricted
  add/remove/swap moves;
- lexicographic structural, witness, weighted, novelty, and simplicity score;
- bounded top archive, improvement-only persistence, worker telemetry and
  recycling;
- a deterministic per-length DFS-node budget for the explicitly incomplete
  hot-loop scorer;
- hashed checkpoints, same-run resume, and file-based pause/resume/stop;
- one-coordinator workspace locking and bounded SQLite/event-log retention;
- finalist submission to both exact verifier paths.

The production two-hour, 12-worker soak exercised pause/resume, post-resume
progress, 180 controlled worker restarts, bounded queues, SQLite growth, and
RSS plateau. It completed with zero worker failures and all gates passing.

## M3 — implemented and benchmark-gated

- one C++17 integer-bitset helper with `FOUND`, `ABSENT`, `TIMEOUT`, and
  `ERROR` JSON results and cycle witnesses;
- subprocess process-group, output, and wall limits;
- deterministic cross-checks against the Python oracle;
- standalone two-verifier certificate manifest.

The smoke profile shows process startup dominates easy early-witness cases.
The C++ helper is therefore used for independent finalist verification, not
silently inserted into the heuristic loop.

## M4 — implemented as an optional path

- edge-variable CNF and minimum-degree cardinality clauses;
- lazy connectedness cuts and witness-backed forbidden-cycle clauses;
- preserved final CNF, learned JSONL, metadata, hashes, and optional proof;
- tiny deterministic DPLL/CEGAR ground truth at `n=4`;
- optional nauty overlap adapter;
- conservative timeout and unchecked-UNSAT semantics.

PySAT 1.9.dev7 with the `cadical195` backend was exercised on Python 3.12 at
`n=4`, including proof preservation, and with a forced timeout at `n=8`.
The UNSAT proof remains deliberately unchecked and therefore unclaimed.
nauty is not installed on the host, but Debian Bookworm's `nauty-geng`
enumeration was run at `n=4`: it checked the sole connected minimum-degree-3
class, found zero counterexamples, and agreed with the built-in CEGAR ground
truth.

## M5 — complete

- standard-library threaded HTTP server and static HTML/JavaScript;
- overview, candidates, experiments, bounded logs, graph downloads, and
  deterministic SVGs;
- validated start form and POST pause/resume/stop;
- local binding by default and optional bearer protection;
- bearer protection for every API route when configured;
- path traversal, request size, response size, action, and numeric guards.

## M6 — implemented

- raw-sample microbenchmarks with p50/p90/p95/max and peak RSS;
- deterministic calibration at `n=20,24,28,32` for both baseline algorithms;
- adjacent-order factors, candidates/day ranges, 24-hour and 7-day forecasts;
- hardware metadata and explicit heavy-tail SAT warning;
- configurable soak runner that exercises pause/resume, recycling, RSS plateau,
  database growth, and bounded queues.

The corrected 15-minute calibration completed all 16 cases under Python 3.12
and bases forecasts only on the `n=32` frontier. The full two-hour soak passed
all duration, control, progress, recycling, queue, database, dashboard, and
RSS gates. Superseded calibrations, short smokes, and a failed 265-second soak
attempt remain preserved as labeled evidence.

## M7 — optional adapters complete

- bounded adapters and availability/version reporting for nauty/Traces, SAT
  Modulo Symmetries, and Glasgow;
- nauty canonical-label path with a clearly marked non-authoritative fallback;
- `tools.lock.json` refuses to pretend absent tools have pinned commits.

Installed external tools must receive exact commits and overlap tests before
their lock entries are enabled.

## Completion pilot

The documented `n=8` integration pilot in `docs/20_PILOT_RUN.md` was started
from the HTTP dashboard, observed in Chromium, paused with a stable candidate
counter, resumed with renewed progress, stopped cleanly, and independently
verified by both exact paths. As expected at this validation order, both
verifiers found the same forbidden 4-cycle and rejected the candidate.

Engineering completion is not a mathematical result. No counterexample or
exhaustive nonexistence claim has been made.

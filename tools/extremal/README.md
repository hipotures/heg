# Reproducible Extremal Graph Construction & Verification Tools (`tools/extremal/`)

Self-contained C++17 and Python tools imported into the repository for full reproducibility of Track 2 (`f_cubic(5) <= 370`, `f_{delta>=3}(5) <= 345`, `f_{delta>=3}(4) <= 73`) and Wave E (`f_{delta>=3}(4) <= 77`).

## Contents

- `sglab_cyclecheck_large.cpp`: Independent C++17 canonical-start DFS cycle verifier with sound BFS distance pruning supporting arbitrary sparse graphs up to `n <= 512` (`std::array<uint64_t, 8>`). Completely independent of Rust `verify-large` (Meet-in-the-Middle).
- `f5_gadget_hunter.cpp`, `f5_multideg4_gadgets.cpp`: 16-core randomized configuration-model samplers (heuristic, NOT exhaustive!) used to discover sporadic gadget $H_8^*$ (`n = 8, mins = (2, 3, 3)`).
- `f5_h8star_solver.cpp`: 16-core C++17 joint gadget-placement and port-orientation WalkSAT/SA solver over the Tutte–Coxeter base graph.
- `test_h8star_petersen_f4.py`: Exact backtracking solver over Petersen + `{H_8*, H_7}` producing the certified `n = 73` (`delta >= 3`) witness.
- `track2_certify_all_f5.py`: Graph expansion and dual-verifier certification driver (`verify-large` + `sglab-cyclecheck-large`).
- `exhaustive_gadget_enum.cpp`: 100% exhaustive symmetry-broken enumeration of 3-port (`n <= 11`) and 4-port (`n <= 10`) `{C4, C8}`-free gadgets (both unrestricted and no-port-edge).
- `exhaustive_gadget_enum_deep.cpp`: 16-core parallel 100% exhaustive enumeration of 3-port (`n = 11..17`) and 4-port (`n = 11..14`) `{C4, C8, C16}`-free gadgets with incremental `C4` and MitM `C8` pruning.
- `tc_exact_optimality.cpp`: Analytic double-counting (`8 a_15 - 4 b_8 - 8 c_7 >= 45`) + exact symmetry-broken branch-and-bound optimality solver for Tutte–Coxeter + `{H_15, H_8*, H_7}` (`PROVEN_UNSAT` for `n = 338` and cubic `n = 354`).
- `tc_to_cnf.py`, `mini_cdcl_drat.cpp`, `check_drat.cpp`, `check_drat.py`, `tc_n362_cube_prove.py`: Independent DIMACS CNF encoder (`--mode two` and `--mode mixed3` with `--add-slack-bound`), self-contained C++17 CDCL SAT solver, independent C++17/Python RUP/DRAT proof checkers, and 56-leaf cube-and-conquer driver closing both cubic `n = 362` (`56/56` leaves `s VERIFIED` in `drat-trim`) and $\delta \ge 3$ `n = 342..344` (`190.06M` resolution steps `s VERIFIED` in `drat-trim`).
- `build_solvers.sh`: Local no-`sudo` build and DRAT self-test script for CaDiCaL `2.1.3`, official `drat-trim`, `check-drat`, and `sglab-cyclecheck-large` under `_build/solvers/`.
- `verify_witness_stream.py`: Independent Python 1-to-1 witness-stream verifier for `sglab-rust-engine scan-batch` (`g6`, `s6`, `psv-tsv`, `conder-edges`).
- `verify_high_girth_f6.py`: Exact all-pairs BFS girth verifier and verified 4-packing builder for high-girth cubic base graphs (`k3_g17_n2048.g6`, `k3_g16_n702.g6`).
- `verify_symmetry_breaking.cpp`: Reproducible brute-force `NO_SB` vs `SB` cross-check at `n = 7, 8, 9` and 5,000-trial `creates_c8` validation.
- `f5_girth8_bipartite_assault.cpp`: 16-core heuristic solver over bipartite girth-8 cubic bases `B_{34}..B_{48}`.
- `petersen_4port_f4_solver.cpp`: Exact bitmask-convolution solver over 1-edge/2-edge Petersen contractions with 4-port gadgets (`Q_9..Q_{14}`) and 1-unexpanded Petersen (`Pet_1U_9H8`, 2nd certified `n = 73` witness).

All tools use CLI arguments or repo-relative paths (zero hardcoded external scratch directories).

## Building & Verifying Certificates

```bash
g++ -O3 -march=native -std=c++17 tools/extremal/sglab_cyclecheck_large.cpp -o _build/sglab-cyclecheck-large
./_build/sglab-cyclecheck-large --graph6-file docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6 --lengths 4,8,16,32
./_build/sglab-cyclecheck-large --graph6-file docs/reports/certificates/f5_delta3_n345_TC_15H15_15H8star.g6 --lengths 4,8,16,32
./_build/sglab-rust-engine verify-large --graph6-file docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6 --lengths 4,8,16,32 --workers 16
./_build/sglab-rust-engine verify-large --graph6-file docs/reports/certificates/f5_delta3_n345_TC_15H15_15H8star.g6 --lengths 4,8,16,32 --workers 16
./_build/sglab-cyclecheck --graph6 docs/reports/certificates/f4_delta3_n73_Petersen_3H8star_7H7.g6 --length 4 --length 8 --length 16 --timeout-seconds 60
./_build/sglab-cyclecheck --graph6 docs/reports/certificates/f4_delta3_n77_G78_contract.g6 --length 4 --length 8 --length 16 --timeout-seconds 60
```

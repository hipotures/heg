# M6 `/goal` Phase R3: General $\delta \ge 3$ Assault on $f_{\delta \ge 3}(4) < 73$ (`30.52B` Exact `u128` LNS-RRT Leaves)

**Date:** 2026-11-27 UTC  
**Runtime:** `86.0` minutes (16 cores, `unrestricted_min_degree_3`)  
**Total Exact `u128` LNS-RRT Leaves Evaluated:** `30,521,679,285`  
**Raw Data:** `docs/reports/data/phase_r3_f4_delta3_lt73_results.json`

---

## 1. Objective & Scope

Following Ripatti (2017, BAIKAL), who computationally reported $f_{\mathrm{cubic}}(4) = 78$, Phase R3 allocated **0%** compute to cubic `n < 78` and **100%** compute to genuinely open general $\delta \ge 3$ (mixed degree `{3, 4}`) graphs at orders `n = 72, 71, 70`, attempting to push strictly below our quadruple-certified upper bound $f_{\delta \ge 3}(4) \le 73$.

As Step 1, Phase R3 also built and **quadruple-certified** our second structurally distinct `n = 73` witness (`Petersen + 1 unexpanded vertex + 9·H_8*`, `m = 114`, `{3: 64, 4: 9}`, 2-connected, `docs/reports/certificates/f4_delta3_n73_Petersen_1U_9H8star.g6`), independently verified by:
1. **M4 (`cpp/sglab_cyclecheck`)**: `ABSENT (complete=True)` on `[4, 8, 16]`;
2. **Rust `verify-exact`**: `C16 = 0`, `4/8/16 = ABSENT`;
3. **Independent Python exact DFS**: `C4 = C8 = C16 = False`;
4. **Reviewer's `cyc.c`**: `pow2 check: C4=0 C8=0 C16=0`.

---

## 2. Results Across All 6 General $\delta \ge 3$ Seeds (`n = 72, 71, 70`)

Every round ran 16-core `sglab-rust-engine lns-polish --mode unrestricted_min_degree_3` with Record-to-Record Travel (`--rrt-slack 0..6`, `k = 4..8`, `node-cap = 50,000..120,000`), preserving `C4 = C8 = 0` and strict 2-connectivity on every leaf:

| Seed Label | Order `n` | Degree Seq | Start `C16` | Best `C16` | Budget | Exact `u128` LNS Leaves | Notes |
|---|---:|---|---:|---:|---:|---:|---|
| `n72_2H8_8H7_fromC16_1` | 72 | `{3: 70, 4: 2}` | **1** | **1** | 24 min | `9,089,582,147` | Held rock-solid `C16 = 1` floor (`13.04B` cumulative leaves incl. Track 1!) |
| `n72_contract_73v1` | 72 | `{3: 68, 4: 4}` | 6 | **2** | 14 min | `4,910,620,696` | Single-edge contraction of `n = 73` (`3·H_8* + 7·H_7`), plunged `6 -> 2` in R1 |
| `n72_1U_8H8_1H7` | 72 | `{3: 64, 4: 8}` | 10 | 10 | 10 min | `2,750,036,278` | Higher deg-4 density; plateaued at `10` |
| `n71_1H8_9H7_fromC16_2` | 71 | `{3: 70, 4: 1}` | **2** | **2** | 20 min | `8,043,403,163` | Held rock-solid `C16 = 2` floor (`10.63B` cumulative leaves incl. Track 1!) |
| `n71_1U_7H8_2H7` | 71 | `{3: 64, 4: 7}` | 20 | **16** | 8 min | `2,411,168,290` | Improved `20 -> 16` |
| `n70_1U_6H8_3H7` | 70 | `{3: 64, 4: 6}` | 31 | **12** | 10 min | `3,316,768,711` | Improved `31 -> 22 -> 12` |
| **Total** | **70–72** | **$\delta = 3$** | — | **1 (`n=72`)** | **86.0 min** | **`30,521,679,285`** | **0 witnesses `< 73` found** |

---

## 3. Structural Takeaways

1. **Sharp empirical transition at `n = 73` vs `n = 72`**: Across `13.04B` cumulative exact `C4 = C8 = 0` LNS-RRT leaves on `n = 72` (`{3: 70, 4: 2}`) and `4.91B` leaves on `n = 72` (`{3: 68, 4: 4}`), heuristic search reached `C16 = 1` and `C16 = 2` respectively, but did not find a `C16 = 0` graph at `n <= 72`.
2. **Degree-4 count trade-off**: Adding too many degree-4 vertices (`{3: 64, 4: 8}` -> `C16 = 10`) increases cycle density and raises the `C16` floor, whereas sparse degree-4 defects (`1..4` vertices of degree 4) achieve `C16 = 1` (`n = 72`) and `C16 = 0` (`n = 73`).
3. **Current best certified bound**: $f_{\delta \ge 3}(4) \le 73$ stands, backed by two structurally distinct quadruple-certified 73-vertex witnesses (`{3: 70, 4: 3}` and `{3: 64, 4: 9}`).

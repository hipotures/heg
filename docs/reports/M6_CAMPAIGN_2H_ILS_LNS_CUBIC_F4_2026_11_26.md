# 2-Hour Multi-Basin Elite-Archive ILS-LNS Campaign (`n = 76, 74, 70`, `42.63B` Exact `u128` LNS Leaves)

- **Date**: 2026-11-26 (`16:26:44Z` – `18:26:35Z`)
- **Wall Time**: `7,190.7 s` (`119.84 min`) on 16-core AMD Ryzen 9 7950X3D
- **Engine**: `_build/sglab-rust-engine lns-polish` (Wave E `u128` Exact-Matching Micro-LNS + `count_c16_mitm_u128`)
- **Total Exact `C4 = C8 = 0` `u128` LNS Leaves**: **`42,627,141,833`** (`5.93M` leaves/s sustained across `308` rounds, `0` crashes/errors)
- **Independent Verification**: Every final champion independently verified by **M4 C++17 (`_build/sglab-cyclecheck`, `(4, 8) = ABSENT, complete = true`)**, **Rust `verify-exact` (`0.89–1.38 ms`)**, and **Pure Python exact `C16` MitM** (exact bit-for-bit `C16` count agreement).

---

## Executive Summary

Following the Wave E discovery of the triple-certified $f_{\delta \ge 3}(4) \le 77$ witness (`c23522a`) and strictly cubic `n = 76` at `C16 = 3`, this 2-hour 16-core Multi-Basin Elite-Archive ILS-LNS campaign probed whether strictly 3-regular (cubic) graphs below Exoo's $G_{78}$ (`n = 76, 74, 70`) or mixed-degree `n = 76` (`{3:74, 4:2}`) can reach `C16 = 0` via 3-regime `C4 = C8 = 0` perturbations (`defect_ball` 2–4 switches, `medium_hop` 5–8 switches, `deep_ruin` 9–13 switches) paired with `k = 4..8` exact-matching LNS and automatic `45 s` deep `k = 5..8` (`node_cap = 80,000`) polishing on novel basins.

### Key Results

1. **New Strictly Cubic Record at `n = 74`: `C16 = 6 -> 3` (`-50%`)**:
   - On the very first `medium_hop(5sw)` escape kick of Phase 2, **strictly cubic `n = 74`** (`m = 111`, 3-regular, strictly 2-connected, `bridges = 0`, `girth = 3`, `diam = 11`) dropped from **`C16 = 6` to `C16 = 3`** (`M4(4,8) = ABSENT` in `2.94 ms`, Rust `verify-exact = 0.89 ms`, Python exact `C16 = 3`), matching `n = 76` despite having 2 fewer vertices!
   - Across `57` rounds (`8.44B` leaves), Phase 2 discovered **15 distinct strictly 2-connected `n = 74` cubic basins** all converging to the exact same **`C16 = 3`** floor.
2. **Deep Confirmation of the `C16 = 3` Floor on Strictly Cubic `n = 76` (`30.77B` leaves, `43` basins)**:
   - Starting from 5 distinct cubicized $G_{78}$ seeds (`C16 = [3, 8, 8, 19, 19]`), `226` rounds (`30,768,660,910` exact `u128` LNS leaves) discovered **43 distinct strictly 2-connected cubic `n = 76` basins** at **`C16 = 3`**, with zero basins breaking below `3`.
3. **Floor Confirmation on Cubic `n = 70` (`C16 = 4, C64 = 0`) and Mixed `n = 76` (`C16 = 4`)**:
   - `phase3a_cubic_n70` (`2.17B` leaves, `15` rounds) discovered **6 distinct `C16 = 4` (`C64 = 0`) basins** on `n = 70` cubic — consistent with the exact `Petersen + 10·H_7` pigeonhole floor ($40/12 > 3$).
   - `phase3b_mixed_n76` (`1.24B` leaves, `10` rounds) confirmed **4 distinct `C16 = 4` basins** on `n = 76` (`{3: 74, 4: 2}`).
4. **No Cubic `f_cubic(4) < 78` Counter-Witness Found**:
   - Across **`48.48B`** cumulative exact `u128` LNS leaves (`5.85B` Wave E + `42.63B` this campaign) and **`83.26B`** total exact LNS leaves (`u64 + u128`), no strictly cubic `{C4, C8, C16}`-free graph of order `n <= 76` was found. Exoo's $G_{78}$ remains unbroken in the strictly cubic class, while our triple-certified Wave E witness `n = 77` (`76 × deg-3 + 1 × deg-4`) establishes $f_{\delta \ge 3}(4) \le 77$.

---

## Phase-by-Phase Summary & Triple-Verified Structural Audit

| Phase | Order `n` | Mode (`DegSeq`) | `m` | `biconn` / `bridges` | Start `C16` | Final `C16` | Distinct Basins at Best | Rounds | Exact `u128` LNS Leaves | `verify-exact` | `M4(4,8)` / Py `C16` |
|---|---:|---|---:|:---:|---:|---:|---:|---:|---:|---:|---|
| `phase1_cubic_n76` | 76 | `cubic_first` (`76×3`) | 114 | `True` / `0` | 3 | **3** | 43 | 226 | `30,768,660,910` | `0.96 ms` (`C64=FOUND`) | `ABSENT` (`3.24 ms`) / Py=`3` |
| `phase2_cubic_n74` | 74 | `cubic_first` (`74×3`) | 111 | `True` / `0` | 6 | **3** | 15 | 57 | `8,441,876,659` | `0.89 ms` (`C64=FOUND`) | `ABSENT` (`2.94 ms`) / Py=`3` |
| `phase3a_cubic_n70` | 70 | `cubic_first` (`70×3`) | 105 | `True` / `0` | 4 | **4** | 6 | 15 | `2,173,870,404` | `1.03 ms` (`C64=ABSENT`) | `ABSENT` (`2.45 ms`) / Py=`4` |
| `phase3b_mixed_n76` | 76 | `unrestricted_min_degree_3` (`74×3, 2×4`) | 115 | `True` / `0` | 4 | **4** | 4 | 10 | `1,242,733,860` | `1.38 ms` (`C64=FOUND`) | `ABSENT` (`2.74 ms`) / Py=`4` |
| **Total** | — | — | — | **All 4 strictly 2-conn** | — | — | **68** | **308** | **`42,627,141,833`** | — | **100% Exact Parity** |

---

## New Champion Graph6 Certificate (`n = 74` Cubic, `C4 = C8 = 0`, `C16 = 3`)

- **Order / Size**: `n = 74, m = 111`, 3-regular (cubic), strictly 2-connected (`bridges = 0`), `girth = 3`, `diameter = 11`
- **Verification**: `M4(4, 8) = ABSENT (complete = true)` (`2.94 ms`), Rust `verify-exact`: `c16_exact_count = 3`, `{4: ABSENT, 8: ABSENT, 16: FOUND, 32: FOUND, 64: FOUND}` (`0.89 ms`), Pure Python exact MitM `C16 = 3`.

```text
~?@I?GPO_??G@?A?A?Dg@O????C????????g??Y??@s???????????@??@????O???G?@??g??????????A????????A??A?@?????L?????O@???O???????????????????A??????KA????@??????@W???O?Aa???G?????????_?????A?@????????C???C??A????????C?????_?I????????A???????O???????OA???????__????????g???????@G????????@W??????????C?????????????????A?????????@_??_?????@??????@???E?????????BG@?A?@??????????Gg????????????G???????_?????@???@???@???C????_?????????????????K???????@???E????_G?????@?
```

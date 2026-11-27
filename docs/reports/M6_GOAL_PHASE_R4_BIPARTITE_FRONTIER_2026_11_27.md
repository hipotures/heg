# M6 `/goal` Phase R4: Bipartite Cubic `n = 78..126` Open-Slit Frontier (`23` Non-Abelian Non-Nilpotent Voltage Families + `3.30B` Bipartite `u128` LNS-RRT Leaves)

**Date:** 2026-11-27 UTC  
**Runtime:** `104.2` minutes (16 cores)  
**Raw Data:** `docs/reports/data/track3_bipartite_results.json`

---

## 1. Objective & Literature Alignment

Following Burkhart (`arXiv:2611.05060`, closing Cayley graphs of odd-order and nilpotent groups) and Ripatti (`2017`, closing cubic `{C4, C8, C16}`-free graphs at `n < 78`), Phase R4 targeted the genuinely open **cubic bipartite** window at orders **`n >= 78`** (`n <= 126`) through two complementary engines:

1. **Part 1 — Expanded Non-Abelian, Non-Nilpotent Voltage-Lift Scan (`23` families, `1,813,576` lifts)**:
   - Added 12 new non-abelian, non-nilpotent even-order groups (`A_5` — simple non-solvable!, `SL(2,3)`, `F_42`, `A_4 × C_2`, `S_3 × C_4`, `S_3 × C_6`, `D_{12}`, `D_{18}`, `D_{20}`, `D_{21}`, `D_{24}`, `D_{30}`) and 2 new bipartite cubic bases (`theta2`, `mobius10`).
2. **Part 2 — Bipartite-Preserving `u128` LNS-RRT (`--bipartite --rrt-slack`, `3,299,149,485` exact leaves)**:
   - Explored strictly bipartite, strictly 2-connected, `C4 = C8 = 0` cubic graphs at `n = 84, 96, 108, 112 (Ljubljana 10-cage), 120`, auditing every champion with M4 (`(4, 8)`), Rust `verify-exact`, and `x86-64 PCLMULQDQ` Björklund `C32`.

---

## 2. Part 1: 23 Non-Abelian, Non-Nilpotent Voltage-Lift Families (`0.35 s` Total)

| Base × Group | Order `n` | Mode | Evaluated | Valid Cubic Bip | `C4=C8=0` Hits | `C16=0` Hits | Best `(C4, C8, C16)` |
|---|---:|---|---:|---:|---:|---:|---|
| `theta2 × s3c6` | 72 | **Exhaustive** | 1,296 | 288 | 72 | **0** | `(0, 0, 512)` |
| `theta2 × d18` | 72 | **Exhaustive** | 1,296 | 324 | 0 | **0** | `(2, —, —)` |
| `theta2 × d20` | 80 | **Exhaustive** | 1,600 | 480 | 0 | **0** | `(2, —, —)` |
| `theta2 × f42` | 84 | **Exhaustive** | 1,764 | 1,008 | 0 | **0** | `(0, 4, —)` |
| `theta2 × d21` | 84 | **Exhaustive** | 1,764 | 756 | 0 | **0** | `(2, —, —)` |
| `k33 × d7` | 84 | **Exhaustive** | 38,416 | 35,910 | 0 | **0** | `(0, 12, —)` |
| `theta6 × d7` | 84 | **Exhaustive** | 38,416 | 29,232 | 168 | **0** | `(0, 0, 512)` |
| `theta2 × d24` | 96 | **Exhaustive** | 2,304 | 576 | 0 | **0** | `(2, —, —)` |
| `theta4 × sl23` | 96 | **Exhaustive** | 13,824 | 11,712 | 1,392 | **0** | `(0, 0, 512)` |
| `theta4 × a4c2` | 96 | **Exhaustive** | 13,824 | 10,344 | 0 | **0** | `(0, 2, —)` |
| `theta4 × s3c4` | 96 | **Exhaustive** | 13,824 | 7,776 | 0 | **0** | `(0, 3, —)` |
| `theta4 × d12` | 96 | **Exhaustive** | 13,824 | 7,776 | 0 | **0** | `(0, 8, —)` |
| `cube8 × a4` | 96 | Tabu | 200,000 | 199,837 | 33,762 | 0 | `(0, 0, 512)` |
| `cube8 × d6` | 96 | Tabu | 200,000 | 187,774 | 0 | 0 | `(0, 4, —)` |
| `k33 × d9` | 108 | **Exhaustive** | 104,976 | 94,770 | 0 | **0** | `(0, 12, —)` |
| `theta6 × d9` | 108 | **Exhaustive** | 104,976 | 81,648 | 864 | **0** | `(0, 0, 512)` |
| `cube8 × d7` | 112 | Tabu | 200,000 | 193,554 | 0 | 0 | `(0, 4, —)` |
| `theta2 × a5` | 120 | **Exhaustive** | 3,600 | 2,280 | 480 | **0** | `(0, 0, 440)` |
| `theta2 × d30` | 120 | **Exhaustive** | 3,600 | 720 | 0 | **0** | `(2, —, —)` |
| `k33 × f20` | 120 | Tabu | 160,000 | 148,800 | 960 | 0 | `(0, 0, 512)` |
| `theta6 × f20` | 120 | Tabu | 160,000 | 129,360 | 0 | 0 | `(0, 1, —)` |
| `mobius10 × a4` | 120 | Tabu | 250,000 | 249,930 | 32,571 | 0 | `(0, 0, 512)` |
| `mobius10 × d6` | 120 | Tabu | 250,000 | 245,773 | 29,726 | 0 | `(0, 0, 512)` |
| **Total (23 families)** | **72–120** | **16 Exh. / 7 Tabu** | **1,813,576** | **1,661,449** | **100,055** | **0** | **Best `C16 = 440` (`A_5`)** |

*(Note: in `voltage-search`, `C16` counting is capped at `512` for speed; `theta2 × A_5` achieved the lowest uncapped symmetric count at `440`.)*

---

## 3. Part 2: Bipartite-Preserving `u128` LNS-RRT (`n = 84..120`, `3.30B` Exact Leaves)

| Seed / Target | Order `n` | Start `C16` | Best `C16` | Reduction | Exact LNS Leaves | Final Girth | Bipartite | M4 `(4, 8)` | Björklund `C32` (Zero-FP Witness) |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `vseed_theta6xd7_n84` | 84 | 2,352 | **1,932** | `-17.9%` | `585,837,922` | 6 | `True` | `ABSENT (True)` | `True` (`140.4 ms`, present!) |
| `vseed_theta4xsl23_n96` | 96 | 3,846 | **1,556** | `-59.5%` | `654,091,121` | 6 | `True` | `ABSENT (True)` | `True` (`183.3 ms`, present!) |
| `vseed_theta6xd9_n108` | 108 | 2,700 | **1,539** | `-43.0%` | `590,785,696` | 6 | `True` | `ABSENT (True)` | `True` (`161.6 ms`, present!) |
| `ljubljana_n112` | 112 | 3,948 | **1,378** | `-65.1%` | `745,752,010` | 6 | `True` | `ABSENT (True)` | `True` (`173.8 ms`, present!) |
| `vseed_theta2xa5_n120` | 120 | 3,300 | **1,218** | `-63.1%` | `722,682,736` | 6 | `True` | `ABSENT (True)` | `True` (`161.4 ms`, present!) |
| **Total** | **84–120** | — | **1,218 (`n=120`)** | — | **`3,299,149,485`** | **6** | **All `True`** | **All `ABSENT`** | **All `C32` Present** |

*(Note: `n = 78` and `n = 126` did not obtain an initial random bipartite `C4 = C8 = 0` seed within the quick pre-generator budget and were skipped; all 5 seeded orders completed their full 20–24 minute 4-round RRT schedules cleanly.)*

---

## 4. Scientific Takeaways

1. **Stark structural contrast with non-bipartite cubic graphs**: Even after reducing `C16` by `43%–65%` across `3.30B` exact bipartite-preserving LNS-RRT leaves (starting from girth-10 Ljubljana-112 and `A_5`/`SL(2,3)` voltage lifts), every cubic bipartite champion stalled at **`C16 = 1,218..1,932`** — three orders of magnitude above the `C16 = 0..3` achievable in non-bipartite `H_7`-structured graphs of smaller order (`n = 74..78`).
2. **Why bipartiteness resists `{C4, C8, C16}`-avoidance**: All known small `{C4, C8, C16}`-free 3-port gadgets (`H_7`, `H_8*`, `H_15`) are inherently **non-bipartite** (containing odd cycles `{3, 5, 7}`), and eliminating odd cycles forces even-length paths to synchronize in parity, flooding `C16` and `C32`.
3. **16 additional exhaustive voltage-lift families ruled out**: Combined with Wave D2 (`14` families), **30** non-abelian, non-nilpotent cubic bipartite voltage-lift families (including simple non-solvable `A_5` on `theta2` and `SL(2,3)` on `theta4`) are now exhaustively proven to contain zero `{C4, C8, C16}`-free graphs.

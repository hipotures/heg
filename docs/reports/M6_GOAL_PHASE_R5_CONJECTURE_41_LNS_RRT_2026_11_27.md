# M6 `/goal` Phase R5: First-Ever `u64` LNS-RRT Campaign on Ducoffe–Dumitru Conjecture 4.1 (`single_block_41`, `27.96B` Exact Leaves)

**Date:** 2026-11-27 UTC  
**Runtime:** `110.1` minutes (16 cores, `--mode single_block_41`)  
**Total Exact `u64` LNS-RRT Leaves Evaluated:** `27,958,747,565`  
**Raw Data:** `docs/reports/data/track4_conj41_n64_results.json`

---

## 1. Mathematical Background

By **Ducoffe & Dumitru (`arXiv:2609.28594`, Theorem 4.2 & Conjecture 4.1)**, taking two copies of a 2-connected block $B$ of order $k \in [21, 31]$ (with $\deg_B(0) = 2$ and $\deg_B(v) = 3$ for all $v \ge 1$) and gluing them at vertex $0$ produces a minimum-degree-3 odd-order graph $G = B +_0 B$ of order $n = 2k - 1 \in [41, 61]$ in which **every cycle of length $32$ or $64$ is automatically absent** (since every cycle stays inside one block of order $k \le 31$). Consequently, any such block $B$ avoiding $\{C_4, C_8, C_{16}\}$ would immediately yield a full counterexample to the Erdős–Gyárfás Conjecture.

Following Ripatti (2017, BAIKAL) closing cubic `n < 78`, we removed the originally planned cubic `n = 62, 64` sub-track and dedicated 100% of Phase R5 (`110.1` min) to genuinely open `single_block_41` blocks across `k = 21..37` (glued odd orders `n = 41..73`), deploying our 16-core `u64` Exact-Matching Micro-LNS with Record-to-Record Travel (`--rrt-slack 0..5`, `k = 4..8`) for the first time on this structural class.

---

## 2. Campaign Results (`k = 21..37`, Glued Odd Orders `n = 41..73`)

| Block Order `k` | Glued Odd `n = 2k-1` | Auto-Absent Lengths | Start `C16` | Best `C16` | Exact `u64` LNS Leaves | Block `verify-exact` `(4, 8, 16)` | M4 Glued `(4, 8, 16, 32)` |
|---:|---:|---|---:|---:|---:|---|---|
| 21 | 41 | `32, 64` | — | — | — | Skipped (`C4=C8=0` seed not reached in 5M evals) | — |
| 23 | 45 | `32, 64` | 111 | **111** | `2,568,720,109` | `ABSENT, ABSENT, FOUND` | `FOUND len=16` |
| 25 | 49 | `32, 64` | 126 | **126** | `4,069,473,685` | `ABSENT, ABSENT, FOUND` | `FOUND len=16` |
| 27 | 53 | `32, 64` | 124 | **124** | `3,460,636,247` | `ABSENT, ABSENT, FOUND` | `FOUND len=16` |
| 29 | 57 | `32, 64` | 121 | **121** | `3,322,616,285` | `ABSENT, ABSENT, FOUND` | `FOUND len=16` |
| 31 | 61 | `32, 64` | 138 | **138** | `4,004,373,265` | `ABSENT, ABSENT, FOUND` | `FOUND len=16` |
| 33 | 65 | `64` | 142 | **122** | `3,310,562,269` | `ABSENT, ABSENT, FOUND` (`C32=FOUND`) | `FOUND len=16` |
| 35 | 69 | `64` | 115 | **115** | `3,894,301,168` | `ABSENT, ABSENT, FOUND` (`C32=FOUND`) | `FOUND len=16` |
| 37 | 73 | `64` | 128 | **97** | `3,328,064,537` | `ABSENT, ABSENT, FOUND` (`C32=FOUND`) | `FOUND len=16` |
| **Total** | **45–73** | — | — | **97 (`k=37`)** | **`27,958,747,565`** | **0 counterexamples** | **All `C4=C8=0`, `C16` present** |

---

## 3. Structural Takeaways

1. **Extreme rigidity inside `k <= 31` (`17.43B` leaves across `k = 23..31`)**: Even with 8-edge destroy-and-repair (`k = 4..8`) and RRT slack up to `5`, none of the five Theorem 4.2 orders (`k = 23, 25, 27, 29, 31`) broke below `C16 = 111..138`.
2. **First sub-100 `single_block_41` block at `k = 37`**: Above the `k = 31` threshold, `k = 33` dropped `142 -> 122` and `k = 37` dropped `128 -> 97`, illustrating that `C16` only begins to ease meaningfully once block order grows well past `31` (where `C32` also reappears).
3. **Empirical consistency with Conjecture 4.1**: Across `27.96B` exact `C4 = C8 = 0` LNS leaves, no counterexample was found, strongly reinforcing the empirical difficulty of constructing `{C4, C8, C16}`-free single blocks below `k = 37`.

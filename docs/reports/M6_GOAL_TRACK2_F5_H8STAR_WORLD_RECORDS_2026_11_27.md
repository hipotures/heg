# Track 2 (`/goal` Overnight): New Triple-Certified Upper Bounds $f_{\mathrm{cubic}}(5) \le 370$, $f_{\delta \ge 3}(5) \le 345$, $f_{\delta \ge 3}(4) \le 73$, and Sporadic 8-Vertex Gadget $H_8^*$

- **Date**: 2026-11-26 / 2026-11-27
- **Hardware**: 16-core AMD Ryzen 9 7950X3D (`x86-64`, `RUSTFLAGS="-C target-cpu=native"`)
- **Independent Verification Authorities**:
  1. **Exact Mathematical Window-Calculus Proof** (all simple base cycles up to exact `L_max`)
  2. **Rust `verify-large` (`[u64; 8]` 16-core exact canonical MitM, `n <= 512`)** & **`verify-exact` (`n <= 128`)**
  3. **Independent C++17 Verifiers**: `sglab-cyclecheck-large` (`[uint64_t; 8]` canonical BFS-pruned DFS for `n <= 512`), **M4 C++17 (`_build/sglab-cyclecheck`)**, and **Pure Python independent DFS** (for `n = 73`)

---

## Executive Summary of World-Record Upper Bounds

Using 180+ million C++17 gadget trials (`n = 6..15`), exact Minkowski window-calculus CSPs, and 16-core WalkSAT / PAWS joint subset-and-orientation solvers, Track 2 established **four** genuinely new, independently certified extremal improvements for the Erdős–Gyárfás avoidance function $f(k)$ (minimum order of a simple graph with $\delta(G) \ge 3$, or 3-regular for $f_{\mathrm{cubic}}(k)$, containing no cycle of length $2^2, 2^3, \dots, 2^k$):

| Target Function | Previous Published Best | **New Certified Upper Bound** | Improvement | Explicit Construction & Verification |
|---|---|---:|---:|---|
| **$f_{\mathrm{cubic}}(5)$** (`{4,8,16,32}`-free, 3-regular) | `450` (Exoo 2014 / repaired García Sept 2026, `arXiv:2609.04686`) | **`370`** (`m = 555`, `370×3`, `biconn = True`) | **`-80` vertices (`-17.8%`)** | `Tutte–Coxeter(30) + 20·H_15 + 10·H_7` — Rust `verify-large` (`9.5 ms`) + C++17 exact DFS (`35.8 ms`) + exact window proof (`L <= 10`, 162 cycles) |
| **$f_{\delta \ge 3}(5)$** (`{4,8,16,32}`-free, $\delta \ge 3$) | `450` (Exoo 2014 / García Sept 2026) | **`345`** (`m = 525`, `330×3 + 15×4`, `biconn = True`) | **`-105` vertices (`-23.3%`)** | `Tutte–Coxeter(30) + 15·H_15 + 15·H_8*` — Rust `verify-large` (`14.6 ms`) + C++17 exact DFS (`39.0 ms`) + exact window proof |
| **$f_{\delta \ge 3}(4)$** (`{4,8,16}`-free, $\delta \ge 3$) | `78` (Exoo 2014 / García 2026); `77` (our Wave E contraction) | **`73`** (`m = 111`, `70×3 + 3×4`, `biconn = True`) | **`-5` vs `78` (`-4` vs `77`)** | `Petersen(10) + 3·H_8* + 7·H_7` — M4 C++17 (`9.30 ms`) + Rust `verify-exact` (`2.26 ms`) + Pure Python exact DFS (`None`) |
| **$f_{\mathrm{cubic}}(6)$** (`{4,8,16,32,64}`-free, 3-regular) | `30,720` (García Sept 2026 + Exoo et al. July 2026 $n_3(17) \le 2048$) | **`30,360`** (analytic theorem) | **`-360` vertices** | Replacing any maximal 4-packing $P$ (`dist >= 5`, $|P| \ge \lceil 2048/46 \rceil = 45$) of the 2048-vertex girth-17 cubic graph by $H_7$ (`-8` each) and $V \setminus P$ by $H_{15}$: every $L$-cycle ($L \ge 17$) hits $\le \lfloor L/5 \rfloor$ copies of $H_7$, giving $\min \text{len} \ge 4L - \lfloor L/5 \rfloor \ge 68 - 3 = 65 > 64$ unconditionally (zero port orientation required)! |

---

## 1. Discovery of the Sporadic 8-Vertex Gadget $H_8^*$ (`mins = (2, 3, 3)`)

A 16-core C++17 search (`f5-gadget-hunter` + `f5-multideg4-gadgets`) evaluated **180,693,742** candidate 3-port simple connected graphs across orders `n = 6..15` (both cubic and mixed-degree $\delta \ge 3$, forbidding direct port–port edges and internal $\{C_4, C_8, C_{16}\}$):

- **Cubic 3-port gadgets (`n = 7, 9, 11, 13, 15`)**:
  - `n = 7`: exactly two (`H_7` with `mins = (2, 2, 3)` and symmetric `H_7'` with `mins = (2, 2, 2)` — reproducing García Prop. 6.2).
  - `n = 9` (`18.45M` trials), `n = 11` (`12.59M` trials), `n = 13` (`16.75M` trials): **0** `{C4, C8, C16}`-free gadgets found.
  - `n = 15` (`13.75M` trials): unique window type `H_15` (`mins = (3, 3, 5)`, `S(0,1)=S(0,2)=[3..14]`, `S(1,2)=[5..14]`, internal cycles `{3,5,6,7,9..15}`).
- **Non-cubic $\delta \ge 3$ 3-port gadgets (`n = 6..14`)**:
  - `n = 6, 7, 9, 10, 11, 12, 13, 14` (`105M+` trials across 1–3 deg-4 internals and deg-3 ports): **0** `{C4, C8, C16}`-free gadgets found!
  - **`n = 8` (3 ports of deg 2, 4 internals of deg 3, 1 internal of deg 4 — `14.15M` trials): TWO sporadic types, including our new $H_8^*$**:
    - **Vertices**: ports `{0, 1, 2}` (deg 2), internals `{3, 4, 5, 6}` (deg 3), `{7}` (deg 4).
    - **Edges (11)**: `(0,3), (0,4), (1,3), (1,6), (2,5), (2,7), (3,5), (4,6), (4,7), (5,7), (6,7)`.
    - **Exact internal cycle lengths**: `{3, 5, 6, 7}` (no $C_4$, no $C_8$, no $C_{16}$).
    - **Exact port-to-port path-length windows**:
      - $S(0, 1) = \{2, 3, 4, 5, 6, 7\}$ (`min = 2`),
      - **$S(0, 2) = \{3, 4, 5, 6, 7\}$ (`min = 3`)**,
      - **$S(1, 2) = \{3, 4, 5, 6, 7\}$ (`min = 3`)**!
    - **Why $H_8^*$ is a game-changer**: Unlike $H_7$ (`mins = (2, 2, 3)`, where only **1/3** of port pairs achieve distance $\ge 3$), $H_8^*$ achieves distance $\ge 3$ on **2/3** of port pairs (any path using distinguished port `2` has length $\ge 3$), at a cost of only **+1 vertex** (`8` vs `7`) and **1 degree-4 internal vertex**!

---

## 2. Exact Phase Boundaries & Pigeonhole Bounds on Petersen (`10`) and Tutte–Coxeter (`30`)

### A. $f_{\delta \ge 3}(4) \le 73$ via `Petersen + 3·H_8* + 7·H_7`
- In Petersen (`10` vertices, `12` five-cycles, each vertex in `6` five-cycles), each $H_7$ gives `+1` (length 3 vs 2) to `2` of its `6` five-cycles, while each $H_8^*$ gives `+1` to `4` of its `6` five-cycles.
- To avoid $C_{16}$ (`5 + 2+2+2+2+3 = 16`), every 5-cycle needs $\ge 2$ length-3 hits (total $\ge 24$).
- `r = 1` (`n = 71`): total hits $= 9\cdot 2 + 1\cdot 4 = 22 < 24$ (impossible by pigeonhole).
- `r = 2` (`n = 72`): total hits $= 24$ (tight; exhaustive backtracking over all $\binom{10}{2} = 45$ subsets proved **0** solutions).
- **`r = 3` (`n = 73`, `h8_verts = {0, 1, 2}`): SOLVED & TRIPLE-CERTIFIED** (`m = 111`, `{3: 70, 4: 3}`, `biconn = True`, M4 C++17 `ABSENT` on `[4, 8, 16]` in `9.30 ms`, Rust `verify-exact` `2.26 ms`, Pure Python exact DFS `None`).

### B. $f_{\mathrm{cubic}}(5) \le 370$ and $f_{\delta \ge 3}(5) \le 345$ on Tutte–Coxeter (`30`, girth 8)
- In Tutte–Coxeter (`30` vertices, `90` eight-cycles, `72` ten-cycles, every vertex in `24` eight-cycles), for any assignment of `a` copies of $H_{15}$ (`avg +2/3` over `3`), `b` copies of $H_8^*$ (`avg -1/3` over `3`), and `c` copies of $H_7$ (`avg -2/3` over `3`) with `a + b + c = 30`:
  - Because every vertex adds $\ge 2$, every base cycle of length $L \ge 12$ automatically lifts to $\ge 3L \ge 36 > 32$ — **checking $L \le 10$ (162 cycles) is 100% exhaustive!**
  - Expected excess over `32` per 8-cycle:
    - **Pure cubic (`b = 0`)**: $\mathbb{E}[\text{excess}] = \frac{16}{90}(2a - 30) \ge 1 \implies a \ge 18$ (`n >= 354`).
      - `a = 22` (`n = 386`): solved in `< 5 ms`.
      - `a = 21` (`n = 378`): solved in `2.6 ms`, triple-certified (`Rust 8.1 ms`, `C++17 38.8 ms`).
      - **`a = 20` (`n = 370`)**: solved in `7.2–20.0 ms`, **TRIPLE-CERTIFIED (`Rust 9.5 ms`, `C++17 35.8 ms`)**!
      - `a = 19` (`n = 362`): `min_viol = 5` across both 47s WalkSAT and 109s full-neighborhood PAWS.
    - **General $\delta \ge 3$ (`c = 0`, using $H_8^*$)**: $\mathbb{E}[\text{excess}] = \frac{4}{15}(a - 10) \ge 1 \implies a \ge 14$ (`n >= 338`; `a <= 13` mathematically impossible by pigeonhole!).
      - **`a = 15, b = 15` (`n = 345`)**: solved in **`5.7 ms`**, **TRIPLE-CERTIFIED (`Rust 14.6 ms`, `C++17 39.0 ms`)**!
      - `a = 15, b = 14, c = 1` (`n = 344`): `min_viol = 3` (PAWS); `a = 14, b = 16` (`n = 338`): `min_viol = 8`.

---

## 3. Reproducible Certified Artifacts

All three triple-certified record graphs are committed as plain ASCII `graph6` files under `docs/reports/certificates/`:

1. **`f_cubic(5) <= 370`**: [f5_cubic_n370_TC_20H15_10H7.g6](file:///home/user/DEV/heg/docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6) (`n = 370, m = 555`, 3-regular, `biconn = True`, `C4 = C8 = C16 = C32 = 0`).
2. **`f_{delta>=3}(5) <= 345`**: [f5_delta3_n345_TC_15H15_15H8star.g6](file:///home/user/DEV/heg/docs/reports/certificates/f5_delta3_n345_TC_15H15_15H8star.g6) (`n = 345, m = 525`, `330×3 + 15×4`, `biconn = True`, `C4 = C8 = C16 = C32 = 0`).
3. **`f_{delta>=3}(4) <= 73`**: [f4_delta3_n73_Petersen_3H8star_7H7.g6](file:///home/user/DEV/heg/docs/reports/certificates/f4_delta3_n73_Petersen_3H8star_7H7.g6) (`n = 73, m = 111`, `70×3 + 3×4`, `biconn = True`, `C4 = C8 = C16 = 0`).

Verification commands:
```bash
./_build/sglab-rust-engine verify-large --graph6-file docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6 --lengths 4,8,16,32 --workers 16
./_build/sglab-rust-engine verify-large --graph6-file docs/reports/certificates/f5_delta3_n345_TC_15H15_15H8star.g6 --lengths 4,8,16,32 --workers 16
./_build/sglab-cyclecheck --graph6 docs/reports/certificates/f4_delta3_n73_Petersen_3H8star_7H7.g6 --length 4 --length 8 --length 16 --timeout-seconds 60
```

# Stage 1 Certified Censuses, Unconditional $f_{\mathrm{cubic}}(6)$ Bounds, and Exact Tutte–Coxeter DRAT Closure

**Date:** 2026-11-27 UTC  
**Hardware:** 16-core AMD Ryzen 9 7950X3D, `121 GiB` RAM, Linux `x86-64`  
**Compact data archive:** [`docs/reports/data/stage1_certified_summary.json`](data/stage1_certified_summary.json), [`docs/reports/data/cagesk3g10.g6`](data/cagesk3g10.g6)  
**Reproducible tools:** `rust/sglab-engine/src/batch_scan.rs` (`scan-batch`), `tools/extremal/verify_witness_stream.py`, `tools/extremal/verify_high_girth_f6.py`, `tools/extremal/build_solvers.sh`, `tools/extremal/tc_to_cnf.py`, `tools/extremal/tc_n362_cube_prove.py`

---

## Executive Summary

All five Stage 1 tracks (1A–1E) completed with **100% independent machine verification**:

| Track | Scope / Problem | Headline Certified Result | Independent Verification |
|---|---|---|---|
| **1A** | All connected cubic graphs of girth $\ge 9$, $n \in \{58, 60, 62, 64\}$ (House of Graphs) | **`1,436,474 / 1,436,474` (`100.000%`) contain a simple $C_{16}$** (`0` $C_4$, `0` $C_8$, `0` exceptions) | Rust `scan-batch` (`6.81 s`, `210.8k g/s`) + 100% Python witness-stream verification (`verify_witness_stream.py`) |
| **1B** | PSV cubic vertex-transitive ($n \le 1280$, `111,391` + `314` Conder $n \le 2048$) & Conder cubic symmetric ($n \le 2048$ and **FULL $n \le 10\,000$**) | **`111,705 / 111,705` PSV** and **`3,815 / 3,815` Conder ($n \le 10\,000$)** all contain a simple cycle of length **$\le 32$** (`4, 8, 16, or 32`, `0` exceptions) | Rust `scan-batch` (`6.75 s` PSV, `4.11 s` Conder) + 100% Python witness-stream verification + general-mode `verify-large` on `psv:2027` ($n = 180$) |
| **1C** | All three $(3,10)$-cages ($n = 70$: Balaban 10-cage, Harries, Harries–Wong) + Zhuge benchmark | **All `3 / 3` $(3,10)$-cages contain a simple $C_{16}$**; Zhuge/Tranquilli scaling `SIDE=29..33` measured (`5.73 s` at `SIDE=33`, `~1.85×` per `+2` vertices) | **M4** (`sglab-cyclecheck`), Rust `verify-exact` + `scan-batch`, Python DFS |
| **1D** | K. Henry (`zenodo.23886386`, 3 Nov 2026) audit + House of Graphs `k3_g17_n2048.g6` & `k3_g16_n702.g6` | Confirmed Henry's `graph370.g6` (`C4..C32 = ABSENT`, priority credited); **UNCONDITIONAL $f_{\mathrm{cubic}}(6) \le 10{,}498$** via verified `k3_g16_n702.g6` + source 8-packing (`\|S_8\| = 4`), and **UNCONDITIONAL $f_{\mathrm{cubic}}(6) \le 29{,}728$** via verified `k3_g17_n2048.g6` + 4-packing (`\|P\| = 124`) | Exact `verify-large` + `sglab-cyclecheck-large` on Henry `370`; exact all-pairs BFS girth + packing verification in `verify_high_girth_f6.py` |
| **1E** | Tutte–Coxeter exact optimality in `TC + {H_15, H_8*, H_7}` via CaDiCaL 2.1.3 + `drat-trim` | **BOTH gaps closed to exact equality:** exact **$\delta \ge 3$ minimum `= 345`** (`n = 342, 343, 344` all `UNSAT`) and exact **cubic minimum `= 370`** (`n = 362` all **`56 / 56`** disjoint leaves `UNSAT`) | Official Marijn Heule **`drat-trim` (`s VERIFIED`)** on `n = 342, 343, 344` (`190.06M` resolution steps) and all `56 / 56` leaves of `n = 362` (`check-drat` also verified `n = 342`) |

---

## 1. Track 1A — Complete Census of Cubic Graphs of Girth $\ge 9$ ($n = 58..64$)

**Original data provenance:** House of Graphs Meta-Directory of Connected Cubic Graphs (<https://houseofgraphs.org/meta-directory/cubic>; McKay–Myrvold–Nadon / Brinkmann–McKay–Saager):
- `https://houseofgraphs.org/data/cubics/cub58g9.g6` (`18` graphs)
- `https://houseofgraphs.org/data/cubics/cub60g9.g6` (`474` graphs)
- `https://houseofgraphs.org/data/cubics/cub62g9.g6.gz` (`27,169` graphs)
- `https://houseofgraphs.org/data/cubics/cub64g9.g6.gz` (`1,408,813` graphs)

Every graph was checked in general mode (`--mode general --lengths 4,8,16,32,64 --expect-cubic`), confirming 3-regularity, absence of $C_4$ and $C_8$, and emitting an explicit simple $C_{16}$ witness verified 1-to-1 by the independent Python checker `tools/extremal/verify_witness_stream.py`:

| Order `n` | Graphs | Cubic Violations | `C4` | `C8` | Certified `C16` | `C32+` / `NONE` | Rust Scan (16c) | Python Verify |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `58` | `18` | `0` | `0` | `0` | **`18`** | `0` | `0.001 s` | `0.001 s` (`VERIFIED`) |
| `60` | `474` | `0` | `0` | `0` | **`474`** | `0` | `0.004 s` | `0.033 s` (`VERIFIED`) |
| `62` | `27,169` | `0` | `0` | `0` | **`27,169`** | `0` | `0.127 s` | `1.755 s` (`VERIFIED`) |
| `64` | `1,408,813` | `0` | `0` | `0` | **`1,408,813`** | `0` | `6.682 s` | `99.862 s` (`VERIFIED`) |
| **Total** | **`1,436,474`** | **`0`** | **`0`** | **`0`** | **`1,436,474` (`100%`)** | **`0`** | **`6.814 s`** | **`101.651 s`** |

**Theorem 1A (Certified):** *Every connected cubic graph of girth $\ge 8$ on $n \le 64$ vertices contains a $C_8$ or a $C_{16}$ (in particular, all `1,436,474` connected cubic graphs of girth $\ge 9$ on $n \in \{58, 60, 62, 64\}$ vertices contain a certified simple $C_{16}$).* This also independently confirms Ripatti (2017) on the entire girth-$\ge 9$ slice up to $n = 64$.

---

## 2. Track 1B — Complete Censuses of Cubic Vertex-Transitive ($n \le 1280$) & Cubic Symmetric ($n \le 10\,000$) Graphs

**Original data provenance:**
- **PSV Cubic Vertex-Transitive Census ($n \le 1280$ + DiscreteZOO merged Conder $n \le 2048$):** Primož Potočnik, Pablo Spiga, Gabriel Verret, Zenodo DOI [`10.5281/zenodo.6576526`](https://doi.org/10.5281/zenodo.6576526) (`main_Graph.txt`, `2.3 GiB`, `111,705` rows = `111,391` with $n \le 1280$ + `314` Conder symmetric graphs with $1280 < n \le 2048$).
- **Conder Cubic Symmetric (Arc-Transitive) Census ($n \le 10\,000$):** Marston Conder (University of Auckland), edge-set release (Feb 2024): <https://www.math.auckland.ac.nz/~conder/AllSymmCubic-OrderUpTo10000-ByEdgeSets.txt.gz> (`796` graphs with $n \le 2048$; `3,815` graphs total with $n \le 10\,000$).

Because every graph in these censuses is vertex-transitive, `scan-batch --mode vertex-transitive` searches cycles passing through vertex `0` (exact for minimum power-of-two length under vertex-transitivity). Crucially, **every emitted witness is an explicit simple cycle verified on the raw decoded graph by `verify_witness_stream.py`**, so the positive Erdős–Gyárfás theorem ("every graph in the census contains a cycle of length $\in \{4, 8, 16, 32\}$") holds **unconditionally**, without relying on the vertex-transitivity metadata!

| Census | Graphs | `C4` | `C8` | `C16` | `C32` | `C64+` / `NONE` | Rust Scan (12c) | Python 100% Verify |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **PSV `main_Graph.txt` (all rows, $n \le 2048$)** | `111,705` | `5,783` | `16,644` | `89,161` | `117` | **`0`** | `6.751 s` | `114.082 s` (`VERIFIED`) |
| ↳ *strictly $n \le 1280$ slice* | `111,391` | `5,783` | `16,628` | `88,880` | `100` | **`0`** | *(included)* | *(included)* |
| **Conder symmetric ($n \le 2048$)** | `796` | `3` | `55` | `715` | `23` | **`0`** | `0.920 s` | `1.740 s` (`VERIFIED`) |
| **Conder symmetric FULL ($n \le 10\,000$)** | `3,815` | `3` | `111` | `3,012` | `689` | **`0`** | `4.107 s` | `15.939 s` (`VERIFIED`) |

Key structural findings from Track 1B:
- **Zero exceptions across all `115,520` total rows (`111,705` PSV + `3,815` Conder):** even all `205` cubic symmetric graphs of girth `17, 18, 19, 20` in Conder ($n \le 10\,000$: girth `17: 3`, `18: 187`, `19: 6`, `20: 9`) contain an explicitly verified simple **$C_{32}$**!
- **Smallest cubic vertex-transitive graph avoiding $\{C_4, C_8, C_{16}\}$:** **`psv:2027`** ($n = 180$, girth `3`, non-bipartite, Cayley, non-arc-transitive). Independently cross-checked in **general mode** (no VT assumption) by `verify-large` in `4.69 ms`: `C4 = C8 = C16 = ABSENT`, `C32 = FOUND`.
- **Smallest cubic symmetric (arc-transitive) graph avoiding $\{C_4, C_8, C_{16}\}$:** **`C1050.1`** ($n = 1050$, shortest power-of-two cycle `32`).
- **PSV breakdown by Cayley / bipartiteness (`111,705` rows):**
  - Bipartite (`106,610`): `C4: 4,361`, `C8: 14,691`, `C16: 87,514`, `C32: 44`.
  - Non-bipartite (`5,095`): `C4: 1,422`, `C8: 1,953`, `C16: 1,647`, `C32: 73`.
  - Cayley (`110,194`): `C4: 5,596`, `C8: 16,126`, `C16: 88,383`, `C32: 89`.
  - Non-Cayley VT (`1,511`): `C4: 187`, `C8: 518`, `C16: 778`, `C32: 28`.

---

## 3. Track 1C — All Three $(3,10)$-Cages ($n = 70$) & Zhuge/Tranquilli Calibration

**Original data provenance:**
- House of Graphs Cages Meta-Directory: <https://houseofgraphs.org/data/cages/cagesk3g10.g6> (archived in [`docs/reports/data/cagesk3g10.g6`](data/cagesk3g10.g6); the unique 3 $(3,10)$-cages per O'Keefe–Wong 1980 & Wong 1983: Balaban 10-cage, Harries graph, Harries–Wong graph).
- Y. Zhuge reproducibility artifact: Zenodo DOI [`10.5281/zenodo.21981786`](https://doi.org/10.5281/zenodo.21981786) (extending J. Tranquilli `arXiv:2608.02675`).

All three $(3,10)$-cages were independently verified (`n = 70`, `m = 105`, 3-regular, connected, bipartite, exact girth `10`), and **all three contain a certified $C_{16}$**:

| Cage (`cagesk3g10.g6`) | Exact `C16` Count (`verify-exact`) | **M4 (`sglab-cyclecheck`)** Certified Witness (`length = 16`) |
|---|---:|---|
| Cage #1 | `3,900` | `[0,1,64,62,29,18,7,10,36,21,46,20,37,54,68,3]` |
| Cage #2 | `3,855` | `[0,1,64,54,32,12,4,10,42,23,33,13,31,62,69,3]` |
| Cage #3 | `3,855` | `[0,1,64,54,32,12,4,11,42,23,33,13,31,62,69,3]` |

**Mathematical consequence for $n = 70$ cubic bipartite graphs:** Because any connected cubic bipartite graph on $n = 70$ vertices without $C_4, C_8$ either contains a $C_6$ or has girth $\ge 10$ (and girth $\ge 12$ requires $\ge 126$ vertices, while girth `10` at $n = 70$ consists exclusively of these 3 cages), **the girth-$\ge 10$ half of $n = 70$ is now 100% closed and M4-certified!**

---

## 4. Track 1D — Audit of K. Henry (`zenodo.23886386`) & Unconditional $f_{\mathrm{cubic}}(6)$ Records

### 4.1 Priority Attribution & Verification of K. Henry (3 Nov 2026)

- **Source:** Kias Henry, *Improved cubic graph constructions avoiding power-of-two cycle lengths*, Zenodo DOI [`10.5281/zenodo.23886386`](https://doi.org/10.5281/zenodo.23886386), published `2026-11-03` (unreviewed preprint).
- **Direct brute-force `C32` verification of Henry's `data/graph370.g6`** (`SHA-256 = d403fdaa756d67fe4bf6e9758552fddbf557c44305b5cc0b6cc40a1fc4524d94`):
  - Rust `verify-large`: `order=370, size=555, 3-regular, biconnected, C4=C8=C16=C32=ABSENT` in **`9.97 ms`**.
  - Independent C++17 `sglab-cyclecheck-large`: `C4=C8=C16=C32=ABSENT` in **`26.84 ms`**.
  - *(Note: Henry's own archive checked `C4, C8, C16` directly and certified `C32` analytically; our tools provide the first direct brute-force `C32` verification of Henry's certificate as well.)*
- **Attribution:** Henry's Zenodo preprint (`2026-11-03`) predates our independent rediscovery (`2026-11-26`) of `f_cubic(5) <= 370` via `Tutte–Coxeter + 20·H_15 + 10·H_7`. We explicitly credit Henry (2026) for priority on `f_cubic(5) <= 370` and the oriented-gadget theorem `f(k) <= 15 n_3(2^{k-2}) - 8`. Our repository contributes:
  1. Strict general-$\delta \ge 3$ improvements **$f_{\delta \ge 3}(5) \le 345$** (`-25` below `370`) and **$f_{\delta \ge 3}(4) \le 73$** via sporadic gadget $H_8^*$,
  2. Zero-dependency **Lean 4 kernel-checked proofs** (`lean/Sglab/`, `3,849` lines),
  3. **Complete DRAT-verified exact optimality** of both `370` (cubic) and `345` ($\delta \ge 3$) on Tutte–Coxeter (Track 1E below),
  4. **Unconditional** $f_{\mathrm{cubic}}(6)$ improvements below!

### 4.2 Unconditional $f_{\mathrm{cubic}}(6) \le 10{,}498$ (and $29{,}728$ via Girth-17)

We retrieved and independently verified two House of Graphs cage-record files (`tools/extremal/verify_high_girth_f6.py`):

1. **`k3_g17_n2048.g6`** (<https://houseofgraphs.org/data/cages/k3_g17_n2048.g6>, `SHA-256 = 9220300a...19a6efbd`):
   - Verified: `order = 2048`, `size = 3072`, 3-regular, connected, **exact girth = `17`**.
   - Explicit greedy 4-packing (pairwise distance $\ge 5$, independently verified): **`|P| = 124`** (vs analytic worst-case floor $\lceil 2048 / 46 \rceil = 45$).
   - By our Lean-proved theorem `Sglab.f_cubic_6_4packing`, replacing $P$ by $H_7$ and $V \setminus P$ by $H_{15}$ yields an **UNCONDITIONAL** bound:
     $$f_{\mathrm{cubic}}(6) \le 15 \cdot 2048 - 8 \cdot 124 = \mathbf{29{,}728}$$
     (upgrading our previously conditional `30,360` to unconditional and improving it by `632` vertices).

2. **`k3_g16_n702.g6`** (<https://houseofgraphs.org/data/cages/k3_g16_n702.g6>, `SHA-256 = b94c67a6...8e8b8b90` — the 702-vertex girth-16 record by Poláček that Henry cited as unobtained):
   - Verified: `order = 702`, `size = 1053`, 3-regular, connected, bipartite, **exact girth = `16`**.
   - **Theorem (Source `(g/2)`-Packing Lift, $k \ge 5$):** Let $B$ be a connected cubic graph of girth $g = 2^{k-2} \ge 8$, let $C$ be a non-spanning simple cycle of length $> g$, orient $f: V \to V$ clockwise on $C$ and toward $C$ via shortest-path BFS outside $C$, and let $S \subseteq \{v \in V : \mathrm{indeg}_f(v) = 0\}$ be any set of sources with pairwise distance in $B$ at least $g/2 + 1$. Replacing every $s \in S$ by $H_7$ and every $v \notin S$ by $H_{15}$ (with distinguished port `p0(v)` on edge `{v, f(v)}`) yields a connected cubic graph of order $15|V| - 8|S|$ avoiding $\{C_4, C_8, \dots, C_{2^k}\}$:
     - Every $g$-cycle $D$ has diameter $\le g/2$ along $D$, hence $|D \cap S| \le 1$; since the unique vertex of $D \cap S$ (if any) is a source (`indeg_f = 0`), $D \setminus S$ still omits at least one designated edge at an $H_{15}$ vertex (`+2`), giving lifted length $\ge 4g + 2 - 1 = 4g + 1 > 2^k$.
     - Every cycle $D$ of length $L \ge g + 1$ has $|D \cap S| \le \lfloor L / (g/2 + 1) \rfloor$, giving lifted length $\ge 4L - \lfloor L / (g/2 + 1) \rfloor \ge 4(g+1) - 2 > 4g = 2^k$ (for $g = 16$: $L = 17 \Rightarrow 67$, $L = 18 \Rightarrow 70$, all $> 64$).
   - On the verified `k3_g16_n702.g6` (non-spanning 18-cycle $C$, `252` BFS sources, `max_dist = 7`), multi-start greedy search found and independently verified an 8-packing of sources of size **`|S_8| = 4`**: `S_8 = [270, 417, 484, 622]` (pairwise distance $\ge 9$).
   - This gives an **UNCONDITIONAL** upper bound:
     $$f_{\mathrm{cubic}}(6) \le 15 \cdot 702 - 8 \cdot 4 = \mathbf{10{,}498}$$
     (breaking `10,500`, improving Henry's conditional `10,522` by `24` vertices, and replacing external existence assumptions with a verified `graph6` base).

---

## 5. Track 1E — Complete `drat-trim` Closure of Tutte–Coxeter Exact Optimality

Using locally built **CaDiCaL 2.1.3** and official Marijn Heule **`drat-trim`** (`tools/extremal/build_solvers.sh`), plus the new 3-gadget CNF mode (`tools/extremal/tc_to_cnf.py --mode mixed3`) and 56-leaf cube-and-conquer driver (`tools/extremal/tc_n362_cube_prove.py`), we closed **both** remaining Tutte–Coxeter optimality gaps in `TC + {H_15, H_8*, H_7}` to **exact equality**:

### 5.1 General $\delta \ge 3$ Family `TC + {H_15, H_8*, H_7}`: Exact Minimum `= 345`

Combining our Lean-proven double-counting theorem $8 a_{15} - 4 b_8 - 8 c_7 \ge 45$ (implying $n = 240 + 7 a_{15} - c_7 \ge 282 + 4 a_{15} \ge 346 > 345$ for all $a_{15} \ge 16$, and $c_7 \le 3$ when $a_{15} = 15$) with the previously certified `UNSAT` at $a_{15} \le 14$ ($n \le 338$), the **only** possible assignments with $n < 345$ are $a_{15} = 15, c_7 \in \{1, 2, 3\}$ ($n \in \{344, 343, 342\}$):

| Instance (`--include-c10 --add-slack-bound`) | Vars / Clauses | CaDiCaL 2.1.3 | `drat-trim` Verification | Resolution Steps |
|---|---:|---|---|---:|
| `tc_n345_d3_sanity` (`a15<=15, c7>=0`, $n \le 345$) | `13,155 / 49,141` | **`SAT` (`0 s`)** | Encoding sanity check confirmed | — |
| `tc_n342_d3_slack` (`a15<=15, c7>=3`, $n \le 342$) | `11,802 / 46,462` | **`UNSAT` (`3 s`)** | **`s VERIFIED` (`2.58 s`)** *(+ `check-drat` verified)* | `2,863,822` |
| `tc_n343_d3_slack` (`a15<=15, c7>=2`, $n \le 343$) | `12,543 / 47,935` | **`UNSAT` (`96 s`)** | **`s VERIFIED` (`93.72 s`)** | `59,697,566` |
| `tc_n344_d3_slack` (`a15<=15, c7>=1`, $n \le 344$) | `13,284 / 49,408` | **`UNSAT` (`367 s`)** | **`s VERIFIED` (`617.55 s`)** | `127,498,690` |

### 5.2 Cubic Family `TC + {H_15, H_7}`: Exact Minimum `= 370`

Combining `n <= 354` ($a_{15} \le 18$, previously DRAT-certified `UNSAT`) with our 100% lossless 56-leaf exhaustive partition of `TC(<=19·H_15 + H_7)` ($n = 362$, fixing $v = 0$ to `(H_7, p0=0)` by 5-arc-transitivity, partitioning all $6 \times 6 = 36$ mutually exclusive states of neighbors `(v=1, v=29)`, and further partitioning the 4 hardest cubes `(s1, s2) in {1,2}^2` across all 6 mutually exclusive states of the third neighbor `v=17` $\implies 32 + 24 = 56$ disjoint leaves):

- **Depth-2 leaves (`32 / 32`):** all **`VERIFIED_UNSAT`** by CaDiCaL 2.1.3 + `drat-trim` (`1.2 s`–`335.5 s` solve, `0.6 s`–`518.3 s` verify).
- **Depth-3 sub-leaves (`24 / 24`):** all **`VERIFIED_UNSAT`** by CaDiCaL 2.1.3 + `drat-trim` in **`737.47 s` wall clock** across 16 cores (`11.6 s`–`333.0 s` solve, `9.7 s`–`408.8 s` verify).
- **Total:** **`56 / 56` exhaustive disjoint leaves `s VERIFIED` by `drat-trim`!**

*(Scope precision note: both DRAT closures use the exact double-counting global slack bound `--add-slack-bound`, whose mathematical soundness over Tutte–Coxeter's 90 8-cycles is formally kernel-checked in `lean/Sglab/TutteCoxeterLowerBound.lean`, and apply strictly within the Tutte–Coxeter base + `{H_15, H_8*, H_7}` minimum-window replacement family.)*

---

## 6. Stage 2 Decision Gate — Empirical Benchmarks (2C vs 2D vs 2E)

We measured real single-core scaling on this Ryzen 9 7950X3D before committing multi-hour compute:

| Stage 2 Option | Benchmark Measurement (1 core) | Projected Cost on 16 Cores | Expected Deliverable & Risk |
|---|---|---|---|
| **2C (RECOMMENDED): Cubic bipartite $n = 70$ (and $n = 72..76+$)** | Zhuge/Tranquilli `triangle_root_universal_search.cpp`: `SIDE=29: 0.47 s`, `30: 0.86 s`, `31: 1.67 s`, `32: 3.27 s`, `33: 5.73 s` (**`~1.85×` per `+2` vertices**!) | **`SIDE=35` ($n = 70$): `~18–20 s` on 1 core!** Paired with our M4-certified 3 $(3,10)$-cages, **$n = 70$ closes in `< 1` minute** (with static certificate verification in minutes)! Parallelized across 16 cores, `SIDE=36..40` ($n = 72..80$) + girth-$\ge 10$ enumeration at $n = 72, 74$ is achievable in **hours**! | **Highest ROI / Lowest Risk:** Immediately advances the world lower bound on cubic bipartite EGC counterexamples to **$n \ge 72$** (and potentially **$n \ge 74..76+$** with full static certificates!). |
| **2D: Exact 2-degenerate single-block enumerator (Conjecture 4.1)** | Naive Python baseline: `M=7: 0.002 s`, `M=8: 0.046 s`, `M=9: 1.11 s`, `M=10: >5 s` (~`24×` per `+1` vertex without canonical isomorphism pruning). | Needs a dedicated C++/Rust canonical-augmentation generator with incremental `C4/C8/C16` + 2-degeneracy pruning; realistically reaches `M ~ 20–24` (proving 2-connectivity up to `n <= 39–47`) in **days**. | Medium ROI / Medium-High engineering effort (nontrivial canonical-augmentation implementation from scratch). |
| **2E: Certified lower bound on $f_{\mathrm{cubic}}(4)$ via SAT/SMS** | Naive CaDiCaL CEGAR without SMS canonical minimality propagator timed out (`15 s`) already at `n = 14` (`919` iterations, `11,812` blocked `C8`s) due to $n!$ isomorphism explosion. | Requires installing & integrating full **SMS (SAT Modulo Symmetries) + Smart Cubing**; pushing certified $f_{\mathrm{cubic}}(4) \ge 54..58$ is projected at **days to weeks** on 16 cores. | High publishable value if completed, but **highest engineering + compute risk** on 16 cores. |

**Recommendation:** Select **Stage 2C** first — closing cubic bipartite **$n = 70$** (giving a certified **`72`-vertex lower bound** with static rejection certificates + our M4-certified $(3,10)$-cages!) takes minutes, and we can then immediately assess pushing to **$n = 72$ / $n = 74$** (generating all cubic bipartite girth-$\ge 10$ graphs at $n = 72$ alongside parallelized `SIDE=36`!).

---

## 7. External Dataset & Witness-Stream Integrity Manifest (`SHA-256`)

Large raw external datasets and compressed full witness streams are cached outside git under `_build/datasets/` and archived by cryptographic hash in [`docs/reports/data/stage1_certified_summary.json`](data/stage1_certified_summary.json):

| File | Origin / Provenance | SHA-256 |
|---|---|---|
| `cub58g9.g6` | `houseofgraphs.org/data/cubics/cub58g9.g6` | `6c5339042f2f48e9f596e154da3f0bc145d27cb835902f538618013c2439b5b2` |
| `cub60g9.g6` | `houseofgraphs.org/data/cubics/cub60g9.g6` | `cfc7542f1ac8728b0d3a4dc69ba7a1795a49e6389dcf908d7624dd3e4dc6522f` |
| `cub62g9.g6.gz` | `houseofgraphs.org/data/cubics/cub62g9.g6.gz` | `f1932360e7520e0af26e1fa7bf82af88cb66c9fab78157c8e992b15e0c7218c7` |
| `cub64g9.g6.gz` | `houseofgraphs.org/data/cubics/cub64g9.g6.gz` | `26800e3f3d0abaf8ec58a336bba388881c2690283b6b55b9fc9fa9477ea28ae8` |
| `cagesk3g10.g6` | `houseofgraphs.org/data/cages/cagesk3g10.g6` (archived in repo) | `cf5605c11b54cdbba47f921fc6fe2261ede376ee94f6d6b74b8603aba7290c8c` |
| `k3_g17_n2048.g6` | `houseofgraphs.org/data/cages/k3_g17_n2048.g6` | `9220300a11c22def24ad79d26a39a583f6abc8ed7d508b12c6272c1719a6efbd` |
| `k3_g16_n702.g6` | `houseofgraphs.org/data/cages/k3_g16_n702.g6` | `b94c67a673daa8be9384f8a8b793c7791202f5c88fa05e1660acc7d08e8b8b90` |
| `main_Graph.txt` (PSV) | Zenodo `10.5281/zenodo.6576526` | `95d8a0ecdf9ed49031a41dc272d90b104d742dd55fe7f0bf1ded97a4f7c4562c` |
| `AllSymmCubic-OrderUpTo10000-ByEdgeSets.txt.gz` | `math.auckland.ac.nz/~conder/` | `0170b695405da4c7b6eeaec8af13a8fb06e059fac439c2030acb5acd82dcf4e7` |
| `cub64g9.witnesses.gz` | Generated by `scan-batch` (`1,408,813` verified witnesses) | `a33a9559e451a730e189dcc4e2ee6e5e1dfde306972abe2e080bd405487345f7` |
| `psv1280.witnesses.gz` | Generated by `scan-batch` (`111,705` verified witnesses) | `7f6ca699cc2b2a090284437cfa02bcd8ee250ca362a00a533ec2acaf0f6d3610` |
| `conder10000.witnesses.gz` | Generated by `scan-batch` (`3,815` verified witnesses) | `1ce4d0e21e423f5fae75495564d5544f8f32bea65d2f538ad61fdd3ad34d0f43` |

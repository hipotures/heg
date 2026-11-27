# Stage 2C Extension: Zero-Oracle Certified 86-Vertex Lower Bound for Cubic Bipartite Counterexamples ($n \le 84$)

**Date:** 2026-11-27  
**Hardware:** 16-core AMD Ryzen 9 7950X3D, 121 GiB RAM  
**Predecessor report (immutable):** [`M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md`](M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md)  
**Machine-readable evidence:** [`data/stage2c_cubic_bipartite_n84_summary.json`](data/stage2c_cubic_bipartite_n84_summary.json)

---

## 1. Main Theorem

> **Theorem (Certified 86-Vertex Lower Bound for Cubic Bipartite Graphs).**  
> Every finite simple 3-regular bipartite graph on $n \le 84$ vertices (at most $V = 42$ vertices per bipartition class) contains a simple cycle of length $4$, $8$, or $16$. Consequently,
> $$f_{\mathrm{cubic,bip}}(4) \ge 86.$$

Combined with our triple-certified and Lean 4-verified upper bound $f_{\delta \ge 3}(4) \le 73$ and Ripatti's non-bipartite cubic threshold $f_{\mathrm{cubic}}(4) = 78$, this strengthens the strict three-way extremal separation to **`+8` vertices** above $f_{\mathrm{cubic}}(4)$:
$$f_{\delta \ge 3}(4) \le 73 < 78 = f_{\mathrm{cubic}}(4) < 86 \le f_{\mathrm{cubic,bip}}(4).$$

This advances the certified cubic bipartite lower bound by **`+16` vertices** over Zhuge (`zenodo.21981786`, $n \le 68$, lower bound `70`) and by **`+26` vertices** over Tranquilli (`arXiv:2608.02675`, $n \le 58$, lower bound `60`).

> **Bonus Theorem (Girth-$\ge 10$ Branch through $n \le 88$).**  
> Every finite simple 3-regular bipartite graph of girth $\ge 10$ on $n \le 88$ vertices ($V \le 44$) contains a simple 16-cycle. In particular, any cubic bipartite counterexample to $\{C_4, C_8, C_{16}\}$-freeness on $n \le 88$ vertices **must contain a 6-cycle**.

---

## 2. Dynamic Adaptive Work-Stealing Zero-Oracle Engine (`cubic_bipartite_parallel.cpp`)

A naive static depth-split parallelization suffers from severe tail stragglers in skewed restricted-growth trees (e.g., at `--split-depth 7`, a single Orbit 2 subtree at `SIDE = 40` held ~40% of the work and `3.0 GiB` of certificate buffer on 1 core).

We implemented an **automatic dynamic work-stealing engine** in [`tools/extremal/cubic_bipartite_parallel.cpp`](../../tools/extremal/cubic_bipartite_parallel.cpp) that automatically adapts to `--workers W` (default: `std::thread::hardware_concurrency()`):

1. **Adaptive frontier expansion:** Workers pull shallow tasks from the front of a shared deque and split them 2 levels deeper whenever `queue.size() < 16 * W`, and pull deep tasks from the back (LIFO) once saturated.
2. **Soft-abort straggler re-splitting:** Whenever any running subtree exceeds `4,096` states while `queue.size() < 4 * W` **or** its witness buffer reaches `32 MiB`, it cleanly soft-aborts and re-splits 2 levels deeper, redistributing children to idle workers and capping per-thread RAM.
3. **100% end-to-end zero-oracle verification:** Every split step (`verify_split`) AND every leaf subtree (`verify_subtree`) emits explicit $C_8$ (3-block) and $C_{16}$ (7-block) witness byte streams that are immediately verified by an independent `ZeroOracleSubtreeVerifier` reconstructing the exact restricted-growth proposal schedule from the active block stack and checking both exact count equality and exact child-frontier equality.

### Exact Bit-for-Bit Cross-Check vs. Immutable Upstream Tranquilli (`67adc92d`)

| `SIDE` ($n_{\max}$) | Orbit | States | Attempted | Structural | $C_8$ | $C_{16}$ | Compl. | Wall time (16c) | Match vs. `67adc92d` |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 29 (58) | 1 | 1,405 | 106,964 | 7,184 | 63,526 | 34,850 | 0 | 0.003 s | **EXACT** |
| 29 (58) | 2 | 20,088 | 1,655,404 | 113,012 | 1,208,473 | 313,832 | 0 | 0.021 s | **EXACT** |
| 34 (68) | 1 | 23,143 | 2,972,750 | 180,011 | 1,424,785 | 1,344,812 | 0 | 0.061 s | **EXACT** |
| 34 (68) | 2 | 202,602 | 25,227,209 | 1,432,521 | 15,207,779 | 8,384,308 | 0 | 0.370 s | **EXACT** |
| 35 (70) | 1 | 51,974 | 7,282,166 | 441,386 | 3,199,099 | 3,589,708 | 0 | 0.140 s | **EXACT** |
| 35 (70) | 2 | 353,357 | 47,941,559 | 2,696,312 | 27,114,667 | 17,777,224 | 0 | 0.818 s | **EXACT** |

---

## 3. Branch A ($C_6$ / Berge-Triangle Branch): `SIDE = 40, 41, 42` ($n \le 80, 82, 84$)

Every run executed on 16 threads with full end-to-end zero-oracle verification enabled (`zero_oracle_verified=true`):

| `SIDE` ($n_{\max}$) | Orbit | States | Attempted proposals | Structural | $C_8$ witnesses | $C_{16}$ witnesses | Compl. | Verified splits / leaves (re-splits) | Zero-oracle cert stream | Wall time |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **40 (80)** | 1 | 1,763,196 | 354,095,363 | 18,070,520 | 148,081,803 | 186,179,845 | **0** | 2,477 / 9,048 (10) | 2.27 GB | 7.622 s |
| **40 (80)** | 2 | 12,393,295 | 2,606,532,806 | 135,470,813 | 1,036,826,697 | 1,421,842,002 | **0** | 5,366 / 23,584 (129) | 16.96 GB | 56.567 s |
| **40 (80)** | **Total** | **14,156,491** | **2,960,628,169** | **153,541,333** | **1,184,908,500** | **1,608,021,847** | **0** | **7,843 / 32,632 (139)** | **19.23 GB** | **64.192 s** |
| **41 (82)** | 1 | 3,111,947 | 618,690,795 | 31,187,384 | 281,123,347 | 303,268,118 | **0** | 3,027 / 9,488 (26) | 3.86 GB | 12.931 s |
| **41 (82)** | 2 | 30,997,584 | 7,353,663,962 | 373,859,991 | 2,860,026,335 | 4,088,780,053 | **0** | 5,354 / 60,535 (733) | 48.27 GB | 195.641 s |
| **41 (82)** | **Total** | **34,109,531** | **7,972,354,757** | **405,047,375** | **3,141,149,682** | **4,392,048,171** | **0** | **8,381 / 70,023 (759)** | **52.13 GB** | **208.575 s** |
| **42 (84)** | 1 | 5,517,089 | 1,141,100,929 | 56,503,556 | 567,886,245 | 511,194,040 | **0** | 3,400 / 15,330 (45) | 6.88 GB | 23.305 s |
| **42 (84)** | 2 | 73,104,843 | 19,186,516,084 | 936,237,621 | 7,358,733,813 | 10,818,439,808 | **0** | 8,591 / 110,231 (2,095) | 126.87 GB | 537.323 s |
| **42 (84)** | **Total** | **78,621,932** | **20,327,617,013** | **992,741,177** | **7,926,620,058** | **11,329,633,848** | **0** | **11,991 / 125,561 (2,140)** | **133.75 GB** | **560.633 s** |

Total wall time for all three new zero-oracle certified levels (`SIDE = 40, 41, 42`): **`833.4 s` (`13.89 min`)**.

---

## 4. Branch B (Girth-$\ge 10$ Moore-Tree Branch): Static Certificates `V = 41..44` ($n \le 82..88$)

Generated via [`tools/extremal/cubic_bipartite_girth10_cert_gen.cpp`](../../tools/extremal/cubic_bipartite_girth10_cert_gen.cpp) and independently verified (`G10_VERIFIED_OK`) by the zero-oracle verifier [`tools/extremal/cubic_bipartite_girth10_cert_verify.cpp`](../../tools/extremal/cubic_bipartite_girth10_cert_verify.cpp) (`V = 35..40` already certified in [`M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md`](M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md)):

| $V$ ($n_{\max}$) | States | Attempted | Structural | $C_6$ | $C_8$ | $C_{16}$ | Compl. | Static cert size | Gen time | Zero-oracle verify | Cert SHA-256 (prefix) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **41 (82)** | 122,678 | 21,779,839 | 960,350 | 5,771,896 | 12,326,772 | 2,598,144 | **0** | 86 MiB | 1.174 s | **0.588 s** | `f41833a64ef2...` |
| **42 (84)** | 151,270 | 30,152,223 | 1,310,846 | 7,802,760 | 14,160,948 | 6,726,400 | **0** | 135 MiB | 2.084 s | **0.910 s** | `e1f271e55f26...` |
| **43 (86)** | 430,471 | 66,385,632 | 3,039,214 | 16,168,760 | 23,969,780 | 22,777,408 | **0** | 334 MiB | 7.718 s | **2.227 s** | `ef24468e7199...` |
| **44 (88)** | 1,192,135 | 259,856,800 | 11,307,910 | 84,761,220 | 72,703,376 | 89,892,160 | **0** | 1.3 GiB | 28.747 s | **8.547 s** | `efef3c3b79e5...` |

---

## 5. Exact Reproduction Commands

```bash
# 1. Build dynamic work-stealing zero-oracle C6-branch verifier
g++ -O3 -march=native -std=c++17 -pthread tools/extremal/cubic_bipartite_parallel.cpp -o _build/cubic_bipartite_parallel

# Cross-check against Tranquilli 67adc92d
./_build/cubic_bipartite_parallel --side 29
./_build/cubic_bipartite_parallel --side 34
./_build/cubic_bipartite_parallel --side 35

# Reproduce n <= 80, 82, 84 (auto-detects all CPU cores; zero-oracle verified end-to-end)
./_build/cubic_bipartite_parallel --side 40
./_build/cubic_bipartite_parallel --side 41
./_build/cubic_bipartite_parallel --side 42

# 2. Build and verify girth >= 10 Moore-tree static certificates (V = 41..44, n <= 82..88)
g++ -O3 -march=native -std=c++17 tools/extremal/cubic_bipartite_girth10_cert_gen.cpp -o _build/g10_cert_gen
g++ -O3 -march=native -std=c++17 tools/extremal/cubic_bipartite_girth10_cert_verify.cpp -o _build/g10_cert_verify
for V in 41 42 43 44; do
  ./_build/g10_cert_gen --side $V --out _build/g10_v${V}.cert
  ./_build/g10_cert_verify _build/g10_v${V}.cert
done
```

# Native Rust Engine CLI (`sglab-rust-engine`)

This page documents the subcommands, flags, contracts, and verification boundaries of `_build/sglab-rust-engine` (`rust/sglab-engine/`).

Build in release mode:

```bash
cargo build --release --manifest-path rust/sglab-engine/Cargo.toml
cp rust/sglab-engine/target/release/sglab-rust-engine _build/sglab-rust-engine
```

---

## Subcommands Overview

| Subcommand | Order Limit | Exactness / Authority | Purpose |
|---|---:|---|---|
| `verify-exact` | `n <= 128` | Exact (`C4, C8, C16` MitM + `C32, C64` Frontier DP / BnR) | Fast exact cycle verification (not M4; use M4 `sglab-cyclecheck` for formal certification) |
| `verify-large` | `n <= 512` | Exact (16-core canonical-start `[u64; 8]` MitM + release witness check) | Exact even-cycle verification for `128 < n <= 512` (see [ADR 0019](../adr/0019-large-order-exact-cycle-verification.md)) |
| `scan-batch` | `n <= 16,384` | Exact MitM (`C4..C32`) + guided MitM (`C64+`) + release witness check | High-throughput parallel census scanner (`g6`, `s6`, `psv-tsv`, `conder-edges`) with general & vertex-transitive modes and witness stream output |
| `lns-polish` | `n <= 128` | Exact `C4=C8=0` repair + exact MitM `C16` scoring | 16-core Exact-Matching Micro-LNS with optional RRT (`--rrt-slack`) and bipartition preservation (`--bipartite`) |
| `voltage-search` | `n <= 128` | Exhaustive (small groups) or parallel Tabu + exact `C4,C8,C16` | Non-abelian, non-nilpotent bipartite cubic voltage-lift search |
| `bjorklund-c32` | `n <= 128` (bipartite) | **One-sided Monte Carlo** ($\mathrm{GF}(2^{16})$ `PCLMULQDQ` narrow sieve) | Fast `C32` witness detection; `found=true` implies `C32` exists, `found=false` is **NOT** a deterministic proof of absence |
| `search` | `n <= 128` | Heuristic (ILS/Tabu/SA + optional LNS) | Multi-worker heuristic search over `cubic_first`, `minimal_structure_mixed_degree`, `unrestricted_min_degree_3`, `single_block_41` |
| `score` | `n <= 128` | Capped cycle counting | Heuristic score inspection for a single `graph6` string |
| `--serve` | `n <= 128` | Persistent JSON-line worker | Host-managed persistent scorer/search bridge |

---

## `verify-large`

Exact parallel even-cycle existence verifier for simple graphs of order `n <= 512` using 512-bit (`[u64; 8]`) bitmasks and canonical-start Meet-in-the-Middle.

```bash
_build/sglab-rust-engine verify-large \
  (--graph6 <G6> | --graph6-file <PATH>) \
  [--lengths 4,8,16,32] \
  [--workers 16]
```

- **Strict input validation (exit code `2`)**:
  - `--lengths` must be a non-empty comma-separated list of even integers `>= 4`. Malformed tokens, odd lengths, or lengths `< 4` exit immediately with code `2`.
  - `graph6` strings are checked for exact expected byte length (trailing garbage bytes or truncated payloads fail with exit code `2`).
- **Runtime witness check**: every reported `FOUND` cycle is verified in release builds (`verify_witness_runtime`: exact length, pairwise distinct vertices, and all cycle edges present).
- **Certification boundary**: `verify-large` is an independent exact verifier for `128 < n <= 512`. Following [ADR 0019](../adr/0019-large-order-exact-cycle-verification.md), certificates at `n > 128` must be cross-checked by at least two independent exact implementations (e.g., `verify-large` + `tools/extremal/sglab_cyclecheck_large.cpp`).

---

## `lns-polish`

16-core shared-champion Exact-Matching Micro-LNS destroy-and-repair over the `C4 = C8 = 0` manifold (`u64` for `n <= 64`, `u128` for `64 < n <= 128`).

```bash
_build/sglab-rust-engine lns-polish \
  --graph6 <G6> \
  --mode <cubic_first|minimal_structure_mixed_degree|unrestricted_min_degree_3|single_block_41> \
  [--k-min 4] [--k-max 8] \
  [--wall-seconds 60] [--workers 16] \
  [--node-cap 50000] \
  [--rrt-slack 0] \
  [--bipartite] \
  [--seed 1]
```

- Destroys `k in [k_min, k_max]` pairwise-disjoint hot/cluster edges (`2k <= 16` boundary ports), precomputes external path lengths `<= 7`, and solves exact `C4 = C8 = 0` 2-connected repairs via MRV branch-and-bound scored by exact Bitset MitM `C16`.
- `--rrt-slack <u32>`: Record-to-Record Travel acceptance threshold (`c16 <= global_best + rrt_slack`), allowing controlled escape from local basins.
- `--bipartite`: Hard-prunes same-side port pairings during repair so every accepted graph remains strictly bipartite.
- Stops immediately via an atomic flag if `best_c16 == 0` is reached.

---

## `voltage-search`

Searches bipartite cubic voltage lifts over base graphs (`theta2`, `theta4`, `k33`, `theta6`, `cube8`, `mobius10`) and finite non-abelian, non-nilpotent groups (`d6`, `a4`, `d7`, `d9`, `d10`, `f20`, `s4`, `d14`, `d15`, `d12`, `d18`, `d20`, `d21`, `d24`, `d30`, `a5`, `sl23`, `a4c2`, `s3c4`, `s3c6`, `f42`).

```bash
_build/sglab-rust-engine voltage-search \
  --base <BASE> --group <GROUP> \
  [--steps 50000] [--workers 16] [--seed 1]
```

- Automatically runs **100% exhaustive** enumeration when `|G|^(e_free)` is below the exhaustive threshold (e.g., `theta2` and `theta4`), and parallel Tabu search otherwise.
- Reports `exhaustive: true|false`, `evaluated_lifts`, `valid_lifts`, `c4_c8_zero_hits`, `c4_c8_c16_zero_hits`, `best_c4/c8/c16`, and `best_c32_flag`.

---

## `bjorklund-c32`

Hardware-accelerated (`x86-64 PCLMULQDQ`) Björklund narrow sieve over $\mathrm{GF}(2^{16})$ for detecting even cycles (default `length = 32`) in bipartite graphs (`n <= 128`).

```bash
_build/sglab-rust-engine bjorklund-c32 \
  --graph6 <G6> [--length 32] [--rounds 2] [--workers 16]
```

- **Exactness contract**:
  - `found: true` is **zero-false-positive** (a non-zero polynomial evaluation proves at least one simple cycle of that length exists).
  - `found: false` is **probabilistic** (false-negative probability $\le (L / 2^{16})^{\text{rounds}}$, e.g. $< 2.4 \times 10^{-7}$ for `L = 32, rounds = 2`). Never cite `found: false` as a deterministic proof of absence; run `verify-exact`, `verify-large`, or M4 (`sglab-cyclecheck`) to certify absence.

---

## `verify-exact`

Exact cycle verification for `n <= 128` combining Bitset MitM (`C4, C8, C16`) with exact Frontier DP and Branch-and-Reduce (`C32, C64`).

```bash
_build/sglab-rust-engine verify-exact --graph6 <G6>
```

Returns JSON with exact `c16_exact_count`, `lengths` (`"ABSENT"` or `"FOUND"` for `4, 8, 16, 32, 64`), and Frontier DP statistics. For formal counterexample certification (`n <= 128`), M4 (`cpp/sglab_cyclecheck.cpp`) remains the sole certification authority ([ADR 0004](../adr/0004-m4-certification-authority.md)).

---

## `scan-batch`

High-throughput multi-threaded batch scanner for large graph censuses (`graph6`, `sparse6`, `psv-tsv`, and `conder-edges`) up to `n <= 16,384`, emitting runtime-verified cycle witness streams and JSON summaries.

```bash
_build/sglab-rust-engine scan-batch \
  --input (<PATH> | -) \
  --format <g6|s6|psv-tsv|conder-edges> \
  --mode <general|vertex-transitive> \
  [--lengths 4,8,16,32,64,...] \
  [--workers 16] \
  [--expect-cubic] \
  [--max-order <N>] \
  [--witness-out <PATH>] \
  [--exceptions-out <PATH>] \
  [--exception-min-len 32] \
  [--summary-json <PATH>]
```

- **`--mode general`**: checks all canonical minimum vertices (`u64` fast path for `n <= 64, L <= 16`; bloom-accelerated exact MitM for `L <= 32`; guided MitM for `L >= 64`).
- **`--mode vertex-transitive`**: searches only cycles containing vertex `0` (exact for minimum cycle length on vertex-transitive graphs, yielding up to `n×` speedup). Every emitted positive cycle witness is independently verified in release builds (`verify_cycle_witness`) and can be cross-checked 1-to-1 against the raw input by `tools/extremal/verify_witness_stream.py`.

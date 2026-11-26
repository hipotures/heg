# M6 Wave D1 Report: Exact-Matching Micro-LNS Destroy-and-Repair (`C4 = C8 = 0`, 2026-11-26)

## Scope

Wave D1 implements Priority 4 (LNS Destroy-and-Repair) from `docs/deep-research/Badania nad Hipotezą Erdősa–Gyárfása.md` as a zero-dependency native Rust solver (`rust/sglab-engine/src/lns.rs`) wired into both standalone `sglab-rust-engine lns-polish` and opt-in `search --lns-interval <N>`:

1. **Exact `C16` Edge-Participation Heat (`compute_c16_edge_heat_u64`)**: Computes exact `w_16(e)` for every edge in ~40 µs via Bitset MitM.
2. **Destroy Operator**: Alternates between hot-edge tournament selection and radius-2 local ball-cluster destruction of `k in [k_min, k_max]` (`4..=8`) pairwise-disjoint edges (`2k <= 16` open boundary ports).
3. **External Path-Length Pre-Filter + MRV Exact Perfect-Matching B&B**:
   - Computes `L_ext(p, q) <= 7` bitmasks in frozen remainder `G_rest` (~25 µs), hard-forbidding any port pair closing a `C4` (`d = 3`) or `C8` (`d = 7`).
   - Explores all legal perfect matchings via Minimum Remaining Values (MRV) fail-first branching with incremental ~5 ns `C4` and ~300 ns `C8` edge-placement pruning.
   - Scores every complete `C4 = C8 = 0`, strictly 2-connected, mode-valid leaf with exact early-aborting Bitset MitM `C16`.
4. **Parallel Shared-Champion LNS Polish (`run_parallel_lns_polish`)**: 16 worker threads share the global `(best_c16, best_graph)` champion while traversing flat `C4 = C8 = 0` plateaus via tabu-guarded sideways repairs.

## Verification Gates

- `cargo test --release --manifest-path rust/sglab-engine/Cargo.toml`: **14/14 passed** (`0` warnings), including `lns::tests::lns_destroy_and_repair_preserves_c4_c8_zero_and_strict_2connectivity`.
- `make rust-engine`: clean native release build (`0` warnings).
- `PYTHONPATH=src python3 -m unittest tests.test_rust_engine -v`: **7/7 passed** (`--serve` protocol v2 parity intact).

## Experiment 9: 16-Core Micro-LNS Polish on Top Phase 1–3 Champions

Evaluated **`689,125,602` exact `C4 = C8 = 0` strictly 2-connected repair leaves** in `~100 s` (~`7M` exact multi-edge repairs/sec across 16 cores). Every result was independently certified by both M4 (`_build/sglab-cyclecheck`) and Wave C `verify-exact`.

| Champion | Order `n` | Mode | Before LNS `C16` | **After LNS `C16`** | Reduction | Exact LNS Leaves Tested | `verify-exact` Time | Certified Absent |
|---|---:|---|---:|---:|---:|---:|---:|---|
| `lns_cubic_n62` | 62 | cubic (1-block, 0 bridges) | `44` | **`17`** | **`-61.4%`** | `98,235,744` | `0.5 ms` | `[4, 8]` |
| `lns_cubic_n60` | 60 | cubic (1-block, 0 bridges) | `65` | **`23`** | **`-64.6%`** | `100,135,186` | `0.5 ms` | `[4, 8]` |
| `lns_cubic_n64` | 64 | cubic (1-block, 0 bridges) | `32` | **`24`** | **`-25.0%`** | `91,476,449` | `0.6 ms` | `[4, 8]` |
| `lns_cubic_n58` | 58 | cubic (1-block, 0 bridges) | `93` | **`44`** | **`-52.7%`** | `77,839,105` | `0.4 ms` | `[4, 8]` |
| `lns_cubic_n50` | 50 | cubic (1-block, 0 bridges) | `136` | **`77`** | **`-43.4%`** | `70,404,133` | `0.4 ms` | `[4, 8]` |
| `lns_cubic_n54` | 54 | cubic (1-block, 0 bridges) | `71` | `71` | `0.0%` | `74,004,847` | `0.4 ms` | `[4, 8]` |
| `lns_sb41_k23..k35` | 23..35 (`n=45..69`) | `single_block_41` | `111..138` | `111..138` | `0.0%` | `177,024,338` | `0.0–0.1 ms` | `[4, 8, 32]` / `[4, 8, 64]` |

### Key Takeaway

Multi-edge Exact-Matching Micro-LNS (`k = 4..8`) shattered every 1-block cubic `n = 50, 58, 60, 62, 64` plateau where 2-edge and 3-edge switches had stalled, cutting strictly 2-connected `C4 = C8 = 0` exact `C16` down to **`17`** at `n = 62` (`76×` below random), **`23`** at `n = 60`, and **`24`** at `n = 64` (`58.5×` below random). No counterexample was found.

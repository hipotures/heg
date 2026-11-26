# Rust Engine HEG Research Experiments 1–4 (2026-11-26)

Date: **2026-11-26**  
Engine: `_build/sglab-rust-engine` (Wave 13, commit `336a961`)  
Authority verifier: **M4** (`_build/sglab-cyclecheck`)  
Host: AMD Ryzen 9 7950X3D (16 physical cores)

## Summary of Key Scientific Findings

1. **Sharp phase transition & bridge-cheating degeneracy in `cubic_first`**:
   - On `n = 50` (`cap = 512`, `node_budget = 250_000`), `cubic_first` broke out of the `C16=C32=cap` plateau all the way down to **`total = 6`** (`4:5, 8:1, 16:0, 32:0`, M4-certified absent `[16, 32]`), but structural block decomposition revealed **11 biconnected blocks** (`[16, 7, 7, 7, 7, 6, 2, 2, 2, 2, 2]`, 5 bridges).
   - On `n = 64` (`cap = 64`), both `ILS-tabu` (739k ev/s) and `SA` (552k ev/s) found **`total = 129`** (`4:1, 8:0, 16:64, 32:64, 64:0`), which decomposed into **3 blocks** (`[57, 7, 2]`: one bridge to a 7-vertex cubic lollipop that forces `C64 = 0` and at least one `C4`).
   - This empirically validates the necessity of the **Ducoffe–Dumitru (`arXiv:2609.28594`, Sept 2026) `blocks <= 2` constraint** (`minimal_structure_mixed_degree`), which eliminates multi-bridge cheating paths.

2. **Genuine 2-block 1-clique-sums in `minimal_structure_mixed_degree` beat `cubic_first` at `n = 32` and `n = 36`**:
   - At `n = 32`, `minimal_structure_mixed_degree` reached **`total = 4`** (`4:3, 8:1, 16:0, 32:0`, M4-certified absent `[16, 32]`) as a bridge-free 1-clique-sum of two biconnected blocks `[18, 15]` (3/3 seeds formed valid 2-block structures).
   - At `n = 36`, `minimal_structure_mixed_degree` broke the `128` plateau where `cubic_first` was stuck (0/3 seeds), reaching **`total = 29`** (`4:5, 8:12, 16:12, 32:0`, M4-certified absent `[32]`) as a bridge-free 2-block 1-clique-sum `[25, 12]`.

3. **Saturation plateau for `n >= 38` from random 1-block seeds**:
   - Starting from random 1-block expanders at `cap = 64` (`n = 35..48` in Exp 1; `n = 40, 44, 48` in Exp 3; `n = 50..60` at `cap = 256` in Exp 2), search eliminates `C4` and `C8` within <0.2 s and stalls on `C16 = cap, C32 = cap` due to zero gradient.
   - Raising `cap` (`n = 50`, `cap = 512`) or seeding directly with valid 2-block 1-clique-sums (each block `< 32` vertices guarantees `C32 = 0` for `n <= 62`) restores gradient.

4. **Experiment 4 — 16-lane durable `sglab` campaign (`--engine-backend rust`, `passive`)**:
   - Campaign `campaign-defbfc5f2bf8485faeef021912454ac3` executed **19,650,000 evaluations in 35 s** (~561k ev/s end-to-end through `LaneManager`, SQLite checkpoints, and M4 verification of 24 promoted candidates at `n = 20`, best `4:4, 8:0, 16:0`, zero orphan processes).
   - **Operational finding (Python race, untouched per scope)**: `src/sglab/resources.py:40` (`current_rss_bytes`) raised unhandled `ProcessLookupError` when a short-lived Rust micro-batch subprocess exited concurrently with `/proc/<pid>/status` inspection during `snapshot.publish()`, cleanly transitioning the campaign to `paused_fault` without data loss.

## Experiment 1 — Transition-Zone Scan (`n = 32..48`, 16 cores, `ILS-tabu`, `2.5 s`/point, `cap = 64`)

| `n` | Mode | ev/s | Best Total | Complete | Counts (`C4,C8,C16,C32`) | Blocks | Girth | M4 Absent |
|---:|---|---:|---:|:---:|---|---:|---:|---|
| 32 | `cubic_first` | 3,755,106 | 3 | Y | `4:3, 8:0, 16:0, 32:0` | 5 | 3 | `8, 16, 32` |
| 32 | `minimal_structure_mixed_degree` | 2,123,957 | 5 | Y | `4:4, 8:1, 16:0, 32:0` | 2 | 3 | `16, 32` |
| 33 | `minimal_structure_mixed_degree` | 77,699 | 33 | Y | `4:2, 8:10, 16:21, 32:0` | 2 | 3 | `32` |
| 34 | `cubic_first` | 107,703 | 32 | Y | `4:4, 8:10, 16:18, 32:0` | 5 | 3 | `32` |
| 34 | `minimal_structure_mixed_degree` | 105,880 | 128 | N | `4:0, 8:0, 16:64, 32:64` | 1 | 3 | `4, 8` |
| 35–48 | both modes (21 points) | 202k–3.29M | 128 | N | `4:0, 8:0, 16:64, 32:64` | 1 | 3 | `4, 8` |

## Experiment 2 — Plateau Breaking (`n = 50, 56, 60, 64`, 16 cores, `cubic_first`)

| `n` | Algorithm | `cap` | `node_budget` | ev/s | Best Total | Counts | Block Sizes | M4 Absent |
|---:|---|---:|---:|---:|---:|---|---|---|
| 50 | ILS-tabu | 64 | 50,000 | 3,542,080 | 128 | `4:0, 8:0, 16:64, 32:64` | `[50]` | `4, 8` |
| 50 | ILS-tabu | 256 | 150,000 | 392,837 | 512 | `4:0, 8:0, 16:256, 32:256` | `[50]` | `4, 8` |
| 50 | ILS-tabu | 512 | 250,000 | 223,530 | **6** | `4:5, 8:1, 16:0, 32:0` | `[16,7,7,7,7,6,2,2,2,2,2]` | `16, 32` |
| 50 | SA | 256 | 150,000 | 380,633 | 512 | `4:0, 8:0, 16:256, 32:256` | `[50]` | `4, 8` |
| 56 | ILS-tabu | 256 | 150,000 | 451,934 | 512 | `4:0, 8:0, 16:256, 32:256` | `[56]` | `4, 8` |
| 60 | ILS-tabu / SA | 256 | 150,000 | 476,517 / 468,046 | 512 | `4:0, 8:0, 16:256, 32:256` | `[60]` | `4, 8` |
| 64 | ILS-tabu / SA | 64 | 50,000 | 738,822 / 551,654 | **129** | `4:1, 8:0, 16:64, 32:64, 64:0` | `[57, 7, 2]` | `8` (`64` timeout) |
| 64 | ILS-tabu | 256 | 150,000 | 16,626 | 768 | `4:0, 8:0, 16:256, 32:256, 64:256` | `[64]` | `4, 8` |

## Experiment 3 — Controlled Class Comparison (3 seeds × matched evals, 16 cores, `ILS-tabu`, `cap = 64`)

| `n` | Evals/run | `cubic_first` best / med | `ducoffe_mixed` best / med | `ducoffe` best structure |
|---:|---:|---:|---:|---|
| 32 | 4,800,000 | `3 / 3.0` (`[18,7,7,2,2]`) | **`4 / 4.0`** (`[18, 15]`) | `4:3, 8:1, 16:0, 32:0` (M4 absent: `16, 32`) |
| 36 | 4,000,000 | `128 / 128.0` (`[36]`) | **`29 / 128.0`** (`[25, 12]`) | `4:5, 8:12, 16:12, 32:0` (M4 absent: `32`) |
| 40 | 3,200,000 | `128 / 128.0` | `128 / 128.0` | 1-block plateau |
| 44 | 3,200,000 | `128 / 128.0` | `128 / 128.0` | 1-block plateau |
| 48 | 3,200,000 | `128 / 128.0` | `128 / 128.0` | 1-block plateau |
| 64 | 960,000 | `129 / 192.0` (`[57,7,2]`) | `192 / 192.0` (`[64]`) | 1-block plateau (`cubic` 129 violates `blocks <= 2`) |

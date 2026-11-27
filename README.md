# Structural Graph Conjecture Lab

Structural Graph Conjecture Lab (`sglab`) is a Linux research system for
reproducible searches for finite counterexamples to structural graph
conjectures. Its implemented research target is the Erdős–Gyárfás conjecture:

> Every finite simple graph with minimum degree at least 3 contains a simple
> cycle whose length is a power of two.

The project is an engineering and experimentation system. It does not claim
that the conjecture has been resolved.

## What the system does

- runs bounded graph-search lanes with deterministic checkpoints;
- uses an AI Research Director to choose reviewed search actions;
- keeps the Director stateless and supplies a bounded scientific-memory
  snapshot on every turn;
- retains promising candidates and protects candidate references with immutable
  snapshots and pins;
- submits finalists to independent Python and C++ exact verifiers;
- certifies success only through the M4 two-path verification boundary;
- stores durable state in a workspace-local SQLite database;
- exposes a local dashboard for campaigns, attempts, lanes, candidates,
  verification, comparisons, and live scientific visualizations;
- resumes the same scientific campaign through new execution attempts, with
  optional resource changes.

## Verified research results & Lean 4 formalization

While the Erdős–Gyárfás conjecture remains open, this repository includes
reproducible computational witnesses, SAT/DRAT UNSAT proofs, and a
**zero-dependency Lean 4 (`v4.36.0`) kernel-checked formalization** (`lean/`,
`6,903` lines, zero Mathlib, zero `sorry`, zero custom axioms, zero
`native_decide`) of our extremal bounds on finite simple graphs avoiding
$\lbrace C_4, C_8, \dots, C_{2^k}\rbrace$:

| Result | Construction / Scope | Verification |
|---|---|---|
| ${f_{\delta \ge 3}(4) \le 73}$ | Two distinct 2-connected witnesses: `Petersen + 3·H_8* + 7·H_7` and `Petersen + 1·U_1 + 9·H_8*` | M4 C++17, Rust `verify-exact`, Python DFS, Lean 4 (`f_delta3_4_le_73`, `f_delta3_4_le_73_alt`, `pet73v{1,2}_is2Connected`) |
| ${f_{\mathrm{cubic}}(4) \le 78}$ | 3-regular, 2-connected `Petersen + 1·H_15 + 9·H_7` (matches Ripatti `f_cubic(4) = 78`) | Lean 4 (`f_cubic_4_le_78`, 2-connected + `IsCubic`) |
| ${f_{\mathrm{cubic}}(5) \le 370}$ | 3-regular, 2-connected `Tutte–Coxeter + 20·H_15 + 10·H_7` (independently rediscovered; prior preprint K. Henry, Zenodo `23886386`, 3 Nov 2026) | Rust `verify-large`, C++17 exact DFS, Lean 4 (`f_cubic_5_le_370`, `tc370_is2Connected`) |
| ${f_{\delta \ge 3}(5) \le 345}$ | 2-connected `Tutte–Coxeter + 15·H_15 + 15·H_8*` | Rust `verify-large`, C++17 exact DFS, Lean 4 (`f_delta3_5_le_345`, `tc345_is2Connected`) |
| ${f_{\mathrm{cubic}}(6) \le 10{,}498}$ (unconditional) | Embedded `k3_g16_n702.g6` (kernel-proved girth `16` via 2-gen transitive automorphisms + Tree-Ball BFS) + source 8-packing ($\lvert S_8\rvert = 4$); also $\le 29{,}728$ on `k3_g17_n2048.g6` and general 4-packing $\le 15 N - 8\lceil N/46\rceil$ | **Unconditional Lean 4** (`f_cubic_6_le_10498`, `k3_g16_n702_girth16`, `f_cubic_6_source_8packing`, `f_cubic_6_4packing`), `verify_high_girth_f6.py` |
| Tutte–Coxeter exact minima<br>$({\lbrace H_{15}, H_8^*, H_7\rbrace})$ | **Exact equality**: **`370`** (cubic, `n = 362` all `56/56` cubes `UNSAT`) and **`345`** ($\delta \ge 3$, `n = 342..344` `UNSAT`); exact double-counting $8 a_{15} - 4 b_8 - 8 c_7 \ge 45$ over all 90 8-cycles | Lean 4 (`tc_double_counting_bound`, `tc_delta3_lt_345_cases`, `tc_slack_card_n362_cubic`, `tc_slack_card_mixed3_delta3`), CaDiCaL 2.1.3 + official `drat-trim` (`s VERIFIED`) |
| Certified cubic graph censuses | All `1,436,474` cubic girth $\ge 9$ ($n = 58..64$: 100% $C_{16}$); all `111,705` PSV VT ($n \le 1280$: 100% $\le C_{32}$); all `3,815` Conder symmetric ($n \le 10{,}000$: 100% $\le C_{32}$); all 3 $(3,10)$-cages ($n = 70$: M4 + Lean 4 $C_{16}$) | Rust `scan-batch` + 100% independent Python witness-stream verifier (`verify_witness_stream.py`) + M4 + Lean 4 (`cage310_{1,2,3}_certified`) |
| ${f_{\mathrm{cubic,bip}}(4) \ge 86}$ | Every cubic bipartite graph on $n \le 84$ vertices contains $C_4, C_8,$ or $C_{16}$ (`+16` vs Zhuge `70`, `+26` vs Tranquilli `60`; girth-$\ge 10$ branch certified through $n \le 88$), proving $f_{\delta \ge 3}(4) \le 73 < 78 = f_{\mathrm{cubic}}(4) < 86 \le f_{\mathrm{cubic,bip}}(4)$ | **Lean 4 reduction & witness soundness** (`bipartite_no_c4_c8_dichotomy`, `c6_two_orbit_dichotomy`, `girth10_moore_tree_62`, `check_c{6,8,16}_witness_sound`) + dynamic work-stealing zero-oracle $C_6$ verifier (`20.33B` proposals / `133.75 GB` verified stream at `SIDE=42`) + static girth-$\ge 10$ certs (`V=35..44`) |

Build and audit the Lean 4 proofs locally:

```bash
cd lean
lake build
```

See [lean/README.md](lean/README.md) for the module map and `#print axioms`
audit command, the
[Master Synthesis Report](docs/reports/M6_OVERNIGHT_10H_GOAL_SYNTHESIS_2026_11_27.md),
the
[Stage 1 Certified Censuses & Tutte–Coxeter Closure Report](docs/reports/M6_STAGE1_CERTIFIED_CENSUSES_AND_TC_CLOSURE_2026_11_27.md),
and the
[Stage 2C Cubic Bipartite 86-Vertex Lower Bound Report](docs/reports/M6_STAGE2C_EXTENSION_86_LOWER_BOUND_2026_11_27.md)
(extending [`M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md`](docs/reports/M6_STAGE2C_CUBIC_BIPARTITE_80_LOWER_BOUND_2026_11_27.md),
with graph6 certificates under `docs/reports/certificates/` and reproducible
solvers under `tools/extremal/`) for the full experimental record.

## Documentation entry points

| You are… | Start here |
|---|---|
| Checking formal Lean 4 proofs | [Lean 4 formalization](lean/README.md) |
| Reading extremal bounds & research status | [Research status](docs/00_RESEARCH_STATUS.md) and [Master synthesis report](docs/reports/M6_OVERNIGHT_10H_GOAL_SYNTHESIS_2026_11_27.md) |
| Running experiments | [User guide](docs/user/README.md) |
| Operating a server | [Operator guide](docs/operator/README.md) |
| Understanding the design | [Architecture](docs/architecture/README.md) |
| Looking up a command or state | [Reference](docs/reference/README.md) |
| Changing the code with Codex | [AGENTS.md](AGENTS.md) and [Codex guide](docs/codex/README.md) |
| Reviewing implementation evidence | [Reports](docs/reports/README.md) |

## Installation

Python 3.12 or newer and a C++17 compiler are required.

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
make cyclecheck
```

Optional SAT and reference packages:

```bash
uv pip install -e '.[sat,reference]'
```

Verify the installation:

```bash
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

## First campaign

Create a workspace and prepare a bounded campaign:

```bash
sglab init --workspace ./workspace
sglab research-campaign prepare   --workspace ./workspace   --time-limit 1h
```

Preparation creates a campaign ID, an immutable plan, and a plan fingerprint
without reading credentials or calling a model. Review the plan before
authorizing it.

Start the local dashboard in another terminal:

```bash
sglab serve   --workspace ./workspace   --host 127.0.0.1   --port 8788
```

Continue with the [campaign quickstart](docs/user/quickstart.md).

## Core safety boundary

A heuristic score is not a mathematical result. A candidate becomes
`COUNTEREXAMPLE_VERIFIED` only when the exact M4 verification boundary records
complete agreement from the independent verifier paths. A timeout, memory
limit, malformed artifact, or verifier disagreement is never treated as proof
of cycle absence.

## Repository status

See [Implementation Status](docs/IMPLEMENTATION_STATUS.md) for the current
schema, completed gates, known limitations, and links to evidence reports.

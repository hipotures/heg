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
`3,849` lines, zero Mathlib, zero `sorry`, zero custom axioms, zero
`native_decide`) of our extremal bounds on finite simple graphs avoiding
$\lbrace C_4, C_8, \dots, C_{2^k}\rbrace$:

| Result | Construction / Scope | Verification |
|---|---|---|
| ${f_{\delta \ge 3}(4) \le 73}$ | Two distinct 2-connected witnesses: `Petersen + 3·H_8* + 7·H_7` and `Petersen + 1·U_1 + 9·H_8*` | M4 C++17, Rust `verify-exact`, Python DFS, Lean 4 (`f_delta3_4_le_73`, `f_delta3_4_le_73_alt`) |
| ${f_{\mathrm{cubic}}(5) \le 370}$ | 3-regular, 2-connected `Tutte–Coxeter + 20·H_15 + 10·H_7` | Rust `verify-large`, C++17 exact DFS, Lean 4 (`f_cubic_5_le_370`) |
| ${f_{\delta \ge 3}(5) \le 345}$ | 2-connected `Tutte–Coxeter + 15·H_15 + 15·H_8*` | Rust `verify-large`, C++17 exact DFS, Lean 4 (`f_delta3_5_le_345`) |
| ${f_{\mathrm{cubic}}(6)}$ via 4-packing | Any cubic base of order $N$ and girth $\ge 17$ lifts to order $\le 15 N - 8 \lceil N / 46 \rceil$ ($\le 30{,}360$ at $N = 2048$) | Lean 4 (`f_cubic_6_4packing`, `f_cubic_6_4packing_N2048`) |
| Tutte–Coxeter lower bounds<br>$({\lbrace H_{15}, H_8^*, H_7\rbrace})$ | Exact double-counting $8 a_{15} - 4 b_8 - 8 c_7 \ge 45$ over all 90 8-cycles; $a_{15} \ge 18$ cubic, $a_{15} \ge 14$ general; DRAT slack-bound soundness: $\le 6$ slack cycles at $n \in \lbrace 354, 338\rbrace$ | Lean 4 (`tc_double_counting_bound`, `tc_slack_card_sound`), independent SAT/DRAT & CaDiCaL UNSAT proofs |

Build and audit the Lean 4 proofs locally:

```bash
cd lean
lake build
```

See [lean/README.md](lean/README.md) for the module map and `#print axioms`
audit command, and the
[Master Synthesis Report](docs/reports/M6_OVERNIGHT_10H_GOAL_SYNTHESIS_2026_11_27.md)
(with graph6 certificates under `docs/reports/certificates/` and reproducible
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

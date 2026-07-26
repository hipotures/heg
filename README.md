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

## Documentation entry points

| You are… | Start here |
|---|---|
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

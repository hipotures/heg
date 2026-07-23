# Structural Graph Conjecture Lab

A specification bundle and runnable starter scaffold for building a small, fast research system that searches for finite counterexamples to structural graph conjectures.

## Research decision

The phrase "structural graph problems" describes a class of problems, not one conjecture. This bundle therefore implements a reusable target interface and selects one default pilot target:

**Erdős–Gyárfás conjecture**

> Every finite simple graph with minimum degree at least 3 contains a simple cycle whose length is a power of two.

As of **2026-07-23**, the general conjecture is still presented as open in a May 2026 structural preprint. A recent public SAT repository claims exhaustive verification through 31 vertices, so this project must not repeat that range as a novel result. The initial research frontier is heuristic search at order 32 and above, together with independent reproduction of smaller validation gates.

## What is included

- a current-status research note;
- a concrete target specification for Erdős–Gyárfás;
- architecture, algorithms, exact-verification, resource-safety, benchmarking, and operations documents;
- a complete Codex CLI implementation prompt;
- `AGENTS.md` project instructions;
- a minimal Python scaffold with:
  - bitset graph representation,
  - a slow reference cycle verifier,
  - atomic state files,
  - a standard-library HTTP dashboard,
  - a system/tool doctor command;
- Linux bootstrap scripts for Ubuntu/Debian and Arch/Manjaro;
- a strict, small test plan.

The scaffold is intentionally not a finished search engine. Codex is expected to implement the milestones in `CODEX_PROMPT.md`.

## Fast start

```bash
unzip structural_graph_lab_codex_bundle_v1.zip
cd structural_graph_lab_codex_bundle_v1

# Review the task and current research status.
less CODEX_PROMPT.md
less docs/00_RESEARCH_STATUS.md

# Optional: verify that the starter scaffold works.
python -m unittest discover -s tests -v
PYTHONPATH=src python -m sglab doctor
PYTHONPATH=src python -m sglab init --workspace ./workspace
PYTHONPATH=src python -m sglab serve --workspace ./workspace --port 8080
```

Then open Codex in the repository and paste `CODEX_PROMPT.md`, or run a non-interactive implementation pass:

```bash
codex exec -C "$PWD" "$(cat CODEX_PROMPT.md)"
```

For a large implementation, interactive Codex is preferable because milestone reviews should occur between stages.

## Design constraints

- Python is the orchestration language.
- Hot graph operations may use one small C++17 helper executable.
- No React, Node.js, Django, FastAPI, Celery, Redis, Kubernetes, ORM, or distributed framework.
- The HTTP dashboard uses the Python standard library and periodic JSON polling.
- No LLM call in the inner search loop.
- No claim of a counterexample without two independent exact verifiers.
- No claim of exhaustive nonexistence from a timeout.
- Do not store every candidate graph.
- Tests target correctness boundaries, not line-by-line coverage.

## Recommended reading order

1. `docs/00_RESEARCH_STATUS.md`
2. `docs/01_SCOPE_AND_GOALS.md`
3. `docs/03_TARGET_ERDOS_GYARFAS.md`
4. `docs/02_ARCHITECTURE.md`
5. `docs/04_ALGORITHMS.md`
6. `docs/05_EXACT_VERIFICATION.md`
7. `docs/06_RESOURCE_SAFETY.md`
8. `docs/07_BENCHMARKING.md`
9. `docs/08_HTTP_DASHBOARD.md`
10. `CODEX_PROMPT.md`

## Important limitation

A search that finds nothing has not proved the conjecture. A SAT run that is interrupted, killed, or times out has not proved UNSAT. Research outputs must distinguish:

- `COUNTEREXAMPLE_VERIFIED`,
- `UNSAT_CERTIFIED`,
- `NO_RESULT_WITHIN_BUDGET`,
- `VERIFIER_TIMEOUT`,
- `INVALID_CANDIDATE`,
- `TOOL_FAILURE`.

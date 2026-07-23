# Scope and Goals

## Research goal

Create a reusable, inspectable system that can search for finite counterexamples to structural graph conjectures and produce artifacts that a mathematician can independently verify.

The system is not a general theorem prover. It is a counterexample laboratory with exact verification and controlled exhaustive components.

## Primary success levels

### Level A — engineering validation

- the pipeline runs reproducibly;
- live state is visible through a browser;
- runs can be paused, resumed, and stopped;
- resource limits work;
- benchmark forecasts are produced.

### Level B — scientific reproduction

- reproduce known small-order bounds or known witnesses;
- agree with an independent generator or solver;
- preserve full artifacts.

### Level C — new computational result

Examples:

- extend a rigorously certified lower bound on counterexample order;
- find a new graph with a stronger near-counterexample profile;
- find a verified counterexample to a current conjecture;
- derive a structural pattern from repeated best candidates.

### Level D — mathematical result

- prove a new theorem about the structure of minimal counterexamples;
- derive an infinite family;
- publish an independently checkable proof or counterexample.

## Explicit non-goals for v1

- solving every structural graph conjecture;
- distributed cluster scheduling;
- GPU graph kernels;
- LLM-driven mutation at every step;
- fully automatic literature ingestion;
- formal proof in Lean;
- exhaustive search at orders beyond demonstrated resource feasibility;
- elaborate web product features.

## Scientific principle

The generator may be heuristic. The verifier may not be heuristic when making a claim.

## Result vocabulary

Use only these terminal statuses:

- `COUNTEREXAMPLE_VERIFIED`
- `UNSAT_CERTIFIED`
- `NO_RESULT_WITHIN_BUDGET`
- `UNKNOWN_TIMEOUT`
- `UNKNOWN_MEMORY_LIMIT`
- `INVALID_CANDIDATE`
- `VERIFIER_DISAGREEMENT`
- `TOOL_FAILURE`

Never collapse `UNKNOWN_*` into `UNSAT`.

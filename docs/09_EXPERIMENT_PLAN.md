# Experiment Plan

## Stage 0 — installation and correctness

1. Run doctor.
2. Verify graph core tests.
3. Compare reference cycle detector against a second implementation on small graphs.
4. Reproduce known trivial positives and negatives.
5. Confirm dashboard and resource controls.

## Stage 1 — small-order ground truth

- use `nauty/geng` where feasible;
- reproduce small known no-counterexample ranges;
- compare exhaustive generator, SAT, and direct verifier;
- do not optimize for novelty.

Deliverable: a reproducibility report.

## Stage 2 — heuristic cubic search at n=32

Run:

- random restart;
- simulated annealing;
- iterated local search.

Track:

- exact `C4` count;
- capped `C8/C16/C32` witnesses;
- best score trajectory;
- duplicate rate;
- exact verifier time.

The objective is to validate search behavior, not immediately claim a counterexample.

## Stage 3 — larger cubic orders

Search selected orders above 32. A larger counterexample is still mathematically decisive, even if not minimal.

Use diverse orders because constraints change only when the next power of two enters the forbidden set.

Suggested bands:

- `32–39`
- `40–47`
- `48–63`
- `64+` only after long-cycle verification is benchmarked.

## Stage 4 — mixed-degree minimal-structure mode

Use the current structural restrictions as generator constraints. Compare against cubic search under equal exact-verifier budget.

## Stage 5 — CEGAR-SAT reproduction

- reproduce small orders;
- compare cardinality encodings;
- measure clause growth;
- validate every learned cycle clause;
- stop before expensive frontier claims unless proof logging is complete.

## Stage 6 — optional SMS frontier

Install pinned SMS and Glasgow solver. Reproduce a small overlap first. Only then attempt order 32.

## Stage 7 — LLM analysis cycle

After a run wave, provide the LLM with:

- target statement;
- immutable run configuration;
- benchmark summary;
- top candidate score trajectories;
- recurring motifs;
- exact-verifier bottlenecks;
- failed mutation statistics.

Ask for:

- new structural priors;
- new legal mutation operators;
- explanation of candidate motifs;
- proof ideas;
- literature-equivalent formulations.

Do not provide millions of raw candidates.

## Stop conditions

Stop or redesign a wave when:

- no improvement across a configured number of accepted moves;
- exact verifier consumes more than 80% of wall time;
- duplicate rate exceeds 90%;
- memory growth is unbounded;
- benchmark forecast exceeds available budget by more than an order of magnitude;
- a newer publication resolves or supersedes the target.

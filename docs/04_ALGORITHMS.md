# Search Algorithms

## Baseline order

Implement and benchmark in this order:

1. random restart;
2. greedy hill climbing;
3. simulated annealing;
4. iterated local search with tabu;
5. genetic population search;
6. beam search for constructive generation;
7. MCTS only if the constructive representation justifies it.

## Simulated annealing

Recommended first serious baseline.

State:

- one graph;
- exact structural-validity flags;
- capped cycle-witness cache;
- score tuple;
- RNG state.

Acceptance:

- always accept an improvement;
- accept degradation with a temperature schedule based on scalarized score delta;
- retain the lexicographic score for archive comparisons;
- periodically re-evaluate from scratch to detect incremental-cache errors.

Use adaptive reheating after stagnation.

The hot-loop cycle counter is intentionally incomplete. It caps witnesses per
forbidden length and also caps deterministic DFS work at
`max(4096, min(50000, cap * 1024))` visited search nodes per length. Exhausting
either bound sets `ScoreResult.complete = false`; it never implies absence.
The ranking path counts with an iterative integer-bitset DFS and reuses one
lane-local traversal workspace; witness-returning diagnostics keep the
separate reference enumerator. Every archived finalist still goes through
uncapped exact verification.

Optional score profiling uses batch-local integer accumulators for nanoseconds
visited DFS nodes, evaluations, complete recounts and early cutoffs per
forbidden length. It creates no candidate record, event, log entry or
persistence write. The counters are serialized once at the micro-batch
boundary and can be disabled independently of search instrumentation.

The mandatory persistent C++17 scorer implements the bounded iterative count
traversal behind a versioned binary protocol. Every production heuristic score
uses that worker. A protocol error, timeout, malformed response, or crash
permits one restart; a repeated failure terminates the lane. No Python
heuristic scorer, shadow mode, or runtime scoring fallback exists. The
independent Python reference enumerator remains part of exact M4 verification
and diagnostics only; it is never a heuristic-scoring substitute.

## Iterated local search

- run greedy or tabu-improving moves to a local optimum;
- perturb with several legal swaps;
- restart from the perturbed state;
- maintain a small elite archive;
- deduplicate elites canonically.

The current ILS/tabu implementation can use a conservative early-exit bound.
It stops only when the partial score is already lexicographically dominated
under the exact applicable acceptance threshold. Perturbation steps do not
use the bound.

Local duplicate/tabu checks may use a deterministic 256-bit incremental
edge-XOR key updated from the exact mutation delta. The key is deliberately
non-authoritative; graph6, checkpoint hashes, candidate IDs and canonical
archive logic are unchanged.

Incremental witness-set maintenance is not implemented. The 2026-07-26 gate
found zero complete C16/C32/C64 evaluations out of 2125 evaluated length
stages, below the required 20% completeness threshold. Without complete
witness membership, a safe edge-to-witness invalidation index cannot be
constructed.

## Genetic search

Use only after local baselines work.

Potential crossover for cubic graphs:

- select induced regions or edge cuts;
- exchange compatible substructures;
- repair degree and connectivity;
- reject if repair cost is too high.

Naive adjacency-matrix crossover usually destroys all useful constraints.

## MCTS assessment

MCTS is not the default because graph rewiring is not naturally a tree. It becomes plausible for a constructive process:

```text
choose degree sequence
add vertex orbit or motif
add constrained edges
close remaining stubs
verify
```

Required evidence before implementing MCTS:

- partial-state score predicts completed-state quality;
- transposition handling is defined;
- rollout cost is controlled;
- it beats beam search under equal verifier budget.

## SAT CEGAR

Variables:

```text
x_ij = 1 iff edge {i,j} exists, i < j.
```

Base constraints:

- simple graph by representation;
- degree at least 3 via cardinality constraints;
- optional connectedness via lazy cuts;
- optional structural priors.

CEGAR loop:

1. solve base CNF;
2. decode graph;
3. exact cycle verifier finds a forbidden cycle;
4. add a clause forbidding that exact edge set from appearing together;
5. repeat.

Cycle clause for witness edges `e1...ek`:

```text
not e1 OR not e2 OR ... OR not ek
```

This blocks the witness cycle but allows other graphs.

## SMS and co-certificate learning

SAT Modulo Symmetries is a strong optional path for isomorph-free graph generation. It can be combined with a co-certificate: when a candidate contains a forbidden cycle, return the cycle as the certificate and learn a clause.

Use SMS only behind an adapter. Do not make it a mandatory dependency of the basic search system.

## Canonicalization

Canonical labeling is expensive enough that it should be applied at archive boundaries rather than every local mutation.

Use:

- `nauty/Traces` canonical labels when available;
- a stable fallback hash for non-authoritative deduplication;
- graph6 for compact persistence.

Never use a non-canonical hash as proof that two graphs are isomorphic or non-isomorphic.

## LLM role

This is an optional, manual, post-run development activity. The installed
search, SAT, verification, and dashboard runtime contains no LLM client and
makes no AI/API request.

The LLM may:

- propose target adapters;
- analyze search stagnation summaries;
- propose new mutation families;
- interpret recurring graph motifs;
- generate proof ideas from verified candidates;
- review implementation and benchmark reports.

The LLM must not:

- decide whether a graph is a valid counterexample;
- run in every candidate evaluation;
- replace exact source/status checking;
- convert a timeout into a mathematical conclusion.

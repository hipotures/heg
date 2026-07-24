# Exact Verification and Scientific Artifacts

The certification entry point accepts an installed target ID and obtains the
exact forbidden lengths and structural reference verifier from that target.
The C++17 checker receives the same explicit length set. Manifests record the
target and length set, and reproduction commands include `--target`. The
default remains `erdos_gyarfas`; the M6 control target is clearly marked
control-only.

## Verification layers

### Layer 1 — internal structural validation

Check:

- vertex count;
- symmetric adjacency;
- no loops;
- no duplicate edges;
- connectedness;
- minimum degree.

### Layer 2 — Python reference verifier

Use a deliberately simple exhaustive DFS for exact cycle length on small graphs. It is the correctness oracle for tests and small artifacts, not the production hot path.

### Layer 3 — independent fast verifier

At least one of:

- C++ bitset cycle checker;
- Glasgow Subgraph Solver with cycle pattern graphs;
- SAT encoding for exact cycle existence.

### Layer 4 — external reproduction

Export graph6 and a human-readable edge list. Provide a standalone verifier command that does not read the search database.

## Counterexample acceptance rule

A graph may be marked `COUNTEREXAMPLE_VERIFIED` only if:

1. structural validation passes;
2. Python reference verifier passes where feasible, or an independently reviewed exact alternative is used for larger graphs;
3. a second implementation passes;
4. the two implementations agree on all target lengths;
5. the graph6 and JSON edge list hashes match the artifact manifest;
6. the status check is current;
7. the result survives a clean-room rerun from the exported graph only.

## Exhaustive UNSAT acceptance rule

A run may be marked `UNSAT_CERTIFIED` only if:

- the full final CNF or equivalent declarative instance is preserved;
- all lazy clauses are preserved;
- every lazy cycle clause includes its witness;
- solver name, version, options, seed, and platform are recorded;
- a proof certificate is generated when supported;
- the certificate is checked by an independent checker;
- the exact instance hash is recorded;
- a second method agrees on a smaller overlap range.

A process exit code without a certificate is not enough for a major mathematical claim.

## Timeout semantics

- cycle verifier timeout: `UNKNOWN_TIMEOUT`;
- SAT solver timeout: `UNKNOWN_TIMEOUT`;
- worker killed for memory: `UNKNOWN_MEMORY_LIMIT`;
- missing external tool: `TOOL_FAILURE`.

## Artifact manifest

```json
{
  "candidate_id": "...",
  "target": "erdos_gyarfas",
  "status_checked_at": "2026-07-23",
  "order": 32,
  "size": 48,
  "minimum_degree": 3,
  "forbidden_lengths": [4, 8, 16, 32],
  "graph6_sha256": "...",
  "edge_list_sha256": "...",
  "verifiers": [
    {"name": "sglab-python-reference", "result": "ABSENT"},
    {"name": "sglab-cyclecheck", "result": "ABSENT"}
  ],
  "environment": "environment.json",
  "reproduce": ["commands.txt"]
}
```

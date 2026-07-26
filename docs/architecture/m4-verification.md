# M4 Exact Verification

## Authority

M4 is the sole certification boundary.

The Director, heuristic scorer, diagnostics, candidate archive, and single
verifier paths cannot certify success.

## Paths

The normal independent verifier boundary includes:

- Python reference DFS;
- independent C++17 bitset verifier.

Optional SAT/CEGAR is a separate bounded path and does not turn unchecked UNSAT
into proof.

## Job input

A verification job references an immutable candidate snapshot containing:

- graph;
- graph hash;
- target definition;
- score/provenance;
- candidate identity;
- expected verifier implementations.

## Outcomes

| Outcome | Meaning |
|---|---|
| `INVALID_CANDIDATE` | Explicit forbidden-cycle witness or structural failure |
| `COUNTEREXAMPLE_VERIFIED` | Reviewed independent paths completely agree on validity and absence of target cycles |
| Timeout/memory/error | Unknown |
| Verifier disagreement | Unknown and review-triggering |
| Malformed/missing artifact | Unknown/failure, never certification |

## Certificate

A certificate manifest preserves:

- graph6 and edge representation;
- target metadata;
- environment/tool versions;
- Python verifier report;
- C++ verifier report;
- witnesses or complete absence results;
- hashes;
- reproduction command.

## Campaign stop

Only a complete persisted M4 certificate may quiesce lanes and stop the
campaign as certified success.

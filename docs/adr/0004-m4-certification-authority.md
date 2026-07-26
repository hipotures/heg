# ADR 0004: M4 Certification Authority

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Heuristic scores, capped witness counts, one verifier, SAT timeout, or model
text cannot safely establish a counterexample.

## Decision

Only M4 may create a certified-success terminal event. M4 requires the
reviewed independent exact-verifier paths and a complete persisted manifest.

## Consequences

- Search remains fast and incomplete.
- Timeouts and disagreements remain unknown.
- The Director can schedule verification but cannot certify.
- Success artifacts are independently reproducible.
- A candidate may be scientifically promising yet rejected by M4.

## Rejected alternatives

- Trusting the best heuristic score.
- Trusting one verifier implementation.
- Treating unchecked UNSAT or timeout as proof.

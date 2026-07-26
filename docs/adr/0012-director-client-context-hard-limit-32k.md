# ADR 0012: Director Client-Context Hard Limit of 32,000

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** ADR 0011 only for the hard-limit value

## Context

The Director already compacts ordinary complete requests toward 15,000
estimated client-owned tokens. The separate 16,000-token hard gate left little
margin when exact-verifier facts or current executable IDs reached their
irreducible safe-state floor, causing repeated fail-closed campaign stops.

## Decision

Raise `CLIENT_ESTIMATED_TOKENS_MAX` from 16,000 to 32,000. Keep the 15,000-token
soft target, deterministic floor recovery, complete-request measurement, and
pre-inference fail-closed behavior unchanged.

## Consequences

- Requests above 16,000 and at most 32,000 estimated client-owned tokens may
  start a Director turn.
- Normal requests are still compacted toward 15,000 tokens.
- The maximum permitted client-owned context and potential per-turn input cost
  increase.
- Exact-verifier facts and current executable IDs remain non-droppable.
- Requests above 32,000 still stop before inference.

## Rejected alternatives

- Removing the hard gate entirely.
- Raising the soft target together with the hard gate.
- Dropping exact-verifier facts or executable IDs to retain the former limit.

# ADR 0002: Campaign Versus Execution Attempt

- **Status:** Accepted
- **Date:** 2026-07-26

## Context

A process may stop because of time, operator action, host restart, or
infrastructure fault without invalidating previous scientific work. Treating
every process start as a new campaign discards continuity and encourages
duplicate search.

## Decision

A campaign is one durable scientific experiment with a stable ID. Every start
or Resume creates an immutable execution attempt under that campaign.

## Consequences

- Time/resources can be extended without resetting knowledge.
- Code commits and resource changes are attributable per attempt.
- Previous faults remain historical evidence.
- Cumulative and attempt-local metrics are both available.
- A scientifically different target/model/prompt contract requires a fresh
  campaign.

## Rejected alternatives

- New campaign for every process.
- Mutating one attempt row across restarts.

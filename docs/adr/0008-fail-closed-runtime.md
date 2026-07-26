# ADR 0008: Fail-Closed Runtime With Preserved Evidence

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

A research system must not continue after an unproven integrity, protocol,
credential, resource, or certification boundary. At the same time, stopping
must not erase completed scientific work.

## Decision

Runtime failures are classified and persisted. Invalid actions never execute.
Infrastructure/security/protocol/resource/model-contract failures stop or
block dependent work. Completed valid turns/actions/results remain valid.
Independent comparison arms may continue after model-output invalidity when
the plan says so.

## Consequences

- No silent unsafe continuation.
- Faults are resumable when they do not invalidate science.
- Historical attempts remain immutable.
- UI must distinguish model invalidity, stale targets, exact rejection, and
  infrastructure failure.
- Recovery requires explicit review/authorization.

## Rejected alternatives

- Best-effort continuation after every exception.
- Rewriting terminal history after a fix.
- Treating every model-invalid response as infrastructure failure.

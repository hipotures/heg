# ADR 0015: Bounded Seed-Generation Telemetry

- Status: accepted
- Date: 2026-07-28

## Context

Campaign seed generators use deterministic bounded retries, but previously
returned only a graph or a generic failure. Operators and the Director could
not distinguish cheap first-attempt construction from retry-heavy or
seed-dominated search. Persisting every construction would create an
unbounded hot-path history, while hashing wall-clock measurements into a
checkpoint would destroy deterministic scientific identity.

## Decision

The target generator accepts an optional mutable trace that records only
attempt count, retry budget, effective mode, and failure category. Lane
runtime measures elapsed nanoseconds and merges each observation immediately
into fixed-size batch and cumulative accumulators grouped by a reviewed source
enum. It never calls the generator again and does not consume RNG.

The cumulative aggregate is stored in the checkpoint under a separate
SHA-256. Scientific checkpoint identity excludes this observational envelope;
recovery verifies both hashes. Existing telemetry-window JSON stores the batch
and cumulative views without a new table or per-seed row.

## Consequences

- Fixed-seed graphs, RNG state, trajectories, scores, provenance, and
  scientific checkpoint IDs remain unchanged.
- Retry exhaustion and implementation failures remain fail-closed and gain a
  bounded category/source summary.
- Resume retains cumulative telemetry; restoring a graph does not count as a
  generation call.
- The reviewed `seed_generation_efficiency` diagnostic can compare current
  lanes/families/orders without exposing graph bodies.
- Timing histograms are approximate and observational, not scientific
  evidence or certification input.

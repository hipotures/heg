# ADR 0010: Versioned Duplicate Keys and Independent Sample Provenance

- **Status:** Accepted
- **Date:** 2026-07-26

## Context

After accelerating witness counting, resumed ILS lanes spent roughly half of
their loop in legacy graph6/SHA duplicate keys. Random-restart lanes spent
about one third constructing mutation ancestry even though successive random
graphs have no parent-child relationship.

Silently replacing a resumed lane's duplicate key can change visited/tabu
membership and its deterministic trajectory. Treating independent samples as
mutations is both expensive and scientifically misleading.

## Decision

Lane checkpoints carry canonical `duplicate_key_scheme` values
`legacy_sha_graph6_v1` or `delta_local_v2`. Historical aliases remain
readable. Resume and trajectory-preserving forks inherit the recorded scheme.
Only new lanes or explicit algorithmic restarts may create fresh duplicate
state with the newer scheme. Historical checkpoints are never rewritten.

The legacy key remains byte-identical SHA-256 over canonical graph6, produced
with a reusable direct byte encoder.

Candidate provenance schema v2 distinguishes `mutation_chain` from
`independent_sample`. Random restart creates full provenance only for durable
records and periodic checkpoints, not for every accepted sample. SQLite
schema v16 stores this provenance on retained candidates and immutable M4
snapshots.

Legacy random-restart checkpoint ancestry remains historical evidence but is
not restored into an `independent_sample` lane's live tracker. This is a
representation migration only: executable generator, RNG, graph, score,
counter and duplicate state are preserved.

## Consequences

- Existing resumed trajectories preserve duplicate membership semantics.
- Fast keys are rollout choices, not scientific graph identities.
- Random-restart telemetry no longer invents mutation parents.
- Reproduction uses seed lineage, RNG/checkpoint state, absolute evaluation
  index, generator version, graph hash and score.
- Historical candidate rows remain valid with `{}` provenance.
- M4 authority and graph/score identity are unchanged.

## Rejected alternatives

- Rehashing historical visited/tabu sets in place.
- Treating a practically collision-free replacement as contract-equivalent.
- Retaining per-sample random-restart mutation ancestry.
- Rewriting historical candidate or checkpoint evidence.

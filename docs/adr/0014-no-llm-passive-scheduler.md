# ADR 0014: No-LLM Passive Scheduler

- Status: accepted
- Date: 2026-07-28

## Context

Search lanes are deterministic, checkpointed workers, but production campaign
coordination previously required an AI Director turn. Synthetic and replay
providers were test controls that still wrote App Server session/turn-shaped
records and did not preserve a production scheduler state.

## Decision

Campaign plans fingerprint two reviewed orchestration contracts and select an
initial `director_mode`:

- `llm` uses the existing AI Director;
- `passive` uses versioned policy `balanced_v1`.

Passive decisions use the existing decision schema, validator, shared action
tables, dispatcher, lane/checkpoint/resource controls, and M4 broker. They
have their own durable source and scheduler-state tables; they never create a
synthetic model session or turn.

The passive policy uses persisted evaluation boundaries, bounded telemetry,
explicit reason codes, and a SHA-256 counter-based seeded RNG. A mode change
is permitted only when creating a new execution attempt and records the old
mode, new mode, and mode-specific contract fingerprint. Runtime failures
never cause an automatic mode fallback.

## Consequences

- Passive campaigns start and resume without credentials or App Server.
- Scheduler continuation, stagnation, exploration order, review index, and
  RNG lineage survive process boundaries.
- The shared action dispatcher remains the sole route to lane and verification
  work, so existing fail-closed and M4 authority invariants still apply.
- `director_action_batches` accepts exactly one durable source: an App Server
  turn or a passive scheduler decision.
- Passive scientific quality is intentionally conservative and is not claimed
  to equal AI-directed search.

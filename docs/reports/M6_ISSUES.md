# M6 Active Director Issue Ledger

Entries are append-only. Resolution notes do not remove prior entries.

## I-001 — open — authenticated live app-server gate

The protocol client and unauthenticated initialization pass, but the required
live model turn cannot be run until the operator explicitly authorizes the
one-time import of existing Codex `auth.json` into the private application
home. This is intentionally not inferred from repository write permission.

## I-002 — resolved — aggregate schema byte ordering

Repeated schema generation changed the exact byte hash of the v2 aggregate
while canonical sorted-JSON hashes and all selected individual schema hashes
remained stable. Reports now retain both exact and canonical hashes.

## I-003 — resolved — missing assumed M5 AI architecture

The package assumed schema v6 and an AI serial orchestrator. The baseline audit
mapped the work onto schema v1 and the real static-worker coordinator without
claiming preservation of nonexistent behavior.

## I-004 — resolved — schema-v7 lane provenance completion

M6.2 committed the additive schema before the executable lane shape proved it
needed explicit target and parent-checkpoint fields. The reviewed v7 SQL now
contains both fields, and `migrate()` forward-completes databases created from
the earlier M6.2 checkout without changing their user version. A compatibility
test preserves a non-default campaign target.

## I-005 — resolved — snapshot checkpoint rotation race

The first delayed-turn orchestrator test showed that a checkpoint named in a
committed snapshot could rotate out before a returned fork action was
delivered. The orchestrator now pins all snapshot-admissible checkpoints
before inference. The pin set remains globally bounded, and the delayed fork
test passes.

## I-006 — resolved — telemetry ahead of recovery checkpoint

The initial recovery test observed a telemetry high-water one batch ahead of
the latest persisted checkpoint because worker events were ordered telemetry
then checkpoint. Worker emission is now checkpoint-first at each safe
boundary. Recovery proves identical checkpoint ID/SHA/high-water before new
progress.

## I-007 — resolved — operator controls blocked by awaited Director turn

The first production composition draft awaited `orchestrator.tick()` directly,
which could delay deadline and emergency control handling for the full
inference timeout. The supervisor now owns the turn as an asynchronous task.
Campaign controls are checked independently; cancellation durably fails the
interrupted turn, and optimistic campaign versions reject late decisions.

## I-008 — resolved — zero-score seed absent from candidate archive

The first candidate path retained only strict improvements emitted after lane
startup, so an initial seed that already falsified the control statement could
not be promoted to M4. Candidate retention now compares every committed
checkpoint's best score against the bounded campaign archive and retains a
strictly better initial best without storing every checkpoint.

## I-009 — resolved — cumulative wire duplication

Each Director turn originally wrote the client's whole rolling wire buffer,
which duplicated older protocol traffic and could grow quickly. The client now
atomically drains the bounded buffer per turn, and the Director retains only
the latest 64 diagnostic wire artifacts.

## I-010 — resolved — nonexistent M5 serial-AI comparison arm

The planning package required retaining an M5 AI controller, but the
authoritative baseline had none. The comparison harness now labels and
implements a compatibility arm using the same app-server Director while
pausing search lanes during inference. It is confined to control studies and
cannot replace the production Active Director.

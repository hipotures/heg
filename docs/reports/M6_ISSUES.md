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

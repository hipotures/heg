# M6 Active Director Decision Ledger

Entries are append-only.

## D-001 — 2026-07-24 — map onto `sglab`

Decision: implement the Active Director additively under `src/sglab/research`
and preserve the existing `sglab run` engine as a legacy deterministic
baseline. Rationale: the planning package's `gilab` M5 AI modules do not exist
in the authoritative repository.

## D-002 — 2026-07-24 — installed schema wins

Decision: omit environment/dynamic-tool/runtime-root RPC fields that are absent
from the installed 0.145.0 schemas, and enforce those isolation properties
through process flags, configuration overrides, private directories, and
discovered-skill disabling. Rationale: sending example-only fields would
violate the generated protocol contract.

## D-003 — 2026-07-24 — dual schema hashes

Decision: retain exact byte hashes and canonical sorted-JSON hashes for
generated protocol schemas. Rationale: repeated 0.145.0 generation preserves
individual schema bytes but can reorder definitions in the v2 aggregate.

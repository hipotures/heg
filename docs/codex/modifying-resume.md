# Modifying Campaign Resume

Resume is a high-risk cross-cutting contract.

## Required invariants

- same campaign ID;
- new immutable execution attempt;
- previous attempt remains terminal evidence;
- cumulative state preserved;
- requested/effective resources recorded;
- checkpoints hash-verified;
- terminal actions/jobs not repeated;
- stale targets excluded;
- scientific contract unchanged;
- new runtime/auth provenance;
- latest terminal scientific-memory snapshot used.

## Change surface

- CLI preview/start;
- protected HTTP preview/start;
- plan/fingerprint;
- state-machine eligibility;
- attempt schema;
- checkpoint recovery;
- memory projection;
- lane restoration;
- candidate registries;
- cumulative/local counters;
- UI attempt history;
- docs/reference.

## Tests

At minimum:

- pause → Resume;
- budget/deadline → Resume;
- repaired fault → Resume;
- host restart;
- refusal for running/success/invalidated;
- 2 → 16 worker slots;
- cumulative evaluations increase;
- checkpoint reused;
- no duplicate action;
- stale historical action not executed;
- memory snapshot and hash recorded;
- Playwright preview.

Never change the target/model/effort/context through ordinary Resume.

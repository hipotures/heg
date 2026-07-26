# Change Map

Use this map to identify the full change surface.

| Change | Likely code areas | Persistence | Required tests/docs |
|---|---|---|---|
| New Director action | protocol/schema, validator, store, dispatcher, coordinator, UI renderer | action/outcome fields if needed | schema, semantic, dispatch, idempotency, UI, action catalog |
| New Director state field | snapshot/memory builder, prompt, schema/validator if referenced | snapshot metadata if durable | byte budget, deterministic hash, resume, director schema |
| Campaign state | campaign coordinator, store, CLI, API, UI | migration/state transition | resume/refusal/recovery, state machine |
| Resume resource | CLI/API form, preview/fingerprint, attempt creation, scheduler | attempt requested/effective resources | preview/start, actual enforcement, UI |
| Candidate field/lifecycle | archive, registries, pins/snapshots, M4 | migration/constraints | pruning, stale target, verification |
| M4 behavior | broker, path implementations, manifest, terminal logic | job/result/manifest | Python/C++ agreement, timeout/error, no false certification |
| Search algorithm/control | action catalog, lane worker, checkpoint schema | checkpoint/telemetry | deterministic replay, resume, parameter applicability |
| App Server field | client/protocol/preflight/compliance/store | turn/session fields | fake server, installed schema, timeout/shutdown |
| Comparison plan | suite/arm planner, fingerprint, worker, UI | suite/arm/authorization | plan invalidation, cap, worker E2E |
| Resource policy | plan, accounting, worker/coordinator, UI | samples/terminal summary | real inequalities, symlink/hardlink/sparse/log cases |
| Dashboard panel | view model, API, HTML/CSS/JS | usually none | HTTP, bounded result, Playwright, accessibility |
| SQLite migration | store/migrations | new schema version | previous-version Online Backup, integrity, FK, historical hashes |
| Scientific memory rule | projection, compactor, plan fingerprint | snapshot metadata | deterministic hash, hard limit, Resume, exact-fact retention |

## Cross-cutting questions

Before editing, answer:

- Does this alter the plan fingerprint?
- Does it affect historical schema/rows?
- Can Resume replay or duplicate it?
- Does it introduce a new executable target?
- Does it affect Director context size?
- Does it affect M4 authority?
- Does it expose auth/private paths?
- Is a new ADR required?

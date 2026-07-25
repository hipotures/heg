# Controlled comparison UI

The comparison subsystem is an auditable, measurement-only control plane and
bounded worker for future model, reasoning-effort, and Director context-mode
comparisons. It is separate from research campaigns and never dispatches a
Director decision.

## Local use

Initialize and serve a workspace:

```bash
sglab init --workspace ./workspace
SGLAB_WEB_TOKEN='choose-a-local-token' \
  sglab serve --workspace ./workspace --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/comparisons#token=choose-a-local-token`.
All state-changing requests use JSON `POST` endpoints and the
`Authorization: Bearer ...` header. The server binds to `127.0.0.1` by
default. It accepts no browser-supplied auth path or shell command.

Import the successful M6 S2/P1/P2 result without model or credential access:

```bash
sglab comparisons import-m6-context-report \
  --workspace ./workspace \
  --report docs/reports/M6_REDUCED_CONTEXT_SCREEN_RERUN.json
```

The imported suite is read-only and records that its runtime occurred
elsewhere. Private paths, credential hashes, rollout contents, and wire logs
are not imported.

Run the deterministic persistence exercise:

```bash
sglab comparisons replay-dry-run --workspace ./workspace
```

It creates simulated completed and failed turns, ratings, a blind preference,
and an immutable cost-profile snapshot. It makes zero model calls, reads no
auth, and creates no lane, batch, evaluation, or action dispatch.

Install a trusted, complete executable fixture outside the browser and launch
an already prepared and authorized suite with the fixed worker entry point:

```bash
sglab comparisons install-fixture \
  --workspace ./workspace \
  --fixture ./director-fixture.json

sglab comparisons worker \
  --workspace ./workspace \
  --suite-id comparison-...
```

The browser Start button invokes the same worker. See
`docs/COMPARISON_WORKER.md` for the exact plan, lease, inference reservation,
private runtime, stop, and recovery contracts.

## Workflow

Suite states are:

```text
draft → prepared → authorized → running → completed | failed | stopped
```

Audited arm states are:

```text
planned → preflight → auth_prepared → server_started → thread_ready
        → inference_reserved → inference_started
        → completed | schema_invalid | semantic_invalid
        | timed_out | aborted | failed | blocked | stopped
```

Creation and authorization are separate. Preparation serializes the exact
fixture, arm order, model/effort/context contracts, hashes, limits, and
measurement policy into a canonical plan fingerprint. Authorization binds to
that fingerprint. Any changed plan is rejected and the authorization is
invalidated before a start.

The auth source is server configuration only:

```text
SGLAB_CODEX_AUTH_SOURCE=/absolute/server/controlled/auth.json
```

The UI reports only whether that setting is configured and available. It
never returns the path or credential contents. The worker enforces private
homes, strict configuration, zero skills, zero tools, and the authorized
inference cap. This milestone implements and deterministically verifies that
runtime path with a fake App Server; it does not perform a paid run.

Before inference, each arm persists:

```text
expected_model
expected_reasoning_effort
effective_model
effective_reasoning_effort
effective_context_mode
model_contract_matched
```

A mismatch marks preflight failed and must abort before inference.

## Schema v11

The v10 comparison schema contains:

- `comparison_fixtures`
- `comparison_suites`
- `comparison_arms`
- `comparison_turns`
- `manual_ratings`
- `pairwise_ratings`
- `model_cost_profiles`
- `comparison_authorizations`

`comparison_turns.app_server_turn_record_id` references the existing durable
App Server lifecycle row. Final answer and usage remain owned by
`app_server_turns`; comparison rows retain only the comparison fields needed
for reporting. Existing campaign/session/turn rows receive nullable context
provenance columns. The migration does not rewrite historical rows.

The v11 migration adds only worker execution state:

- `comparison_execution_attempts`
- `comparison_runtime_campaigns`
- `comparison_worker_leases`
- `comparison_stop_requests`
- `comparison_inference_reservations`
- `comparison_arm_transitions`

It also adds explicit conversation grouping, sequencing, dependencies,
fresh/resumed-thread provenance, runtime-relative references, terminal
reasons, resource limits, and immutable fixture material. Historical
comparison suites and imported M6 rows are neither rewritten nor made
executable.

Cost profiles are append-only inputs to a snapshot. Each arm and rendered turn
retains the exact profile ID, multiplier, API-equivalent rates, and currency
used when it was planned. Later profile edits cannot change old results.

## Catalog and fixtures

The checked-in catalog is configuration-driven and currently permits:

- `gpt-5.6-luna`: `medium`, `high`, `xhigh`
- `gpt-5.6-sol`: `medium`, `high`, `xhigh`

An absent model/effort pair is rejected; the server never invents a
combination.

Fixtures support:

- `preserved_director_state`
- `campaign_snapshot`
- `custom_director_state_json`

Every fixture records an immutable ID, source reference, SHA-256, state schema
version, target/status metadata, byte size, and conservative input estimate.
Directly compared arms copy identical state, prompt, output-schema, applicable
action-space, evidence/advisory/executable registry, instruction, personality,
and campaign-budget hashes into the immutable plan.

## Usage and cost semantics

Server usage fields remain distinct:

- input tokens
- cached input tokens
- cache-write input tokens
- output tokens
- reasoning-output tokens
- server-reported total tokens

Cached input is treated as a subset of input. Reasoning output is treated as a
subset of output. Neither is added again to total tokens. Missing usage is
`null`, never zero.

Relative units:

```text
relative_cost_units =
  server_reported_total_tokens × relative_cost_multiplier
```

When explicit API-equivalent rates exist:

```text
api_equivalent_input_cost =
  ((input_tokens - cached_input_tokens) × input_rate
   + cached_input_tokens × cached_input_rate) / 1_000_000

api_equivalent_output_cost =
  output_tokens × output_rate / 1_000_000

api_equivalent_total_cost =
  api_equivalent_input_cost + api_equivalent_output_cost
```

These are labelled “API-equivalent estimate,” not subscription charges.

## Pages

- `/comparisons` lists and filters suites.
- `/comparisons/new` creates arm matrices from presets or custom rows.
- `/comparisons/<id>` shows preflight, usage, cost, latency, hard validity,
  decisions, ratings, pairwise summaries, quality-cost points, worker lease,
  stop state, current arm, and live progress.
- `/comparisons/<id>/blind` hides model, effort, context, usage, latency, and
  cost until a rating is submitted.
- `/model-cost-profiles` appends relative and optional API-equivalent profiles.

The main dashboard links to comparisons and shows the measured default,
`stateless_turns`, with recommendation basis
`single controlled S2/P2 pair`.

The comparison interface uses semantic suite, plan, decision, effect, and cost
cards. Protocol JSON is available only through technical-detail disclosures.
Long identifiers are abbreviated visually while preserving their full value
for inspection. Both light and dark themes are available from the persistent
header toggle; the preference is saved in browser local storage.

The comparison UI is phone-first at its narrow breakpoint. The global
navigation remains identical on every page, arranged as a two-by-two grid;
forms and primary actions use 44-pixel touch targets; suites and turns render
as readable cards without page-wide horizontal overflow. Desktop and tablet
layouts use the same information hierarchy with more simultaneous columns.
Failed or schema-invalid turns are excluded from ordinary blind comparison
and produce a reliability-focused empty state instead of blank answer cards.

Bounded polling uses:

```text
GET /api/comparisons/<id>/progress
GET /api/comparisons/<id>/turns
```

Protected Start launches a fixed `sys.executable -m sglab comparisons worker`
argv without a shell. Protected Stop records a durable request; it never
accepts a PID from the browser.

## Quality layers

Automatic hard validity, human judgment, and downstream scientific outcome
are separate. No opaque aggregate quality score is stored.

Automatic flags include schema/semantic validity, evidence and executable
target validity, implemented parameters, budgets, counterexample-claim
safety, and absence of tool/code/shell/measurement-execution requests.

Human records are append-only 1–5 usefulness, clarity, novelty, execution
intent, comments, and blind pairwise preference. Failed and schema-invalid
turns are excluded from ordinary blind quality comparison.

Optional downstream columns exist for decision batch, metric window, score
change, time to improvement, evaluations, CPU time, and exact-verifier result.
This milestone does not execute them.

Pareto labels appear only when both relative cost and manual usefulness exist.
Missing human quality never receives a fabricated coordinate.

## Known limitations

- The measured default rests on one controlled S2/P2 pair; it is a
  recommendation, not a statistical-superiority claim.
- `compacted_thread` remains an explicit experiment and is never selected
  automatically.
- The web control plane and bounded worker persist and consume exact plans,
  but this milestone intentionally performs no authenticated comparison. The
  real path still requires separate authorization.
- The preserved fixture import stores a safe public descriptor and hashes, not
  private runtime payloads, so historical fixtures are not executable.
- `compacted_thread` remains visible as an experimental catalog mode but the
  worker rejects it before auth access in this milestone.
- Host-restart recovery never silently resumes paid work.

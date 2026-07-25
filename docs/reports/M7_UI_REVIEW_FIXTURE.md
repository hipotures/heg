# M7 UI review fixture — Phase A

Date: 2026-07-25

## Result

A rich deterministic UI-review workspace is available at
`workspace/ui-review-demo`. It is explicitly marked as synthetic demo data,
uses seed `20260725`, and can be safely regenerated only when the target
already carries the exact demo marker.

Phase A stops here. No browser inspection, screenshot capture, page inventory,
UI redesign, or Playwright-CDP action has started. The HTTP server on port
8787 was not started by the agent.

## Baseline and preservation

- Baseline commit:
  `45c93e3441a2a8e95733d5cf56848a31d8c2b6c3`
- Work is isolated on branch `m7-ui-review-phase-a`; the later `main` history
  was not reset or discarded.
- `planning/` remains untouched.
- SQLite schema remains version 10; no migration was added.
- Preserved M6 JSON SHA-256:
  `a1f01415059494161b5c0d9feb608160e48afff1e3b23404e234eec87f27883c`
- Preserved M6 Markdown SHA-256:
  `b339e14e959755ba8fec5f475b443cb1df39652a92af22c5249d722ae82ceef8`
- The successful M6 S2/P1/P2 comparison is imported into the demo database as
  a read-only historical suite. Its original reports are unchanged.

## Generator

```bash
PYTHONPATH=src python3 -m sglab ui-fixture create \
  --workspace workspace/ui-review-demo \
  --profile full \
  --replace
```

The generator:

- uses fixed IDs, timestamps and a deterministic seed;
- performs no model call, auth access, external network request, paid
  comparison, production search campaign, or tool execution;
- creates only a new workspace;
- refuses to replace a directory without all four marker fields:
  `workspace_kind=ui_demo`, `synthetic_data=true`, `fixture_version=1`, and
  `generated_by=deterministic_fixture`;
- records synthetic exact-verifier “pass” states as demo-only and never as a
  mathematical claim;
- writes no credential material or private runtime path.

Two independent generations with the same seed produced byte-identical SQLite
files and the same logical fixture hash. A different seed produced a different
logical hash.

## Workspace manifest

| Property | Value |
|---|---:|
| Logical fixture SHA-256 | `8946be289122d42312983727ef9330b98a6a54c52822da03d9533b9a91a2f8c9` |
| SQLite SHA-256 | `d6fe9f7a130afeaf51b9fc35af7ca2e713e248255eeac06b684aa148451d4610` |
| SQLite size | 692,224 bytes |
| Approximate directory size | 0.72 MiB |
| Files | 123 |
| Schema | 10 |
| `integrity_check` | `ok` |
| `foreign_key_check` | no rows |
| Measured generation time | 0.093 s |

The actual duration is reported separately from deterministic fixture content,
so it cannot perturb screenshot data or the logical fingerprint.

## Data coverage

The fixture contains:

- 8 research campaigns: completed, running, paused, stopped, failed, empty,
  timeout, and verifier-disagreement shapes;
- 24 Director actions across start, diagnostic, review trigger, promotion,
  verification, stop, patch, restart, fork, and resource reallocation;
- 20 measured outcomes covering improvement, no improvement, regression,
  plateau, exact rejection, synthetic demo pass, timeout, ancestry, and cycle
  profile;
- 12 search lanes spanning active and terminal states, no telemetry, high/low
  throughput, memory pressure, three algorithms, two graph orders, two witness
  caps, and both mutation operators;
- 110 metric windows with throughput, score, mutation acceptance, duplicates,
  diversity, RSS, witness counts, token usage, and model latency;
- 40 retained/notable campaign candidates and 40 legacy candidate files,
  including compact and long IDs, ancestry, multiple score levels, cycle
  rejection lengths 4/8/16, verifier states, and missing artifact metadata;
- 12 hypothesis revisions covering creation, revision, rejection, confidence,
  evidence for/against, and long statements;
- 12 app-server turn lifecycle records: completed, schema-invalid,
  semantic-invalid, timed out after reasoning, aborted, in progress, missing
  usage, and a clearly labelled synthetic prohibited-tool attempt;
- 36 structured events covering normal, warning, error, timeout, resource,
  graceful shutdown, lease, and authorization events;
- 9 comparison suites: draft, prepared, authorized, running, completed, failed,
  timed out, stopped, and imported read-only M6 historical;
- Luna/Sol, medium/high/xhigh, stateless/persistent arms, valid/invalid turns,
  nullable usage, manual ratings, blind pairwise rating, and seven cost
  profiles.

Raw and normalized comparison decisions are both present and intentionally
different. Normalized parameters omit null values.

## Scale and response preparation

The fixture is deliberately large enough to expose wrapping, row-height,
filter, empty-state, and pagination issues but remains compact. Existing
bounded endpoints prevent thousands of rows from entering the DOM:

- actions, lanes and hypotheses: at most 32;
- campaign turns: at most 10;
- candidates: 50 by default;
- runs: at most 100;
- comparison suites: at most 200.

Without starting an HTTP server, local view-data construction measured:

- campaign status: 2.741 ms mean, 9.481 ms maximum over 20 samples;
- comparison list plus completed-suite detail: 10.369 ms mean, 19.620 ms
  maximum over 20 samples.

These are local preparation measurements, not browser navigation timings.
Phase B will measure rendered behavior.

## Verification

- fixture-focused tests: 5/5;
- full safe suite: 158/158;
- `make doctor`: pass;
- `make check`: pass;
- `make benchmark-smoke`: pass;
- `make dashboard-smoke`: pass;
- SQLite integrity and foreign-key checks: pass;
- credential/private-path scan: pass.

The required test and benchmark commands exercise existing deterministic test
code. The fixture generator itself starts no production search campaign.

## Phase-B boundary

Run exactly:

```bash
PYTHONPATH=src python3 -m sglab serve \
  --workspace workspace/ui-review-demo \
  --host 127.0.0.1 \
  --port 8787
```

Then confirm explicitly that `http://127.0.0.1:8787` is running. Only after
that confirmation may Phase B begin with Playwright-CDP.

```text
ui_demo_workspace_created: true
all_pages_inventoried: false
before_playwright_audit_completed: false
after_playwright_audit_completed: false
ready_for_phase_b_browser_audit: true
ready_for_real_user_ui_testing: false
```

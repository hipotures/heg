# Configuration Reference

## Layers

Configuration may come from project defaults, workspace/campaign plans, CLI
arguments, and server environment variables. Exact precedence is defined by
the installed parser/config code.

## Campaign scientific contract

Fingerprint-stable fields include:

- target and target-definition hash;
- Director model;
- reasoning effort;
- context mode;
- prompt/schema versions;
- stop contract;
- replan policy;
- search/verifier limits;
- App Server/resource policy;
- scientific-memory policy.

Resume cannot silently change scientific-contract fields.

`director_mode` is `llm` by default or `passive`. The fingerprint also covers
the fixed passive policy ID/version, scheduler-state version, seed,
evaluation-review delta, and stagnation threshold. These fields are reviewed
data, not arbitrary executable policy configuration.

## Resume execution resources

Attempt-local override fields include:

- additional wall time;
- CPU worker slots;
- max active lanes;
- aggregate resource share;
- lane memory;
- verifier concurrency/memory;
- reviewed queue bounds.

`--director-mode` may explicitly select the already fingerprinted LLM or
passive contract for the new attempt. Omitting it preserves the current mode
and passive scheduler state.

## Search profiling

`search_limits.score_profiling_enabled` controls per-forbidden-length
nanosecond, DFS-node, evaluation, completeness and cutoff counters. It
defaults to enabled for newly prepared campaigns. Disabling it removes the
score timers and both score/mutation profile accumulator updates without
changing the scorer, witness cache, RNG, acceptance policy or durable
scientific contract.

Completed profiled batches expose `timing.mutation_profile` with scalar
`uniform_*`, `targeted_*`, `random_restart_*`, `witness_search_*` and
`witness_cache_*` counters. They are one aggregate record per completed batch,
not candidate-level telemetry. `score_backend.mutation_witness_cache_enabled`
reports the effective cache path.

## Score kernel

Heuristic scoring has no backend configuration. Every lane uses the optimized
persistent C++ worker with conservative early exit and the
`delta_local_v2` duplicate key for new work. Attempt provenance records this
fixed implementation plus the worker path, SHA-256 and protocol version.
Completed batch metrics report C++ requests and bounded worker restarts.
If the worker cannot start or fails again after one restart, the lane fails
closed.

## Scientific memory defaults

```text
scientific_state_soft_limit_bytes = 24576
scientific_state_hard_limit_bytes = 32768
scientific_snapshot_interval_cycles = 5
```

## Web

Common environment settings:

```text
SGLAB_WEB_TOKEN
SGLAB_DASHBOARD_TOKEN
```

Auth source for controlled runtime is configured server-side and must not be
browser-editable.

The systemd launcher reads deployment options from
`~/.config/sglab/dashboard.env`:

```text
SGLAB_DASHBOARD_REPOSITORY
SGLAB_DASHBOARD_WORKSPACE
SGLAB_DASHBOARD_HOST
SGLAB_DASHBOARD_PORT
SGLAB_DASHBOARD_PYTHON
SGLAB_DASHBOARD_TOKEN_FILE
SGLAB_CODEX_AUTH_SOURCE  # optional
```

Repository/workspace paths must be absolute. The token-file variable points
to a separate regular file; its contents are exported only to the dashboard
process.

## App Server

The production runtime requires strict configuration and private homes.
Expected/effective model and effort are checked before inference.

## Comparison cost profiles

Relative multipliers and optional API-equivalent rates are versioned data, not
hardcoded subscription claims.

## Inspection

Use:

```bash
sglab --help
sglab <command> --help
make doctor
```

Never assume a configuration field is active merely because it appears in an
old report; use the current plan and implementation.

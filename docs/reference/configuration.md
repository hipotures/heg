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

## Resume execution resources

Attempt-local override fields include:

- additional wall time;
- CPU worker slots;
- max active lanes;
- aggregate resource share;
- lane memory;
- verifier concurrency/memory;
- reviewed queue bounds.

## Search profiling

`search_limits.score_profiling_enabled` controls per-forbidden-length
nanosecond and DFS-node counters. It defaults to enabled for newly prepared
campaigns. Disabling it removes the score timers and profile accumulator
updates without changing the scorer, RNG, acceptance policy or durable
scientific contract.

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
```

Auth source for controlled runtime is configured server-side and must not be
browser-editable.

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

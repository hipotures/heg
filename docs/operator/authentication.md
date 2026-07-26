# Authentication and Codex App Server Isolation

## Credential source

The operator authorizes an explicit Codex home. The runtime copies only:

```text
auth.json
```

into a private campaign/comparison `CODEX_HOME`.

It must not copy:

- config;
- sessions;
- history;
- skills;
- prompts;
- SQLite;
- `AGENTS.md`;
- arbitrary files from the normal Codex home.

## Exact-plan authorization

Campaigns and comparisons use a plan fingerprint.

Before credential access:

1. reload the plan;
2. recompute the canonical fingerprint;
3. compare it with the authorized fingerprint;
4. verify model, effort, context, fixture/target, order, limits, and policies;
5. abort on any mismatch.

Authorization is not reusable for a changed plan.

## Private runtime

Use separate:

- `CODEX_HOME`;
- `CODEX_SQLITE_HOME`;
- empty runtime workspace;
- wire/stderr/audit directories.

Credential files use restrictive permissions and are excluded from manifests.

## App Server contract

The reviewed runtime uses:

- direct stdio JSON-RPC;
- strict configuration;
- experimental API capability negotiation;
- custom base instructions;
- empty developer instructions;
- personality `none`;
- read-only sandbox;
- approval policy `never`;
- no dynamic tools;
- no selected environments;
- no capability/workspace roots;
- zero active skills after disable/reload verification.

Platform-owned sandbox or developer instructions may still be present. The
system proves isolation from local user/project inputs, not absence of all
platform instructions.

## Logging rules

Never publish:

- auth contents;
- auth hash;
- bearer token;
- private absolute runtime paths;
- normal Codex-home paths;
- private symlink targets.

Public reports may state that credential copying occurred and that only the
authorized file was copied.

## Version changes

The currently tested protocol baseline is Codex CLI 0.145.0. After a version
change, run the deterministic compliance audit and schema preflight before any
authenticated campaign.

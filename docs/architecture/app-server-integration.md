# Codex App Server Integration

## Transport

The runtime talks directly to Codex App Server over stdio JSON-RPC.

It does not use `codex exec` as the production Director path.

## Isolation

Per runtime:

- private `CODEX_HOME`;
- separate private `CODEX_SQLITE_HOME`;
- empty runtime workspace;
- strict config;
- custom base instructions;
- empty developer instructions;
- personality `none`;
- read-only sandbox;
- approval `never`;
- empty tools/environments/capability/workspace roots;
- two-pass skill disable/reload verification.

## Auth

Only explicitly authorized `auth.json` is copied. No other normal Codex-home
content is imported.

## Turn lifecycle

The client persists:

- request ID;
- thread ID;
- turn ID;
- item IDs/types;
- reasoning items;
- event sequence;
- final response;
- nullable usage;
- terminal state/reason;
- wire/stderr references.

The row exists as soon as an authoritative turn ID is known.

## Timeout

- persist known correlation;
- use `turn/interrupt` when available;
- drain late events;
- keep missing answer/usage null;
- bounded graceful shutdown;
- no hidden inference retry.

## Stateless production mode

Production Director turns are fresh threads. Continuity comes from
scientific-memory state, not conversation history.

## Client-owned request budget

The host targets 15,000 estimated client-owned tokens through deterministic
scientific-state compaction. The independent fail-closed hard gate is 32,000
estimated tokens and is enforced before `turn/start`.

## Platform instructions

Platform-owned sandbox/developer/environment wrappers may be present. The
runtime proves isolation from normal user Codex home, project instructions,
active skills, tools, and workspace roots; it does not claim a bare model
prompt without platform instructions.

## Filesystem wrappers

Reviewed transient App Server wrappers are accepted only at the expected
private runtime path and with trusted installation targets. Accounting uses
`lstat` and never follows them.

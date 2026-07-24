# M6 Codex App Server Preflight

Status: **deterministic no-model compliance audit passed; authenticated live
turn remains pending explicit authorization**

Audit date: **2026-07-24**

## Installed protocol

- Installed target: `codex-cli 0.145.0`.
- Schema discovery uses
  `codex app-server generate-json-schema --experimental --out <directory>`.
- The full generated manifest and canonical hashes are preserved in
  `M6_APP_SERVER_PREFLIGHT.json`.
- Experimental schema discovery is required and passed.

The earlier audit omitted `--experimental` and therefore incorrectly reported
that isolation fields were absent. The installed experimental schemas do
contain:

- `thread/start`: `environments`, `dynamicTools`,
  `selectedCapabilityRoots`, and `runtimeWorkspaceRoots`;
- `thread/resume`: `runtimeWorkspaceRoots`;
- `turn/start`: `environments` and `runtimeWorkspaceRoots`.

The client now sends empty arrays for each supported isolation surface.

## Strict startup and private runtime

Every production app-server process starts through an argv array containing
`app-server --stdio --strict-config`. The obsolete
`tools.view_image=false` override and the non-contractual analytics override
were removed; there is no non-strict fallback. A deterministic installed-CLI
test proves that an intentionally unknown field fails startup.

`CODEX_HOME`, `CODEX_SQLITE_HOME`, and the app-server working directory are
three distinct absolute mode-0700 directories. No auth was imported for this
audit.

## Skill isolation

Startup performs this complete proof before permitting `thread/start` or
`thread/resume`:

1. call `skills/list` with forced reload;
2. reject every non-empty per-entry `errors` array;
3. require every discovered skill path to be absolute;
4. write `enabled: false` for every discovered skill and require
   `effectiveEnabled: false`;
5. call `skills/list` again with forced reload;
6. reject startup unless the second result has no errors and zero active
   skills.

Both raw list results are written atomically as private audit artifacts
`skills-before.json` and `skills-after.json`.

## Events, usage, persistence, and shutdown

- Request, thread, turn, and `itemId` correlations are checked. The final
  agent-message item ID is stored with the turn.
- Usage explicitly stores `inputTokens`, `cachedInputTokens`,
  `cacheWriteInputTokens`, `outputTokens`, `reasoningOutputTokens`, and the
  server-authoritative `totalTokens`, while retaining the raw payload.
- After `turn/completed`, the client always observes a bounded final-usage
  grace window. The newest correlated usage event wins.
- SQLite schema v8 adds `cache_write_input_tokens` and
  `final_agent_item_id`; campaign JSON, control reports, and the dashboard
  expose cache-write tokens.
- Shutdown closes stdin and drains stdout/stderr while waiting for natural
  exit, then escalates to `SIGTERM` and finally `SIGKILL` only after separate
  bounded timeouts.
- `inspect-session` reads the exact `thread_path` stored in SQLite. It does not
  infer or glob a session layout, and rejects missing, relative, non-file, or
  out-of-root paths before inspection.

## Deterministic acceptance

Run:

```text
sglab ai-director compliance-audit --workspace ./workspace
```

The versioned result is `M6_APP_SERVER_COMPLIANCE.json`. On this host every
required condition passed, `post_reload_active_skills` was `0`, `failures` was
empty, and `ok` was `true`. The audit initialized and shut down a private
app-server, generated schemas, and exercised strict configuration; it did not
start a model turn, contact the model, copy auth, or import `auth.json`.

This result proves deterministic protocol/configuration compliance only. It
does not claim that runtime isolation has been demonstrated by an
authenticated rollout.

## Remaining authenticated gate

The first authenticated smoke turn still requires an explicit operator
authorization to import one chosen `auth.json` into the private
`CODEX_HOME`, followed by account/network/model availability. After that, the
pending live checks are one minimal structured turn, validation of the opaque
server-returned rollout path, and same-thread resume after process restart.
No credential action was performed as part of this work.

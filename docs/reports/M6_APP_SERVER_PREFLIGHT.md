# M6 Codex App Server Preflight

Status: **deterministic no-model compliance audit passed; authenticated runtime
smoke executed with a residual isolation failure**

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

This result proves deterministic protocol/configuration compliance only. By
itself it does not claim authenticated local isolation or absence of
platform-owned instructions; those properties require inspection of a
completed authenticated rollout.

## Authenticated follow-up

The operator subsequently authorized importing exactly one selected
`auth.json` into the private `CODEX_HOME`. The runtime smoke completed two
structured turns on one persisted thread with a natural app-server restart
between them. Opaque rollout inspection proved isolation from local/user
configuration, repository instructions, project `AGENTS.md`, active skills,
tools, capability roots, and runtime workspace roots. Skill isolation, tool
isolation, workspace isolation, structured decision execution, and resume all
passed.

The complete rollout also contained platform-owned Codex multi-agent developer
instructions and skill-inclusion flags in `world_state`. Their presence is
reported without treating them as local leakage:
`platform_instruction_absence` is `unsupported`. For compatibility, the old
aggregate `authenticated_runtime_isolation` is retained only as
`proven_for_local_inputs`. See `M6_APP_SERVER_RUNTIME_SMOKE.md`. No graph-search
campaign was started.

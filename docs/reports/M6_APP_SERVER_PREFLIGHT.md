# M6 Codex App Server Preflight

Status: **protocol/client preflight passed; authenticated live turn pending
explicit auth import**

Preflight timestamp: **2026-07-24T08:13:56Z**

## Installed implementation

- Version: `codex-cli 0.145.0`
- Launcher: `/home/xai/.nvm/versions/node/v22.15.0/bin/codex`
- Resolved executable:
  `/home/xai/.nvm/versions/node/v22.15.0/lib/node_modules/@openai/codex/bin/codex.js`
- Executable SHA-256:
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`
- `codex features list` stdout SHA-256:
  `d3d4366c4fb3177f4920dcf4eaca28100571dab6c30463ce3ef9e641266adb83`
- Feature output bytes: 5,915

The exact commands completed successfully:

```text
codex --version
codex features list
codex app-server generate-json-schema --out <private-temporary-directory>
```

## Generated protocol hashes

| Generated schema | Exact byte SHA-256 |
| --- | --- |
| `codex_app_server_protocol.schemas.json` | `8a9694a5508a95ba4a48b1ba43551f88b704dbe6cd0c4f9f04f330d3166d2930` |
| `codex_app_server_protocol.v2.schemas.json` | `07d21d7335b88e46a6dd11bbf099dbf868dd24156d6ce4aa9441d41e22ccd296` |
| `v1/InitializeParams.json` | `4f576f99e285beb28f71f48a72b887c1f517dada86fee348fe2af0a35511de23` |
| `v2/SkillsListParams.json` | `a942aa92e6da4cf8a76d6b99cbdaf6672864e6ff955f44a6d469f0363afd3bf2` |
| `v2/SkillsConfigWriteParams.json` | `24c9645b4f09b3d4d6ed8a18dda989717959e200eb3a70cd455a97e0c3754ca1` |
| `v2/ThreadStartParams.json` | `01aece2283d733451fec34d3bc0394f9d47e6dc22213ccd50e9f87321926b52d` |
| `v2/ThreadResumeParams.json` | `ed7af2227449f7d9f520c3541d93ceac31cdff251f41b57faede35e094ef3f02` |
| `v2/TurnStartParams.json` | `48a0ee95b669b47f5557c68b99a4d459b50577ccce8ebc5976532f50e3c6d059` |
| `v2/ItemCompletedNotification.json` | `047016f3132b046cedc98b62672656f834e7561c872c06c155643a018f51eef8` |
| `v2/TurnCompletedNotification.json` | `96a42581ca7053aba0d86acf7259bc1993628ff782c243f649215652c1562fbd` |
| `v2/ThreadTokenUsageUpdatedNotification.json` | `a30830510723d95793880f2a629472f0142c3df936799e24c8c92afde8e24402` |
| `v2/ErrorNotification.json` | `1ec871b02771300a26a34e41a7cfaf7484330a8c37c197d1ac133e753b083a09` |
| `v2/ThreadStatusChangedNotification.json` | `146af6d3702c4f3c844bd10b6b6b3e2b872e958a8d7d822157c19aaa6dc085f6` |

The v2 aggregate's exact byte hash changes across repeated generation because
definition-map order is nondeterministic. Its canonical sorted-JSON SHA-256 is
stable at
`27f8d983f19d8e1a5548d52176de0a460fb05aaf2a72110f913c6f4af2bd4f27`.
The legacy aggregate canonical hash is
`5469280cfbdaa12f6d28e2206f942da808f8b699ce6c43b13f2439d843432f38`.
Individual schemas used by the client were byte-stable in repeated generation.

## Compatibility adjustments

The installed schemas differ from the thin-inference example:

- `ThreadStartParams` has no `environments`, `dynamicTools`,
  `selectedCapabilityRoots`, or `runtimeWorkspaceRoots`;
- `ThreadResumeParams` likewise has no environment/root fields;
- `TurnStartParams` has no `environments` or `runtimeWorkspaceRoots`;
- installed text input is `{"type":"text","text":"..."}`;
- the returned thread includes both `sessionId` and unstable `path`;
- final message phase is exactly `final_answer`;
- turn statuses are `completed`, `interrupted`, `failed`, and `inProgress`;
- usage is read from `tokenUsage.last` and includes the four required
  categories plus `totalTokens`.

The client therefore sends only installed-schema RPC fields and enforces
tool/project/environment isolation at process configuration plus discovered
skill disabling. It does not send fields rejected by this binary.

## Implemented client behavior

`src/sglab/research/app_server_client.py` now:

- launches a long-lived process with `asyncio.create_subprocess_exec`, never a
  shell and never `codex exec`;
- uses private mode-0700 home/work directories and separate
  `CODEX_HOME`/`CODEX_SQLITE_HOME`;
- disables apps, browser/computer use, multi-agent, plugins, shell/unified
  execution, hooks, goals, workspace dependencies, tool suggestion and MCP
  elicitation surfaces;
- sets project-doc size to zero, web search disabled, MCP servers empty,
  image-view false, and analytics false;
- initializes once and sends `initialized`;
- discovers and disables every enabled skill, requiring
  `effectiveEnabled == false`;
- starts persisted threads with `ephemeral: false` or resumes the same thread;
- keeps `sandbox: read-only` and `approvalPolicy: never`;
- correlates responses/notifications, rejects unsupported server requests,
  selects the completed `final_answer`, waits for late usage, and normalizes
  tokens without double counting;
- bounds the notification queue, JSONL line, wire log, and stderr;
- terminates the complete process group on timeout or fatal failure.

The explicit `sglab ai-director auth-import` command copies only `auth.json`;
it never copies `config.toml`, skills, hooks, plugins, trust, or memory.

## Tests and current gate

- Five focused client/auth tests pass.
- Fake app-server tests cover initialization, skill disabling, persisted
  start/resume, structured final selection, post-completion usage,
  unsupported server requests, malformed JSONL, timeout and process cleanup.
- A real installed app-server process initialized successfully in the isolated
  home, discovered six bundled enabled skills, disabled all six, and shut down
  cleanly without authentication.

No existing Codex login has been copied. An authenticated greeting, real
structured Director request, saved-rollout inspection, and same-thread
process-restart proof require the package-mandated explicit one-time operator
authorization. Until those checks pass, this report and M6.1 remain
intentionally incomplete.

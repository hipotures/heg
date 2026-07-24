# M6 App Server Authenticated Runtime Smoke

Date: **2026-07-24**

Tested code: **8b52a495bfaf28752c8e93b48ecdcd74365660f7**

Installed target: **codex-cli 0.145.0**

## Outcome

The operator explicitly authorized copying only the selected `auth.json` into
one isolated private `CODEX_HOME`. Source and destination hashes matched; no
configuration, history, sessions, SQLite state, prompts, project
instructions, or user skills were imported. Credentials and private artifact
paths are not tracked by Git.

Exactly two authenticated structured model turns completed:

- the first returned a locally valid `CONTINUE` decision and persisted its
  rollout;
- stdin-first shutdown exited naturally;
- a fresh strict app-server repeated the two-pass skill gate;
- `thread/resume` continued the same opaque server thread;
- the follow-up returned a second valid `CONTINUE` decision with new turn and
  item identifiers;
- the second shutdown also exited naturally.

No search lane, graph evaluation, candidate, verifier job, tool call, or real
research campaign was started.

## Usage

The first turn reported 6,392 input tokens, 0 cached input tokens, 0
cache-write input tokens, 205 output tokens, 0 reasoning output tokens, and
the server-authoritative total of 6,597.

The resumed turn reported 6,484 input tokens, 4,864 cached input tokens, 0
cache-write input tokens, 203 output tokens, 0 reasoning output tokens, and
the server-authoritative total of 6,687. The cumulative raw server total was
13,284.

## Defect found and fixed

Three authenticated requests were rejected with HTTP 400 before model
execution while validating the output schema. Their complete rollouts contain
no final agent message or token usage. They exposed that the Structured
Outputs transport subset requires:

- explicit types for `const` and `enum` nodes;
- removal of unsupported uniqueness and object constraints;
- `anyOf` rather than `oneOf`;
- every object property to appear in `required`, with optional values encoded
  as nullable.

The transport schema now follows those rules. The local semantic validator
remains authoritative and removes only reviewed nullable transport
placeholders before returning a normalized decision.

## Isolation finding

Both process startups ended with zero active skills, empty skill-list error
arrays, absolute discovered paths, strict configuration, empty dynamic tools,
empty environments, empty capability roots, and empty runtime workspace
roots. The complete rollout contained no tool-call event, no normal user
Codex-home reference, and no content loaded from repository instruction
files.

However, the complete rollout did contain platform-owned developer messages
describing multi-agent operation and a `world_state` whose `host_skills` and
`skills` entries had `includeInstructions: true`. The literal string
`AGENTS.md` occurred inside that generic platform wrapper, not as loaded
project-file content.

Accordingly:

- `protocol_configuration_compliance`: **proven**
- `authenticated_runtime_isolation`: **not_proven**
- `persisted_thread_resume`: **proven**

This smoke does not satisfy the live-campaign completion condition for M6.

## Verification

After the schema fix, the deterministic no-model audit again passed with
`ok: true`, an empty failure list, strict startup, zero post-reload active
skills, and separate private homes. The full 93-test suite and all required
repository commands passed:

```text
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

The first sandboxed full-test attempt could not bind four loopback HTTP
sockets; the same suite passed outside that socket restriction.

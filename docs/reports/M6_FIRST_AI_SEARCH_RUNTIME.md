# First End-to-End AI-Directed Search

Date: **2026-07-24**

Initial and tested commit:
**ad47e9027d4333c4833c8ee9580d9bd7b3ed8abd**

Installed runtime: **codex-cli 0.145.0**

## Command and authorization

The operator explicitly authorized copying only
`/home/xai/.codex/auth.json` into a new private `CODEX_HOME` and exactly two
authenticated turns. No other file from the normal Codex home was copied.
The private runtime used separate `CODEX_HOME`, `CODEX_SQLITE_HOME`, and an
initially empty work directory.

The experiment command was:

```text
PYTHONPATH=src python3 -m sglab ai-experiment run \
  --workspace workspace/first-ai-search-auth-20260724-01 \
  --codex codex --evaluation-cap 10000
```

## Correlation

Campaign:
`ai-experiment-f428e11c80514d23ac06085f7f0b8380`

Thread: `019f9441-d29a-7ab0-aa4c-e7450bdf0a6c`

First turn:

- JSON-RPC request: `11`
- turn: `019f9441-d2ae-7cd3-b025-2da1db0d30ba`
- local turn record: `app-turn-47422bb2aa274edd82eacc1e8f0d3a5a`
- final item: `msg_0875688206979de0016a6364e8302081918239401c1b4a1486`
- snapshot: `snapshot-91548976ee6e424485ca3b00b5e82f98`
- decision batch:
  `decision-batch-ed3f16ef1b1f460f84d75273359217ea`

Second turn:

- JSON-RPC request: `12`
- turn: `019f9442-bd19-7e20-b905-c5cb6c78c858`
- local turn record: `app-turn-1de81efc1234452692d9e93993e19ecc`
- final item: `msg_0875688206979de0016a63653bae788191952fa94918a0241e`
- snapshot: `snapshot-f05c68797620478d87764fd4e0717b1f`
- decision batch:
  `decision-batch-f7c4c84930b6449292309ca2d5bc274c`

## First decision and ordering proof

The first raw response selected one `start_lane` action:

- algorithm: `iterated_local_search_tabu`
- graph family: `connected_cubic`
- order: `20`
- seed: `24072026`
- batch/evaluation limit: `10000`
- wall limit: `120` seconds
- witness cap: `10000`
- tabu tenure: `48`
- perturbation interval: `200`
- restart threshold: `1500`
- promotion penalty: `10`
- resource share: `1.0`

The raw transport decision contained nullable placeholders for parameters not
used by this algorithm. Local validation removed only those placeholders.
The normalized decision retained every scientific value listed above.

SQLite contained the accepted decision batch and the applied action event with
`first_graph_evaluation_count: 0` before construction of the search kernel.
The action was applied at `2026-07-24T13:13:29Z`; the batch began afterward in
the same recorded second.

## One measured search batch

- evaluations: `10000`
- elapsed: `20.4477208089` seconds
- throughput: `489.0520608` candidates/second
- peak coordinator RSS: `191623168` bytes
- accepted mutations: `1063`
- legal mutations: `10000`
- duplicate mutations: `174`
- improvements: `18`
- acceptance rate: `0.1063`
- duplicate rate: `0.0174`
- diversity: `0.9826`
- operator yield: `0.0018`
- termination: `evaluation_limit`

The initial score had 192 forbidden-cycle witnesses and weighted penalty 860.
The best retained candidate had 3 witnesses, all of length 4, and weighted
penalty 48. Its identifier is
`candidate-e4e7a245edf7b7e86caec15a`.

The Python exact reference verifier returned `REJECTED` after finding a
forbidden 4-cycle. No M4-certified counterexample was claimed.

## Outcome feedback and second decision

The complete persisted batch outcome has SHA-256
`a14a2559b9408f3854de23244ff0e8195016a88693b1ca5348c70765bbee01d2`.
That exact hash and all 10,000-evaluation metrics appeared in the second
snapshot.

The second response began `CHANGE_STRATEGY:`. It observed that the best score
was reached by evaluation 921 and that the next 9,079 diverse evaluations did
not improve it. It proposed one `mutation_ancestry` diagnostic for the
retained candidate. The proposal was validated and persisted as action `A2`,
but no dispatcher ran it: SQLite has no outcome for `A2`.

## Protocol and usage

The preserved evidence contains exactly two `turn/start` requests, two
completed-valid turns, two decision batches, one lane, and one metric window.
It contains zero retry notifications, zero tool-call items, zero unsupported
server requests, and zero second-action outcomes. The session state is
`closed`, shutdown mode is `graceful`, and `PRAGMA integrity_check` is `ok`.

First turn usage:

- input: `7344`
- cached input: `0`
- cache-write input: `0`
- output: `1245`
- reasoning output: `756`
- server-authoritative total: `8589`

Second turn usage:

- input: `12895`
- cached input: `6912`
- cache-write input: `0`
- output: `2370`
- reasoning output: `1685`
- server-authoritative total: `15265`

## Rollout inspection

The exact opaque `thread.path` stored in SQLite exists within the private
runtime root. The complete rollout has 29 JSONL records and 92,418 bytes.
There are two agent messages and no tool, command, shell, MCP, web-search, or
file-change items.

The rollout contains no reference to the normal user Codex home, repository
`src/`, or `planning/`. It uses only the empty private work directory. Six
bundled skills were discovered before startup; all paths were absolute, all
error arrays were empty, and the post-reload active count was zero.

Platform-owned sandbox and multi-agent developer messages were present, as in
the prior M6 smoke. The literal `AGENTS.md` occurs in that generic platform
message, not as loaded repository content. No claim of platform-instruction
absence is made.

## Preserved artifacts

The untracked private runtime report is:

```text
workspace/first-ai-search-auth-20260724-01/ai-experiment-report.json
```

Report SHA-256:
`97d6fdeabedc159725730bc06ffa3025fd75e0ac3e1b1649bd2ed8ce393faa1d`

The report includes a 15-entry artifact manifest. All 15 files were rehashed
after shutdown and matched. Runtime artifacts, rollout, wire logs, private
SQLite state and credentials are not tracked by Git.

## Acceptance

```text
protocol_configuration_compliance: proven
decision_before_search: proven
bounded_search_batch_execution: proven
outcome_feedback_to_llm: proven
second_decision_persisted: proven
exactly_two_model_turns: proven
second_batch_not_executed: proven
end_to_end_ai_directed_loop: proven
```

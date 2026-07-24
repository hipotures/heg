# Director context-mode comparison

Date: **2026-07-24**
Installed protocol source: generated experimental schemas from
**codex-cli 0.145.0**

Following the updated `codex-app-server` integration contract, schema
generation used `--experimental`; runtime remains strict-config with
experimental capability negotiation rather than a runtime
`--experimental` flag. Schema inspection did not start app-server; the later
safe test suite exercised only deterministic unauthenticated startup paths.
No model turn was used.

## Implemented modes

### `persistent_thread`

One persisted thread is resumed normally. DirectorStateV2 bounds each new
client submission, but no automatic thread compaction occurs. Conversational
history can still grow linearly inside the server. Replay cannot measure that
server-side token growth.

### `compacted_thread`

After a completed Director turn and before the next decision, the client calls:

```json
{"method":"thread/compact/start","params":{"threadId":"..."}}
```

The installed schema requires only `threadId` and defines an empty object
response. Original snapshots, decisions and outcomes remain outside the model
thread in immutable application artifacts. The boundary and response are
persisted.

Whether compaction itself consumes model tokens, how much history it retains
and whether it changes scientific decisions are not exposed by schema
generation and require an authorized runtime measurement.

### `stateless_turns`

Every Director decision starts a fresh isolated thread with the same verified
base instructions and complete DirectorStateV2. Scientific continuity uses
campaign, snapshot, action, outcome and artifact hashes rather than
conversation memory. Restart selects the latest durable session boundary, and
the next decision still starts a fresh thread.

## Deterministic comparison

| property | persistent | compacted | stateless |
|---|---|---|---|
| action schema | identical | identical | identical |
| submitted scientific state | identical V2 | identical V2 | identical V2 |
| maximum 100-batch state | 16,682 B | 16,682 B | 16,682 B |
| outcome hashes | preserved | preserved | preserved |
| replay decisions validate | yes | yes | yes |
| reconstruction after restart | deterministic | deterministic | deterministic |
| server conversation growth | expected linear | unknown after compaction | none across turns |
| conversational continuity | full | summarized by server | none |
| additional protocol operation | none | compaction before turns 2+ | thread/start per turn |

No mode is selected as winner from replay. Replay proves scientific-state
equivalence and size bounds, not model behavior or paid token cost.

## Recommended authenticated A/B test

Use a no-search comparison before another campaign:

1. Reuse the same four immutable Phase-B scientific states and output schema.
2. Run separate private homes for each mode with the same model and effort.
3. Request the same four structured decisions, but dispatch no search.
4. Record server `last` and cumulative usage, cache fields, latency, decision
   validity and semantic differences.
5. Count any compaction usage or inference separately; abort the compacted arm
   if the installed server makes that cost opaque.
6. Compare persistent versus stateless first. Admit compacted mode as a
   candidate only after its operation and token accounting are directly
   observed.

Primary measures should be cumulative input tokens, valid-decision rate,
decision agreement on algorithm/parameters and wall time. The test needs fresh
authorization because every decision and possibly compaction may be
model-backed.

## Remaining uncertainties

- Token attribution within a request is unavailable.
- The schema does not state whether manual compaction is locally or remotely
  generated, nor its token cost.
- The semantic fidelity of a compacted thread cannot be proven by replay.
- Stateless turns may lose useful unstated reasoning despite receiving the same
  scientific facts.
- Persistent history may improve consistency while increasing tokens; the
  current four-turn sample cannot quantify that tradeoff.
- The four preserved decisions are a controlled fixture, not a distribution
  of campaign states.

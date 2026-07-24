# M6.5 Retained Candidates and M4 Broker

Date: 2026-07-24

## Result

The offline candidate/M4 boundary milestone passes. This proves the software
authority boundary and a real negative verification case. It does not certify
a counterexample and does not complete M6.

## Retained candidate boundary

- Lane improvement events are parsed back through `BitGraph` before retention.
- Candidate IDs derive from SHA-256 of canonical graph6.
- Exact graph bodies live in bounded campaign artifacts and SQLite, never in
  Director snapshots.
- The default ordinary retained-candidate limit is 256; promoted/verifying
  scientific artifacts are protected from ordinary rotation.
- Snapshots expose stable candidate/evidence IDs, score/structural summaries,
  checkpoint provenance, and certification status.
- The Director can only promote/schedule IDs admitted by its committed
  snapshot.

## M4 broker boundary

- priority queue: at most 32 queued/running jobs by default;
- concurrency: one certification process by default;
- process address space: 1 GiB broker, 512 MiB per verifier by default;
- subprocess output, wall time, and process groups remain bounded by the
  existing certification/resource layer;
- exact paths: `python-reference-dfs` and `cpp17-bitset-dfs`;
- the broker re-reads `manifest.json`, requires an exact two-verifier shape,
  and rejects in-memory/file disagreement;
- timeout and memory/tool failures become retryable unknowns;
- verifier disagreement is a critical Director trigger;
- only two complete independent success results may enter the terminal
  transaction.

On verified success, lanes are quiesced before the atomic transaction records
the candidate, certification artifact, verification job, and
`succeeded_certified_counterexample` terminal event. There is no Director
action that can directly end a campaign.

## Complete typed-action coverage

The reviewed action catalog now maps as follows:

- lane runtime: start, patch, fork, restart, stop, reallocate;
- candidate/M4 broker: promote candidate, schedule verification;
- deterministic scientific dispatcher: request diagnostic, set review trigger.

Diagnostics have a 64 KiB artifact limit and fixed implementations. They
accept IDs only and never model-provided code, SQL, expressions, paths, or
commands. Cycle profiles derived from heuristic score data are explicitly
marked incomplete; exact authority remains M4.

## Real focused gate

Command:

```text
uv run python -m unittest tests.test_verification_broker tests.test_diagnostics -v
```

Observed:

```text
Ran 3 tests in 0.165s
OK
wall_seconds=0.24s
user_seconds=0.17s
system_seconds=0.06s
cpu_percent=93%
```

The integration retains K4, promotes it by ID, runs both real exact paths,
validates the persisted manifest, and obtains `INVALID_CANDIDATE`. Both paths
agree on rejection. The candidate is marked rejected, the campaign stays
`running`, and the terminal-event count remains zero.

The manifest-guard test also proves that a purported success is rejected if a
path is incomplete or the two implementations are not independent.

## Regression gate

`make test`: 65 tests passed in 12.247 seconds.

`make check`: passed.

## Remaining proof

The positive terminal path deliberately remains pending until the installed
hidden-witness/control target is added. That acceptance campaign must reach a
real M4-certified control witness or its explicit deadline. No inference about
the open Erdős–Gyárfás target is made here.

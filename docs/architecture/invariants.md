# System Invariants

This is the authoritative engineering-invariant matrix.

| Invariant | Enforced in | Evidence/tests | Failure behavior |
|---|---|---|---|
| Decision committed before dispatch | Director/store/action dispatcher | decision-before-search and campaign tests | action is not delivered |
| Invalid decision never executes | schema/semantic validator | invalid/replan tests | persist, one repair, then clean stop |
| M4 alone certifies success | verification broker/terminal event | two-verifier gates | unknown/reject; no success |
| Accepted candidate target is pinned | candidate store/action transaction | pin/pruning tests | reject action transaction |
| M4 consumes immutable snapshot | verification job input | candidate snapshot tests | no mutable-row lookup |
| Resume keeps campaign ID | campaign/attempt store | 65+65 continuation demo | Resume refused on mismatch |
| Resume creates new attempt | campaign runtime | attempt lifecycle tests | no process reuse |
| Scientific contract cannot change on Resume | plan/preview validation | Resume contract tests | require fresh campaign |
| Cumulative counters never reset | attempt accounting | continuation demo | integrity failure |
| Terminal actions/jobs are not repeated | recovery/idempotency | recovery tests | duplicate/no-op or reject |
| Raw history survives compaction | memory store | compaction tests | overflow before inference |
| Exact facts/current executable IDs are non-droppable | memory projection, irreducible-floor recovery and complete-request compaction before final Director limit | forced-compaction, floor-search, request-budget and SnapshotBuilder ordering tests | `scientific_state_overflow` |
| Distinct fresh campaigns remain independent | workspace/campaign creation | isolation tests | no implicit import |
| Evidence visibility does not imply executability | registries/action schema | applicability tests | validation rejection |
| Action IDs are workspace-unique | schema + transaction | collision tests | batch rejected before insert |
| Hypothesis existing operations use submitted IDs | schema/validator | hypothesis contract tests | structural/semantic invalid |
| Hypothesis evidence uses registry IDs, not prose | schema/prompt/validator | repair-context tests | invalid response |
| Repair context remains bounded | Director repair builder | context budget tests | fail before inference |
| No model tools/shell/file execution | App Server contract + output validation | tool-attempt tests | fail closed |
| Auth content never enters public artifacts | auth/report/manifests | scans and runtime audits | abort/report failure |
| Byte-quota error requires true inequality | resource accounting | quota tests | separate failure domain |
| Symlink targets are not followed | `lstat` accounting/policy | wrapper/escape/race tests | policy fail closed |
| Worker child is reaped by owner | dashboard process registry | reaper tests | stale process state corrected |
| SQLite migration preserves history | migration harness | Online Backup + canonical hashes | migration rejected |
| Missing usage remains null | turn lifecycle | timeout/missing usage tests | no fabricated zero |
| Timeout is unknown, not proof | verifier/SAT/runtime | timeout tests | unknown/fault |
| Heuristic score-worker failure is not cycle absence | mandatory C++ lane scorer | score-worker contract/crash tests | restart once, then fail closed |
| Resume never silently migrates duplicate membership | versioned lane checkpoint key scheme | legacy alias, fork and explicit-restart tests | inherit checkpoint scheme; require explicit restart |
| Browser cannot supply executable/auth path | HTTP validation | security tests | request rejected |

When changing an invariant:

1. update this table;
2. update the relevant ADR;
3. add or modify a focused test;
4. update architecture/reference/user/operator docs;
5. create an evidence report when acceptance is nontrivial.

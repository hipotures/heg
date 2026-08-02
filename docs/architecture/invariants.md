# System Invariants

This is the authoritative engineering-invariant matrix.

| Invariant | Enforced in | Evidence/tests | Failure behavior |
|---|---|---|---|
| Decision committed before dispatch | Director/store/action dispatcher | decision-before-search and campaign tests | action is not delivered |
| Invalid decision never executes | schema/semantic validator | invalid/replan/passive-fault tests | persist; LLM permits one repair, invalid passive output faults immediately |
| Zero-lane bootstrap is constructive | snapshot action-space projection, Director prompt/schema | issue-19 zero-lane bootstrap regression | expose `start_lane` when capacity exists; omit candidate/lane-target actions |
| Validation diagnostics remain durable | app-server turn store/status projection | issue-19 repair persistence regression | retain bounded `{path,message}` issues for both invalid turns |
| Model targets never expose durable IDs | Director alias projection/request artifacts/host resolver | issue-19 alias and prompt-bound checks | submit bounded per-turn aliases; resolve and role-check them before durable validation; unknown/stale aliases fail closed |
| M4 alone certifies success | verification broker/terminal event | two-verifier gates | unknown/reject; no success |
| Accepted candidate target is pinned | candidate store/action transaction | pin/pruning tests | reject action transaction |
| M4 consumes immutable snapshot | verification job input | candidate snapshot tests | no mutable-row lookup |
| Resume keeps campaign ID | campaign/attempt store | 65+65 continuation demo | Resume refused on mismatch |
| Resume creates new attempt | campaign runtime | attempt lifecycle tests | no process reuse |
| Scientific contract cannot change on Resume | plan/preview validation | Resume contract tests | require fresh campaign; choosing a pre-fingerprinted orchestration mode is attempt provenance, not a target/model/prompt change |
| Orchestration mode changes only on a new attempt | campaign/attempt store | passive mode-transition tests | reject active-attempt mutation |
| LLM failures never trigger passive fallback | campaign supervisor | no-fallback tests | retain LLM fault and stop fail-closed |
| Passive decisions create no model turns | passive scheduler/store | no-credential/App Server guard tests | scheduler fault |
| Stale passive campaign snapshots never dispatch | passive scheduler/orchestrator/store | passive commit-boundary and stale-campaign retry tests | persist rejection; one fresh deterministic review; repeated conflict faults |
| Cumulative counters never reset | attempt accounting | continuation demo | integrity failure |
| Terminal actions/jobs are not repeated | recovery/idempotency | recovery tests | duplicate/no-op or reject |
| Raw history survives compaction | memory store | compaction tests | overflow before inference |
| Exact facts/current executable IDs are non-droppable | memory projection, integrity-checked latest-checkpoint-per-active-lane registry, atomic checkpoint-batch pinning, irreducible-floor recovery and complete-request compaction before final Director limit | missing-checkpoint, executable-history, self-eviction, forced-compaction, floor-search, request-budget and SnapshotBuilder ordering tests | unavailable/older references remain historical; an executable batch never evicts itself; `scientific_state_overflow` |
| Distinct fresh campaigns remain independent | workspace/campaign creation | isolation tests | no implicit import |
| Evidence visibility does not imply executability | registries/action schema | applicability tests | validation rejection |
| Action IDs are workspace-unique | schema + transaction | collision tests | batch rejected before insert |
| Hypothesis existing operations use submitted IDs | schema/validator | hypothesis contract tests | structural/semantic invalid |
| Hypothesis evidence uses registry IDs, not prose | schema/prompt/validator | repair-context tests | invalid response |
| Repair context remains bounded | Director repair builder | context budget tests | fail before inference |
| No model tools/shell/file execution | App Server contract + output validation | tool-attempt tests | fail closed |
| Auth content never enters public artifacts | auth/report/manifests | scans and runtime audits | abort/report failure |
| Artifact projections never replace authority | capsule/index migration | artifact capsule/idempotence tests | SQLite/raw records remain authoritative; unavailable fields are explicit |
| Imported AI-program archive is byte-preserving | Mutation Forge import manifest/champion proof | archive identity, manifest, and secret scans | missing/changed/extra/unsafe archive path is reported; no silent omission |
| Byte-quota error requires true inequality | resource accounting | quota tests | separate failure domain |
| Symlink targets are not followed | `lstat` accounting/policy | wrapper/escape/race tests | policy fail closed |
| Worker child is reaped by owner | dashboard process registry, lane-manager shutdown | reaper and queue-closure tests | stale process state corrected |
| SQLite migration preserves history | migration harness | Online Backup + canonical hashes | migration rejected |
| Missing usage remains null | turn lifecycle | timeout/missing usage tests | no fabricated zero |
| Timeout is unknown, not proof | verifier/SAT/runtime | timeout tests | unknown/fault |
| Heuristic score-worker failure is not cycle absence | mandatory C++ lane scorer | score-worker contract/crash tests | restart once, then fail closed |
| Resume never silently migrates duplicate membership | versioned lane checkpoint key scheme | legacy alias, fork and explicit-restart tests | inherit checkpoint scheme; require explicit restart |
| Browser cannot supply executable/auth path | HTTP validation | security tests | request rejected |
| Reviewed proposal ranking is opt-in and catalog-bound | lane/catalog validation | proposal-ranking seam tests | reject unknown/patch activation |
| Campaign ranking authorization is plan-bound | prepare/start CLI, plan fingerprint, Director validation | issue-17 activation tests | reject disabled/changed/unknown values before dispatch |
| Random restart remains unranked | Director validation and lane validator | issue-17 activation tests | reject ranker on random_restart |
| Proposal worker cannot choose a fallback | host bridge/worker boundary | red-team and process tests | lane fails closed and worker group is reaped |
| Policy cannot certify or score | proposal bridge/M4 broker | scorer/M4 isolation tests | selected plan is the only scored plan; M4 remains sole authority |
| Proposal-ranking checkpoint identity is exact | checkpoint/recovery | checkpoint/resume tests | resume rejected on any identity drift |
| Proposal-ranking optimization preserves the frozen contract | host pool/worker/profile boundary | batch parity, replay, profile and performance-matrix gates | any hash, RNG, limit, schema, scorer, M4, or lane-state drift fails closed |
| Ranking profile is bounded and reconciled | bridge/lane telemetry | fixed-width profile and residual gate | per-proposal history is not emitted; residual above 2% is a gate failure |

When changing an invariant:

1. update this table;
2. update the relevant ADR;
3. add or modify a focused test;
4. update architecture/reference/user/operator docs;
5. create an evidence report when acceptance is nontrivial.

# M6 adaptive campaign — authenticated Phase B

Date: **2026-07-24**

Phase-B starting commit:
**870d4e101c512a3d67542c952735654863192fe1**

Installed runtime: **codex-cli 0.145.0**

## Authorization and runtime boundary

The operator authorized exactly four authenticated model turns and three
bounded search batches. Only `/home/xai/.codex/auth.json` was copied, once,
into the new private `CODEX_HOME`. No other normal Codex-home file was copied.
The runtime used separate absolute `CODEX_HOME`, `CODEX_SQLITE_HOME`, empty
private workspace, audit, wire-log and stderr directories.

Before inference, the deterministic compliance audit returned `ok: true` and
an empty failure list. Both app-server startups used strict configuration.
Their two-pass skill inspections had empty error arrays, absolute discovered
paths and zero enabled skills after reload. Runtime settings were read-only,
approval policy `never`, no dynamic tools and no workspace or capability
roots. The complete rollout contains no tool/function item and no loaded
repository `AGENTS.md` content.

Platform-owned Codex sandbox and multi-agent developer instructions are
present in the complete rollout. They are not from the normal Codex home,
repository, an active skill, dynamic tool or runtime workspace root. This
report does not claim platform-instruction absence.

## Campaign and correlation

Campaign:
`ai-experiment-163b7b6f9d6c45e1be1352f64e025202`

One persisted thread was used throughout:
`019f94de-c908-7bc2-b1a4-0e696a01cbfd`

| turn | turn ID | local turn record | final item | decision batch |
|---:|---|---|---|---|
| A1 | `019f94de-c915-7291-aa9d-8dd4ffe4e27f` | `app-turn-e996a58e040b4346b7b90caaa15fb495` | `msg_043f878cdb628304016a638d1cacf08191b1ccde04514c01d2` | `decision-batch-7541928559534ed2ab2d5dd90373edd5` |
| A2 | `019f94df-a1ab-7cb0-b170-dc7bf52e2661` | `app-turn-9acf548b109840db9b32fbbbcda603aa` | `msg_043f878cdb628304016a638d60bf348191a8ae824ee15d4e59` | `decision-batch-8f029c1671e242dd836ec8bc1033625b` |
| A3 | `019f94eb-15b3-7341-b9f9-4c76cd6f0694` | `app-turn-81c6d8d5ea594f4794c97c651ae4a3ad` | `msg_0eda958b33456533016a6390587e648191aa4bc97250f1fd4f` | `decision-batch-24c29dbe778d49b0b556807eefde216b` |
| A4 | `019f94ec-627b-72a1-993a-d996ba8ffdb7` | `app-turn-13f048a7197d45e0bdf8d8f5f632ef51` | `msg_0eda958b33456533016a63908ee6408191b15ba6826c227821` | `decision-batch-5c5089762cb74074888de92304d57da8` |

The first process completed A1/B1 and A2/B2, then stopped before A3 inference
when the complete two-outcome snapshot exceeded the 256 KiB protocol payload
bound. There was no inference retry. Commit
`a460dd752119eea9340d01e872956eab1b6c2580` bounded historical snapshot
ancestry while retaining hashes and references to the complete outcome
artifacts, and added resume from a verified durable boundary. A fresh strict
app-server then resumed the same thread without copying authentication again
and completed only A3/B3 and A4.

The database contains four `completed_valid` turns, four accepted decision
batches, four accepted actions and three outcomes. Both processes exited
naturally through the graceful path. The durable terminal sequence state is
four successful turns, four committed decisions, three persisted batches and
next transition `stop`.

## Raw and validated decisions

The complete raw responses and locally validated objects are retained in the
private report and per-turn response artifacts. The scientific contents were:

1. **A1 — start ILS-tabu baseline.** Order 20, seed 24072027, 10,000
   evaluations, cap 64, tabu tenure 512, perturbation interval 128 and
   normalized mutation weights 0.9 uniform / 0.1 targeted. Validation recorded
   all six fields as effective, with no ignored or rejected parameter.
2. **A2 — change strategy after O1.** The response cited O1's best evaluation
   3700, 6300-evaluation plateau and operator yields. It selected simulated
   annealing on order 22, seed 24072028, 10,000 evaluations, cap 10000,
   temperature 2.0, cooling 0.999, restart threshold 3000 and weights 0.5 /
   0.5. All controls were implemented and effective.
3. **A3 — combine measured signals from O1 and O2.** The response cited O2's
   three actual reseeds, 108 record events, exact witness counts and failure
   to replace the order-20 incumbent. It selected ILS-tabu on order 22, seed
   24072029, 10,000 evaluations, cap 64, tabu tenure 1024, perturbation
   interval 64 and weights 0.6 uniform / 0.4 targeted. Validation accepted only
   implemented ILS controls.
4. **A4 — stop.** After O1/O2/O3, the response recorded that the full
   30,000-evaluation allowance was exhausted, that A3 improved the score but
   retained forbidden cycles, and that exact verification rejected it. The
   accepted `set_review_trigger` action closed the review state. It did not
   dispatch search.

No decision used `promotion_penalty`. No ILS decision included
`restart_threshold`. Mutation weights were known, non-negative, positive-sum
and normalized before persistence and execution.

## Three measured batches

| batch | algorithm/order/cap | seed | elapsed | cand/s | accepted / duplicate / records | best eval / plateau | best score | exact result |
|---:|---|---:|---:|---:|---:|---:|---|---|
| B1 | ILS-tabu / 20 / 64 | 24072027 | 14.834 s | 674.13 | 1272 / 140 / 17 | 3700 / 6300 | `[0,3,48,0,30]` | `REJECTED`, cycle 4 |
| B2 | annealing / 22 / 10000 | 24072028 | 32.041 s | 312.10 | 1327 / 177 / 108 | 6109 / 3891 | `[0,3,48,0,33]` | `REJECTED`, cycle 4 |
| B3 | ILS-tabu / 22 / 64 | 24072029 | 17.005 s | 588.06 | 1436 / 120 / 15 | 548 / 9452 | `[0,3,40,0,33]` | `REJECTED`, cycle 4 |

Every batch stopped at its 10,000-evaluation limit and remained below 120
seconds. Total evaluations were exactly 30,000. Peak coordinator RSS was
215,818,240 bytes for B1/B2 and 218,419,200 bytes for B3. B2 performed three
actual annealing restarts; B1 and B3 performed none.

Witness counting dominated measured loop cost: 12.896 seconds in B1, 25.725
seconds in B2 and 13.614 seconds in B3. Mutation generation cost 1.119, 5.560
and 2.403 seconds respectively. SQLite persistence was 1.0–1.4 ms per batch,
and telemetry construction was 1.0–1.6 ms. Cap-64 search scores in B1/B3 were
truncated during search and are not represented as exact; cap-10000 B2 scores
were not truncated. Each lane-end exact reference verification was complete
and rejected the retained graph.

The targeted operator produced 3/17 B1 records from 1005 uses, 49/108 B2
records from 4959 uses, and 8/15 B3 records from 3998 uses. The uniform
operator produced 14, 59 and 7 records respectively. This is useful adaptive
telemetry, not evidence of statistical superiority.

## Ordering, feedback and comparison

For B1/B2/B3, the persisted ordering event names the corresponding decision
batch and records `first_graph_evaluation_count: 0`. Each event precedes the
first graph evaluation. The outcome IDs are:

- B1: `action-outcome-b8aaa89e71e04203a1ea9bd9c13f0852`
- B2: `action-outcome-88b425681ec94c88914c5c25f2c115bc`
- B3: `action-outcome-4186d270f5da452290e6726bdbe69913`

O1's artifact hash and metrics appeared in the A2 snapshot; O1/O2 appeared in
A3; O1/O2/O3 appeared in A4. The Director therefore changed algorithm, order,
witness fidelity, restart behavior, tabu/perturbation controls and mutation
weights in response to measured outcomes and ancestry.

B1 and B2 did not improve over the best Phase-A static score. B2 did not
improve over B1. B3 improved the weighted component from 48 to 40 and is
better than B2 and the Phase-A static baseline under the recorded
lexicographic score. Continuing each prior configuration is an unmeasured
counterfactual. Three batches do not support a statistical-superiority claim.

## Usage and rollout inspection

| turn | input | cached input | cache-write input | output | reasoning output | server total |
|---:|---:|---:|---:|---:|---:|---:|
| A1 | 8577 | 0 | 0 | 1304 | 818 | 9881 |
| A2 | 42286 | 7936 | 0 | 2337 | 1552 | 44623 |
| A3 | 112209 | 4864 | 0 | 2827 | 1965 | 115036 |
| A4 | 201142 | 111360 | 0 | 1410 | 734 | 202552 |

The authoritative server total for the campaign is **372,092 tokens**.

The exact opaque `thread.path` stored in SQLite was passed to
`ai-director inspect-session`; it exists inside the private runtime root and
is valid. The complete 1,318,380-byte rollout has 52 valid JSONL records,
four turn contexts, four assistant messages, no tool/function items, no
loaded AGENTS entries and no active environment entries. No session layout
was inferred or globbed for inspection.

## Preserved private artifacts

The runtime root and its contents remain untracked. Important relative paths
and SHA-256 hashes are:

- `ai-experiment-report.json`:
  `1bd7011db5c380ff4944d71b5bc23bbded5e56d929d60868434fe442747c8b50`
- `no-model-compliance.json`:
  `81897562f19a4f97fed2cafaeef1b6edabb883c2933f17f461080689b4e2d12a`
- `experiment/batch-outcome-A1.json`:
  `4eb752b7275194530a96ce13b0a4bbc0b8a070d41de4cd42f7903ba0082099b9`
- `experiment/batch-outcome-A2.json`:
  `6145071ee7cfea359d936a5a929acdac3c2fa0e99a94e1d10df10d2dbb152c1e`
- `experiment/batch-outcome-A3.json`:
  `7b7c458c802f7e52394d27601c870cc0368e341515c082f1853f0168ef86e217`
- complete opaque rollout:
  `eebc78599b8bdbbf506d5183fdc2dc836869b2d25d25a1de8a70e627fc2baa8a`

The report contains the full artifact manifest for requests, responses, wire
logs, snapshots, checkpoints, candidates, preflights and both skill-list
passes. Credentials, private SQLite homes, rollouts and wire logs are not
tracked by Git.

## Failures and uncertainties

The initial process encountered one deterministic local payload-size defect
after B2 and before A3 inference. The fault did not create a failed model turn
or hidden retry. It was fixed and tested before the exact persisted thread was
resumed. No other report failure is present.

All three retained candidates were rejected by the exact reference verifier.
No counterexample or mathematical certification claim is made. The comparison
has only one run per adaptive configuration, and counterfactual continuation
was not measured.

## Acceptance

```text
protocol_configuration_compliance: proven
semantically_valid_decision_space: proven
mutation_operator_choice: proven
decision_before_each_batch: proven
three_bounded_batches_executed: proven
outcomes_fed_back_to_llm: proven
fourth_decision_persisted: proven
fourth_batch_not_executed: proven
exactly_four_model_turns: proven
adaptive_ai_campaign_loop: proven
```

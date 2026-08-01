# Issue #16 — ranking profile contract and Phase A root cause

## Fixed schema

The opt-in aggregate profile uses schema `stage7.heg.profile.v1`. It contains
the following fixed exclusive phases, with nanoseconds and invocation counts:

1. `base_current_graph_preparation`
2. `context_cycle_count_preparation`
3. `sampled_cycle_witness_discovery`
4. `edge_load_construction`
5. `proposal_generation`
6. `legality_validation_and_deduplication`
7. `removed_edge_distance_computation`
8. `new_edge_distance_computation`
9. `triangle_c4_local_risk_computation`
10. `proposal_id_pool_hash_canonicalization`
11. `python_object_construction_copying`
12. `json_framing_serialization`
13. `policy_ipc_execution`
14. `sorting_tie_breaking`
15. `selected_rewrite_application`
16. `authoritative_selected_plan_scoring`
17. `checkpoint_telemetry_integration`
18. `residual_unattributed`

It also records fixed per-length (4–9) witness totals, per-k (2–4) and
per-selector generation totals, pool attempts/accepted counts, feature-budget
exhaustions, cache hits/misses, policy calls/failures, worker startup/IPC/
orphan counts, selected-plan scorer calls, selection/ranked wall totals, and
reconciliation. No proposal ID, payload, graph, or per-candidate timing is
stored.

## Root-cause profile before optimization

The retained order-14/order-16 reproduction showed the ranking path dominated
by repeated pool generation and feature preparation, with policy framing and
per-proposal validation/copying also material. The observed order-14 retained
reference was approximately 15,003 evaluations/s baseline versus 135
evaluations/s ranked (ratio 0.00903); the worker-only p99 was 116,899 ns with
zero failures/orphans. These values are historical diagnostics, not the fresh
authoritative matrix.

The optimized development profile is reconciled against the complete ranked
evaluation interval. Any measured coordinator remainder is assigned to the
fixed checkpoint/telemetry integration phase; `residual_unattributed` is
required to remain ≤2% of ranked wall time. The final profile artifact and
phase Pareto table are recorded under the external issue-16 evidence root.

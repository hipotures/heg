ASSIGNED SLOT: slot-07

ASSIGNED BRIEF
Radical redesign within the same safe contract. Explore a clearly distinct composition while preserving exact validation requirements.


PARENT SOURCE
def priority(ctx, proposal):
    counts = ctx['capped_cycle_counts']
    broken = proposal['broken_sampled_witnesses_by_length']
    loads = proposal['removed_edge_load_sum_by_length']
    k = proposal['k']
    triangles = proposal['local_triangle_risk']
    c4 = proposal['local_c4_risk']
    coverage = 0
    load_score = 0
    for i in range(16):
        weight = 1
        if i < len(counts):
            weight = 1 + min(counts[i], 8)
        if i < len(broken):
            coverage += broken[i] * weight
        if i < len(loads):
            load_score += loads[i] * weight
    risk = triangles + 2 * c4
    bonus = 0
    if risk <= 6:
        bonus = (k - 2) * 4
    score = coverage * 100 + load_score * 3 - risk * 5 + bonus
    return score

PARENT METADATA
{"app_server_request_id":null,"app_server_thread_id":null,"app_server_turn_id":null,"behavior_signature":"3694bd0b8813621c2abe98186dbbe933f3f7758b7b660d4c9229616e77d76c3c","duplicate_of":null,"error":null,"fitness_status":"verified","generation":0,"generation_mode":"imported-stage3","metadata":{"assumptions":["More broken sampled witnesses indicate greater expected reduction of forbidden-cycle witnesses.","Higher removed-edge sampled witness load indicates greater expected usefulness.","Higher current capped witness counts identify cycle lengths where candidate witness signals deserve more weight.","Higher combined local triangle/C4 risk predicts a less desirable rewrite.","Larger k can be beneficial when local risk is below the fixed control threshold."],"design_summary":"Hypothesis: prioritizing proposals that touch more sampled forbidden witnesses and higher-load witness edges should beat unstructured selection, while a small k bonus should help larger switches only when their bounded local triangle/C4 risk is controlled.","provenance":{"archive_sha256":"4acdc374914005681a0792abc84f4efd424e9a59292869278c144f7bf4bd4b4e","evidence_manifest_sha256":"b1cacc1340bddd548d9b4b3ed2b358c1a99e7d2b24bfe0c589ddc040c84359dc","stage3_canonical_sha256":"43dee7e356ccc3f11c3fff326a78d16c70b0524a5b046732f6aca289335ccd73"},"used_fields":["ctx.capped_cycle_counts","proposal.broken_sampled_witnesses_by_length","proposal.removed_edge_load_sum_by_length","proposal.k","proposal.local_triangle_risk","proposal.local_c4_risk"]},"metrics":{},"mutation_brief_id":null,"normalized_ast_sha256":"cef05bb644e2e0a9acbc4972fbaa6d4ba3e033ee8a73ecd756da44100c767f5c","parent_id":null,"parent_program_id":null,"probe_status":"passed","program_id":"stage3-slot-04","replay_status":"verified","request_id":null,"schema_version":"stage4.program.v1","search_metrics":{"by_order":{"10":{"complete_curve_compatible":true,"episodes":64,"median_accepted":2.5,"median_auc":0.940625,"median_best_total_witness":0.0,"median_best_witnesses":0.0,"median_divergence":31.0,"median_duplicate":25.0,"median_evaluations_to_first_improvement":1.0,"median_first_improvement_ns":0.0,"median_nonimproving":29.5,"median_normalized_best_so_far_auc":0.940625,"median_rejected":29.5},"12":{"complete_curve_compatible":true,"episodes":64,"median_accepted":3.0,"median_auc":0.9166666666666666,"median_best_total_witness":0.0,"median_best_witnesses":0.0,"median_divergence":31.0,"median_duplicate":27.5,"median_evaluations_to_first_improvement":1.0,"median_first_improvement_ns":0.0,"median_nonimproving":29.0,"median_normalized_best_so_far_auc":0.9166666666666666,"median_rejected":29.0}},"complete_curve_compatible":true,"median_accepted":3.0,"median_divergence":31.0,"median_duplicate":26.0,"median_duplicates":26.0,"median_evaluations_to_first_improvement":1.0,"median_first_improvement_ns":0.0,"median_nonimproving":29.0,"median_rejected":29.0,"median_time_to_first_improvement":0.0,"paired_deltas":{"random":{"bootstrap":{"confidence_level":0.95,"interval":[0.11927083333333338,0.18749999999999994],"median":0.14479166666666665,"samples":10000,"seed":2026073004},"median_auc_delta":0.14479166666666665,"relative_median_auc":0.2085889570552146},"structural":{"bootstrap":{"confidence_level":0.95,"interval":[-0.009374999999999967,0.00520833333333337],"median":0.0,"samples":10000,"seed":2026073004},"median_auc_delta":0.0,"relative_median_auc":-0.017728531855955732}},"phase_timing":{"median":{}},"pooled_median_auc":0.9234375,"pooled_median_best_total_witness":0.0,"pooled_median_best_total_witnesses":0.0,"pooled_median_best_witnesses":0.0,"pooled_median_normalized_best_so_far_auc":0.9234375,"worker_health":{"failures":0,"healthy":true,"records":128}},"seed_id":"stage3-slot-04","slot":"slot-04","smoke_10k_status":"passed","source_path":"archive/sources/stage3-slot-04.py","source_sha256":"a5f540459695bbf7d454eeccbb8e48158d6130df6a769b67d1447de18276dc01","thread_id":null,"tombstone":false,"turn_id":null,"usage":{},"validation_status":"valid"}

SEARCH-TRAINING FEEDBACK (COMPACT)
{"behavior_signature":"3694bd0b8813621c2abe98186dbbe933f3f7758b7b660d4c9229616e77d76c3c","median_best_total_witness":0.0,"order_10_median_auc":0.940625,"pooled_median_auc":0.9234375,"program_id":"stage3-slot-04"}

BOUNDED ARCHIVE CONTEXT
[{"ast_sha256":"4f5fe00e9df0c13e1b4b86fcc640908f3c07b0b20150b90d4bfafdb990120465","behavior_signature":"a04d07efc782ae99cfce7a15ea00f13ef5e91de308051d494b559ca6bcc3844d","generation":2,"program_id":"program-0993a28566fea0c416212a86"},{"ast_sha256":"542f77947d9ffb3a5e94d4e7e7a0d2f445a8e17e20b801a90ce532fba1334445","behavior_signature":"65f8d9b747b5d1c14c27554c4b173c1a3fc1dd0a6beae178e235a7a84c6e8206","generation":3,"program_id":"program-09afb6d9d32f17867df27005"},{"ast_sha256":"c321705f3c842f2c4093c0351c9175b7e3d85915a707cf4cd4493d2faee6eab7","behavior_signature":"7a07807493f323694f572c7a7d6519eb554d94fffa43910690492428f3791ee5","generation":4,"program_id":"program-21e113206d7aa0d0f898df70"},{"ast_sha256":"a2ba5f3b89a5520589338194fdbd6eaf7245ab74a8a23472467e585ce8376aae","behavior_signature":"c86ad0b7a9d4ee9add2d884e696808e79f0f720defe1f1ade287ee3bed2f85d2","generation":2,"program_id":"program-2a31faba49191d7f092dacd8"},{"ast_sha256":"f15a20681bb9734e20c29344800ab4d9c3e342a75d3263ee99a901dafeb0cadd","behavior_signature":"c9a017b1423acf0cd705b20570b34ee8c916bda1f5a29792dcf4636c135091cc","generation":4,"program_id":"program-404f87f2d01a5aeae83004a1"},{"ast_sha256":"f169bf5ba2b300869566d95212d81d9e76c734c63ece810c28ddaf7cbea8a40e","behavior_signature":"98c9d51a9da0bb2aca6e1ec96f302af09ef593c8452e57745802567e560144dc","generation":4,"program_id":"program-40a50237da8779157099fc56"},{"ast_sha256":"f0f2346d260dd51d0a1d0ab1d76b8366e3988b2e994e5902134a880968f7618f","behavior_signature":"a4b75610fa14ad4809cd8873f1293766b4244b3018d91dffbd537c80d0ee4c06","generation":4,"program_id":"program-53b072d57250398e0b98fff8"},{"ast_sha256":"399fc6044dc64f9a59db241a347833ce9482ca4ecbbed207df66c5d41d187e00","behavior_signature":"df4cdc7d54c51422bf3a8885a91f941009db38f0edc67825da704a213c966da6","generation":2,"program_id":"program-60e92473fe0fb9dc53dc9a91"}]

Context schema (https://mutation-forge.invalid/schemas/stage2b-context.v1.json):
- schema_version: string constant 'stage2b.context.v1' (required)
- order: integer; minimum 4 (required)
- forbidden_lengths: array (1..16 items; unique) of integer; minimum 1 (required)
- capped_cycle_counts: array (1..16 items) of integer; minimum 0 (required)
- weighted_penalty: integer; minimum 0 (required)
- step: integer; minimum 0 (required)
- remaining_steps: integer; minimum 0 (required)
- stagnation: integer; minimum 0 (required)
- recent_best_improvement: number (required)
- recent_acceptance_rate: number; range [0, 1] (required)
- recent_duplicate_rate: number; range [0, 1] (required)
Alignment: forbidden_lengths and capped_cycle_counts have equal length

Proposal schema (https://mutation-forge.invalid/schemas/stage2b-proposal.v1.json):
- schema_version: string constant 'stage2b.proposal.v1' (required)
- proposal_id: string; pattern '^[0-9a-f]{64}$' (required)
- k: integer; allowed values: [2, 3, 4] (required)
- operator_family: string; allowed values: ['legal_2_switch', 'legal_3_switch', 'legal_4_switch'] (required)
- selector_tags: array (1..8 items) of string; allowed values: ['uniform_random', 'sampled_forbidden_cycle_anchored', 'high_sampled_witness_load', 'remote_from_anchor', 'pairwise_distant_disjoint', 'mixed_exploit_explore'] (required)
- anchor_forbidden_length: null or integer; minimum 1 (required)
- broken_sampled_witnesses_by_length: array (1..16 items) of integer; minimum 0 (required)
- removed_edge_load_sum_by_length: array (1..16 items) of integer; minimum 0 (required)
- removed_edge_load_max_by_length: array (1..16 items) of integer; minimum 0 (required)
- minimum_distance_between_removed_edges: integer; minimum 0 (required)
- mean_distance_between_removed_edges: number; minimum 0 (required)
- minimum_preexisting_distance_for_new_edges: integer; minimum 0 (required)
- mean_preexisting_distance_for_new_edges: number; minimum 0 (required)
- local_triangle_risk: integer; minimum 0 (required)
- local_c4_risk: integer; minimum 0 (required)
- reconnection_span: number; minimum 0 (required)
Alignment: three count vectors align with context.forbidden_lengths
Authority boundary: No graph, vertices, backend, scorer, verifier, or hidden-test data

SCIENTIFIC DECISION PROBLEM

Select legal graph rewrites likely to reduce forbidden-cycle witnesses as early as possible in a bounded search trajectory.

For one current graph, the host creates a bounded pool of already-legal k-switch proposals and calls priority(ctx, proposal) separately for every proposal.
Larger finite priorities are preferred; the host resolves equal numeric priorities deterministically by proposal_id.
Only the selected proposal is applied and authoritatively scored. The ranker never receives true post-rewrite scores for unselected proposals.

IMPORTANT WITHIN-POOL DISTINCTION

ctx describes the current graph and is identical for every proposal in the same pool. Context may modulate or normalize a ranking, but a context-only expression cannot distinguish candidates.
proposal contains candidate-specific bounded structural proxies and must provide the principal within-pool ranking signal.

CONTEXT FIELDS (POOL-CONSTANT)

- ctx.schema_version [string constant 'stage2b.context.v1'; scope=pool_constant]:
  Fixed context contract literal stage2b.context.v1.
  Interpretation: provenance_only.
- ctx.order [integer; minimum 4; scope=pool_constant]:
  Number of vertices in the current graph.
  Interpretation: neutral.
- ctx.forbidden_lengths [array (1..16 items; unique) of integer; minimum 1; scope=pool_constant]:
  Ordered configured cycle lengths used by the aligned context and proposal vectors.
  Interpretation: index_only.
- ctx.capped_cycle_counts [array (1..16 items) of integer; minimum 0; scope=pool_constant]:
  Current bounded witness counts aligned with forbidden_lengths; these are current-state counts, not proposal predictions.
  Interpretation: larger_is_generally_worse_but_capped.
- ctx.weighted_penalty [integer; minimum 0; scope=pool_constant]:
  Aggregate penalty of the current graph under the host scorer; identical for all proposals in the pool.
  Interpretation: larger_is_worse_for_current_state_only.
- ctx.step [integer; minimum 0; scope=pool_constant]:
  Current zero-based search-trajectory step.
  Interpretation: provenance_only.
- ctx.remaining_steps [integer; minimum 0; scope=pool_constant]:
  Number of search decisions remaining after the current step.
  Interpretation: provenance_only.
- ctx.stagnation [integer; minimum 0; scope=pool_constant]:
  Caller-supplied recent steps without strict accepted improvement; the retained Stage 2B path currently supplies the default zero.
  Interpretation: heuristic_history_only.
- ctx.recent_best_improvement [number; scope=pool_constant]:
  Caller-supplied finite summary of recent improvement; the retained Stage 2B path currently supplies the default 0.0.
  Interpretation: caller_defined_history.
- ctx.recent_acceptance_rate [number; range [0, 1]; scope=pool_constant]:
  Caller-supplied recent accepted-move fraction in [0,1]; the retained Stage 2B path currently supplies the default 0.0.
  Interpretation: heuristic_history_only.
- ctx.recent_duplicate_rate [number; range [0, 1]; scope=pool_constant]:
  Caller-supplied recent duplicate-proposal fraction in [0,1]; the retained Stage 2B path currently supplies the default 0.0.
  Interpretation: heuristic_history_only.

PROPOSAL FIELDS (CANDIDATE-SPECIFIC OR PROVENANCE)

- proposal.schema_version [string constant 'stage2b.proposal.v1'; scope=contract_constant]:
  Fixed proposal contract literal stage2b.proposal.v1.
  Interpretation: provenance_only.
- proposal.proposal_id [string; pattern '^[0-9a-f]{64}$'; scope=candidate_specific]:
  Opaque deterministic SHA-256 identifier for the declarative rewrite plan.
  Interpretation: no_quality_signal.
- proposal.k [integer; allowed values: [2, 3, 4]; scope=candidate_specific]:
  Switch arity: the number of pairwise vertex-disjoint existing edges removed and new edges added; one of 2, 3, or 4.
  Interpretation: heuristic_no_guarantee.
- proposal.operator_family [string; allowed values: ['legal_2_switch', 'legal_3_switch', 'legal_4_switch']; scope=candidate_specific_alias]:
  Label legal_2_switch, legal_3_switch, or legal_4_switch, determined exactly by k.
  Interpretation: no_independent_signal.
- proposal.selector_tags [array (1..8 items) of string; allowed values: ['uniform_random', 'sampled_forbidden_cycle_anchored', 'high_sampled_witness_load', 'remote_from_anchor', 'pairwise_distant_disjoint', 'mixed_exploit_explore']; scope=candidate_specific_provenance]:
  Bounded labels describing which deterministic host selector generated the proposal; current generation emits one tag and no tag guarantees quality.
  Interpretation: heuristic_provenance_only.
- proposal.anchor_forbidden_length [null or integer; minimum 1; scope=candidate_specific_provenance]:
  Null unless sampled-forbidden-cycle anchoring was available; otherwise the first configured forbidden length with a nonempty sampled witness set. It does not guarantee that every selected edge breaks that anchor.
  Interpretation: heuristic_provenance_only.
- proposal.broken_sampled_witnesses_by_length [array (1..16 items) of integer; minimum 0; scope=candidate_specific]:
  At index i, the number of sampled source-graph cycles of length ctx.forbidden_lengths[i] touched by at least one removed edge. A cycle touched by multiple removed edges counts once.
  Interpretation: larger_may_be_better_sampled_proxy.
- proposal.removed_edge_load_sum_by_length [array (1..16 items) of integer; minimum 0; scope=candidate_specific]:
  At index i, the sum of sampled source-witness edge loads over all removed edges for ctx.forbidden_lengths[i]; multi-hit cycles can contribute more than once.
  Interpretation: larger_may_be_better_sampled_proxy.
- proposal.removed_edge_load_max_by_length [array (1..16 items) of integer; minimum 0; scope=candidate_specific]:
  At index i, the maximum sampled source-witness load among the removed edges for ctx.forbidden_lengths[i].
  Interpretation: larger_is_concentration_proxy_only.
- proposal.minimum_distance_between_removed_edges [integer; minimum 0; scope=candidate_specific]:
  Minimum pairwise edge distance between removed edges, computed by endpoint BFS distances in the original source graph.
  Interpretation: larger_means_more_separated_heuristically.
- proposal.mean_distance_between_removed_edges [number; minimum 0; scope=candidate_specific]:
  Arithmetic mean of pairwise removed-edge distances in the original source graph; for k=2 it equals the minimum because only one pair exists.
  Interpretation: larger_means_more_spread_heuristically.
- proposal.minimum_preexisting_distance_for_new_edges [integer; minimum 0; scope=candidate_specific]:
  Minimum original-source-graph BFS distance between endpoints that the proposal reconnects, measured before removing or adding edges.
  Interpretation: larger_means_more_remote_heuristically.
- proposal.mean_preexisting_distance_for_new_edges [number; minimum 0; scope=candidate_specific]:
  Mean original-source-graph BFS distance between endpoints that the proposal reconnects, measured before the rewrite.
  Interpretation: larger_means_more_remote_heuristically.
- proposal.local_triangle_risk [integer; minimum 0; scope=candidate_specific]:
  Bounded count of unique triangles around newly added edges after applying the proposal to a local cloned adjacency.
  Interpretation: larger_is_riskier_heuristically.
- proposal.local_c4_risk [integer; minimum 0; scope=candidate_specific]:
  Bounded count of unique 4-cycles around newly added edges after applying the proposal to a local cloned adjacency.
  Interpretation: larger_is_riskier_heuristically.
- proposal.reconnection_span [number; minimum 0; scope=candidate_specific_alias]:
  Exact alias of mean_preexisting_distance_for_new_edges in the current implementation.
  Interpretation: no_independent_signal.

VECTOR ALIGNMENT

- ctx.capped_cycle_counts[i] describes the current graph at cycle length ctx.forbidden_lengths[i].
- proposal.broken_sampled_witnesses_by_length[i], proposal.removed_edge_load_sum_by_length[i], and proposal.removed_edge_load_max_by_length[i] use the same ctx.forbidden_lengths[i] index.

ALIASES AND REDUNDANCIES

- proposal.k, proposal.operator_family: operator_family is exactly legal_{k}_switch and is not independent evidence.
- proposal.mean_preexisting_distance_for_new_edges, proposal.reconnection_span: the two fields are computed from the same arithmetic mean and are exact aliases.

BOUNDED-FEATURE CAVEATS

- Witness features use bounded sampled source-graph cycles and are not exhaustive.
- Distance-budget exhaustion may use graph order as a sentinel distance.
- Local-risk budget exhaustion may return partial or zero local triangle/C4 counts.
- Selector tags are bounded generator provenance, not ground-truth quality labels.

Write the policy and exact response fields now.
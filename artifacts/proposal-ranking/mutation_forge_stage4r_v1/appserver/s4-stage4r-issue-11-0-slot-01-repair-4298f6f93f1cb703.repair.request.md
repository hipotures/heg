Repair the supplied policy using only bounded schema, AST, signature, and finite-output diagnostics.
Performance, fitness, validation-set, archive, and trace feedback is unavailable and must not be inferred.

DIAGNOSTICS
{"ast":[{"code":"multiplication_bound","message":"literal multiplier exceeds the static bound"}],"schema":[{"code":"multiplication_bound","message":"literal multiplier exceeds the static bound"}]}

SOURCE
def priority(ctx, proposal):
    n = min(16, len(ctx["forbidden_lengths"]))
    risk = min(64, proposal["local_triangle_risk"]) + min(64, proposal["local_c4_risk"])
    secondary = 0
    breadth = 0
    load_breadth = 0
    for i in range(n):
        burden = min(12, ctx["capped_cycle_counts"][i])
        hit = min(12, proposal["broken_sampled_witnesses_by_length"][i])
        load = min(24, proposal["removed_edge_load_sum_by_length"][i])
        peak = min(12, proposal["removed_edge_load_max_by_length"][i])
        secondary += hit * (2 + burden)
        secondary += min(load, hit * 4 + peak) * (1 + burden)
        breadth += min(1, hit)
        load_breadth += min(1, load)
    secondary += 20 * breadth + 4 * load_breadth
    secondary += min(32, proposal["minimum_distance_between_removed_edges"])
    secondary += min(32, proposal["mean_distance_between_removed_edges"])
    secondary += min(32, proposal["minimum_preexisting_distance_for_new_edges"])
    secondary += min(32, proposal["mean_preexisting_distance_for_new_edges"])
    if risk == 0:
        secondary += 16
    return -100000 * risk + secondary

Return exactly one stage4.generated_policy.v1 object.

Repair only the output listed below.
[{"code":"multiplication_bound","message":"literal multiplier exceeds the static bound"}]
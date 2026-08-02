Repair the supplied policy using only bounded schema, AST, signature, and finite-output diagnostics.
Performance, fitness, validation-set, archive, and trace feedback is unavailable and must not be inferred.

DIAGNOSTICS
{"ast":[{"code":"multiplication_bound","message":"literal multiplier exceeds the static bound"}],"schema":[{"code":"multiplication_bound","message":"literal multiplier exceeds the static bound"}]}

SOURCE
def priority(ctx, proposal):
    counts = ctx['capped_cycle_counts']
    broken = proposal['broken_sampled_witnesses_by_length']
    loads = proposal['removed_edge_load_sum_by_length']
    breadth = 0
    product = 1
    weighted = 0
    for i in range(16):
        signal = 0
        if i < len(broken):
            signal += broken[i]
        if i < len(loads):
            signal += loads[i]
        if i < len(counts):
            signal *= 1 + min(counts[i], 8)
        if signal > 0:
            breadth += 1
            product *= 1 + min(signal, 24)
            weighted += signal
    risk = proposal['local_triangle_risk'] + 2 * proposal['local_c4_risk']
    separation = proposal['minimum_distance_between_removed_edges'] + proposal['mean_distance_between_removed_edges']
    remoteness = proposal['minimum_preexisting_distance_for_new_edges'] + proposal['mean_preexisting_distance_for_new_edges']
    score = product * 100 + breadth * 1000 + weighted * 3 + separation * 2 + remoteness * 2
    score -= risk * risk * 20
    score -= proposal['k'] * 3
    if ctx['recent_duplicate_rate'] > 0.5:
        score += separation + remoteness
    if ctx['remaining_steps'] <= 4:
        score -= risk * 15
    return score

Return exactly one stage4.generated_policy.v1 object.

Repair only the output listed below.
[{"code":"multiplication_bound","message":"literal multiplier exceeds the static bound"}]
def priority(ctx, proposal):
    counts = ctx['capped_cycle_counts']
    lengths = ctx['forbidden_lengths']
    broken = proposal['broken_sampled_witnesses_by_length']
    loads = proposal['removed_edge_load_sum_by_length']
    score = 0
    for i in range(16):
        if i < len(lengths):
            weight = 1 + min(lengths[i], 16)
            if i < len(counts):
                weight += min(counts[i], 8)
            if i < len(broken):
                score += broken[i] * weight * 80
            if i < len(loads):
                score += loads[i] * weight * 5
    risk = proposal['local_triangle_risk'] + 2 * proposal['local_c4_risk']
    score -= risk * 6
    if risk <= 6:
        score += (proposal['k'] - 2) * 2
    return score
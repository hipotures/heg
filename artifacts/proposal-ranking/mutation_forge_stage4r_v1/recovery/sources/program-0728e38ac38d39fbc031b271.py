def priority(ctx, proposal):
    broken = proposal["broken_sampled_witnesses_by_length"]
    loads = proposal["removed_edge_load_sum_by_length"]
    load_max = proposal["removed_edge_load_max_by_length"]
    counts = ctx["capped_cycle_counts"]
    stagnation = min(6, ctx["stagnation"])
    urgent = 0
    if ctx["remaining_steps"] < 4:
        urgent = 2
    explore = 1 + stagnation
    if ctx["remaining_steps"] > 8:
        explore += 1
    explore += round(2 * ctx["recent_duplicate_rate"])
    score = 0
    for i in range(16):
        if i < len(broken):
            state = 0
            if i < len(counts):
                state = min(4, counts[i])
            b = broken[i] / (1 + broken[i])
            l = loads[i] / (1 + loads[i])
            m = load_max[i] / (1 + load_max[i])
            score += (56 + 8 * state + 8 * urgent) * b
            score += (6 + state) * l
            score += 2 * m
    score += (2 + explore) * proposal["minimum_distance_between_removed_edges"] / (1 + proposal["minimum_distance_between_removed_edges"])
    score += (2 + explore) * proposal["mean_distance_between_removed_edges"] / (1 + proposal["mean_distance_between_removed_edges"])
    score += (2 + explore) * proposal["minimum_preexisting_distance_for_new_edges"] / (1 + proposal["minimum_preexisting_distance_for_new_edges"])
    score += (1 + explore) * proposal["mean_preexisting_distance_for_new_edges"] / (1 + proposal["mean_preexisting_distance_for_new_edges"])
    score -= (16 + min(4, stagnation) + urgent) * proposal["local_triangle_risk"] / (1 + proposal["local_triangle_risk"])
    score -= (8 + min(3, stagnation) + urgent) * proposal["local_c4_risk"] / (1 + proposal["local_c4_risk"])
    score += 0.01 * proposal["k"] / 4
    score += 0.001 * proposal["minimum_distance_between_removed_edges"] / (1 + proposal["minimum_distance_between_removed_edges"])
    score += 0.0001 * proposal["mean_preexisting_distance_for_new_edges"] / (1 + proposal["mean_preexisting_distance_for_new_edges"])
    return score
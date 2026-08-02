def priority(ctx, proposal):
    lengths = ctx["forbidden_lengths"]
    counts = ctx["capped_cycle_counts"]
    broken = proposal["broken_sampled_witnesses_by_length"]
    loads = proposal["removed_edge_load_sum_by_length"]
    peaks = proposal["removed_edge_load_max_by_length"]
    limit = min(16, len(lengths))
    total = 0
    weighted_broken = 0
    weighted_load = 0
    weighted_peak = 0
    for i in range(limit):
        relevance = 1 + min(8, counts[i])
        total += relevance
        weighted_broken += relevance * min(16, broken[i])
        weighted_load += relevance * min(16, loads[i])
        weighted_peak += relevance * min(16, peaks[i])
    denominator = max(1, total)
    stalled = min(4, ctx["stagnation"])
    explore = stalled / 4
    remaining = min(16, ctx["remaining_steps"])
    urgency = 1 / (1 + remaining)
    spread = min(16, proposal["minimum_distance_between_removed_edges"]) + min(16, proposal["mean_distance_between_removed_edges"])
    remote = min(16, proposal["minimum_preexisting_distance_for_new_edges"]) + min(16, proposal["mean_preexisting_distance_for_new_edges"])
    score = (8 + 4 * urgency + 2 * explore) * weighted_broken / denominator + (3 + explore) * weighted_load / denominator + 0.5 * weighted_peak / denominator + (1 + 4 * explore) * spread + (1 + 2 * explore) * remote - (5 + 2 * explore) * min(16, proposal["local_triangle_risk"]) - (4 + 2 * explore) * min(16, proposal["local_c4_risk"])
    return round(score, 6)
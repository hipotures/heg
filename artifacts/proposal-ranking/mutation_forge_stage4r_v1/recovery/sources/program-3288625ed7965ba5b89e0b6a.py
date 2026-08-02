def priority(ctx, proposal):
    lengths = ctx["forbidden_lengths"]
    counts = ctx["capped_cycle_counts"]
    order = ctx["order"]
    broken = proposal["broken_sampled_witnesses_by_length"]
    loads = proposal["removed_edge_load_sum_by_length"]
    separation = proposal["mean_distance_between_removed_edges"]
    tags = proposal["selector_tags"]
    n = len(lengths)
    hit_total = 0.0
    load_total = 0.0
    for i in range(16):
        if i < n:
            scale = max(1, counts[i])
            hit_total = hit_total + broken[i] / scale
            load_total = load_total + loads[i] / max(1, scale * 4)
    hit_fraction = hit_total / max(1, n)
    load_fraction = load_total / max(1, n)
    normalized_separation = separation / max(1, order)
    risk = (proposal["local_triangle_risk"] + proposal["local_c4_risk"]) / max(1, order)
    selector_bonus = 0.0
    if "sampled_forbidden_cycle_anchored" in tags:
        selector_bonus = selector_bonus + 0.08
    if "high_sampled_witness_load" in tags:
        selector_bonus = selector_bonus + 0.08
    if "pairwise_distant_disjoint" in tags:
        selector_bonus = selector_bonus + 0.04
    if "remote_from_anchor" in tags:
        selector_bonus = selector_bonus + 0.03
    if "mixed_exploit_explore" in tags:
        selector_bonus = selector_bonus + 0.02
    selector_bonus = min(0.18, selector_bonus)
    selector_bonus = selector_bonus * (0.25 + 0.75 * min(1.0, hit_fraction))
    return 5.0 * hit_fraction + 2.0 * load_fraction + normalized_separation + selector_bonus - 0.25 * risk
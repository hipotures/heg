def priority(ctx, proposal):
    counts = ctx["capped_cycle_counts"]
    broken = proposal["broken_sampled_witnesses_by_length"]
    loads = proposal["removed_edge_load_sum_by_length"]
    n = max(1, min(16, len(counts)))
    coverage = 0.0
    load = 0.0
    for i in range(16):
        if i < n and i < len(broken) and i < len(loads):
            c = min(1000000, max(0, counts[i]))
            b = min(1000000, max(0, broken[i]))
            l = min(1000000, max(0, loads[i]))
            weight = 1.0 + c / (1.0 + c)
            coverage = coverage + weight * b / (1.0 + b)
            load = load + l / (1.0 + l)
    coverage = coverage / (2.0 * n)
    load = load / n
    risk_raw = min(1000000, max(0, proposal["local_triangle_risk"]) + max(0, proposal["local_c4_risk"]))
    risk = risk_raw / (1.0 + risk_raw)
    return coverage + 0.02 * load - 0.005 * risk
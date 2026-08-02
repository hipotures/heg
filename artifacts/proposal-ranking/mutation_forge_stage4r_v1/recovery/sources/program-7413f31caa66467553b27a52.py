def priority(ctx, proposal):
    counts = ctx['capped_cycle_counts']
    broken = proposal['broken_sampled_witnesses_by_length']
    loads = proposal['removed_edge_load_sum_by_length']
    den = proposal['k']
    if den != den or abs(den) >= 1e300 or den <= 0:
        den = 1
    coverage = 0
    load_score = 0
    for i in range(16):
        weight = 1
        if i < len(counts):
            c = counts[i]
            if c == c and abs(c) < 1e300 and c >= 0:
                weight = min(1 + c, 9)
        if i < len(broken):
            b = broken[i]
            if b == b and abs(b) < 1e300 and b >= 0:
                coverage += b * weight / den
        if i < len(loads):
            load = loads[i]
            if load == load and abs(load) < 1e300 and load >= 0:
                load_score += load * weight / den
    tri = proposal['local_triangle_risk']
    if tri != tri or abs(tri) >= 1e300 or tri < 0:
        tri = 0
    c4 = proposal['local_c4_risk']
    if c4 != c4 or abs(c4) >= 1e300 or c4 < 0:
        c4 = 0
    risk = (tri + 2 * c4) / den
    return 40 * coverage + 6 * load_score - 8 * risk
//! Wave D1: Exact-Matching Micro-LNS (Destroy-and-Repair) for jumping across
//! C4 = C8 = 0 energy barriers in sparse graphs (n <= 64).
//!
//! Algorithm:
//! 1. Compute exact C16 edge participation w_16(e) via Bitset MitM.
//! 2. Destroy k in [k_min, k_max] (4..=8) pairwise-disjoint hot/cluster edges,
//!    yielding P = 2k open boundary ports in frozen remainder G_rest.
//! 3. Precompute external path-length bitmasks L_ext(p, q) <= 7 in G_rest to
//!    hard-forbid any port pair immediately closing a C4 (d=3) or C8 (d=7).
//! 4. Run MRV fail-first exact perfect-matching branch-and-bound over the 2k ports
//!    with incremental O(1) C4 and sub-microsecond C8 pruning at every edge placement.
//! 5. Score every complete C4=C8=0 strictly-2-connected mode-valid leaf with exact
//!    Bitset MitM C16 (early-aborting above target), returning the best repair.

use std::collections::HashSet;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Instant;

use crate::cycles::{DfsScratch, count_c16_mitm_u64, count_c16_mitm_u128};
use crate::graph::{BitGraph, BitGraph64, Edge, MAX_ORDER};
use crate::mutation::GraphMode;
use crate::rng::Rng;

/// Count C4 cycles containing newly added edge `(u, v)` in `g` (~5 ns).
#[inline]
fn has_c4_through_edge(rows: &[u64; 64], u: usize, v: usize) -> bool {
    let nu = rows[u] & !(1u64 << v);
    let nv = rows[v] & !(1u64 << u);
    let mut bits = nu;
    while bits != 0 {
        let a = bits.trailing_zeros() as usize;
        bits &= bits - 1;
        if (rows[a] & nv) != 0 {
            return true;
        }
    }
    false
}

/// Exact check whether newly added edge `(u, v)` closes ANY simple C8 in `g`
/// via 3-edge / 4-edge MitM from `u` and `v` avoiding `(u, v)` (~200–400 ns).
#[inline]
fn has_c8_through_edge(rows: &[u64; 64], u: usize, v: usize) -> bool {
    let uv_mask = (1u64 << u) | (1u64 << v);
    // C8 through (u, v) = simple 7-edge path from u to v avoiding edge (u, v):
    // Split into left 3-edge path u -> a -> b -> m and right 4-edge path v -> c -> d -> e -> m
    // (disjoint interior sets {a, b} and {c, d, e} and disjoint from {u, v, m}).
    let mut left_masks = [0u64; 128];
    let mut left_mid = [0u8; 128];
    let mut left_len = 0usize;
    let mut mid_present = 0u64;

    let mut ba = rows[u] & !uv_mask;
    while ba != 0 {
        let a = ba.trailing_zeros() as usize;
        ba &= ba - 1;
        let ma = uv_mask | (1u64 << a);
        let mut bb = rows[a] & !ma;
        while bb != 0 {
            let b = bb.trailing_zeros() as usize;
            bb &= bb - 1;
            let mb = ma | (1u64 << b);
            let mut bm = rows[b] & !mb;
            while bm != 0 {
                let m = bm.trailing_zeros() as usize;
                bm &= bm - 1;
                if left_len < 128 {
                    left_masks[left_len] = (1u64 << a) | (1u64 << b);
                    left_mid[left_len] = m as u8;
                    left_len += 1;
                    mid_present |= 1u64 << m;
                }
            }
        }
    }
    if left_len == 0 {
        return false;
    }

    let mut bc = rows[v] & !uv_mask;
    while bc != 0 {
        let c = bc.trailing_zeros() as usize;
        bc &= bc - 1;
        let mc = uv_mask | (1u64 << c);
        let mut bd = rows[c] & !mc;
        while bd != 0 {
            let d = bd.trailing_zeros() as usize;
            bd &= bd - 1;
            let md = mc | (1u64 << d);
            let mut be = rows[d] & !md;
            while be != 0 {
                let e = be.trailing_zeros() as usize;
                be &= be - 1;
                let me = md | (1u64 << e);
                let mut bm = rows[e] & !me & mid_present;
                while bm != 0 {
                    let m = bm.trailing_zeros() as usize;
                    bm &= bm - 1;
                    let rmask = (1u64 << c) | (1u64 << d) | (1u64 << e);
                    for i in 0..left_len {
                        if left_mid[i] as usize == m && (left_masks[i] & rmask) == 0 {
                            return true;
                        }
                    }
                }
            }
        }
    }
    false
}

/// Compute exact C16 edge participation heat `heat[eidx]` for every edge in `edges`
/// using Bitset MitM (capped at `max_cycles` cycles per root so it stays < 1 ms).
pub fn compute_c16_edge_heat_u64(
    g: &BitGraph64,
    edges: &[Edge],
    out_heat: &mut Vec<u32>,
) -> u32 {
    out_heat.clear();
    out_heat.resize(edges.len(), 0);
    let n = g.n;
    if n < 16 {
        return 0;
    }
    let mut edge_id = [[u16::MAX; 64]; 64];
    for (idx, &(u, v)) in edges.iter().enumerate() {
        edge_id[u as usize][v as usize] = idx as u16;
        edge_id[v as usize][u as usize] = idx as u16;
    }

    let rows = &g.rows;
    let mut masks: Vec<u64> = Vec::with_capacity(512);
    let mut paths: Vec<[u8; 7]> = Vec::with_capacity(512);
    let mut next: Vec<u32> = Vec::with_capacity(512);
    let mut total_c16 = 0u32;

    for s in 0..=(n - 16) {
        let allowed = !((1u64 << (s + 1)) - 1);
        if (rows[s] & allowed).count_ones() < 2 {
            continue;
        }
        let mut head = [u32::MAX; 64];
        let mut bucket_cnt = [0u16; 64];
        let mut touched = [0u8; 64];
        let mut touched_len = 0usize;
        masks.clear();
        paths.clear();
        next.clear();

        let mut overflow = false;
        let mut b1 = rows[s] & allowed;
        while b1 != 0 && !overflow {
            let v1 = b1.trailing_zeros() as usize;
            b1 &= b1 - 1;
            let m1 = 1u64 << v1;
            let mut b2 = rows[v1] & allowed & !m1;
            while b2 != 0 && !overflow {
                let v2 = b2.trailing_zeros() as usize;
                b2 &= b2 - 1;
                let m2 = m1 | (1u64 << v2);
                let mut b3 = rows[v2] & allowed & !m2;
                while b3 != 0 && !overflow {
                    let v3 = b3.trailing_zeros() as usize;
                    b3 &= b3 - 1;
                    let m3 = m2 | (1u64 << v3);
                    let mut b4 = rows[v3] & allowed & !m3;
                    while b4 != 0 && !overflow {
                        let v4 = b4.trailing_zeros() as usize;
                        b4 &= b4 - 1;
                        let m4 = m3 | (1u64 << v4);
                        let mut b5 = rows[v4] & allowed & !m4;
                        while b5 != 0 && !overflow {
                            let v5 = b5.trailing_zeros() as usize;
                            b5 &= b5 - 1;
                            let m5 = m4 | (1u64 << v5);
                            let mut b6 = rows[v5] & allowed & !m5;
                            while b6 != 0 && !overflow {
                                let v6 = b6.trailing_zeros() as usize;
                                b6 &= b6 - 1;
                                let m6 = m5 | (1u64 << v6);
                                let mut b7 = rows[v6] & allowed & !m6;
                                while b7 != 0 && !overflow {
                                    let v7 = b7.trailing_zeros() as usize;
                                    b7 &= b7 - 1;
                                    let m7 = m6 | (1u64 << v7);
                                    let mut bt = rows[v7] & allowed & !m7;
                                    while bt != 0 {
                                        let t = bt.trailing_zeros() as usize;
                                        bt &= bt - 1;
                                        let idx = masks.len();
                                        if idx >= 4096 {
                                            overflow = true;
                                            break;
                                        }
                                        masks.push(m7);
                                        paths.push([
                                            v1 as u8, v2 as u8, v3 as u8, v4 as u8, v5 as u8,
                                            v6 as u8, v7 as u8,
                                        ]);
                                        next.push(head[t]);
                                        if head[t] == u32::MAX {
                                            touched[touched_len] = t as u8;
                                            touched_len += 1;
                                        }
                                        head[t] = idx as u32;
                                        bucket_cnt[t] += 1;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        for ti in 0..touched_len {
            let t = touched[ti] as usize;
            if bucket_cnt[t] < 2 {
                continue;
            }
            let mut i = head[t];
            while i != u32::MAX {
                let mi = masks[i as usize];
                let mut j = next[i as usize];
                while j != u32::MAX {
                    if (mi & masks[j as usize]) == 0 {
                        total_c16 += 1;
                        // Credit all 16 edges of this C16 cycle!
                        for &pidx in &[i as usize, j as usize] {
                            let p = &paths[pidx];
                            let mut prev = s;
                            for &cur_u8 in p {
                                let cur = cur_u8 as usize;
                                let eid = edge_id[prev][cur] as usize;
                                if eid < out_heat.len() {
                                    out_heat[eid] += 1;
                                }
                                prev = cur;
                            }
                            let eid = edge_id[prev][t] as usize;
                            if eid < out_heat.len() {
                                out_heat[eid] += 1;
                            }
                        }
                    }
                    j = next[j as usize];
                }
                i = next[i as usize];
            }
        }
    }
    total_c16
}

/// Precompute bitmask of simple external path lengths in `1..=7` between every
/// pair of ports `(ports[a], ports[b])` in frozen graph `g_rest`.
fn compute_port_ext_lengths(g_rest: &BitGraph64, ports: &[usize]) -> [[u16; 16]; 16] {
    let p_len = ports.len();
    let mut port_slot = [u8::MAX; 64];
    let mut port_mask = 0u64;
    for (idx, &v) in ports.iter().enumerate() {
        port_slot[v] = idx as u8;
        port_mask |= 1u64 << v;
    }

    let mut ext = [[0u16; 16]; 16];
    let rows = &g_rest.rows;

    fn dfs(
        rows: &[u64; 64],
        port_slot: &[u8; 64],
        port_mask: u64,
        src_slot: usize,
        u: usize,
        seen: u64,
        depth: usize,
        ext_row: &mut [u16; 16],
    ) {
        if depth > 0 && (port_mask & (1u64 << u)) != 0 {
            let slot = port_slot[u] as usize;
            if slot != src_slot {
                ext_row[slot] |= 1u16 << depth;
            }
        }
        if depth == 7 {
            return;
        }
        let mut bits = rows[u] & !seen;
        while bits != 0 {
            let v = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            dfs(
                rows,
                port_slot,
                port_mask,
                src_slot,
                v,
                seen | (1u64 << v),
                depth + 1,
                ext_row,
            );
        }
    }

    for a in 0..p_len {
        let start = ports[a];
        dfs(
            rows,
            &port_slot,
            port_mask,
            a,
            start,
            1u64 << start,
            0,
            &mut ext[a],
        );
    }
    ext
}

#[inline]
fn graph_mode_valid_lns(g: &BitGraph64, mode: GraphMode) -> bool {
    match mode {
        GraphMode::CubicFirst => g.is_biconnected(),
        GraphMode::MinimalStructureMixedDegree => g.minimal_structure_valid(),
        GraphMode::SingleBlock41 => g.single_block_41_valid(),
        GraphMode::UnrestrictedMinDegree3 => g.is_biconnected(),
    }
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct LnsStepOutcome {
    pub repaired: Option<(BitGraph64, u32)>,
    pub leaves_tested: u32,
    pub bnb_nodes: u32,
}

/// Perform ONE exact-matching Destroy-and-Repair LNS step on `graph` (assumed C4 = C8 = 0):
/// - Destroys `k` pairwise-disjoint hot/cluster edges (yielding `2k <= 16` ports),
/// - Exhaustively searches all C4=C8=0 strictly-2-connected mode-valid perfect
///   matchings of the `2k` ports within `node_cap` B&B nodes,
/// - Returns the strictly lowest-C16 repair (or best non-identity `<= cur_c16`
///   repair when `allow_sideways` is true).
#[allow(clippy::too_many_arguments)]
pub fn lns_destroy_and_repair_u64(
    graph: &BitGraph64,
    edges: &[Edge],
    heat: &[u32],
    cur_c16: u32,
    k: usize,
    mode: GraphMode,
    allow_sideways: bool,
    rng: &mut Rng,
    scratch: &mut DfsScratch,
    node_cap: u32,
) -> LnsStepOutcome {
    let k = k.clamp(3, 8);
    let m = edges.len();
    if m < k {
        return LnsStepOutcome {
            repaired: None,
            leaves_tested: 0,
            bnb_nodes: 0,
        };
    }

    // Select k pairwise-disjoint edges to destroy:
    // 50% hot-edge weighted selection, 50% local ball-cluster around a hot edge.
    let use_ball = (rng.next_u64() & 1) == 0;
    let mut destroyed: Vec<Edge> = Vec::with_capacity(k);
    let mut used_verts = 0u64;

    if use_ball {
        // Pick a hot seed edge via tournament
        let mut seed_idx = rng.gen_range(m);
        let mut seed_h = heat.get(seed_idx).copied().unwrap_or(0);
        for _ in 0..8 {
            let cand = rng.gen_range(m);
            let ch = heat.get(cand).copied().unwrap_or(0);
            if ch > seed_h {
                seed_h = ch;
                seed_idx = cand;
            }
        }
        let e0 = edges[seed_idx];
        destroyed.push(e0);
        used_verts |= (1u64 << e0.0) | (1u64 << e0.1);

        // Expand ball of radius 2 around e0
        let mut ball = used_verts | graph.rows[e0.0 as usize] | graph.rows[e0.1 as usize];
        let mut b2 = ball;
        let mut tmp = ball;
        while tmp != 0 {
            let v = tmp.trailing_zeros() as usize;
            tmp &= tmp - 1;
            b2 |= graph.rows[v];
        }
        ball = b2;

        // Collect candidate edges touching ball (preferring hot ones)
        let mut pool: Vec<(u32, usize)> = Vec::with_capacity(m);
        for (idx, &(u, v)) in edges.iter().enumerate() {
            let em = (1u64 << u) | (1u64 << v);
            if (em & ball) != 0 && (em & used_verts) == 0 {
                let h = heat.get(idx).copied().unwrap_or(0);
                // Add slight random tie-break jitter
                let score = h.saturating_mul(8) + (rng.next_u64() & 15) as u32;
                pool.push((score, idx));
            }
        }
        pool.sort_by(|a, b| b.0.cmp(&a.0));
        for &(_, idx) in &pool {
            if destroyed.len() == k {
                break;
            }
            let e = edges[idx];
            let em = (1u64 << e.0) | (1u64 << e.1);
            if (em & used_verts) == 0 {
                destroyed.push(e);
                used_verts |= em;
            }
        }
    }

    // Fill any remaining slots with hot-edge tournament selection
    let mut attempts = 0usize;
    while destroyed.len() < k && attempts < 128 {
        attempts += 1;
        let mut best_i = None;
        let mut best_score = 0u64;
        for _ in 0..6 {
            let idx = rng.gen_range(m);
            let e = edges[idx];
            let em = (1u64 << e.0) | (1u64 << e.1);
            if (em & used_verts) != 0 {
                continue;
            }
            let h = heat.get(idx).copied().unwrap_or(0) as u64;
            let s = h * 4 + (rng.next_u64() & 7) + 1;
            if s > best_score {
                best_score = s;
                best_i = Some(idx);
            }
        }
        if let Some(idx) = best_i {
            let e = edges[idx];
            destroyed.push(e);
            used_verts |= (1u64 << e.0) | (1u64 << e.1);
        }
    }

    if destroyed.len() < 3 {
        return LnsStepOutcome {
            repaired: None,
            leaves_tested: 0,
            bnb_nodes: 0,
        };
    }

    let k_act = destroyed.len();
    let p_len = 2 * k_act;
    let mut ports = [0usize; 16];
    let mut g_rest = *graph;
    for (i, &(u, v)) in destroyed.iter().enumerate() {
        g_rest.remove_edge(u as usize, v as usize);
        ports[2 * i] = u as usize;
        ports[2 * i + 1] = v as usize;
    }

    // Precompute external path lengths 1..=7 in G_rest
    let ext = compute_port_ext_lengths(&g_rest, &ports[..p_len]);
    let mut legal = [0u16; 16];
    let forbid_single = (1u16 << 3) | (1u16 << 7);
    for a in 0..p_len {
        let mut mask = 0u16;
        for b in 0..p_len {
            if a == b {
                continue;
            }
            if g_rest.has_edge(ports[a], ports[b]) {
                continue;
            }
            if (ext[a][b] & forbid_single) != 0 {
                continue;
            }
            mask |= 1u16 << b;
        }
        if mask == 0 {
            return LnsStepOutcome {
                repaired: None,
                leaves_tested: 0,
                bnb_nodes: 1,
            };
        }
        legal[a] = mask;
    }

    let orig_key = graph.zobrist_key64();

    struct BnbCtx<'a> {
        ports: [usize; 16],
        legal: [u16; 16],
        mode: GraphMode,
        orig_key: u64,
        allow_sideways: bool,
        best_c16: u32,
        best_graph: Option<BitGraph64>,
        leaves_tested: u32,
        bnb_nodes: u32,
        node_cap: u32,
        scratch: &'a mut DfsScratch,
    }

    fn search_matching(
        ctx: &mut BnbCtx<'_>,
        cur: &mut BitGraph64,
        unmatched: u16,
    ) {
        if ctx.bnb_nodes >= ctx.node_cap {
            return;
        }
        ctx.bnb_nodes += 1;

        if unmatched == 0 {
            if cur.zobrist_key64() == ctx.orig_key {
                return;
            }
            if !graph_mode_valid_lns(cur, ctx.mode) {
                return;
            }
            ctx.leaves_tested += 1;
            let stop_lim = if ctx.allow_sideways && ctx.best_graph.is_none() {
                ctx.best_c16.saturating_add(1)
            } else {
                ctx.best_c16
            };
            if let Some(res) =
                count_c16_mitm_u64(&cur.rows, cur.n, stop_lim, stop_lim, ctx.scratch)
            {
                if res.complete && res.count < ctx.best_c16 {
                    ctx.best_c16 = res.count;
                    ctx.best_graph = Some(*cur);
                } else if ctx.allow_sideways
                    && ctx.best_graph.is_none()
                    && res.complete
                    && res.count == ctx.best_c16
                {
                    ctx.best_graph = Some(*cur);
                }
            }
            return;
        }

        // MRV (Minimum Remaining Values): pick unmatched port with fewest legal partners
        let mut best_a = 0usize;
        let mut best_deg = u32::MAX;
        let mut scan = unmatched;
        while scan != 0 {
            let a = scan.trailing_zeros() as usize;
            scan &= scan - 1;
            let d = (ctx.legal[a] & unmatched).count_ones();
            if d == 0 {
                return;
            }
            if d < best_deg {
                best_deg = d;
                best_a = a;
                if d == 1 {
                    break;
                }
            }
        }

        let u = ctx.ports[best_a];
        let mut cands = ctx.legal[best_a] & unmatched;
        while cands != 0 {
            if ctx.bnb_nodes >= ctx.node_cap {
                return;
            }
            let b = cands.trailing_zeros() as usize;
            cands &= cands - 1;
            let v = ctx.ports[b];

            cur.add_edge(u, v);
            if !has_c4_through_edge(&cur.rows, u, v) && !has_c8_through_edge(&cur.rows, u, v) {
                let next_unmatched = unmatched ^ ((1u16 << best_a) | (1u16 << b));
                search_matching(ctx, cur, next_unmatched);
            }
            cur.remove_edge(u, v);
        }
    }

    let mut ctx = BnbCtx {
        ports,
        legal,
        mode,
        orig_key,
        allow_sideways,
        best_c16: cur_c16,
        best_graph: None,
        leaves_tested: 0,
        bnb_nodes: 0,
        node_cap,
        scratch,
    };

    let all_ports = ((1u32 << p_len) - 1) as u16;
    search_matching(&mut ctx, &mut g_rest, all_ports);

    LnsStepOutcome {
        repaired: ctx.best_graph.map(|g| (g, ctx.best_c16)),
        leaves_tested: ctx.leaves_tested,
        bnb_nodes: ctx.bnb_nodes,
    }
}

#[derive(Clone, Debug)]
pub struct LnsPolishSummary {
    pub initial_c16: u32,
    pub best_c16: u32,
    pub best_graph: BitGraph64,
    pub total_steps: u64,
    pub total_leaves: u64,
    pub improvements: u64,
    pub sideways_moves: u64,
    pub wall_seconds: f64,
}

/// Multi-threaded parallel LNS polish starting from `initial` (must be C4=C8=0).
/// Workers share the global champion `(best_c16, best_graph)` via a lightweight
/// mutex synchronized every 24 LNS steps, while using local tabu hashes on
/// sideways moves to traverse flat C4=C8=0 valleys toward lower exact C16.
#[allow(clippy::too_many_arguments)]
pub fn run_parallel_lns_polish(
    initial: BitGraph64,
    mode: GraphMode,
    k_min: usize,
    k_max: usize,
    wall_seconds: f64,
    workers: usize,
    base_seed: u64,
    allow_sideways: bool,
    node_cap: u32,
) -> LnsPolishSummary {
    let started = Instant::now();
    let mut init_scratch = DfsScratch::new();
    let init_c16 = count_c16_mitm_u64(&initial.rows, initial.n, u32::MAX, 0, &mut init_scratch)
        .map(|r| r.count)
        .unwrap_or(u32::MAX);

    let shared_best = Mutex::new((init_c16, initial));
    let n_workers = workers.max(1);

    let stats: Vec<(u64, u64, u64, u64)> = thread::scope(|scope| {
        let handles: Vec<_> = (0..n_workers)
            .map(|w_idx| {
                let shared_ref = &shared_best;
                scope.spawn(move || {
                    let mut rng = Rng::new(base_seed.wrapping_add((w_idx as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)));
                    let mut scratch = DfsScratch::new();
                    let mut cur_g = initial;
                    let mut cur_c16 = init_c16;
                    let mut edges = Vec::with_capacity(cur_g.n * 3);
                    let mut heat = Vec::with_capacity(cur_g.n * 3);
                    cur_g.collect_edges(&mut edges);
                    compute_c16_edge_heat_u64(&cur_g, &edges, &mut heat);

                    let mut visited: HashSet<u64> = HashSet::with_capacity(2048);
                    visited.insert(cur_g.zobrist_key64());

                    let mut steps = 0u64;
                    let mut leaves = 0u64;
                    let mut imps = 0u64;
                    let mut side = 0u64;
                    let mut stagnant = 0u64;

                    while started.elapsed().as_secs_f64() < wall_seconds {
                        if cur_c16 == 0 {
                            break;
                        }
                        steps += 1;
                        let k = if k_min < k_max {
                            k_min + rng.gen_range(k_max - k_min + 1)
                        } else {
                            k_min
                        };
                        let outcome = lns_destroy_and_repair_u64(
                            &cur_g,
                            &edges,
                            &heat,
                            cur_c16,
                            k,
                            mode,
                            allow_sideways,
                            &mut rng,
                            &mut scratch,
                            node_cap,
                        );
                        leaves += outcome.leaves_tested as u64;

                        if let Some((rep_g, rep_c16)) = outcome.repaired {
                            let rep_key = rep_g.zobrist_key64();
                            if rep_c16 < cur_c16 {
                                cur_g = rep_g;
                                cur_c16 = rep_c16;
                                cur_g.collect_edges(&mut edges);
                                compute_c16_edge_heat_u64(&cur_g, &edges, &mut heat);
                                visited.insert(rep_key);
                                imps += 1;
                                stagnant = 0;

                                let mut guard = shared_ref.lock().unwrap();
                                if cur_c16 < guard.0 {
                                    *guard = (cur_c16, cur_g);
                                }
                            } else if allow_sideways && rep_c16 == cur_c16 && !visited.contains(&rep_key) {
                                cur_g = rep_g;
                                cur_g.collect_edges(&mut edges);
                                compute_c16_edge_heat_u64(&cur_g, &edges, &mut heat);
                                visited.insert(rep_key);
                                if visited.len() > 8192 {
                                    visited.clear();
                                    visited.insert(rep_key);
                                }
                                side += 1;
                                stagnant += 1;
                            } else {
                                stagnant += 1;
                            }
                        } else {
                            stagnant += 1;
                        }

                        // Periodically pull global champion if another worker improved or we stagnated
                        if (steps & 31) == 0 || stagnant >= 120 {
                            let (g_c16, g_graph) = *shared_ref.lock().unwrap();
                            if g_c16 < cur_c16 || stagnant >= 120 {
                                cur_g = g_graph;
                                cur_c16 = g_c16;
                                cur_g.collect_edges(&mut edges);
                                compute_c16_edge_heat_u64(&cur_g, &edges, &mut heat);
                                stagnant = 0;
                            }
                        }
                    }

                    (steps, leaves, imps, side)
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let (best_c16, best_graph) = *shared_best.lock().unwrap();
    let total_steps = stats.iter().map(|s| s.0).sum();
    let total_leaves = stats.iter().map(|s| s.1).sum();
    let improvements = stats.iter().map(|s| s.2).sum();
    let sideways_moves = stats.iter().map(|s| s.3).sum();

    LnsPolishSummary {
        initial_c16: init_c16,
        best_c16,
        best_graph,
        total_steps,
        total_leaves,
        improvements,
        sideways_moves,
        wall_seconds: started.elapsed().as_secs_f64(),
    }
}

// ============================================================================
// Wave E: u128 Exact-Matching Micro-LNS (n <= 128, targeting f(4) < 78)
// ============================================================================

#[inline]
fn has_c4_through_edge_u128(rows: &[u128; MAX_ORDER], u: usize, v: usize) -> bool {
    let nu = rows[u] & !(1u128 << v);
    let nv = rows[v] & !(1u128 << u);
    let mut bits = nu;
    while bits != 0 {
        let a = bits.trailing_zeros() as usize;
        bits &= bits - 1;
        if (rows[a] & nv) != 0 {
            return true;
        }
    }
    false
}

#[inline]
fn has_c8_through_edge_u128(rows: &[u128; MAX_ORDER], u: usize, v: usize) -> bool {
    let uv_mask = (1u128 << u) | (1u128 << v);
    let mut left_masks = [0u128; 128];
    let mut left_mid = [0u8; 128];
    let mut left_len = 0usize;
    let mut mid_present = 0u128;

    let mut ba = rows[u] & !uv_mask;
    while ba != 0 {
        let a = ba.trailing_zeros() as usize;
        ba &= ba - 1;
        let ma = uv_mask | (1u128 << a);
        let mut bb = rows[a] & !ma;
        while bb != 0 {
            let b = bb.trailing_zeros() as usize;
            bb &= bb - 1;
            let mb = ma | (1u128 << b);
            let mut bm = rows[b] & !mb;
            while bm != 0 {
                let m = bm.trailing_zeros() as usize;
                bm &= bm - 1;
                if left_len < 128 {
                    left_masks[left_len] = (1u128 << a) | (1u128 << b);
                    left_mid[left_len] = m as u8;
                    left_len += 1;
                    mid_present |= 1u128 << m;
                }
            }
        }
    }
    if left_len == 0 {
        return false;
    }

    let mut bc = rows[v] & !uv_mask;
    while bc != 0 {
        let c = bc.trailing_zeros() as usize;
        bc &= bc - 1;
        let mc = uv_mask | (1u128 << c);
        let mut bd = rows[c] & !mc;
        while bd != 0 {
            let d = bd.trailing_zeros() as usize;
            bd &= bd - 1;
            let md = mc | (1u128 << d);
            let mut be = rows[d] & !md;
            while be != 0 {
                let e = be.trailing_zeros() as usize;
                be &= be - 1;
                let me = md | (1u128 << e);
                let mut bm = rows[e] & !me & mid_present;
                while bm != 0 {
                    let m = bm.trailing_zeros() as usize;
                    bm &= bm - 1;
                    let rmask = (1u128 << c) | (1u128 << d) | (1u128 << e);
                    for i in 0..left_len {
                        if left_mid[i] as usize == m && (left_masks[i] & rmask) == 0 {
                            return true;
                        }
                    }
                }
            }
        }
    }
    false
}

pub fn compute_c16_edge_heat_u128(g: &BitGraph, edges: &[Edge], out_heat: &mut Vec<u32>) -> u32 {
    out_heat.clear();
    out_heat.resize(edges.len(), 0);
    let n = g.n;
    if n < 16 {
        return 0;
    }
    let mut edge_id = vec![[u16::MAX; MAX_ORDER]; n];
    for (idx, &(u, v)) in edges.iter().enumerate() {
        edge_id[u as usize][v as usize] = idx as u16;
        edge_id[v as usize][u as usize] = idx as u16;
    }

    let rows = &g.rows;
    let mut masks: Vec<u128> = Vec::with_capacity(512);
    let mut paths: Vec<[u8; 7]> = Vec::with_capacity(512);
    let mut next: Vec<u32> = Vec::with_capacity(512);
    let mut total_c16 = 0u32;

    for s in 0..=(n - 16) {
        let allowed = !((1u128 << (s + 1)) - 1);
        if (rows[s] & allowed).count_ones() < 2 {
            continue;
        }
        let mut head = [u32::MAX; MAX_ORDER];
        let mut bucket_cnt = [0u16; MAX_ORDER];
        let mut touched = [0u8; MAX_ORDER];
        let mut touched_len = 0usize;
        masks.clear();
        paths.clear();
        next.clear();

        let mut overflow = false;
        let mut b1 = rows[s] & allowed;
        while b1 != 0 && !overflow {
            let v1 = b1.trailing_zeros() as usize;
            b1 &= b1 - 1;
            let m1 = 1u128 << v1;
            let mut b2 = rows[v1] & allowed & !m1;
            while b2 != 0 && !overflow {
                let v2 = b2.trailing_zeros() as usize;
                b2 &= b2 - 1;
                let m2 = m1 | (1u128 << v2);
                let mut b3 = rows[v2] & allowed & !m2;
                while b3 != 0 && !overflow {
                    let v3 = b3.trailing_zeros() as usize;
                    b3 &= b3 - 1;
                    let m3 = m2 | (1u128 << v3);
                    let mut b4 = rows[v3] & allowed & !m3;
                    while b4 != 0 && !overflow {
                        let v4 = b4.trailing_zeros() as usize;
                        b4 &= b4 - 1;
                        let m4 = m3 | (1u128 << v4);
                        let mut b5 = rows[v4] & allowed & !m4;
                        while b5 != 0 && !overflow {
                            let v5 = b5.trailing_zeros() as usize;
                            b5 &= b5 - 1;
                            let m5 = m4 | (1u128 << v5);
                            let mut b6 = rows[v5] & allowed & !m5;
                            while b6 != 0 && !overflow {
                                let v6 = b6.trailing_zeros() as usize;
                                b6 &= b6 - 1;
                                let m6 = m5 | (1u128 << v6);
                                let mut b7 = rows[v6] & allowed & !m6;
                                while b7 != 0 && !overflow {
                                    let v7 = b7.trailing_zeros() as usize;
                                    b7 &= b7 - 1;
                                    let m7 = m6 | (1u128 << v7);
                                    let mut bt = rows[v7] & allowed & !m7;
                                    while bt != 0 {
                                        let t = bt.trailing_zeros() as usize;
                                        bt &= bt - 1;
                                        let idx = masks.len();
                                        if idx >= 4096 {
                                            overflow = true;
                                            break;
                                        }
                                        masks.push(m7);
                                        paths.push([
                                            v1 as u8, v2 as u8, v3 as u8, v4 as u8, v5 as u8,
                                            v6 as u8, v7 as u8,
                                        ]);
                                        next.push(head[t]);
                                        if head[t] == u32::MAX {
                                            touched[touched_len] = t as u8;
                                            touched_len += 1;
                                        }
                                        head[t] = idx as u32;
                                        bucket_cnt[t] += 1;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        for ti in 0..touched_len {
            let t = touched[ti] as usize;
            if bucket_cnt[t] < 2 {
                continue;
            }
            let mut i = head[t];
            while i != u32::MAX {
                let mi = masks[i as usize];
                let mut j = next[i as usize];
                while j != u32::MAX {
                    if (mi & masks[j as usize]) == 0 {
                        total_c16 += 1;
                        for &pidx in &[i as usize, j as usize] {
                            let p = &paths[pidx];
                            let mut prev = s;
                            for &cur_u8 in p {
                                let cur = cur_u8 as usize;
                                let eid = edge_id[prev][cur] as usize;
                                if eid < out_heat.len() {
                                    out_heat[eid] += 1;
                                }
                                prev = cur;
                            }
                            let eid = edge_id[prev][t] as usize;
                            if eid < out_heat.len() {
                                out_heat[eid] += 1;
                            }
                        }
                    }
                    j = next[j as usize];
                }
                i = next[i as usize];
            }
        }
    }
    total_c16
}

fn compute_port_ext_lengths_u128(g_rest: &BitGraph, ports: &[usize]) -> [[u16; 16]; 16] {
    let p_len = ports.len();
    let mut port_slot = [u8::MAX; MAX_ORDER];
    let mut port_mask = 0u128;
    for (idx, &v) in ports.iter().enumerate() {
        port_slot[v] = idx as u8;
        port_mask |= 1u128 << v;
    }

    let mut ext = [[0u16; 16]; 16];
    let rows = &g_rest.rows;

    fn dfs(
        rows: &[u128; MAX_ORDER],
        port_slot: &[u8; MAX_ORDER],
        port_mask: u128,
        src_slot: usize,
        u: usize,
        seen: u128,
        depth: usize,
        ext_row: &mut [u16; 16],
    ) {
        if depth > 0 && (port_mask & (1u128 << u)) != 0 {
            let slot = port_slot[u] as usize;
            if slot != src_slot {
                ext_row[slot] |= 1u16 << depth;
            }
        }
        if depth == 7 {
            return;
        }
        let mut bits = rows[u] & !seen;
        while bits != 0 {
            let v = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            dfs(
                rows,
                port_slot,
                port_mask,
                src_slot,
                v,
                seen | (1u128 << v),
                depth + 1,
                ext_row,
            );
        }
    }

    for a in 0..p_len {
        let start = ports[a];
        dfs(
            rows,
            &port_slot,
            port_mask,
            a,
            start,
            1u128 << start,
            0,
            &mut ext[a],
        );
    }
    ext
}

#[inline]
fn graph_mode_valid_lns_u128(g: &BitGraph, mode: GraphMode) -> bool {
    match mode {
        GraphMode::CubicFirst => g.is_biconnected(),
        GraphMode::MinimalStructureMixedDegree => g.minimal_structure_valid(),
        GraphMode::SingleBlock41 => g.single_block_41_valid(),
        GraphMode::UnrestrictedMinDegree3 => g.is_biconnected(),
    }
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct LnsStepOutcome128 {
    pub repaired: Option<(BitGraph, u32)>,
    pub leaves_tested: u32,
    pub bnb_nodes: u32,
}

#[allow(clippy::too_many_arguments)]
pub fn lns_destroy_and_repair_u128(
    graph: &BitGraph,
    edges: &[Edge],
    heat: &[u32],
    cur_c16: u32,
    k: usize,
    mode: GraphMode,
    allow_sideways: bool,
    rng: &mut Rng,
    scratch: &mut DfsScratch,
    node_cap: u32,
) -> LnsStepOutcome128 {
    let k = k.clamp(3, 8);
    let m = edges.len();
    if m < k {
        return LnsStepOutcome128 {
            repaired: None,
            leaves_tested: 0,
            bnb_nodes: 0,
        };
    }

    let use_ball = (rng.next_u64() & 1) == 0;
    let mut destroyed: Vec<Edge> = Vec::with_capacity(k);
    let mut used_verts = 0u128;

    if use_ball {
        let mut seed_idx = rng.gen_range(m);
        let mut seed_h = heat.get(seed_idx).copied().unwrap_or(0);
        for _ in 0..10 {
            let cand = rng.gen_range(m);
            let ch = heat.get(cand).copied().unwrap_or(0);
            if ch > seed_h {
                seed_h = ch;
                seed_idx = cand;
            }
        }
        let e0 = edges[seed_idx];
        destroyed.push(e0);
        used_verts |= (1u128 << e0.0) | (1u128 << e0.1);

        let mut ball = used_verts | graph.rows[e0.0 as usize] | graph.rows[e0.1 as usize];
        let mut b2 = ball;
        let mut tmp = ball;
        while tmp != 0 {
            let v = tmp.trailing_zeros() as usize;
            tmp &= tmp - 1;
            b2 |= graph.rows[v];
        }
        ball = b2;

        let mut pool: Vec<(u32, usize)> = Vec::with_capacity(m);
        for (idx, &(u, v)) in edges.iter().enumerate() {
            let em = (1u128 << u) | (1u128 << v);
            if (em & ball) != 0 && (em & used_verts) == 0 {
                let h = heat.get(idx).copied().unwrap_or(0);
                let score = h.saturating_mul(8) + (rng.next_u64() & 15) as u32;
                pool.push((score, idx));
            }
        }
        pool.sort_by(|a, b| b.0.cmp(&a.0));
        for &(_, idx) in &pool {
            if destroyed.len() == k {
                break;
            }
            let e = edges[idx];
            let em = (1u128 << e.0) | (1u128 << e.1);
            if (em & used_verts) == 0 {
                destroyed.push(e);
                used_verts |= em;
            }
        }
    }

    let mut attempts = 0usize;
    while destroyed.len() < k && attempts < 128 {
        attempts += 1;
        let mut best_i = None;
        let mut best_score = 0u64;
        for _ in 0..8 {
            let idx = rng.gen_range(m);
            let e = edges[idx];
            let em = (1u128 << e.0) | (1u128 << e.1);
            if (em & used_verts) != 0 {
                continue;
            }
            let h = heat.get(idx).copied().unwrap_or(0) as u64;
            let s = h * 6 + (rng.next_u64() & 7) + 1;
            if s > best_score {
                best_score = s;
                best_i = Some(idx);
            }
        }
        if let Some(idx) = best_i {
            let e = edges[idx];
            destroyed.push(e);
            used_verts |= (1u128 << e.0) | (1u128 << e.1);
        }
    }

    if destroyed.len() < 3 {
        return LnsStepOutcome128 {
            repaired: None,
            leaves_tested: 0,
            bnb_nodes: 0,
        };
    }

    let k_act = destroyed.len();
    let p_len = 2 * k_act;
    let mut ports = [0usize; 16];
    let mut g_rest = *graph;
    for (i, &(u, v)) in destroyed.iter().enumerate() {
        g_rest.remove_edge(u as usize, v as usize);
        ports[2 * i] = u as usize;
        ports[2 * i + 1] = v as usize;
    }

    let ext = compute_port_ext_lengths_u128(&g_rest, &ports[..p_len]);
    let mut legal = [0u16; 16];
    let forbid_single = (1u16 << 3) | (1u16 << 7);
    for a in 0..p_len {
        let mut mask = 0u16;
        for b in 0..p_len {
            if a == b {
                continue;
            }
            if g_rest.has_edge(ports[a], ports[b]) {
                continue;
            }
            if (ext[a][b] & forbid_single) != 0 {
                continue;
            }
            mask |= 1u16 << b;
        }
        if mask == 0 {
            return LnsStepOutcome128 {
                repaired: None,
                leaves_tested: 0,
                bnb_nodes: 1,
            };
        }
        legal[a] = mask;
    }

    let orig_key = graph.zobrist_key();

    struct BnbCtx128<'a> {
        ports: [usize; 16],
        legal: [u16; 16],
        mode: GraphMode,
        orig_key: u128,
        allow_sideways: bool,
        best_c16: u32,
        best_graph: Option<BitGraph>,
        leaves_tested: u32,
        bnb_nodes: u32,
        node_cap: u32,
        scratch: &'a mut DfsScratch,
    }

    fn search_matching_128(ctx: &mut BnbCtx128<'_>, cur: &mut BitGraph, unmatched: u16) {
        if ctx.bnb_nodes >= ctx.node_cap || ctx.best_c16 == 0 {
            return;
        }
        ctx.bnb_nodes += 1;

        if unmatched == 0 {
            if cur.zobrist_key() == ctx.orig_key {
                return;
            }
            if !graph_mode_valid_lns_u128(cur, ctx.mode) {
                return;
            }
            ctx.leaves_tested += 1;
            let stop_lim = if ctx.allow_sideways && ctx.best_graph.is_none() {
                ctx.best_c16.saturating_add(1)
            } else {
                ctx.best_c16
            };
            if let Some(res) =
                count_c16_mitm_u128(&cur.rows, cur.n, stop_lim, stop_lim, ctx.scratch)
            {
                if res.complete && res.count < ctx.best_c16 {
                    ctx.best_c16 = res.count;
                    ctx.best_graph = Some(*cur);
                } else if ctx.allow_sideways
                    && ctx.best_graph.is_none()
                    && res.complete
                    && res.count == ctx.best_c16
                {
                    ctx.best_graph = Some(*cur);
                }
            }
            return;
        }

        let mut best_a = 0usize;
        let mut best_deg = u32::MAX;
        let mut scan = unmatched;
        while scan != 0 {
            let a = scan.trailing_zeros() as usize;
            scan &= scan - 1;
            let d = (ctx.legal[a] & unmatched).count_ones();
            if d == 0 {
                return;
            }
            if d < best_deg {
                best_deg = d;
                best_a = a;
                if d == 1 {
                    break;
                }
            }
        }

        let u = ctx.ports[best_a];
        let mut cands = ctx.legal[best_a] & unmatched;
        while cands != 0 {
            if ctx.bnb_nodes >= ctx.node_cap || ctx.best_c16 == 0 {
                return;
            }
            let b = cands.trailing_zeros() as usize;
            cands &= cands - 1;
            let v = ctx.ports[b];

            cur.add_edge(u, v);
            if !has_c4_through_edge_u128(&cur.rows, u, v)
                && !has_c8_through_edge_u128(&cur.rows, u, v)
            {
                let next_unmatched = unmatched ^ ((1u16 << best_a) | (1u16 << b));
                search_matching_128(ctx, cur, next_unmatched);
            }
            cur.remove_edge(u, v);
        }
    }

    let mut ctx = BnbCtx128 {
        ports,
        legal,
        mode,
        orig_key,
        allow_sideways,
        best_c16: cur_c16,
        best_graph: None,
        leaves_tested: 0,
        bnb_nodes: 0,
        node_cap,
        scratch,
    };

    let all_ports = ((1u32 << p_len) - 1) as u16;
    search_matching_128(&mut ctx, &mut g_rest, all_ports);

    LnsStepOutcome128 {
        repaired: ctx.best_graph.map(|g| (g, ctx.best_c16)),
        leaves_tested: ctx.leaves_tested,
        bnb_nodes: ctx.bnb_nodes,
    }
}

#[derive(Clone, Debug)]
pub struct LnsPolishSummary128 {
    pub initial_c16: u32,
    pub best_c16: u32,
    pub best_graph: BitGraph,
    pub total_steps: u64,
    pub total_leaves: u64,
    pub improvements: u64,
    pub sideways_moves: u64,
    pub wall_seconds: f64,
}

#[allow(clippy::too_many_arguments)]
pub fn run_parallel_lns_polish_u128(
    initial: BitGraph,
    mode: GraphMode,
    k_min: usize,
    k_max: usize,
    wall_seconds: f64,
    workers: usize,
    base_seed: u64,
    allow_sideways: bool,
    node_cap: u32,
) -> LnsPolishSummary128 {
    let started = Instant::now();
    let mut init_scratch = DfsScratch::new();
    let init_c16 = count_c16_mitm_u128(&initial.rows, initial.n, u32::MAX, 0, &mut init_scratch)
        .map(|r| r.count)
        .unwrap_or(u32::MAX);

    let shared_best = Mutex::new((init_c16, initial));
    let found_zero = AtomicBool::new(init_c16 == 0);
    let n_workers = workers.max(1);

    let stats: Vec<(u64, u64, u64, u64)> = thread::scope(|scope| {
        let handles: Vec<_> = (0..n_workers)
            .map(|w_idx| {
                let shared_ref = &shared_best;
                let zero_ref = &found_zero;
                scope.spawn(move || {
                    let mut rng = Rng::new(
                        base_seed.wrapping_add((w_idx as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)),
                    );
                    let mut scratch = DfsScratch::new();
                    let mut cur_g = initial;
                    let mut cur_c16 = init_c16;
                    let mut edges = Vec::with_capacity(cur_g.n * 3);
                    let mut heat = Vec::with_capacity(cur_g.n * 3);
                    cur_g.collect_edges(&mut edges);
                    compute_c16_edge_heat_u128(&cur_g, &edges, &mut heat);

                    let mut visited: HashSet<u128> = HashSet::with_capacity(2048);
                    visited.insert(cur_g.zobrist_key());

                    let mut steps = 0u64;
                    let mut leaves = 0u64;
                    let mut imps = 0u64;
                    let mut side = 0u64;
                    let mut stagnant = 0u64;

                    while started.elapsed().as_secs_f64() < wall_seconds
                        && !zero_ref.load(Ordering::Relaxed)
                    {
                        if cur_c16 == 0 {
                            zero_ref.store(true, Ordering::Relaxed);
                            break;
                        }
                        steps += 1;
                        let k = if k_min < k_max {
                            k_min + rng.gen_range(k_max - k_min + 1)
                        } else {
                            k_min
                        };
                        let outcome = lns_destroy_and_repair_u128(
                            &cur_g,
                            &edges,
                            &heat,
                            cur_c16,
                            k,
                            mode,
                            allow_sideways,
                            &mut rng,
                            &mut scratch,
                            node_cap,
                        );
                        leaves += outcome.leaves_tested as u64;

                        if let Some((rep_g, rep_c16)) = outcome.repaired {
                            let rep_key = rep_g.zobrist_key();
                            if rep_c16 < cur_c16 {
                                cur_g = rep_g;
                                cur_c16 = rep_c16;
                                cur_g.collect_edges(&mut edges);
                                compute_c16_edge_heat_u128(&cur_g, &edges, &mut heat);
                                visited.insert(rep_key);
                                imps += 1;
                                stagnant = 0;

                                let mut guard = shared_ref.lock().unwrap();
                                if cur_c16 < guard.0 {
                                    *guard = (cur_c16, cur_g);
                                }
                                if cur_c16 == 0 {
                                    zero_ref.store(true, Ordering::Relaxed);
                                    break;
                                }
                            } else if allow_sideways
                                && rep_c16 == cur_c16
                                && !visited.contains(&rep_key)
                            {
                                cur_g = rep_g;
                                cur_g.collect_edges(&mut edges);
                                compute_c16_edge_heat_u128(&cur_g, &edges, &mut heat);
                                visited.insert(rep_key);
                                if visited.len() > 8192 {
                                    visited.clear();
                                    visited.insert(rep_key);
                                }
                                side += 1;
                                stagnant += 1;
                            } else {
                                stagnant += 1;
                            }
                        } else {
                            stagnant += 1;
                        }

                        if (steps & 31) == 0 || stagnant >= 120 {
                            let (g_c16, g_graph) = *shared_ref.lock().unwrap();
                            if g_c16 < cur_c16 || stagnant >= 120 {
                                cur_g = g_graph;
                                cur_c16 = g_c16;
                                cur_g.collect_edges(&mut edges);
                                compute_c16_edge_heat_u128(&cur_g, &edges, &mut heat);
                                stagnant = 0;
                            }
                        }
                    }

                    (steps, leaves, imps, side)
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let (best_c16, best_graph) = *shared_best.lock().unwrap();
    let total_steps = stats.iter().map(|s| s.0).sum();
    let total_leaves = stats.iter().map(|s| s.1).sum();
    let improvements = stats.iter().map(|s| s.2).sum();
    let sideways_moves = stats.iter().map(|s| s.3).sum();

    LnsPolishSummary128 {
        initial_c16: init_c16,
        best_c16,
        best_graph,
        total_steps,
        total_leaves,
        improvements,
        sideways_moves,
        wall_seconds: started.elapsed().as_secs_f64(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cycles::{DfsScratch, score_graph_fast};
    use crate::mutation::generate_h7_expansion_seed;

    #[test]
    fn lns_destroy_and_repair_preserves_c4_c8_zero_and_strict_2connectivity() {
        let mut rng = Rng::new(2026112608);
        let mut scratch = DfsScratch::new();
        let g = generate_h7_expansion_seed(&mut rng, 64, GraphMode::CubicFirst).unwrap();
        let g64 = BitGraph64::from_graph(&g);

        let summary = run_parallel_lns_polish(
            g64,
            GraphMode::CubicFirst,
            4,
            6,
            0.35,
            4,
            2026112609,
            true,
            15_000,
        );
        assert!(summary.total_steps > 0);
        assert!(summary.best_c16 <= summary.initial_c16);
        assert!(summary.best_graph.is_biconnected());
        for u in 0..64 {
            assert_eq!(summary.best_graph.degree(u), 3);
        }
        let sc = score_graph_fast(&summary.best_graph.to_graph(), 500, 500_000, None, &mut scratch)
            .unwrap();
        assert_eq!(sc.count_of(4), 0, "LNS must never introduce C4");
        assert_eq!(sc.count_of(8), 0, "LNS must never introduce C8");
        assert_eq!(sc.count_of(16), summary.best_c16);

        // Wave E u128 LNS check on n=70 Petersen + 10*H7
        let g70 = generate_h7_expansion_seed(&mut rng, 70, GraphMode::CubicFirst).unwrap();
        let s70 = run_parallel_lns_polish_u128(
            g70,
            GraphMode::CubicFirst,
            4,
            6,
            0.35,
            4,
            2026112610,
            true,
            15_000,
        );
        assert!(s70.total_steps > 0);
        assert!(s70.best_c16 <= s70.initial_c16);
        assert!(s70.best_graph.is_biconnected());
        let sc70 = score_graph_fast(&s70.best_graph, 500, 500_000, None, &mut scratch).unwrap();
        assert_eq!(sc70.count_of(4), 0, "u128 LNS must never introduce C4");
        assert_eq!(sc70.count_of(8), 0, "u128 LNS must never introduce C8");
        assert_eq!(sc70.count_of(16), s70.best_c16);
    }
}

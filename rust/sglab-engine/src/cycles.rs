//! Ultra-fast cycle counting & scoring:
//! 1. Parity-exact DFS (`count_cycles`) for `--serve` v2 protocol (with u64 fast path).
//! 2. Fast exact/pruned engine for native Rust search:
//!    - Analytic bitwise C4 (zero DFS, ~0.15 us for n=64)
//!    - Exact Meet-in-the-Middle C8 (~1-2 us for n=64)
//!    - Dedicated forced-vertex + dead-end pruned Hamiltonian counter (`target == n`)
//!      for C32 (n=32) and C64 (n=64)
//!    - Register-resident recursive u64 DFS with pre-filled `dist_mask` and
//!      2-level `popcnt` leaf collapse for C16/C32/C64/C128
//! 3. Zero-allocation stack-only witness-cycle discovery with distance pruning.

use std::time::Instant;

use crate::bank::CycleBank64;
use crate::graph::{BitGraph, BitGraph64, Edge, MAX_ORDER, normalize_edge};

pub const FORBIDDEN_ALL: [u16; 6] = [4, 8, 16, 32, 64, 128];

#[inline]
pub fn forbidden_lengths(n: usize) -> &'static [u16] {
    let mut count = 0;
    while count < FORBIDDEN_ALL.len() && (FORBIDDEN_ALL[count] as usize) <= n {
        count += 1;
    }
    &FORBIDDEN_ALL[..count]
}

#[derive(Clone, Copy, Debug, Default)]
pub struct CountResult {
    pub length: u16,
    pub count: u32,
    pub complete: bool,
    pub nodes: u64,
    pub elapsed_ns: u64,
    pub cutoff_reached: bool,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Cutoff {
    pub total: u32,
    pub weighted: u32,
    pub simplicity: u32,
    pub inclusive: bool,
}

impl Cutoff {
    #[inline]
    pub fn reached(&self, total: u32, weighted: u32, simplicity: u32) -> bool {
        let greater = total > self.total
            || (total == self.total
                && (weighted > self.weighted
                    || (weighted == self.weighted && simplicity > self.simplicity)));
        let equal =
            total == self.total && weighted == self.weighted && simplicity == self.simplicity;
        greater || (self.inclusive && equal)
    }
}

/// Stack-allocated Copy score (zero heap allocations in the search hot loop).
#[derive(Clone, Copy, Debug)]
pub struct ScoreResult {
    pub valid: bool,
    pub counts: [(u16, u32); 6],
    pub counts_len: u8,
    pub complete_mask: u8,
    pub total: u32,
    pub weighted_penalty: u32,
    pub complete: bool,
    pub simplicity: u32,
}

impl ScoreResult {
    #[inline]
    pub fn counts_slice(&self) -> &[(u16, u32)] {
        &self.counts[..(self.counts_len as usize)]
    }

    #[inline]
    pub fn nonzero_len_mask(&self) -> u8 {
        let mut mask = 0u8;
        for i in 0..(self.counts_len as usize) {
            if self.counts[i].1 > 0 {
                mask |= 1u8 << i;
            }
        }
        mask
    }

    #[inline]
    pub fn c4_c8_zero(&self) -> bool {
        for i in 0..(self.counts_len as usize) {
            let (len, cnt) = self.counts[i];
            if (len == 4 || len == 8) && cnt > 0 {
                return false;
            }
        }
        true
    }

    #[inline]
    pub fn has_saturated_length(&self, cap: u32) -> bool {
        for i in 0..(self.counts_len as usize) {
            if self.counts[i].1 >= cap {
                return true;
            }
        }
        false
    }

    #[inline]
    pub fn ordering_key(&self) -> (u8, u32, u32, u32) {
        (
            if self.valid { 0 } else { 1 },
            self.total,
            self.weighted_penalty,
            self.simplicity,
        )
    }

    #[inline]
    pub fn scalar(&self) -> f64 {
        let invalid = if self.valid { 0.0 } else { 1.0 };
        invalid * 2_000_000.0
            + (self.total as f64)
            + (self.weighted_penalty as f64) / 2_000_000.0
            + (self.simplicity as f64) / 80_000_000_000_000_000.0
    }
}

/// Reusable DFS scratch buffers (zero heap allocations in the hot loop).
pub struct DfsScratch {
    pub seen_at: [u128; MAX_ORDER],
    pub available_at: [u128; MAX_ORDER],
    pub seen_at64: [u64; 64],
    pub available_at64: [u64; 64],
    pub dist_mask64: [u64; 65],
    pub dist_mask128: [u128; MAX_ORDER + 1],
    pub path: [u8; MAX_ORDER],
    pub mitm_left_mid: [u8; 64],
    pub mitm_left_mask: [u64; 64],
}

impl DfsScratch {
    pub fn new() -> Self {
        Self {
            seen_at: [0u128; MAX_ORDER],
            available_at: [0u128; MAX_ORDER],
            seen_at64: [0u64; 64],
            available_at64: [0u64; 64],
            dist_mask64: [0u64; 65],
            dist_mask128: [0u128; MAX_ORDER + 1],
            path: [0u8; MAX_ORDER],
            mitm_left_mid: [0u8; 64],
            mitm_left_mask: [0u64; 64],
        }
    }
}

// ============================================================================
// 1. PARITY-EXACT DFS FOR `--serve` v2 PROTOCOL (matches cpp/sglab_score_worker.cpp)
// ============================================================================

#[inline]
fn count_cycles_parity_u64(
    rows: &[u64; 64],
    order: usize,
    length: u16,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
    measure_time: bool,
) -> CountResult {
    let started = if measure_time {
        Some(Instant::now())
    } else {
        None
    };
    let mut result = CountResult {
        length,
        ..Default::default()
    };
    let mut budget_exhausted = false;
    let target = length as usize;
    let budget = node_budget as u64;
    let seen_at = &mut scratch.seen_at64;
    let available_at = &mut scratch.available_at64;

    for start in 0..order {
        let start_bit = 1u64 << start;
        let greater_mask: u64 = if start >= 63 {
            0
        } else {
            !((1u64 << (start + 1)) - 1)
        };
        seen_at[0] = start_bit;
        available_at[0] = rows[start] & greater_mask;
        result.nodes += 1;
        if budget != 0 && result.nodes > budget {
            budget_exhausted = true;
            break;
        }

        let mut depth: usize = 1;
        let mut first_neighbor: usize = 0;
        while depth != 0 {
            let parent_index = depth - 1;
            let bits = available_at[parent_index];
            if bits == 0 {
                depth -= 1;
                continue;
            }
            let vertex = bits.trailing_zeros() as usize;
            let bit = 1u64 << vertex;
            available_at[parent_index] = bits ^ bit;
            if depth == 1 {
                first_neighbor = vertex;
            }
            let seen = seen_at[parent_index] | bit;
            seen_at[depth] = seen;
            result.nodes += 1;
            if budget != 0 && result.nodes > budget {
                budget_exhausted = true;
                break;
            }

            let child_depth = depth + 1;
            if child_depth == target {
                if (rows[vertex] & start_bit) != 0 && first_neighbor < vertex {
                    result.count += 1;
                    if stop_at_count != 0 && result.count >= stop_at_count {
                        result.cutoff_reached = true;
                        break;
                    }
                    if result.count >= limit {
                        break;
                    }
                }
                continue;
            }
            available_at[depth] = rows[vertex] & !seen & greater_mask;
            depth = child_depth;
        }
        if result.count >= limit || budget_exhausted || result.cutoff_reached {
            break;
        }
    }

    result.complete = !budget_exhausted && !result.cutoff_reached && result.count < limit;
    if let Some(t0) = started {
        result.elapsed_ns = t0.elapsed().as_nanos() as u64;
    }
    result
}

/// Exact bit-for-bit equivalent of `count_cycles` in `cpp/sglab_score_worker.cpp`.
pub fn count_cycles(
    graph: &BitGraph,
    length: u16,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
    measure_time: bool,
) -> CountResult {
    if graph.n <= 64 {
        let g64 = BitGraph64::from_graph(graph);
        return count_cycles_parity_u64(
            &g64.rows,
            g64.n,
            length,
            limit,
            node_budget,
            stop_at_count,
            scratch,
            measure_time,
        );
    }
    let started = if measure_time {
        Some(Instant::now())
    } else {
        None
    };
    let mut result = CountResult {
        length,
        ..Default::default()
    };
    let mut budget_exhausted = false;
    let order = graph.n;
    let target = length as usize;
    let budget = node_budget as u64;

    let rows = &graph.rows;
    let seen_at = &mut scratch.seen_at;
    let available_at = &mut scratch.available_at;

    for start in 0..order {
        let start_bit = 1u128 << start;
        let greater_mask: u128 = if start >= 127 {
            0
        } else {
            !((1u128 << (start + 1)) - 1)
        };
        seen_at[0] = start_bit;
        available_at[0] = rows[start] & greater_mask;
        result.nodes += 1;
        if budget != 0 && result.nodes > budget {
            budget_exhausted = true;
            break;
        }

        let mut depth: usize = 1;
        let mut first_neighbor: usize = 0;
        while depth != 0 {
            let parent_index = depth - 1;
            let bits = available_at[parent_index];
            if bits == 0 {
                depth -= 1;
                continue;
            }
            let vertex = bits.trailing_zeros() as usize;
            let bit = 1u128 << vertex;
            available_at[parent_index] = bits ^ bit;
            if depth == 1 {
                first_neighbor = vertex;
            }
            let seen = seen_at[parent_index] | bit;
            seen_at[depth] = seen;
            result.nodes += 1;
            if budget != 0 && result.nodes > budget {
                budget_exhausted = true;
                break;
            }

            let child_depth = depth + 1;
            if child_depth == target {
                if (rows[vertex] & start_bit) != 0 && first_neighbor < vertex {
                    result.count += 1;
                    if stop_at_count != 0 && result.count >= stop_at_count {
                        result.cutoff_reached = true;
                        break;
                    }
                    if result.count >= limit {
                        break;
                    }
                }
                continue;
            }
            available_at[depth] = rows[vertex] & !seen & greater_mask;
            depth = child_depth;
        }
        if result.count >= limit || budget_exhausted || result.cutoff_reached {
            break;
        }
    }

    result.complete = !budget_exhausted && !result.cutoff_reached && result.count < limit;
    if let Some(t0) = started {
        result.elapsed_ns = t0.elapsed().as_nanos() as u64;
    }
    result
}

/// Parity-exact length evaluator used by `--serve` v2 protocol.
pub fn evaluate_lengths(
    graph: &BitGraph,
    lengths: &[u16],
    cap: u32,
    node_budget: u32,
    cutoff: Option<Cutoff>,
    longest_first: bool,
    scratch: &mut DfsScratch,
    measure_time: bool,
) -> (bool, Vec<CountResult>) {
    let limit = cap + 1;
    let simplicity = graph.size();
    let mut partial_total = 0u32;
    let mut partial_weighted = 0u32;
    let mut dominated = false;
    let mut results = Vec::with_capacity(lengths.len());

    for eval_idx in 0..lengths.len() {
        let len_idx = if longest_first {
            lengths.len() - 1 - eval_idx
        } else {
            eval_idx
        };
        let length = lengths[len_idx];
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                dominated = true;
                break;
            }
        }
        let weight = (64u32 / (length as u32)).max(1);
        let mut stop_at_count = 0u32;
        if let Some(co) = cutoff {
            for c in 1..=limit {
                let bounded = c.min(cap);
                if co.reached(
                    partial_total + bounded,
                    partial_weighted + bounded * weight,
                    simplicity,
                ) {
                    stop_at_count = c;
                    break;
                }
            }
        }
        let res = count_cycles(
            graph,
            length,
            limit,
            node_budget,
            stop_at_count,
            scratch,
            measure_time,
        );
        let effective_count = if !res.complete && !res.cutoff_reached {
            cap
        } else {
            res.count.min(cap)
        };
        partial_total += effective_count;
        partial_weighted += effective_count * weight;
        let hit_cutoff = res.cutoff_reached
            || cutoff
                .map(|co| co.reached(partial_total, partial_weighted, simplicity))
                .unwrap_or(false);
        results.push(res);
        if hit_cutoff {
            dominated = true;
            break;
        }
    }

    (dominated, results)
}

// ============================================================================
// 2. ULTRA-FAST ALGORITHMIC SCORER
// ============================================================================

/// Exact count of simple C4 cycles containing edge `(u, v)` in `rows`.
#[inline]
fn count_c4_through_edge_u64(rows: &[u64; 64], u: usize, v: usize) -> u32 {
    let nu = rows[u] & !(1u64 << v);
    let mut nv = rows[v] & !(1u64 << u);
    let mut c = 0u32;
    while nv != 0 {
        let x = nv.trailing_zeros() as usize;
        nv &= nv - 1;
        c += (rows[x] & nu).count_ones();
    }
    c
}

/// Exact count of simple C4 cycles containing at least one of two vertex-disjoint
/// edges `e1`, `e2` present in `rows`.
#[inline]
pub fn count_c4_through_two_edges_u64(rows: &[u64; 64], e1: Edge, e2: Edge) -> u32 {
    let (u1, v1) = (e1.0 as usize, e1.1 as usize);
    let (u2, v2) = (e2.0 as usize, e2.1 as usize);
    let c1 = count_c4_through_edge_u64(rows, u1, v1);
    let c2 = count_c4_through_edge_u64(rows, u2, v2);
    let c_both = u32::from(
        (rows[v1] & (1u64 << u2)) != 0 && (rows[u1] & (1u64 << v2)) != 0,
    ) + u32::from(
        (rows[v1] & (1u64 << v2)) != 0 && (rows[u1] & (1u64 << u2)) != 0,
    );
    c1 + c2 - c_both
}

/// Exact count of simple C8 cycles containing edge `(u, v)` present in `rows`.
/// Returns `None` only on extreme high-degree overflow (>128 depth-3 left paths).
#[inline]
fn count_c8_through_edge_raw_u64(rows: &[u64; 64], u: usize, v: usize) -> Option<u32> {
    const MAX_SIDE: usize = 128;
    let u_bit = 1u64 << u;
    let v_bit = 1u64 << v;
    let uv_mask = u_bit | v_bit;

    let mut left_a3 = [0u8; MAX_SIDE];
    let mut left_mask = [0u64; MAX_SIDE];
    let mut left_len = 0usize;
    let mut left_a3_bits = 0u64;

    let mut a1_bits = rows[u] & !v_bit;
    while a1_bits != 0 {
        let a1 = a1_bits.trailing_zeros() as usize;
        a1_bits &= a1_bits - 1;
        let m1 = uv_mask | (1u64 << a1);
        let mut a2_bits = rows[a1] & !m1;
        while a2_bits != 0 {
            let a2 = a2_bits.trailing_zeros() as usize;
            a2_bits &= a2_bits - 1;
            let m12 = m1 | (1u64 << a2);
            let mut a3_bits = rows[a2] & !m12;
            left_a3_bits |= a3_bits;
            while a3_bits != 0 {
                if left_len >= MAX_SIDE {
                    return None;
                }
                let a3 = a3_bits.trailing_zeros() as usize;
                a3_bits &= a3_bits - 1;
                left_a3[left_len] = a3 as u8;
                left_mask[left_len] = (m12 | (1u64 << a3)) & !uv_mask;
                left_len += 1;
            }
        }
    }
    if left_len == 0 {
        return Some(0);
    }

    let mut adj_to_left_a3 = 0u64;
    let mut m = left_a3_bits;
    while m != 0 {
        let x = m.trailing_zeros() as usize;
        m &= m - 1;
        adj_to_left_a3 |= rows[x];
    }
    adj_to_left_a3 &= !uv_mask;
    if adj_to_left_a3 == 0 {
        return Some(0);
    }

    let mut count = 0u32;
    let mut b1_bits = rows[v] & !u_bit;
    while b1_bits != 0 {
        let b1 = b1_bits.trailing_zeros() as usize;
        b1_bits &= b1_bits - 1;
        let mb1 = uv_mask | (1u64 << b1);
        let mut b2_bits = rows[b1] & !mb1;
        while b2_bits != 0 {
            let b2 = b2_bits.trailing_zeros() as usize;
            b2_bits &= b2_bits - 1;
            let mb12 = mb1 | (1u64 << b2);
            let mut b3_bits = rows[b2] & !mb12 & adj_to_left_a3;
            while b3_bits != 0 {
                let b3 = b3_bits.trailing_zeros() as usize;
                b3_bits &= b3_bits - 1;
                let mb123 = (mb12 | (1u64 << b3)) & !uv_mask;
                let adj_b3 = rows[b3] & left_a3_bits & !mb123;
                if adj_b3 != 0 {
                    for i in 0..left_len {
                        if (adj_b3 & (1u64 << left_a3[i])) != 0
                            && (left_mask[i] & mb123) == 0
                        {
                            count += 1;
                        }
                    }
                }
            }
        }
    }
    Some(count)
}

/// Exact count of simple C8 cycles containing at least one of two vertex-disjoint
/// edges `e1`, `e2` present in `rows` (temporarily toggles `e1` in-place to avoid
/// double counting without branches).
#[inline]
pub fn count_c8_through_two_edges_u64(rows: &mut [u64; 64], e1: Edge, e2: Edge) -> Option<u32> {
    let (u1, v1) = (e1.0 as usize, e1.1 as usize);
    let (u2, v2) = (e2.0 as usize, e2.1 as usize);
    let c1 = count_c8_through_edge_raw_u64(rows, u1, v1)?;
    // Temporarily mask out e1 so c2 counts ONLY C8 cycles containing e2 and NOT e1.
    rows[u1] ^= 1u64 << v1;
    rows[v1] ^= 1u64 << u1;
    let c2 = count_c8_through_edge_raw_u64(rows, u2, v2);
    rows[u1] ^= 1u64 << v1;
    rows[v1] ^= 1u64 << u1;
    Some(c1 + c2?)
}

/// Exact count of simple `target`-cycles containing edge `(u, v)` present in `rows`.
/// Returns `None` if `node_budget` is exhausted; early-stops if `stop_lim > 0 && count >= stop_lim`.
fn count_cycles_through_edge_raw_u64(
    rows: &[u64; 64],
    order: usize,
    target: usize,
    u: usize,
    v: usize,
    stop_lim: u32,
    node_budget: u64,
    dist_mask: &mut [u64; 65],
) -> Option<u32> {
    if target < 4 || target > order {
        return Some(0);
    }
    let full_mask: u64 = if order == 64 {
        !0u64
    } else {
        (1u64 << order) - 1
    };
    let u_bit = 1u64 << u;
    let v_bit = 1u64 << v;
    let closing_set = rows[u] & !v_bit;
    if closing_set == 0 {
        return Some(0);
    }
    let allowed_domain = full_mask & !(u_bit | v_bit);
    let max_r = target - 2;

    let mut reached = closing_set;
    let mut frontier = closing_set;
    let mut adj_to_closing = 0u64;
    dist_mask[1] = reached;
    let mut built_r = 1usize;
    while built_r < max_r && frontier != 0 {
        let mut next = 0u64;
        let mut f = frontier;
        while f != 0 {
            let x = f.trailing_zeros() as usize;
            f &= f - 1;
            next |= rows[x];
        }
        if built_r == 1 {
            adj_to_closing = next & allowed_domain;
        }
        frontier = (next & allowed_domain) & !reached;
        reached |= frontier;
        built_r += 1;
        dist_mask[built_r] = reached;
    }
    for r in (built_r + 1)..=max_r {
        dist_mask[r] = reached;
    }
    if adj_to_closing == 0 || (rows[v] & dist_mask[max_r]) == 0 {
        return Some(0);
    }

    struct EdgeDfsState<'a> {
        rows: &'a [u64; 64],
        dist_mask: &'a [u64; 65],
        adj_to_closing: u64,
        closing_set: u64,
        count: u32,
        nodes: u64,
        budget: u64,
        stop_lim: u32,
        exhausted: bool,
    }

    fn dfs(st: &mut EdgeDfsState<'_>, vertex: usize, seen: u64, rem: usize) {
        if rem == 3 {
            let mut x_bits = st.rows[vertex] & !seen & st.dist_mask[3];
            while x_bits != 0 {
                let x = x_bits.trailing_zeros() as usize;
                x_bits &= x_bits - 1;
                st.nodes += 1;
                if st.budget != 0 && st.nodes > st.budget {
                    st.exhausted = true;
                    return;
                }
                let seen_x = seen | (1u64 << x);
                let closing_avail = st.closing_set & !seen_x;
                if closing_avail == 0 {
                    continue;
                }
                let mut w_bits = st.rows[x] & !seen_x & st.adj_to_closing;
                while w_bits != 0 {
                    let w = w_bits.trailing_zeros() as usize;
                    w_bits &= w_bits - 1;
                    let c = (st.rows[w] & closing_avail).count_ones();
                    if c != 0 {
                        st.count += c;
                        if st.stop_lim != 0 && st.count >= st.stop_lim {
                            return;
                        }
                    }
                }
            }
            return;
        }

        let mut next_bits = st.rows[vertex] & !seen & st.dist_mask[rem];
        let next_rem = rem - 1;
        while next_bits != 0 {
            let x = next_bits.trailing_zeros() as usize;
            next_bits &= next_bits - 1;
            st.nodes += 1;
            if st.budget != 0 && st.nodes > st.budget {
                st.exhausted = true;
                return;
            }
            let next_seen = seen | (1u64 << x);
            if (st.closing_set & !next_seen) == 0 {
                continue;
            }
            dfs(st, x, next_seen, next_rem);
            if st.exhausted || (st.stop_lim != 0 && st.count >= st.stop_lim) {
                return;
            }
        }
    }

    let mut st = EdgeDfsState {
        rows,
        dist_mask,
        adj_to_closing,
        closing_set,
        count: 0,
        nodes: 0,
        budget: node_budget,
        stop_lim,
        exhausted: false,
    };
    dfs(&mut st, v, u_bit | v_bit, max_r);
    if st.exhausted {
        None
    } else {
        Some(st.count)
    }
}

/// Exact count of simple `target`-cycles containing at least one of two vertex-disjoint
/// edges `e1`, `e2` present in `rows`. If `stop_lim > 0`, early-stops once total >= `stop_lim`.
pub fn count_cycles_through_two_edges_u64(
    rows: &mut [u64; 64],
    order: usize,
    target: usize,
    e1: Edge,
    e2: Edge,
    stop_lim: u32,
    node_budget: u64,
    dist_mask: &mut [u64; 65],
) -> Option<u32> {
    let (u1, v1) = (e1.0 as usize, e1.1 as usize);
    let (u2, v2) = (e2.0 as usize, e2.1 as usize);
    let c1 = count_cycles_through_edge_raw_u64(
        rows,
        order,
        target,
        u1,
        v1,
        stop_lim,
        node_budget,
        dist_mask,
    )?;
    if stop_lim != 0 && c1 >= stop_lim {
        return Some(c1);
    }
    let rem_lim = if stop_lim != 0 { stop_lim - c1 } else { 0 };
    rows[u1] ^= 1u64 << v1;
    rows[v1] ^= 1u64 << u1;
    let c2 = count_cycles_through_edge_raw_u64(
        rows,
        order,
        target,
        u2,
        v2,
        rem_lim,
        node_budget,
        dist_mask,
    );
    rows[u1] ^= 1u64 << v1;
    rows[v1] ^= 1u64 << u1;
    Some(c1 + c2?)
}

/// Exact analytic C4 count on u64 (zero DFS, ~0.15 us for n=64).
#[inline]
pub fn count_c4_u64(rows: &[u64; 64], order: usize, limit: u32, stop_at_count: u32) -> CountResult {
    let mut count = 0u32;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };
    let max_start = order.saturating_sub(3);
    for start in 0..max_start {
        let greater_mask = !((1u64 << (start + 1)) - 1);
        let mut nbrs = rows[start] & greater_mask;
        if nbrs.count_ones() < 2 {
            continue;
        }
        while nbrs != 0 {
            let a = nbrs.trailing_zeros() as usize;
            nbrs &= nbrs - 1;
            let ra = rows[a] & greater_mask;
            let mut rest = nbrs;
            while rest != 0 {
                let c = rest.trailing_zeros() as usize;
                rest &= rest - 1;
                count += (ra & rows[c]).count_ones();
                if count >= stop_lim {
                    let cutoff_reached = stop_at_count != 0 && count >= stop_at_count;
                    return CountResult {
                        length: 4,
                        count: count.min(limit),
                        complete: false,
                        nodes: 0,
                        elapsed_ns: 0,
                        cutoff_reached,
                    };
                }
            }
        }
    }
    CountResult {
        length: 4,
        count,
        complete: count < limit,
        nodes: 0,
        elapsed_ns: 0,
        cutoff_reached: false,
    }
}

/// Exact analytic C4 count on u128.
#[inline]
pub fn count_c4_u128(
    rows: &[u128; MAX_ORDER],
    order: usize,
    limit: u32,
    stop_at_count: u32,
) -> CountResult {
    let mut count = 0u32;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };
    let max_start = order.saturating_sub(3);
    for start in 0..max_start {
        let greater_mask = !((1u128 << (start + 1)) - 1);
        let mut nbrs = rows[start] & greater_mask;
        if nbrs.count_ones() < 2 {
            continue;
        }
        while nbrs != 0 {
            let a = nbrs.trailing_zeros() as usize;
            nbrs &= nbrs - 1;
            let ra = rows[a] & greater_mask;
            let mut rest = nbrs;
            while rest != 0 {
                let c = rest.trailing_zeros() as usize;
                rest &= rest - 1;
                count += (ra & rows[c]).count_ones();
                if count >= stop_lim {
                    let cutoff_reached = stop_at_count != 0 && count >= stop_at_count;
                    return CountResult {
                        length: 4,
                        count: count.min(limit),
                        complete: false,
                        nodes: 0,
                        elapsed_ns: 0,
                        cutoff_reached,
                    };
                }
            }
        }
    }
    CountResult {
        length: 4,
        count,
        complete: count < limit,
        nodes: 0,
        elapsed_ns: 0,
        cutoff_reached: false,
    }
}

/// Exact Meet-in-the-Middle C8 counter on u64.
pub fn count_c8_mitm_u64(
    rows: &[u64; 64],
    order: usize,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
) -> CountResult {
    const MAX_LEFT_PATHS: usize = 64;

    let mut count = 0u32;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };
    let max_start = order.saturating_sub(7);

    for start in 0..max_start {
        let greater_mask = !((1u64 << (start + 1)) - 1);
        let nbrs = rows[start] & greater_mask;
        if nbrs.count_ones() < 2 {
            continue;
        }
        let max_nbr_bit = 1u64 << (63 - nbrs.leading_zeros());
        let mut a1_choices = nbrs ^ max_nbr_bit;

        while a1_choices != 0 {
            let a1 = a1_choices.trailing_zeros() as usize;
            a1_choices &= a1_choices - 1;
            let a1_bit = 1u64 << a1;
            let gt_a1 = if a1 >= 63 { 0 } else { !((1u64 << (a1 + 1)) - 1) };
            let b1_set = nbrs & gt_a1;
            if b1_set == 0 {
                continue;
            }

            let mut left_len = 0usize;
            let mut left_mids_mask = 0u64;
            let mut overflow = false;

            let mut a2_bits = rows[a1] & greater_mask;
            while a2_bits != 0 {
                let a2 = a2_bits.trailing_zeros() as usize;
                a2_bits &= a2_bits - 1;
                let m12 = a1_bit | (1u64 << a2);
                let mut a3_bits = rows[a2] & greater_mask & !m12;
                while a3_bits != 0 {
                    let a3 = a3_bits.trailing_zeros() as usize;
                    a3_bits &= a3_bits - 1;
                    let m123 = m12 | (1u64 << a3);
                    let mut mid_bits = rows[a3] & greater_mask & !m123;
                    left_mids_mask |= mid_bits;
                    while mid_bits != 0 {
                        if left_len >= MAX_LEFT_PATHS {
                            overflow = true;
                            break;
                        }
                        let mid = mid_bits.trailing_zeros() as u8;
                        mid_bits &= mid_bits - 1;
                        scratch.mitm_left_mid[left_len] = mid;
                        scratch.mitm_left_mask[left_len] = m123;
                        left_len += 1;
                    }
                    if overflow {
                        break;
                    }
                }
                if overflow {
                    break;
                }
            }

            if overflow {
                return count_cycles_pruned_u64(
                    rows,
                    order,
                    8,
                    limit,
                    node_budget,
                    stop_at_count,
                    scratch,
                );
            }
            if left_len == 0 {
                continue;
            }

            let mut r1 = 0u64;
            let mut m = left_mids_mask;
            while m != 0 {
                let u = m.trailing_zeros() as usize;
                m &= m - 1;
                r1 |= rows[u];
            }
            r1 &= greater_mask;

            let mut r2 = 0u64;
            let mut m = r1;
            while m != 0 {
                let u = m.trailing_zeros() as usize;
                m &= m - 1;
                r2 |= rows[u];
            }
            r2 &= greater_mask;

            let base_avail = greater_mask & !a1_bit;
            let mut b1_bits = b1_set;
            while b1_bits != 0 {
                let b1 = b1_bits.trailing_zeros() as usize;
                b1_bits &= b1_bits - 1;
                let b1_bit = 1u64 << b1;
                let mut b2_bits = rows[b1] & base_avail & r2;
                while b2_bits != 0 {
                    let b2 = b2_bits.trailing_zeros() as usize;
                    b2_bits &= b2_bits - 1;
                    let rb12 = b1_bit | (1u64 << b2);
                    let mut b3_bits = rows[b2] & base_avail & !rb12 & r1;
                    while b3_bits != 0 {
                        let b3 = b3_bits.trailing_zeros() as usize;
                        b3_bits &= b3_bits - 1;
                        let rb123 = rb12 | (1u64 << b3);
                        let mut mid_bits = rows[b3] & base_avail & !rb123 & left_mids_mask;
                        while mid_bits != 0 {
                            let mid = mid_bits.trailing_zeros() as u8;
                            mid_bits &= mid_bits - 1;
                            for i in 0..left_len {
                                if scratch.mitm_left_mid[i] == mid
                                    && (scratch.mitm_left_mask[i] & rb123) == 0
                                {
                                    count += 1;
                                    if count >= stop_lim {
                                        let cutoff_reached =
                                            stop_at_count != 0 && count >= stop_at_count;
                                        return CountResult {
                                            length: 8,
                                            count: count.min(limit),
                                            complete: false,
                                            nodes: 0,
                                            elapsed_ns: 0,
                                            cutoff_reached,
                                        };
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    CountResult {
        length: 8,
        count,
        complete: count < limit,
        nodes: 0,
        elapsed_ns: 0,
        cutoff_reached: false,
    }
}

/// Fast sound Posa extension + cubic-specialized Thomason lollipop witness harvester
/// for Hamiltonian cycles (`target == order`).
/// If it finds `target_count` pairwise-distinct, edge-verified simple Hamiltonian
/// cycles within a small rotation budget, that mathematically proves the true
/// count is >= `target_count`. Otherwise returns `None` so exact DFS runs.
fn posa_hamiltonian_fast_cert_u64(
    rows: &[u64; 64],
    order: usize,
    target_count: u32,
) -> Option<u32> {
    if order < 8 || order > 64 || target_count == 0 || target_count > 128 {
        return None;
    }
    let full_mask: u64 = if order == 64 {
        !0u64
    } else {
        (1u64 << order) - 1
    };

    #[inline(always)]
    fn edge_mix(a: u8, b: u8) -> u64 {
        let lo = a.min(b) as u64;
        let hi = a.max(b) as u64;
        let k = (lo | (hi << 8)).wrapping_add(1);
        let z = k.wrapping_mul(0x9e37_79b9_7f4a_7c15);
        let z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z ^ (z >> 27)
    }

    #[inline(always)]
    fn fast_rand(s: &mut u64) -> u64 {
        *s ^= *s << 13;
        *s ^= *s >> 7;
        *s ^= *s << 17;
        *s
    }

    #[inline(always)]
    fn rev_suffix(path: &mut [u8; 64], pos_of: &mut [u8; 64], lo: usize, order: usize) {
        let mut l = lo;
        let mut r = order - 1;
        while l < r {
            let vl = path[l];
            let vr = path[r];
            path[l] = vr;
            path[r] = vl;
            pos_of[vr as usize] = l as u8;
            pos_of[vl as usize] = r as u8;
            l += 1;
            r -= 1;
        }
    }

    let mut is_cubic = true;
    for u in 0..order {
        if rows[u].count_ones() != 3 {
            is_cubic = false;
            break;
        }
    }

    // 256-slot open-addressed u64 hash table (2 KB, L1-resident) for O(1) dedup!
    let mut seen_tbl = [0u64; 256];
    let mut found = 0u32;
    let mut path = [0u8; 64];
    let mut tmp_path = [0u8; 64];
    let mut pos_of = [255u8; 64];
    let mut rng_state: u64 = 0x9e37_79b9_7f4a_7c15 ^ (order as u64);

    let mut total_rotations = 0usize;
    let max_total_rotations = 4_500usize;
    let mut shift_cursor = 7usize;

    for restart in 0..4usize {
        if total_rotations >= max_total_rotations {
            break;
        }
        let start = (restart * 13) % order;
        path[0] = start as u8;
        let mut len = 1usize;
        let mut in_path: u64 = 1u64 << start;
        pos_of.fill(255);
        pos_of[start] = 0;

        let mut local_stuck = 0usize;
        let mut prev_tail_p1: usize = usize::MAX;
        while len < order && total_rotations < max_total_rotations && local_stuck < 200 {
            let tail = path[len - 1] as usize;
            let unvis = rows[tail] & !in_path;
            if unvis != 0 {
                let mut best_v = unvis.trailing_zeros() as usize;
                let mut best_d = (rows[best_v] & !in_path).count_ones();
                let mut b = unvis & (unvis - 1);
                while b != 0 {
                    let v = b.trailing_zeros() as usize;
                    b &= b - 1;
                    let d = (rows[v] & !in_path).count_ones();
                    if d < best_d {
                        best_d = d;
                        best_v = v;
                    }
                }
                path[len] = best_v as u8;
                pos_of[best_v] = len as u8;
                in_path |= 1u64 << best_v;
                len += 1;
                local_stuck = 0;
                prev_tail_p1 = usize::MAX;
                continue;
            }
            let head = path[0] as usize;
            if (rows[head] & !in_path) != 0 {
                rev_suffix(&mut path, &mut pos_of, 0, len);
                prev_tail_p1 = usize::MAX;
                continue;
            }
            if len >= 3 && (rows[tail] & (1u64 << head)) != 0 {
                let mut ext_idx = None;
                for idx in 0..len {
                    if (rows[path[idx] as usize] & !in_path) != 0 {
                        ext_idx = Some(idx);
                        break;
                    }
                }
                if let Some(idx) = ext_idx {
                    let shift = (idx + 1) % len;
                    if shift != 0 {
                        path[..len].rotate_left(shift);
                        for k in 0..len {
                            pos_of[path[k] as usize] = k as u8;
                        }
                    }
                    prev_tail_p1 = usize::MAX;
                    continue;
                } else {
                    break;
                }
            }
            let mut nbrs = rows[tail] & in_path;
            if len >= 2 {
                nbrs &= !(1u64 << path[len - 2]);
            }
            if nbrs == 0 {
                break;
            }
            let mut chosen_pos = None;
            let mut fallback = [0usize; 8];
            let mut fb_len = 0usize;
            while nbrs != 0 {
                let u = nbrs.trailing_zeros() as usize;
                nbrs &= nbrs - 1;
                let p = pos_of[u] as usize;
                if p + 1 < len {
                    let new_tail = path[p + 1] as usize;
                    if (rows[new_tail] & !in_path) != 0 {
                        chosen_pos = Some(p);
                        break;
                    }
                    if new_tail != prev_tail_p1 && fb_len < fallback.len() {
                        fallback[fb_len] = p;
                        fb_len += 1;
                    }
                }
            }
            let rot_p = match chosen_pos {
                Some(p) => p,
                None if fb_len > 0 => fallback[(fast_rand(&mut rng_state) as usize) % fb_len],
                None => break,
            };
            prev_tail_p1 = tail;
            rev_suffix(&mut path, &mut pos_of, rot_p + 1, len);
            total_rotations += 1;
            local_stuck += 1;
        }

        if len < order || in_path != full_mask {
            continue;
        }

        let mut path_hash = 0u64;
        for i in 0..(order - 1) {
            path_hash ^= edge_mix(path[i], path[i + 1]);
        }

        let mut since_found = 0usize;
        let mut walk_steps = 0usize;
        let mut prev_tail: usize = usize::MAX;
        let mut cycle_basis = [0u8; 64];
        let mut cycle_basis_hash = 0u64;
        let mut have_cycle = false;
        let mut head_close_mask = rows[path[0] as usize];

        while total_rotations < max_total_rotations && since_found < 480 {
            let head = path[0] as usize;
            let tail = path[order - 1] as usize;
            let is_closed = (head_close_mask & (1u64 << tail)) != 0;
            let timed_out = !is_closed && have_cycle && walk_steps >= 256;

            let mut just_found_new = false;
            if is_closed {
                let raw_h = path_hash ^ edge_mix(path[order - 1], path[0]);
                let k = if raw_h == 0 { 1 } else { raw_h };
                let mut slot = ((k ^ (k >> 17)) as usize) & 255;
                let mut is_new = false;
                loop {
                    let cur = seen_tbl[slot];
                    if cur == 0 {
                        seen_tbl[slot] = k;
                        is_new = true;
                        break;
                    }
                    if cur == k {
                        break;
                    }
                    slot = (slot + 1) & 255;
                }
                if is_new {
                    found += 1;
                    since_found = 0;
                    just_found_new = true;
                    cycle_basis = path;
                    cycle_basis_hash = raw_h;
                    have_cycle = true;
                    if found >= target_count {
                        return Some(found);
                    }
                }
            }

            if is_closed || timed_out {
                if just_found_new && is_cubic {
                    rev_suffix(&mut path, &mut pos_of, 0, order);
                    let new_tail = path[order - 1] as usize;
                    let new_head = path[0] as usize;
                    head_close_mask = rows[new_head];
                    let open_nbrs =
                        rows[new_tail] & !((1u64 << path[order - 2]) | (1u64 << new_head));
                    if open_nbrs != 0 {
                        let u_v = open_nbrs.trailing_zeros() as usize;
                        let p = pos_of[u_v] as usize;
                        if p > 0 && p + 1 < order {
                            let u = path[p];
                            let nxt = path[p + 1];
                            path_hash ^= edge_mix(u, nxt) ^ edge_mix(u, new_tail as u8);
                            prev_tail = new_tail;
                            walk_steps = 1;
                            rev_suffix(&mut path, &mut pos_of, p + 1, order);
                            total_rotations += 1;
                            since_found += 1;
                            continue;
                        }
                    }
                }
                let (src, base_cycle_hash) = if timed_out {
                    (&cycle_basis, cycle_basis_hash)
                } else {
                    (&path, path_hash ^ edge_mix(path[order - 1], path[0]))
                };
                shift_cursor += 11;
                if shift_cursor >= order {
                    shift_cursor -= order - 1;
                }
                let shift = shift_cursor;
                let rev = (fast_rand(&mut rng_state) & 1) != 0;
                if !rev {
                    for idx in 0..order {
                        let mut s = idx + shift;
                        if s >= order {
                            s -= order;
                        }
                        let v = src[s];
                        tmp_path[idx] = v;
                        pos_of[v as usize] = idx as u8;
                    }
                } else {
                    for idx in 0..order {
                        let s = (order - 1 + shift - idx) % order;
                        let v = src[s];
                        tmp_path[idx] = v;
                        pos_of[v as usize] = idx as u8;
                    }
                }
                path = tmp_path;
                let new_tail = path[order - 1] as usize;
                let new_head = path[0] as usize;
                head_close_mask = rows[new_head];
                path_hash = base_cycle_hash ^ edge_mix(new_tail as u8, new_head as u8);

                let open_nbrs =
                    rows[new_tail] & !((1u64 << path[order - 2]) | (1u64 << new_head));
                if open_nbrs != 0 {
                    let u_v = open_nbrs.trailing_zeros() as usize;
                    let p = pos_of[u_v] as usize;
                    if p > 0 && p + 1 < order {
                        let u = path[p];
                        let nxt = path[p + 1];
                        path_hash ^= edge_mix(u, nxt) ^ edge_mix(u, new_tail as u8);
                        prev_tail = new_tail;
                        walk_steps = 1;
                        rev_suffix(&mut path, &mut pos_of, p + 1, order);
                        total_rotations += 1;
                        since_found += 1;
                        continue;
                    }
                }
                break;
            }

            let rot_p = if is_cubic {
                let nbrs = rows[tail] & !(1u64 << path[order - 2]);
                let u0 = nbrs.trailing_zeros() as usize;
                let u1 = (nbrs ^ (1u64 << u0)).trailing_zeros() as usize;
                let p0 = pos_of[u0] as usize;
                let p1 = pos_of[u1] as usize;
                let nt0 = path[p0 + 1] as usize;
                if prev_tail != usize::MAX {
                    if nt0 == prev_tail { p1 } else { p0 }
                } else {
                    let nt1 = path[p1 + 1] as usize;
                    if (head_close_mask & (1u64 << nt0)) != 0 {
                        p0
                    } else if (head_close_mask & (1u64 << nt1)) != 0 {
                        p1
                    } else if (fast_rand(&mut rng_state) & 1) == 0 {
                        p0
                    } else {
                        p1
                    }
                }
            } else {
                let mut nbrs = rows[tail] & !((1u64 << path[order - 2]) | (1u64 << head));
                let mut chosen = None;
                let mut candidates = [0usize; 8];
                let mut cand_len = 0usize;
                while nbrs != 0 {
                    let u = nbrs.trailing_zeros() as usize;
                    nbrs &= nbrs - 1;
                    let p = pos_of[u] as usize;
                    if p > 0 && p + 1 < order {
                        let new_tail = path[p + 1] as usize;
                        if new_tail == prev_tail {
                            continue;
                        }
                        if (head_close_mask & (1u64 << new_tail)) != 0 {
                            chosen = Some(p);
                            break;
                        }
                        if cand_len < candidates.len() {
                            candidates[cand_len] = p;
                            cand_len += 1;
                        }
                    }
                }
                if let Some(p) = chosen {
                    p
                } else if cand_len > 0 {
                    candidates[(fast_rand(&mut rng_state) as usize) % cand_len]
                } else {
                    rev_suffix(&mut path, &mut pos_of, 0, order);
                    head_close_mask = rows[path[0] as usize];
                    prev_tail = usize::MAX;
                    walk_steps += 1;
                    since_found += 1;
                    continue;
                }
            };
            let u = path[rot_p];
            let nxt = path[rot_p + 1];
            path_hash ^= edge_mix(u, nxt) ^ edge_mix(u, tail as u8);
            prev_tail = tail;
            walk_steps += 1;
            rev_suffix(&mut path, &mut pos_of, rot_p + 1, order);
            total_rotations += 1;
            since_found += 1;
        }
    }

    None
}

/// Bitset connectivity check on `unvisited` starting from `seed` (at least one
/// vertex in `unvisited`). Returns true iff all bits of `unvisited` are connected.
#[inline]
fn is_subset_connected_u64(rows: &[u64; 64], unvisited: u64, seed: u64) -> bool {
    let mut seen = seed;
    let mut frontier = seed;
    while frontier != 0 {
        let mut next = 0u64;
        let mut f = frontier;
        while f != 0 {
            let u = f.trailing_zeros() as usize;
            f &= f - 1;
            next |= rows[u];
        }
        frontier = (next & unvisited) & !seen;
        seen |= frontier;
    }
    seen == unvisited
}

/// Ultra-fast 2-bit register-only Hamiltonian counter for max-degree <= 3 graphs
/// (e.g. all connected cubic graphs up to n=64!).
/// Stores unvisited degree of ALL 64 vertices in two u64 registers `(hi, lo)`,
/// eliminating all per-node array loops and backtracking restoration, while
/// adding Warnsdorff minimum-degree ordering and periodic connectivity pruning!
fn count_hamiltonian_cubic_u64(
    rows: &[u64; 64],
    order: usize,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
) -> CountResult {
    let mut count = 0u32;
    let mut nodes = 0u64;
    let mut budget_exhausted = false;
    let mut cutoff_reached = false;
    let budget = node_budget as u64;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };

    let full_mask: u64 = if order == 64 {
        !0u64
    } else {
        (1u64 << order) - 1
    };
    let nbrs = rows[0];
    if nbrs.count_ones() < 2 {
        return CountResult {
            length: order as u16,
            complete: true,
            ..Default::default()
        };
    }

    struct CubicHamState<'a> {
        rows: &'a [u64; 64],
        closing_set: u64,
        count: u32,
        nodes: u64,
        budget: u64,
        stop_lim: u32,
        stop_at_count: u32,
        budget_exhausted: bool,
        cutoff_reached: bool,
    }

    fn dfs_cubic(
        st: &mut CubicHamState<'_>,
        vertex: usize,
        unvisited: u64,
        rem_left: usize,
        hi: u64,
        lo: u64,
        mut next_avail: u64,
    ) {
        if rem_left == 1 {
            if (st.rows[vertex] & st.closing_set & unvisited) != 0 {
                st.count += 1;
                if st.count >= st.stop_lim {
                    st.cutoff_reached = st.stop_at_count != 0 && st.count >= st.stop_at_count;
                }
            }
            return;
        }

        let rem_closing = st.closing_set & unvisited;
        if rem_closing == 0 {
            return;
        }
        if (rem_closing & (rem_closing - 1)) == 0 {
            next_avail &= !rem_closing;
            if next_avail == 0 {
                return;
            }
        }

        // Warnsdorff ordering: if two choices exist, explore the lower-degree vertex first!
        let mut ordered = [0usize; 3];
        let mut ord_len = 0usize;
        // First push vertices with deg <= 2 (bit !(hi & lo)), then deg == 3 (hi & lo).
        let low_deg = next_avail & !(hi & lo);
        let high_deg = next_avail & (hi & lo);
        let mut b = low_deg;
        while b != 0 {
            let v = b.trailing_zeros() as usize;
            b &= b - 1;
            ordered[ord_len] = v;
            ord_len += 1;
        }
        let mut b = high_deg;
        while b != 0 {
            let v = b.trailing_zeros() as usize;
            b &= b - 1;
            ordered[ord_len] = v;
            ord_len += 1;
        }

        for i in 0..ord_len {
            let v = ordered[i];
            let v_bit = 1u64 << v;
            let next_unvisited = unvisited ^ v_bit;

            st.nodes += 1;
            if st.budget != 0 && st.nodes > st.budget {
                st.budget_exhausted = true;
                return;
            }

            if rem_left == 2 {
                if (st.rows[v] & st.closing_set & next_unvisited) != 0 {
                    st.count += 1;
                    if st.count >= st.stop_lim {
                        st.cutoff_reached =
                            st.stop_at_count != 0 && st.count >= st.stop_at_count;
                        return;
                    }
                }
                continue;
            }

            // Subtract 1 from 2-bit degree counters (hi, lo) for all w in adj_u — ZERO LOOPS!
            let adj_u = st.rows[v] & next_unvisited;
            let borrow = adj_u & !lo;
            let new_lo = lo ^ adj_u;
            let new_hi = hi ^ borrow;

            // Any neighbor in adj_u dropping to degree 0 is immediately fatal (rem_left - 1 >= 2).
            if (adj_u & !(new_hi | new_lo)) != 0 {
                continue;
            }
            // Any non-closing neighbor dropping to degree 1 is FORCED to be visited next!
            let forced = adj_u & !st.closing_set & !new_hi & new_lo;
            if (forced & forced.wrapping_sub(1)) != 0 {
                // Two forced vertices simultaneously -> impossible!
                continue;
            }
            let child_avail = if forced != 0 { forced } else { adj_u };
            if child_avail != 0 {
                dfs_cubic(
                    st,
                    v,
                    next_unvisited,
                    rem_left - 1,
                    new_hi,
                    new_lo,
                    child_avail,
                );
                if st.budget_exhausted || st.cutoff_reached || st.count >= st.stop_lim {
                    return;
                }
            }
        }
    }

    let max_nbr_bit = 1u64 << (63 - nbrs.leading_zeros());
    let mut first_choices = nbrs ^ max_nbr_bit;

    while first_choices != 0 {
        let first = first_choices.trailing_zeros() as usize;
        first_choices &= first_choices - 1;
        let first_bit = 1u64 << first;
        let gt_first = if first >= 63 {
            0
        } else {
            !((1u64 << (first + 1)) - 1)
        };
        let closing_set = nbrs & gt_first;
        if closing_set == 0 {
            continue;
        }

        let unvisited = full_mask ^ (1u64 | first_bit);
        let adj_first = rows[first] & unvisited;
        if adj_first == 0 {
            continue;
        }

        let mut hi = 0u64;
        let mut lo = 0u64;
        let mut feasible = true;
        let mut forced = 0u64;
        let mut rem_bits = unvisited;
        while rem_bits != 0 {
            let u = rem_bits.trailing_zeros() as usize;
            rem_bits &= rem_bits - 1;
            let d = (rows[u] & unvisited).count_ones();
            let u_bit = 1u64 << u;
            if (d & 1) != 0 {
                lo |= u_bit;
            }
            if (d & 2) != 0 {
                hi |= u_bit;
            }
            if (closing_set & u_bit) == 0 {
                if (adj_first & u_bit) == 0 {
                    if d < 2 {
                        feasible = false;
                        break;
                    }
                } else if d == 0 {
                    feasible = false;
                    break;
                } else if d == 1 {
                    forced |= u_bit;
                }
            } else if d == 0 {
                feasible = false;
                break;
            }
        }
        if !feasible || (forced & forced.wrapping_sub(1)) != 0 {
            continue;
        }
        if !is_subset_connected_u64(rows, unvisited, closing_set & closing_set.wrapping_neg()) {
            continue;
        }

        let init_avail = if forced != 0 { forced } else { adj_first };
        let mut st = CubicHamState {
            rows,
            closing_set,
            count,
            nodes,
            budget,
            stop_lim,
            stop_at_count,
            budget_exhausted,
            cutoff_reached,
        };
        dfs_cubic(&mut st, first, unvisited, order - 2, hi, lo, init_avail);
        count = st.count;
        nodes = st.nodes;
        budget_exhausted = st.budget_exhausted;
        cutoff_reached = st.cutoff_reached;

        if count >= stop_lim || budget_exhausted || cutoff_reached {
            break;
        }
    }

    CountResult {
        length: order as u16,
        count: count.min(limit),
        complete: !budget_exhausted && !cutoff_reached && count < limit,
        nodes,
        elapsed_ns: 0,
        cutoff_reached,
    }
}

/// Exact forced-vertex & dead-end pruned Hamiltonian cycle counter (`target == order`, n <= 64).
pub fn count_hamiltonian_u64(
    rows: &[u64; 64],
    order: usize,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
) -> CountResult {
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };
    // For large Hamiltonian targets (e.g. C64 on n=64), try ultra-fast sound
    // Posa rotation harvesting first: proves `count >= stop_lim` in ~15 us when
    // Hamiltonian cycles are abundant, and falls back to exact DFS otherwise!
    if order >= 48 && stop_lim <= 128 {
        if let Some(found) = posa_hamiltonian_fast_cert_u64(rows, order, stop_lim) {
            return CountResult {
                length: order as u16,
                count: found.min(limit),
                complete: false,
                nodes: 0,
                elapsed_ns: 0,
                cutoff_reached: stop_at_count != 0 && found >= stop_at_count,
            };
        }
    }
    if order >= 4 && order <= 64 {
        let mut max_deg = 0u32;
        for u in 0..order {
            let d = rows[u].count_ones();
            if d > max_deg {
                max_deg = d;
            }
        }
        if max_deg <= 3 {
            return count_hamiltonian_cubic_u64(rows, order, limit, node_budget, stop_at_count);
        }
    }
    let mut count = 0u32;
    let mut nodes = 0u64;
    let mut budget_exhausted = false;
    let mut cutoff_reached = false;
    let budget = node_budget as u64;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };

    if order < 4 || order > 64 {
        return CountResult {
            length: order as u16,
            complete: true,
            ..Default::default()
        };
    }

    let full_mask: u64 = if order == 64 {
        !0u64
    } else {
        (1u64 << order) - 1
    };
    let nbrs = rows[0];
    if nbrs.count_ones() < 2 {
        return CountResult {
            length: order as u16,
            complete: true,
            ..Default::default()
        };
    }

    struct HamState<'a> {
        rows: &'a [u64; 64],
        closing_set: u64,
        deg: [u8; 64],
        count: u32,
        nodes: u64,
        budget: u64,
        stop_lim: u32,
        stop_at_count: u32,
        budget_exhausted: bool,
        cutoff_reached: bool,
    }

    fn ham_dfs(st: &mut HamState<'_>, vertex: usize, unvisited: u64, rem_left: usize, mut next_avail: u64) {
        if rem_left == 1 {
            // Only 1 unvisited vertex remains; it must be adjacent to vertex AND in closing_set!
            if (st.rows[vertex] & st.closing_set & unvisited) != 0 {
                st.count += 1;
                if st.count >= st.stop_lim {
                    st.cutoff_reached = st.stop_at_count != 0 && st.count >= st.stop_at_count;
                }
            }
            return;
        }

        // If only 1 closing vertex remains unvisited and rem_left > 1, we cannot visit it early.
        let rem_closing = st.closing_set & unvisited;
        if rem_closing == 0 {
            return;
        }
        if (rem_closing & (rem_closing - 1)) == 0 {
            next_avail &= !rem_closing;
        }

        while next_avail != 0 {
            let v = next_avail.trailing_zeros() as usize;
            next_avail &= next_avail - 1;
            let v_bit = 1u64 << v;
            let next_unvisited = unvisited ^ v_bit;

            st.nodes += 1;
            if st.budget != 0 && st.nodes > st.budget {
                st.budget_exhausted = true;
                return;
            }

            if rem_left == 2 {
                // Only 1 vertex left in next_unvisited!
                if (st.rows[v] & st.closing_set & next_unvisited) != 0 {
                    st.count += 1;
                    if st.count >= st.stop_lim {
                        st.cutoff_reached =
                            st.stop_at_count != 0 && st.count >= st.stop_at_count;
                        return;
                    }
                }
                continue;
            }

            // Decrement deg for all unvisited neighbors of v; detect dead-ends and forced moves.
            let adj_u = st.rows[v] & next_unvisited;
            let mut dead = false;
            let mut forced: u64 = 0;
            let mut bits = adj_u;
            while bits != 0 {
                let w = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                st.deg[w] -= 1;
                let d = st.deg[w];
                let w_bit = 1u64 << w;
                if (st.closing_set & w_bit) == 0 {
                    if d == 0 {
                        dead = true;
                    } else if d == 1 {
                        forced |= w_bit;
                    }
                } else if d == 0 {
                    // rem_left - 1 >= 2, so a closing vertex with deg 0 in next_unvisited cannot be reached.
                    dead = true;
                }
            }

            if !dead && (forced & (forced.wrapping_sub(1))) == 0 {
                let child_avail = if forced != 0 { forced } else { adj_u };
                if child_avail != 0 {
                    ham_dfs(st, v, next_unvisited, rem_left - 1, child_avail);
                }
            }

            // Restore deg for backtracking.
            let mut bits = adj_u;
            while bits != 0 {
                let w = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                st.deg[w] += 1;
            }

            if st.budget_exhausted || st.cutoff_reached || st.count >= st.stop_lim {
                return;
            }
        }
    }

    let max_nbr_bit = 1u64 << (63 - nbrs.leading_zeros());
    let mut first_choices = nbrs ^ max_nbr_bit;

    while first_choices != 0 {
        let first = first_choices.trailing_zeros() as usize;
        first_choices &= first_choices - 1;
        let first_bit = 1u64 << first;
        let gt_first = if first >= 63 {
            0
        } else {
            !((1u64 << (first + 1)) - 1)
        };
        let closing_set = nbrs & gt_first;
        if closing_set == 0 {
            continue;
        }

        let unvisited = full_mask ^ (1u64 | first_bit);
        let adj_first = rows[first] & unvisited;
        if adj_first == 0 {
            continue;
        }

        let mut deg = [0u8; 64];
        let mut feasible = true;
        let mut forced = 0u64;
        let mut rem_bits = unvisited;
        while rem_bits != 0 {
            let u = rem_bits.trailing_zeros() as usize;
            rem_bits &= rem_bits - 1;
            let d = (rows[u] & unvisited).count_ones() as u8;
            deg[u] = d;
            let u_bit = 1u64 << u;
            if (closing_set & u_bit) == 0 {
                if (adj_first & u_bit) == 0 {
                    if d < 2 {
                        feasible = false;
                        break;
                    }
                } else if d == 0 {
                    feasible = false;
                    break;
                } else if d == 1 {
                    forced |= u_bit;
                }
            } else if d == 0 {
                feasible = false;
                break;
            }
        }
        if !feasible || (forced & (forced.wrapping_sub(1))) != 0 {
            continue;
        }

        let init_avail = if forced != 0 { forced } else { adj_first };
        let mut st = HamState {
            rows,
            closing_set,
            deg,
            count,
            nodes,
            budget,
            stop_lim,
            stop_at_count,
            budget_exhausted,
            cutoff_reached,
        };
        ham_dfs(&mut st, first, unvisited, order - 2, init_avail);
        count = st.count;
        nodes = st.nodes;
        budget_exhausted = st.budget_exhausted;
        cutoff_reached = st.cutoff_reached;

        if count >= stop_lim || budget_exhausted || cutoff_reached {
            break;
        }
    }

    CountResult {
        length: order as u16,
        count: count.min(limit),
        complete: !budget_exhausted && !cutoff_reached && count < limit,
        nodes,
        elapsed_ns: 0,
        cutoff_reached,
    }
}

/// Register-resident recursive u64 DFS with pre-filled `dist_mask` and
/// 2-level `popcnt` leaf collapse (`rem == 2`) for C16, C32, etc.
pub fn count_cycles_pruned_u64(
    rows: &[u64; 64],
    order: usize,
    length: u16,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
) -> CountResult {
    let target = length as usize;
    if target < 4 || target > order {
        return CountResult {
            length,
            complete: true,
            ..Default::default()
        };
    }
    if target == order {
        return count_hamiltonian_u64(rows, order, limit, node_budget, stop_at_count);
    }

    struct PrunedState<'a> {
        rows: &'a [u64; 64],
        dist_mask: &'a [u64; 65],
        adj_to_closing: u64,
        closing_set: u64,
        count: u32,
        nodes: u64,
        budget: u64,
        stop_lim: u32,
        stop_at_count: u32,
        budget_exhausted: bool,
        cutoff_reached: bool,
    }

    fn dfs(st: &mut PrunedState<'_>, vertex: usize, seen: u64, rem: usize) {
        if rem == 3 {
            // Unrolled 3-level leaf collapse: vertex -> u -> w -> last (in closing_set) -> start.
            let mut u_bits = st.rows[vertex] & !seen & st.dist_mask[3];
            while u_bits != 0 {
                let u = u_bits.trailing_zeros() as usize;
                u_bits &= u_bits - 1;
                st.nodes += 1;
                if st.budget != 0 && st.nodes > st.budget {
                    st.budget_exhausted = true;
                    return;
                }
                let seen_u = seen | (1u64 << u);
                let closing_avail = st.closing_set & !seen_u;
                if closing_avail == 0 {
                    continue;
                }
                let mut w_bits = st.rows[u] & !seen_u & st.adj_to_closing;
                while w_bits != 0 {
                    let w = w_bits.trailing_zeros() as usize;
                    w_bits &= w_bits - 1;
                    let c = (st.rows[w] & closing_avail).count_ones();
                    if c != 0 {
                        st.count += c;
                        if st.count >= st.stop_lim {
                            st.cutoff_reached =
                                st.stop_at_count != 0 && st.count >= st.stop_at_count;
                            return;
                        }
                    }
                }
            }
            return;
        }
        if rem == 2 {
            // Two edges left: vertex -> w -> last (in closing_set) -> start.
            let closing_avail = st.closing_set & !seen;
            if closing_avail == 0 {
                return;
            }
            let mut w_bits = st.rows[vertex] & !seen & st.adj_to_closing;
            while w_bits != 0 {
                let w = w_bits.trailing_zeros() as usize;
                w_bits &= w_bits - 1;
                // rows[w] has no self-loop, so bit w is already 0 in rows[w]!
                let c = (st.rows[w] & closing_avail).count_ones();
                if c != 0 {
                    st.count += c;
                    if st.count >= st.stop_lim {
                        st.cutoff_reached =
                            st.stop_at_count != 0 && st.count >= st.stop_at_count;
                        return;
                    }
                }
            }
            return;
        }

        let mut next_bits = st.rows[vertex] & !seen & st.dist_mask[rem];
        let next_rem = rem - 1;
        while next_bits != 0 {
            let v = next_bits.trailing_zeros() as usize;
            next_bits &= next_bits - 1;
            st.nodes += 1;
            if st.budget != 0 && st.nodes > st.budget {
                st.budget_exhausted = true;
                return;
            }
            let next_seen = seen | (1u64 << v);
            if (st.closing_set & !next_seen) == 0 {
                continue;
            }
            dfs(st, v, next_seen, next_rem);
            if st.budget_exhausted || st.cutoff_reached || st.count >= st.stop_lim {
                return;
            }
        }
    }

    let mut count = 0u32;
    let mut nodes = 0u64;
    let mut budget_exhausted = false;
    let mut cutoff_reached = false;
    let budget = node_budget as u64;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };

    let dist_mask = &mut scratch.dist_mask64;
    let max_start = order - target + 1;
    let max_r = target - 2;

    for start in 0..max_start {
        let start_bit = 1u64 << start;
        let greater_mask = !((1u64 << (start + 1)) - 1);
        let nbrs = rows[start] & greater_mask;
        if nbrs.count_ones() < 2 {
            continue;
        }
        let max_nbr_bit = 1u64 << (63 - nbrs.leading_zeros());
        let mut first_choices = nbrs ^ max_nbr_bit;

        while first_choices != 0 {
            let first = first_choices.trailing_zeros() as usize;
            first_choices &= first_choices - 1;
            let first_bit = 1u64 << first;
            let gt_first = if first >= 63 {
                0
            } else {
                !((1u64 << (first + 1)) - 1)
            };
            let closing_set = nbrs & gt_first;
            if closing_set == 0 {
                continue;
            }

            // Build cumulative distance masks inside `greater_mask & !first_bit`
            // and pre-fill up to `max_r` so DFS has zero bounds branch!
            let allowed_domain = greater_mask & !first_bit;
            let mut reached = closing_set;
            let mut frontier = closing_set;
            let mut adj_to_closing = 0u64;
            dist_mask[1] = reached;
            let mut built_r = 1usize;
            while built_r < max_r && frontier != 0 {
                let mut next = 0u64;
                let mut f = frontier;
                while f != 0 {
                    let u = f.trailing_zeros() as usize;
                    f &= f - 1;
                    next |= rows[u];
                }
                if built_r == 1 {
                    adj_to_closing = next & allowed_domain;
                }
                frontier = (next & allowed_domain) & !reached;
                reached |= frontier;
                built_r += 1;
                dist_mask[built_r] = reached;
            }
            for r in (built_r + 1)..=max_r {
                dist_mask[r] = reached;
            }

            if adj_to_closing == 0 || (rows[first] & dist_mask[max_r]) == 0 {
                continue;
            }

            let mut st = PrunedState {
                rows,
                dist_mask,
                adj_to_closing,
                closing_set,
                count,
                nodes,
                budget,
                stop_lim,
                stop_at_count,
                budget_exhausted,
                cutoff_reached,
            };
            dfs(&mut st, first, start_bit | first_bit, max_r);
            count = st.count;
            nodes = st.nodes;
            budget_exhausted = st.budget_exhausted;
            cutoff_reached = st.cutoff_reached;

            if count >= stop_lim || budget_exhausted || cutoff_reached {
                break;
            }
        }
        if count >= stop_lim || budget_exhausted || cutoff_reached {
            break;
        }
    }

    CountResult {
        length,
        count: count.min(limit),
        complete: !budget_exhausted && !cutoff_reached && count < limit,
        nodes,
        elapsed_ns: 0,
        cutoff_reached,
    }
}

/// Register-resident recursive u128 DFS with pre-filled `dist_mask` and
/// 2-level `popcnt` leaf collapse for n > 64.
pub fn count_cycles_pruned_u128(
    rows: &[u128; MAX_ORDER],
    order: usize,
    length: u16,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
) -> CountResult {
    let target = length as usize;
    if target < 4 || target > order {
        return CountResult {
            length,
            complete: true,
            ..Default::default()
        };
    }

    struct PrunedState128<'a> {
        rows: &'a [u128; MAX_ORDER],
        dist_mask: &'a [u128; MAX_ORDER + 1],
        closing_set: u128,
        count: u32,
        nodes: u64,
        budget: u64,
        stop_lim: u32,
        stop_at_count: u32,
        budget_exhausted: bool,
        cutoff_reached: bool,
    }

    fn dfs128(st: &mut PrunedState128<'_>, vertex: usize, seen: u128, rem: usize) {
        if rem == 2 {
            let closing_avail = st.closing_set & !seen;
            if closing_avail == 0 {
                return;
            }
            let mut w_bits = st.rows[vertex] & !seen & st.dist_mask[2];
            while w_bits != 0 {
                let w = w_bits.trailing_zeros() as usize;
                w_bits &= w_bits - 1;
                let c = (st.rows[w] & closing_avail).count_ones();
                if c != 0 {
                    st.count += c;
                    if st.count >= st.stop_lim {
                        st.cutoff_reached =
                            st.stop_at_count != 0 && st.count >= st.stop_at_count;
                        return;
                    }
                }
            }
            return;
        }

        let mut next_bits = st.rows[vertex] & !seen & st.dist_mask[rem];
        let next_rem = rem - 1;
        while next_bits != 0 {
            let v = next_bits.trailing_zeros() as usize;
            next_bits &= next_bits - 1;
            st.nodes += 1;
            if st.budget != 0 && st.nodes > st.budget {
                st.budget_exhausted = true;
                return;
            }
            let next_seen = seen | (1u128 << v);
            if (st.closing_set & !next_seen) == 0 {
                continue;
            }
            dfs128(st, v, next_seen, next_rem);
            if st.budget_exhausted || st.cutoff_reached || st.count >= st.stop_lim {
                return;
            }
        }
    }

    let mut count = 0u32;
    let mut nodes = 0u64;
    let mut budget_exhausted = false;
    let mut cutoff_reached = false;
    let budget = node_budget as u64;
    let stop_lim = if stop_at_count != 0 {
        stop_at_count.min(limit)
    } else {
        limit
    };

    let dist_mask = &mut scratch.dist_mask128;
    let max_start = order - target + 1;
    let max_r = target - 2;

    for start in 0..max_start {
        let start_bit = 1u128 << start;
        let greater_mask = !((1u128 << (start + 1)) - 1);
        let nbrs = rows[start] & greater_mask;
        if nbrs.count_ones() < 2 {
            continue;
        }
        let max_nbr_bit = 1u128 << (127 - nbrs.leading_zeros());
        let mut first_choices = nbrs ^ max_nbr_bit;

        while first_choices != 0 {
            let first = first_choices.trailing_zeros() as usize;
            first_choices &= first_choices - 1;
            let first_bit = 1u128 << first;
            let gt_first = if first >= 127 {
                0
            } else {
                !((1u128 << (first + 1)) - 1)
            };
            let closing_set = nbrs & gt_first;
            if closing_set == 0 {
                continue;
            }

            let allowed_domain = greater_mask & !first_bit;
            let mut reached = closing_set;
            let mut frontier = closing_set;
            dist_mask[1] = reached;
            let mut built_r = 1usize;
            while built_r < max_r && frontier != 0 {
                let mut next = 0u128;
                let mut f = frontier;
                while f != 0 {
                    let u = f.trailing_zeros() as usize;
                    f &= f - 1;
                    next |= rows[u];
                }
                frontier = (next & allowed_domain) & !reached;
                reached |= frontier;
                built_r += 1;
                dist_mask[built_r] = reached;
            }
            for r in (built_r + 1)..=max_r {
                dist_mask[r] = reached;
            }

            if (rows[first] & dist_mask[max_r]) == 0 {
                continue;
            }

            let mut st = PrunedState128 {
                rows,
                dist_mask,
                closing_set,
                count,
                nodes,
                budget,
                stop_lim,
                stop_at_count,
                budget_exhausted,
                cutoff_reached,
            };
            dfs128(&mut st, first, start_bit | first_bit, max_r);
            count = st.count;
            nodes = st.nodes;
            budget_exhausted = st.budget_exhausted;
            cutoff_reached = st.cutoff_reached;

            if count >= stop_lim || budget_exhausted || cutoff_reached {
                break;
            }
        }
        if count >= stop_lim || budget_exhausted || cutoff_reached {
            break;
        }
    }

    CountResult {
        length,
        count: count.min(limit),
        complete: !budget_exhausted && !cutoff_reached && count < limit,
        nodes,
        elapsed_ns: 0,
        cutoff_reached,
    }
}

#[inline]
pub fn count_cycles_fast_u64(
    g: &BitGraph64,
    length: u16,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
) -> CountResult {
    match length {
        4 => count_c4_u64(&g.rows, g.n, limit, stop_at_count),
        8 => count_c8_mitm_u64(&g.rows, g.n, limit, node_budget, stop_at_count, scratch),
        _ => {
            let (block_count, blocks, max_block) = g.biconnected_blocks();
            if max_block < length as usize {
                return CountResult {
                    length,
                    count: 0,
                    complete: true,
                    nodes: 0,
                    elapsed_ns: 0,
                    cutoff_reached: false,
                };
            }
            if block_count <= 1 {
                return count_cycles_pruned_u64(
                    &g.rows,
                    g.n,
                    length,
                    limit,
                    node_budget,
                    stop_at_count,
                    scratch,
                );
            }
            let mut total_count = 0u32;
            let mut total_nodes = 0u64;
            let mut all_complete = true;
            for &bmask in &blocks[..block_count] {
                if (bmask.count_ones() as usize) < (length as usize) {
                    continue;
                }
                let mut sub_rows = [0u64; 64];
                let mut bits = bmask;
                while bits != 0 {
                    let u = bits.trailing_zeros() as usize;
                    bits &= bits - 1;
                    sub_rows[u] = g.rows[u] & bmask;
                }
                let rem_limit = limit.saturating_sub(total_count).max(1);
                let rem_stop = if stop_at_count != 0 {
                    stop_at_count.saturating_sub(total_count).max(1)
                } else {
                    0
                };
                let r = count_cycles_pruned_u64(
                    &sub_rows,
                    g.n,
                    length,
                    rem_limit,
                    node_budget,
                    rem_stop,
                    scratch,
                );
                total_count = total_count.saturating_add(r.count);
                total_nodes = total_nodes.saturating_add(r.nodes);
                all_complete = all_complete && r.complete;
                if r.cutoff_reached || (stop_at_count != 0 && total_count >= stop_at_count) {
                    return CountResult {
                        length,
                        count: total_count.min(limit),
                        complete: false,
                        nodes: total_nodes,
                        elapsed_ns: 0,
                        cutoff_reached: true,
                    };
                }
                if total_count >= limit {
                    return CountResult {
                        length,
                        count: limit,
                        complete: false,
                        nodes: total_nodes,
                        elapsed_ns: 0,
                        cutoff_reached: false,
                    };
                }
            }
            CountResult {
                length,
                count: total_count,
                complete: all_complete,
                nodes: total_nodes,
                elapsed_ns: 0,
                cutoff_reached: false,
            }
        }
    }
}

#[inline]
pub fn count_cycles_fast_u128(
    g: &BitGraph,
    length: u16,
    limit: u32,
    node_budget: u32,
    stop_at_count: u32,
    scratch: &mut DfsScratch,
) -> CountResult {
    match length {
        4 => count_c4_u128(&g.rows, g.n, limit, stop_at_count),
        _ => count_cycles_pruned_u128(
            &g.rows,
            g.n,
            length,
            limit,
            node_budget,
            stop_at_count,
            scratch,
        ),
    }
}

#[inline]
fn eval_order(lengths: &[u16], order: usize, has_cutoff: bool) -> ([usize; 6], usize) {
    let n_len = lengths.len();
    let mut idxs = [0usize; 6];
    if !has_cutoff {
        for i in 0..n_len {
            idxs[i] = i;
        }
        return (idxs, n_len);
    }
    let last = n_len - 1;
    if n_len >= 2 && (lengths[last] as usize) == order && lengths[last] >= 32 {
        // Non-Hamiltonian lengths first (C32/C16 hit CAP fast, C4/C8 are ~1 us),
        // Hamiltonian length last so cutoff stops early whenever possible!
        let mut pos = 0usize;
        for i in (0..last).rev() {
            idxs[pos] = i;
            pos += 1;
        }
        idxs[pos] = last;
        return (idxs, n_len);
    }
    if n_len == 4 && lengths == [4, 8, 16, 32] {
        idxs[0] = 2; // C16 (weight 4, fast CAP)
        idxs[1] = 3; // C32 (weight 2, fast CAP)
        idxs[2] = 0; // C4  (weight 16, 0.15 us)
        idxs[3] = 1; // C8  (weight 8, 1.5 us)
        return (idxs, 4);
    }
    for i in 0..n_len {
        idxs[i] = n_len - 1 - i;
    }
    (idxs, n_len)
}

/// Ultra-fast hot-loop scorer for n <= 64 (zero heap allocation, u64).
pub fn score_graph_fast_u64(
    graph: &BitGraph64,
    cap: u32,
    node_budget: u32,
    cutoff: Option<Cutoff>,
    scratch: &mut DfsScratch,
) -> Option<ScoreResult> {
    let lengths = forbidden_lengths(graph.n);
    let (order_idxs, n_len) = eval_order(lengths, graph.n, cutoff.is_some());
    let limit = cap + 1;
    let simplicity = graph.size();
    let mut partial_total = 0u32;
    let mut partial_weighted = 0u32;
    let mut complete = true;
    let mut complete_mask = 0u8;
    let mut counts_arr = [(0u16, 0u32); 6];

    for pos in 0..n_len {
        let len_idx = order_idxs[pos];
        let length = lengths[len_idx];
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                return None;
            }
        }
        let weight = (64u32 / (length as u32)).max(1);
        let mut stop_at_count = 0u32;
        if let Some(co) = cutoff {
            for c in 1..=limit {
                let bounded = c.min(cap);
                if co.reached(
                    partial_total + bounded,
                    partial_weighted + bounded * weight,
                    simplicity,
                ) {
                    stop_at_count = c;
                    break;
                }
            }
        }
        let res = count_cycles_fast_u64(graph, length, limit, node_budget, stop_at_count, scratch);
        let effective_count = if !res.complete && !res.cutoff_reached {
            cap
        } else {
            res.count.min(cap)
        };
        partial_total += effective_count;
        partial_weighted += effective_count * weight;
        let is_len_exact = res.count <= cap && res.complete;
        if is_len_exact {
            complete_mask |= 1u8 << len_idx;
        }
        complete = complete && is_len_exact;
        counts_arr[len_idx] = (length, effective_count);
        if res.cutoff_reached {
            return None;
        }
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                return None;
            }
        }
    }

    Some(ScoreResult {
        valid: true,
        counts: counts_arr,
        counts_len: n_len as u8,
        complete_mask,
        total: partial_total,
        weighted_penalty: partial_weighted,
        complete,
        simplicity,
    })
}

/// Exact delta + orientation-aware cycle-bank accelerated scorer for 2-edge switches (`n <= 64`).
/// - C4/C8: O(1) exact delta when parent count is complete (< cap).
/// - C16/C32/C64: O(1) transposed bitset lower-bound proof (`CycleBank64`) when parent
///   is saturated at `cap`, falling back to exact fast scorer whenever `proven < stop_lim`.
/// Preserves 100% mathematical soundness and exactness.
#[allow(clippy::too_many_arguments)]
pub fn score_graph_delta_u64(
    parent: &mut BitGraph64,
    parent_score: &ScoreResult,
    cand: &mut BitGraph64,
    is_two_edge_switch: bool,
    removed: [Edge; 2],
    removed_idx: [u16; 2],
    added: [Edge; 2],
    simplicity: u32,
    cap: u32,
    node_budget: u32,
    cutoff: Option<Cutoff>,
    scratch: &mut DfsScratch,
    bank: &mut CycleBank64,
) -> Option<ScoreResult> {
    let lengths = forbidden_lengths(cand.n);
    let (mut order_idxs, n_len) = eval_order(lengths, cand.n, cutoff.is_some());
    // When exact O(1) delta C4 (~10ns) & delta C8 (~50ns) are available on 4-length
    // graphs (n=33..63), evaluate C4 & C8 FIRST so any positive C4/C8 immediately
    // lowers `stop_at_count` for C16 & C32 (reducing bank misses and early-stopping)!
    if is_two_edge_switch
        && cutoff.is_some()
        && n_len == 4
        && lengths == [4, 8, 16, 32]
        && (parent_score.complete_mask & 0b11) == 0b11
    {
        order_idxs[0] = 0; // C4 (delta ~10ns)
        order_idxs[1] = 1; // C8 (delta ~50ns)
        order_idxs[2] = 2; // C16 (bank ~5ns)
        order_idxs[3] = 3; // C32 (bank ~5ns, lowered stop_lim!)
    }
    let limit = cap + 1;
    let mut partial_total = 0u32;
    let mut partial_weighted = 0u32;
    let mut complete = true;
    let mut complete_mask = 0u8;
    let mut counts_arr = [(0u16, 0u32); 6];

    for pos in 0..n_len {
        let len_idx = order_idxs[pos];
        let length = lengths[len_idx];
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                return None;
            }
        }
        let weight = (64u32 / (length as u32)).max(1);
        let mut stop_at_count = 0u32;
        if let Some(co) = cutoff {
            for c in 1..=limit {
                let bounded = c.min(cap);
                if co.reached(
                    partial_total + bounded,
                    partial_weighted + bounded * weight,
                    simplicity,
                ) {
                    stop_at_count = c;
                    break;
                }
            }
        }
        let stop_lim = if stop_at_count != 0 {
            stop_at_count.min(limit)
        } else {
            limit
        };

        let res = if is_two_edge_switch
            && length == 4
            && (parent_score.complete_mask & (1u8 << len_idx)) != 0
        {
            let p_c4 = parent_score.counts[len_idx].1;
            let minus = if p_c4 == 0 {
                0
            } else {
                count_c4_through_two_edges_u64(&parent.rows, removed[0], removed[1])
            };
            let plus = count_c4_through_two_edges_u64(&cand.rows, added[0], added[1]);
            let exact = p_c4 + plus - minus;
            let cutoff_reached = stop_at_count != 0 && exact >= stop_at_count;
            CountResult {
                length: 4,
                count: exact.min(limit),
                complete: exact < limit && !cutoff_reached,
                nodes: 0,
                elapsed_ns: 0,
                cutoff_reached,
            }
        } else if is_two_edge_switch
            && length == 8
            && (parent_score.complete_mask & (1u8 << len_idx)) != 0
        {
            let p_c8 = parent_score.counts[len_idx].1;
            let minus_opt = if p_c8 == 0 {
                Some(0)
            } else {
                count_c8_through_two_edges_u64(&mut parent.rows, removed[0], removed[1])
            };
            let plus_opt = minus_opt
                .and_then(|_| count_c8_through_two_edges_u64(&mut cand.rows, added[0], added[1]));
            if let (Some(minus), Some(plus)) = (minus_opt, plus_opt) {
                let exact = p_c8 + plus - minus;
                let cutoff_reached = stop_at_count != 0 && exact >= stop_at_count;
                CountResult {
                    length: 8,
                    count: exact.min(limit),
                    complete: exact < limit && !cutoff_reached,
                    nodes: 0,
                    elapsed_ns: 0,
                    cutoff_reached,
                }
            } else {
                count_cycles_fast_u64(cand, 8, limit, node_budget, stop_at_count, scratch)
            }
        } else if is_two_edge_switch
            && length == 16
            && cand.n <= 40
            && (parent_score.complete_mask & (1u8 << len_idx)) != 0
            && parent_score.counts[len_idx].1 == 0
        {
            // Zero-minus exact delta C16 (e.g. n=32 when parent has C16 == 0!):
            // ONLY 2 fixed-edge DFS roots instead of 17 starts, with instant stop_lim exit!
            if let Some(plus) = count_cycles_through_two_edges_u64(
                &mut cand.rows,
                cand.n,
                16,
                added[0],
                added[1],
                stop_lim,
                node_budget as u64,
                &mut scratch.dist_mask64,
            ) {
                let cutoff_reached = stop_at_count != 0 && plus >= stop_at_count;
                CountResult {
                    length: 16,
                    count: plus.min(limit),
                    complete: plus < limit && !cutoff_reached,
                    nodes: 0,
                    elapsed_ns: 0,
                    cutoff_reached,
                }
            } else {
                count_cycles_fast_u64(cand, 16, limit, node_budget, stop_at_count, scratch)
            }
        } else if is_two_edge_switch
            && length >= 16
            && (parent_score.complete_mask & (1u8 << len_idx)) == 0
            && parent_score.counts[len_idx].1 >= cap
            && stop_lim <= 384
        {
            if let Some(proven) =
                bank.query_or_refill(parent, length, removed, removed_idx, added)
            {
                if proven >= stop_lim {
                    CountResult {
                        length,
                        count: proven.min(limit),
                        complete: false,
                        nodes: 0,
                        elapsed_ns: 0,
                        cutoff_reached: stop_at_count != 0 && proven >= stop_at_count,
                    }
                } else {
                    count_cycles_fast_u64(cand, length, limit, node_budget, stop_at_count, scratch)
                }
            } else {
                count_cycles_fast_u64(cand, length, limit, node_budget, stop_at_count, scratch)
            }
        } else {
            count_cycles_fast_u64(cand, length, limit, node_budget, stop_at_count, scratch)
        };

        let effective_count = if !res.complete && !res.cutoff_reached {
            cap
        } else {
            res.count.min(cap)
        };
        partial_total += effective_count;
        partial_weighted += effective_count * weight;
        let is_len_exact = res.count <= cap && res.complete;
        if is_len_exact {
            complete_mask |= 1u8 << len_idx;
        }
        complete = complete && is_len_exact;
        counts_arr[len_idx] = (length, effective_count);
        if res.cutoff_reached {
            return None;
        }
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                return None;
            }
        }
    }

    Some(ScoreResult {
        valid: true,
        counts: counts_arr,
        counts_len: n_len as u8,
        complete_mask,
        total: partial_total,
        weighted_penalty: partial_weighted,
        complete,
        simplicity,
    })
}

/// Fast hot-loop scorer for general n <= 128 (dispatches to u64 when n <= 64).
pub fn score_graph_fast(
    graph: &BitGraph,
    cap: u32,
    node_budget: u32,
    cutoff: Option<Cutoff>,
    scratch: &mut DfsScratch,
) -> Option<ScoreResult> {
    if graph.n <= 64 {
        let g64 = BitGraph64::from_graph(graph);
        return score_graph_fast_u64(&g64, cap, node_budget, cutoff, scratch);
    }
    let lengths = forbidden_lengths(graph.n);
    let (order_idxs, n_len) = eval_order(lengths, graph.n, cutoff.is_some());
    let limit = cap + 1;
    let simplicity = graph.size();
    let mut partial_total = 0u32;
    let mut partial_weighted = 0u32;
    let mut complete = true;
    let mut complete_mask = 0u8;
    let mut counts_arr = [(0u16, 0u32); 6];

    for pos in 0..n_len {
        let len_idx = order_idxs[pos];
        let length = lengths[len_idx];
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                return None;
            }
        }
        let weight = (64u32 / (length as u32)).max(1);
        let mut stop_at_count = 0u32;
        if let Some(co) = cutoff {
            for c in 1..=limit {
                let bounded = c.min(cap);
                if co.reached(
                    partial_total + bounded,
                    partial_weighted + bounded * weight,
                    simplicity,
                ) {
                    stop_at_count = c;
                    break;
                }
            }
        }
        let res = count_cycles_fast_u128(graph, length, limit, node_budget, stop_at_count, scratch);
        let effective_count = if !res.complete && !res.cutoff_reached {
            cap
        } else {
            res.count.min(cap)
        };
        partial_total += effective_count;
        partial_weighted += effective_count * weight;
        let is_len_exact = res.count <= cap && res.complete;
        if is_len_exact {
            complete_mask |= 1u8 << len_idx;
        }
        complete = complete && is_len_exact;
        counts_arr[len_idx] = (length, effective_count);
        if res.cutoff_reached {
            return None;
        }
        if let Some(co) = cutoff {
            if co.reached(partial_total, partial_weighted, simplicity) {
                return None;
            }
        }
    }

    Some(ScoreResult {
        valid: true,
        counts: counts_arr,
        counts_len: n_len as u8,
        complete_mask,
        total: partial_total,
        weighted_penalty: partial_weighted,
        complete,
        simplicity,
    })
}

// ============================================================================
// 3. ZERO-ALLOCATION STACK-ONLY WITNESS-CYCLE DISCOVERY
// ============================================================================

pub struct StackWitnesses {
    pub groups: [[Edge; MAX_ORDER]; 6],
    pub lens: [u8; 6],
    pub count: usize,
}

impl StackWitnesses {
    pub fn new() -> Self {
        Self {
            groups: [[(0, 0); MAX_ORDER]; 6],
            lens: [0u8; 6],
            count: 0,
        }
    }
}

/// Fast analytic C4 witness extractor (~30 ns vs ~5 us DFS).
#[inline]
fn find_c4_witness_u64(rows: &[u64; 64], order: usize, out: &mut [Edge]) -> usize {
    let max_start = order.saturating_sub(3);
    for start in 0..max_start {
        let greater_mask = !((1u64 << (start + 1)) - 1);
        let mut nbrs = rows[start] & greater_mask;
        if nbrs.count_ones() < 2 {
            continue;
        }
        while nbrs != 0 {
            let a = nbrs.trailing_zeros() as usize;
            nbrs &= nbrs - 1;
            let ra = rows[a] & greater_mask;
            let mut rest = nbrs;
            while rest != 0 {
                let c = rest.trailing_zeros() as usize;
                rest &= rest - 1;
                let common = ra & rows[c];
                if common != 0 {
                    let b = common.trailing_zeros() as usize;
                    out[0] = normalize_edge(start as u8, a as u8);
                    out[1] = normalize_edge(a as u8, b as u8);
                    out[2] = normalize_edge(b as u8, c as u8);
                    out[3] = normalize_edge(c as u8, start as u8);
                    return 4;
                }
            }
        }
    }
    0
}

/// Fast single Hamiltonian witness finder via Posa extension + lollipop close (~2 us).
fn find_hamiltonian_witness_posa_u64(rows: &[u64; 64], order: usize, out: &mut [Edge]) -> usize {
    if order < 8 || order > 64 {
        return 0;
    }
    let full_mask: u64 = if order == 64 {
        !0u64
    } else {
        (1u64 << order) - 1
    };
    let mut path = [0u8; 64];
    let mut pos_of = [255u8; 64];
    let mut rng_state: u64 = 0x517c_c1b7_2722_0a95 ^ (order as u64);

    #[inline]
    fn fast_rand(s: &mut u64) -> u64 {
        *s ^= *s << 13;
        *s ^= *s >> 7;
        *s ^= *s << 17;
        *s
    }

    let mut total_rot = 0usize;
    for restart in 0..3usize {
        if total_rot >= 400 {
            break;
        }
        let start = (restart * 17) % order;
        path[0] = start as u8;
        let mut len = 1usize;
        let mut in_path = 1u64 << start;
        pos_of.fill(255);
        pos_of[start] = 0;
        let mut stuck = 0usize;
        let mut prev_tail = usize::MAX;
        while len < order && total_rot < 400 && stuck < 120 {
            let tail = path[len - 1] as usize;
            let unvis = rows[tail] & !in_path;
            if unvis != 0 {
                let mut best_v = unvis.trailing_zeros() as usize;
                let mut best_d = (rows[best_v] & !in_path).count_ones();
                let mut b = unvis & (unvis - 1);
                while b != 0 {
                    let v = b.trailing_zeros() as usize;
                    b &= b - 1;
                    let d = (rows[v] & !in_path).count_ones();
                    if d < best_d {
                        best_d = d;
                        best_v = v;
                    }
                }
                path[len] = best_v as u8;
                pos_of[best_v] = len as u8;
                in_path |= 1u64 << best_v;
                len += 1;
                stuck = 0;
                prev_tail = usize::MAX;
                continue;
            }
            let head = path[0] as usize;
            if (rows[head] & !in_path) != 0 {
                path[..len].reverse();
                for idx in 0..len {
                    pos_of[path[idx] as usize] = idx as u8;
                }
                prev_tail = usize::MAX;
                continue;
            }
            if len >= 3 && (rows[tail] & (1u64 << head)) != 0 {
                let mut ext_idx = None;
                for idx in 0..len {
                    if (rows[path[idx] as usize] & !in_path) != 0 {
                        ext_idx = Some(idx);
                        break;
                    }
                }
                if let Some(idx) = ext_idx {
                    let shift = (idx + 1) % len;
                    if shift != 0 {
                        path[..len].rotate_left(shift);
                        for k in 0..len {
                            pos_of[path[k] as usize] = k as u8;
                        }
                    }
                    prev_tail = usize::MAX;
                    continue;
                } else {
                    break;
                }
            }
            let mut nbrs = rows[tail] & in_path;
            if len >= 2 {
                nbrs &= !(1u64 << path[len - 2]);
            }
            let mut chosen = None;
            let mut fb = [0usize; 8];
            let mut fb_len = 0usize;
            while nbrs != 0 {
                let u = nbrs.trailing_zeros() as usize;
                nbrs &= nbrs - 1;
                let p = pos_of[u] as usize;
                if p + 1 < len {
                    let nt = path[p + 1] as usize;
                    if (rows[nt] & !in_path) != 0 {
                        chosen = Some(p);
                        break;
                    }
                    if nt != prev_tail && fb_len < fb.len() {
                        fb[fb_len] = p;
                        fb_len += 1;
                    }
                }
            }
            let rot_p = match chosen {
                Some(p) => p,
                None if fb_len > 0 => fb[(fast_rand(&mut rng_state) as usize) % fb_len],
                None => break,
            };
            prev_tail = tail;
            path[(rot_p + 1)..len].reverse();
            for idx in (rot_p + 1)..len {
                pos_of[path[idx] as usize] = idx as u8;
            }
            total_rot += 1;
            stuck += 1;
        }
        if len < order || in_path != full_mask {
            continue;
        }
        let mut prev_t = usize::MAX;
        for _ in 0..120 {
            let head = path[0] as usize;
            let tail = path[order - 1] as usize;
            if (rows[tail] & (1u64 << head)) != 0 {
                for i in 0..order {
                    out[i] = normalize_edge(path[i], path[(i + 1) % order]);
                }
                return order;
            }
            let mut nbrs = rows[tail] & !((1u64 << path[order - 2]) | (1u64 << head));
            let mut chosen = None;
            let mut cands = [0usize; 8];
            let mut clen = 0usize;
            while nbrs != 0 {
                let u = nbrs.trailing_zeros() as usize;
                nbrs &= nbrs - 1;
                let p = pos_of[u] as usize;
                if p > 0 && p + 1 < order {
                    let nt = path[p + 1] as usize;
                    if nt == prev_t {
                        continue;
                    }
                    if (rows[nt] & (1u64 << head)) != 0 {
                        chosen = Some(p);
                        break;
                    }
                    if clen < cands.len() {
                        cands[clen] = p;
                        clen += 1;
                    }
                }
            }
            let rot_p = match chosen {
                Some(p) => p,
                None if clen > 0 => cands[(fast_rand(&mut rng_state) as usize) % clen],
                None => break,
            };
            prev_t = tail;
            path[(rot_p + 1)..order].reverse();
            for idx in (rot_p + 1)..order {
                pos_of[path[idx] as usize] = idx as u8;
            }
        }
    }
    0
}

pub fn find_witness_edge_groups_u64(
    graph: &BitGraph64,
    edges: &[Edge],
    nonzero_len_mask: u8,
    bank: Option<&CycleBank64>,
    node_budget: u32,
    scratch: &mut DfsScratch,
    out: &mut StackWitnesses,
) {
    out.count = 0;
    let lengths = forbidden_lengths(graph.n);
    let rows = &graph.rows;
    let order = graph.n;
    let budget = node_budget as u64;

    for (len_idx, &length) in lengths.iter().enumerate() {
        // Exact skip: if score already proved zero cycles of `length`, no witness exists!
        if (nonzero_len_mask & (1u8 << len_idx)) == 0 {
            continue;
        }
        let target = length as usize;
        let slot = out.count;

        // Instant O(m) (~40 ns) witness extraction directly from CycleBank64 when available!
        if let Some(b) = bank {
            let extracted = b.extract_witness_edges(length, edges, &mut out.groups[slot]);
            if extracted == target {
                out.lens[slot] = target as u8;
                out.count += 1;
                continue;
            }
        }

        // Fast analytic C4 witness (~30 ns).
        if length == 4 {
            let found = find_c4_witness_u64(rows, order, &mut out.groups[slot]);
            if found == 4 {
                out.lens[slot] = 4;
                out.count += 1;
            }
            continue;
        }

        // Fast Posa Hamiltonian witness (~2 us vs 25 us failing iterative DFS).
        if target == order && order >= 48 {
            let found = find_hamiltonian_witness_posa_u64(rows, order, &mut out.groups[slot]);
            if found == order {
                out.lens[slot] = order as u8;
                out.count += 1;
            }
            continue;
        }

        let max_start = order - target + 1;
        let close_depth = target - 2;
        let mut nodes = 0u64;

        'starts: for start in 0..max_start {
            let start_bit = 1u64 << start;
            let greater_mask = !((1u64 << (start + 1)) - 1);
            let nbrs = rows[start] & greater_mask;
            if nbrs.count_ones() < 2 {
                continue;
            }
            let max_nbr_bit = 1u64 << (63 - nbrs.leading_zeros());
            let mut first_choices = nbrs ^ max_nbr_bit;

            while first_choices != 0 {
                let first = first_choices.trailing_zeros() as usize;
                first_choices &= first_choices - 1;
                let first_bit = 1u64 << first;
                let gt_first = if first >= 63 {
                    0
                } else {
                    !((1u64 << (first + 1)) - 1)
                };
                let closing_set = nbrs & gt_first;
                if closing_set == 0 {
                    continue;
                }

                let allowed_domain = greater_mask & !first_bit;
                let mut reached = closing_set;
                let mut frontier = closing_set;
                scratch.dist_mask64[1] = reached;
                let max_r = target - 2;
                let mut built_r = 1usize;
                while built_r < max_r && frontier != 0 {
                    let mut next = 0u64;
                    let mut f = frontier;
                    while f != 0 {
                        let u = f.trailing_zeros() as usize;
                        f &= f - 1;
                        next |= rows[u];
                    }
                    frontier = (next & allowed_domain) & !reached;
                    reached |= frontier;
                    built_r += 1;
                    scratch.dist_mask64[built_r] = reached;
                }

                let init_avail = rows[first]
                    & allowed_domain
                    & if target - 2 <= built_r {
                        scratch.dist_mask64[target - 2]
                    } else {
                        reached
                    };
                if init_avail == 0 {
                    continue;
                }

                scratch.path[0] = start as u8;
                scratch.path[1] = first as u8;
                scratch.seen_at64[1] = start_bit | first_bit;
                scratch.available_at64[1] = init_avail;
                nodes += 1;
                if budget != 0 && nodes > budget {
                    break 'starts;
                }

                let mut depth = 2usize;
                while depth >= 2 {
                    let parent_idx = depth - 1;
                    let bits = scratch.available_at64[parent_idx];
                    if bits == 0 {
                        depth -= 1;
                        continue;
                    }
                    let vertex = bits.trailing_zeros() as usize;
                    let bit = 1u64 << vertex;
                    scratch.available_at64[parent_idx] = bits ^ bit;
                    scratch.path[depth] = vertex as u8;
                    let seen = scratch.seen_at64[parent_idx] | bit;
                    nodes += 1;
                    if budget != 0 && nodes > budget {
                        break 'starts;
                    }

                    if depth == close_depth {
                        let valid_close = rows[vertex] & closing_set & !seen;
                        if valid_close != 0 {
                            let last = valid_close.trailing_zeros() as u8;
                            scratch.path[target - 1] = last;
                            let slot = out.count;
                            for i in 0..target {
                                let a = scratch.path[i];
                                let b = scratch.path[(i + 1) % target];
                                out.groups[slot][i] = normalize_edge(a, b);
                            }
                            out.lens[slot] = target as u8;
                            out.count += 1;
                            break 'starts;
                        }
                        continue;
                    }
                    if (closing_set & !seen) == 0 {
                        continue;
                    }
                    let rem = target - 1 - depth;
                    let dmask = if rem <= built_r {
                        scratch.dist_mask64[rem]
                    } else {
                        reached
                    };
                    let next_avail = rows[vertex] & !seen & allowed_domain & dmask;
                    if next_avail != 0 {
                        scratch.seen_at64[depth] = seen;
                        scratch.available_at64[depth] = next_avail;
                        depth += 1;
                    }
                }
            }
        }
    }
}

pub fn find_witness_edge_groups(
    graph: &BitGraph,
    node_budget: u32,
    scratch: &mut DfsScratch,
    out: &mut StackWitnesses,
) {
    if graph.n <= 64 {
        let g64 = BitGraph64::from_graph(graph);
        return find_witness_edge_groups_u64(&g64, &[], !0u8, None, node_budget, scratch, out);
    }
    out.count = 0;
    let lengths = forbidden_lengths(graph.n);
    let rows = &graph.rows;
    let order = graph.n;
    let budget = node_budget as u64;

    for &length in lengths {
        let target = length as usize;
        let max_start = order - target + 1;
        let close_depth = target - 2;
        let mut nodes = 0u64;

        'starts: for start in 0..max_start {
            let start_bit = 1u128 << start;
            let greater_mask = !((1u128 << (start + 1)) - 1);
            let nbrs = rows[start] & greater_mask;
            if nbrs.count_ones() < 2 {
                continue;
            }
            let max_nbr_bit = 1u128 << (127 - nbrs.leading_zeros());
            let mut first_choices = nbrs ^ max_nbr_bit;

            while first_choices != 0 {
                let first = first_choices.trailing_zeros() as usize;
                first_choices &= first_choices - 1;
                let first_bit = 1u128 << first;
                let gt_first = if first >= 127 {
                    0
                } else {
                    !((1u128 << (first + 1)) - 1)
                };
                let closing_set = nbrs & gt_first;
                if closing_set == 0 {
                    continue;
                }

                let allowed_domain = greater_mask & !first_bit;
                let mut reached = closing_set;
                let mut frontier = closing_set;
                scratch.dist_mask128[1] = reached;
                let max_r = target - 2;
                let mut built_r = 1usize;
                while built_r < max_r && frontier != 0 {
                    let mut next = 0u128;
                    let mut f = frontier;
                    while f != 0 {
                        let u = f.trailing_zeros() as usize;
                        f &= f - 1;
                        next |= rows[u];
                    }
                    frontier = (next & allowed_domain) & !reached;
                    reached |= frontier;
                    built_r += 1;
                    scratch.dist_mask128[built_r] = reached;
                }

                let init_avail = rows[first]
                    & allowed_domain
                    & if target - 2 <= built_r {
                        scratch.dist_mask128[target - 2]
                    } else {
                        reached
                    };
                if init_avail == 0 {
                    continue;
                }

                scratch.path[0] = start as u8;
                scratch.path[1] = first as u8;
                scratch.seen_at[1] = start_bit | first_bit;
                scratch.available_at[1] = init_avail;
                nodes += 1;
                if budget != 0 && nodes > budget {
                    break 'starts;
                }

                let mut depth = 2usize;
                while depth >= 2 {
                    let parent_idx = depth - 1;
                    let bits = scratch.available_at[parent_idx];
                    if bits == 0 {
                        depth -= 1;
                        continue;
                    }
                    let vertex = bits.trailing_zeros() as usize;
                    let bit = 1u128 << vertex;
                    scratch.available_at[parent_idx] = bits ^ bit;
                    scratch.path[depth] = vertex as u8;
                    let seen = scratch.seen_at[parent_idx] | bit;
                    nodes += 1;
                    if budget != 0 && nodes > budget {
                        break 'starts;
                    }

                    if depth == close_depth {
                        let valid_close = rows[vertex] & closing_set & !seen;
                        if valid_close != 0 {
                            let last = valid_close.trailing_zeros() as u8;
                            scratch.path[target - 1] = last;
                            let slot = out.count;
                            for i in 0..target {
                                let a = scratch.path[i];
                                let b = scratch.path[(i + 1) % target];
                                out.groups[slot][i] = normalize_edge(a, b);
                            }
                            out.lens[slot] = target as u8;
                            out.count += 1;
                            break 'starts;
                        }
                        continue;
                    }
                    if (closing_set & !seen) == 0 {
                        continue;
                    }
                    let rem = target - 1 - depth;
                    let dmask = if rem <= built_r {
                        scratch.dist_mask128[rem]
                    } else {
                        reached
                    };
                    let next_avail = rows[vertex] & !seen & allowed_domain & dmask;
                    if next_avail != 0 {
                        scratch.seen_at[depth] = seen;
                        scratch.available_at[depth] = next_avail;
                        depth += 1;
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mutation::{GraphMode, generate_seed};
    use crate::rng::Rng;

    #[test]
    fn fast_c4_c8_c16_match_parity_dfs_exactly() {
        let mut rng = Rng::new(20261126);
        let mut scratch = DfsScratch::new();
        for &mode in &[
            GraphMode::CubicFirst,
            GraphMode::MinimalStructureMixedDegree,
            GraphMode::UnrestrictedMinDegree3,
        ] {
            for &n in &[6usize, 10, 16, 20, 24, 32, 50, 64] {
                if mode == GraphMode::CubicFirst && n % 2 != 0 {
                    continue;
                }
                for _ in 0..4 {
                    let g = generate_seed(&mut rng, n, mode).unwrap();
                    let g64 = BitGraph64::from_graph(&g);
                    for &len in &[4u16, 8, 16] {
                        if (len as usize) > n {
                            continue;
                        }
                        let limit = if len <= 8 { 10_000 } else { 500 };
                        let budget = if len <= 8 { 500_000 } else { 200_000 };
                        let ref_res = count_cycles(&g, len, limit, budget, 0, &mut scratch, false);
                        let fast_u64 =
                            count_cycles_fast_u64(&g64, len, limit, budget, 0, &mut scratch);
                        let fast_u128 =
                            count_cycles_fast_u128(&g, len, limit, budget, 0, &mut scratch);
                        if ref_res.complete {
                            assert!(
                                fast_u64.complete,
                                "u64 incomplete for n={n} len={len} mode={mode:?}"
                            );
                            assert_eq!(
                                fast_u64.count, ref_res.count,
                                "u64 mismatch for n={n} len={len} mode={mode:?}"
                            );
                            assert!(
                                fast_u128.complete,
                                "u128 incomplete for n={n} len={len} mode={mode:?}"
                            );
                            assert_eq!(
                                fast_u128.count, ref_res.count,
                                "u128 mismatch for n={n} len={len} mode={mode:?}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn hamiltonian_pruned_matches_parity_dfs_exactly() {
        let mut rng = Rng::new(777);
        let mut scratch = DfsScratch::new();
        for &mode in &[
            GraphMode::CubicFirst,
            GraphMode::MinimalStructureMixedDegree,
        ] {
            for &n in &[8usize, 16, 20, 32] {
                for _ in 0..8 {
                    let g = generate_seed(&mut rng, n, mode).unwrap();
                    let g64 = BitGraph64::from_graph(&g);
                    let ref_res = count_cycles(&g, n as u16, 10_000, 0, 0, &mut scratch, false);
                    let ham = count_hamiltonian_u64(&g64.rows, n, 10_000, 0, 0);
                    assert_eq!(
                        ham.count, ref_res.count,
                        "Hamiltonian count mismatch for n={n} mode={mode:?}"
                    );
                    assert_eq!(ham.complete, ref_res.complete);
                }
            }
        }
    }

    #[test]
    fn posa_certifies_hamiltonian_cubic_64_fast() {
        let mut rng = Rng::new(20261126);
        let mut hits = 0;
        for _ in 0..10 {
            let g = generate_seed(&mut rng, 64, GraphMode::CubicFirst).unwrap();
            let g64 = BitGraph64::from_graph(&g);
            if posa_hamiltonian_fast_cert_u64(&g64.rows, 64, 65).is_some() {
                hits += 1;
            }
        }
        assert!(hits >= 8, "expected Posa to certify >=8/10 random cubic n=64, got {hits}");
    }

    #[test]
    fn delta_c4_and_c8_match_exact_counts() {
        use crate::mutation::{WitnessCache, mutate_u64};
        let mut rng = Rng::new(20261127);
        let mut scratch = DfsScratch::new();
        let mut wc = WitnessCache::new();
        let mut edges_buf = Vec::new();
        for &mode in &[GraphMode::CubicFirst, GraphMode::MinimalStructureMixedDegree] {
            for &n in &[16usize, 32, 50, 64] {
                let mut g = BitGraph64::from_graph(&generate_seed(&mut rng, n, mode).unwrap());
                g.collect_edges(&mut edges_buf);
                for _ in 0..40 {
                    let exact_c4_p = count_c4_u64(&g.rows, n, 10_000, 0).count;
                    let exact_c8_p = count_c8_mitm_u64(&g.rows, n, 10_000, 0, 0, &mut scratch).count;
                    let (mut cand, delta) = mutate_u64(&g, &edges_buf, &mut rng, mode, false, !0u8, 0u64, None, &mut wc, &mut scratch);
                    if !delta.changed || delta.removed_count != 2 || delta.added_count != 2 {
                        continue;
                    }
                    let exact_c4_c = count_c4_u64(&cand.rows, n, 10_000, 0).count;
                    let exact_c8_c = count_c8_mitm_u64(&cand.rows, n, 10_000, 0, 0, &mut scratch).count;

                    let m4 = count_c4_through_two_edges_u64(&g.rows, delta.removed[0], delta.removed[1]);
                    let p4 = count_c4_through_two_edges_u64(&cand.rows, delta.added[0], delta.added[1]);
                    assert_eq!(exact_c4_p + p4 - m4, exact_c4_c, "delta C4 mismatch n={n} mode={mode:?}");

                    let m8 = count_c8_through_two_edges_u64(&mut g.rows, delta.removed[0], delta.removed[1]).unwrap();
                    let p8 = count_c8_through_two_edges_u64(&mut cand.rows, delta.added[0], delta.added[1]).unwrap();
                    assert_eq!(exact_c8_p + p8 - m8, exact_c8_c, "delta C8 mismatch n={n} mode={mode:?}");

                    if n <= 32 {
                        let exact_c16_p = count_cycles_pruned_u64(&g.rows, n, 16, 10_000, 0, 0, &mut scratch).count;
                        let exact_c16_c = count_cycles_pruned_u64(&cand.rows, n, 16, 10_000, 0, 0, &mut scratch).count;
                        let m16 = count_cycles_through_two_edges_u64(
                            &mut g.rows, n, 16, delta.removed[0], delta.removed[1], 0, 0, &mut scratch.dist_mask64
                        ).unwrap();
                        let p16 = count_cycles_through_two_edges_u64(
                            &mut cand.rows, n, 16, delta.added[0], delta.added[1], 0, 0, &mut scratch.dist_mask64
                        ).unwrap();
                        assert_eq!(exact_c16_p + p16 - m16, exact_c16_c, "delta C16 mismatch n={n} mode={mode:?}");
                    }

                    g = cand;
                    g.collect_edges(&mut edges_buf);
                }
            }
        }
    }
}

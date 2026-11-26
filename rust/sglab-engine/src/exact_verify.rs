//! Wave C exact deterministic verifiers:
//! 1. Forced-Edge Branch-and-Reduce (Eppstein 2007 / Xiao-Nagamochi 2016) for
//!    exact cubic Hamiltonian cycle certification (C32 at n=32, C64 at n=64).
//! 2. Single-pass Frontier DP (Simpath / mate-array + u128 length bitmask) for
//!    exact simultaneous spectrum certification of {C4, C8, C16, C32, C64}.

use std::collections::HashMap;
use std::time::Instant;

use crate::graph::{BitGraph, Edge};

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub enum BnrResult {
    Found { cycle: Vec<u8>, nodes: u64 },
    Absent { nodes: u64 },
    BudgetExceeded { nodes: u64 },
}

#[derive(Clone, Copy)]
struct BnrState {
    avail: [u64; 64],
    forced: [u64; 64],
    /// Endpoint mate of forced path segments:
    /// - if `forced[u].count_ones() == 0`: `mate[u] = u`
    /// - if `forced[u].count_ones() == 1`: `mate[u]` is the other endpoint of u's forced path
    /// - if `forced[u].count_ones() == 2`: `mate[u] = u` (internal vertex)
    mate: [u8; 64],
    forced_edges: u8,
}

impl BnrState {
    fn new(rows: &[u64; 64], n: usize) -> Self {
        let mut avail = [0u64; 64];
        let mut mate = [0u8; 64];
        for u in 0..n {
            avail[u] = rows[u];
            mate[u] = u as u8;
        }
        Self {
            avail,
            forced: [0u64; 64],
            mate,
            forced_edges: 0,
        }
    }

    #[inline]
    fn delete_edge(&mut self, u: usize, v: usize) -> bool {
        let bit_v = 1u64 << v;
        if (self.forced[u] & bit_v) != 0 {
            return false; // cannot delete a forced edge
        }
        self.avail[u] &= !bit_v;
        self.avail[v] &= !(1u64 << u);
        true
    }

    /// Force edge `(u, v)`. Returns:
    /// - `Ok(true)` if this closes a complete Hamiltonian cycle (`forced_edges == n`),
    /// - `Ok(false)` if forced consistently and still partial,
    /// - `Err(())` on contradiction (unavailable, degree > 2, or premature subcycle).
    #[inline]
    fn force_edge(&mut self, n: usize, u: usize, v: usize) -> Result<bool, ()> {
        let bit_v = 1u64 << v;
        if (self.forced[u] & bit_v) != 0 {
            return Ok(false); // already forced
        }
        if (self.avail[u] & bit_v) == 0 {
            return Err(());
        }
        if self.forced[u].count_ones() >= 2 || self.forced[v].count_ones() >= 2 {
            return Err(());
        }
        let a = self.mate[u] as usize;
        let b = self.mate[v] as usize;
        if a == v {
            // Closing a cycle!
            if (self.forced_edges as usize) + 1 == n {
                self.forced[u] |= bit_v;
                self.forced[v] |= 1u64 << u;
                self.forced_edges += 1;
                return Ok(true);
            }
            return Err(()); // premature subcycle of length < n
        }
        self.forced[u] |= bit_v;
        self.forced[v] |= 1u64 << u;
        self.forced_edges += 1;

        self.mate[u] = u as u8;
        self.mate[v] = v as u8;
        self.mate[a] = b as u8;
        self.mate[b] = a as u8;

        // Premature-cycle lookahead: if (a, b) is undecided and closing it would
        // form a cycle of length < n, delete (a, b) immediately!
        if (self.forced_edges as usize) + 1 < n
            && (self.avail[a] & (1u64 << b)) != 0
            && (self.forced[a] & (1u64 << b)) == 0
        {
            self.avail[a] &= !(1u64 << b);
            self.avail[b] &= !(1u64 << a);
        }
        Ok(false)
    }

    /// Run deterministic forced-edge / degree-2 / premature-cycle propagation to fixed point.
    fn propagate(&mut self, n: usize) -> Result<bool, ()> {
        let mut changed = true;
        while changed {
            changed = false;
            for u in 0..n {
                let av = self.avail[u];
                let fc = self.forced[u];
                let ad = av.count_ones();
                let fd = fc.count_ones();
                if ad < 2 || fd > 2 {
                    return Err(());
                }
                if fd == 2 && av != fc {
                    // Delete all undecided edges incident to u
                    let mut rem = av & !fc;
                    while rem != 0 {
                        let v = rem.trailing_zeros() as usize;
                        rem &= rem - 1;
                        if !self.delete_edge(u, v) {
                            return Err(());
                        }
                    }
                    changed = true;
                } else if ad == 2 && fd < 2 {
                    // Force all remaining available edges incident to u
                    let mut rem = av & !fc;
                    while rem != 0 {
                        let v = rem.trailing_zeros() as usize;
                        rem &= rem - 1;
                        if self.force_edge(n, u, v)? {
                            return Ok(true);
                        }
                    }
                    changed = true;
                }
            }
        }
        Ok(false)
    }

    /// Verify `avail` is still 2-connected (necessary for any Hamiltonian graph!).
    /// Fast Tarjan articulation-point check on `avail[0..n]`.
    fn is_avail_biconnected(&self, n: usize) -> bool {
        let mut disc = [0u8; 64];
        let mut low = [0u8; 64];
        let mut timer = 0u8;
        let mut root_children = 0u8;
        let mut failed = false;

        fn dfs(
            rows: &[u64; 64],
            u: usize,
            parent: usize,
            disc: &mut [u8; 64],
            low: &mut [u8; 64],
            timer: &mut u8,
            root_children: &mut u8,
            failed: &mut bool,
        ) {
            *timer += 1;
            disc[u] = *timer;
            low[u] = *timer;
            let mut bits = rows[u];
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                if v == parent {
                    continue;
                }
                if disc[v] == 0 {
                    if parent == usize::MAX {
                        *root_children += 1;
                        if *root_children > 1 {
                            *failed = true;
                            return;
                        }
                    }
                    dfs(rows, v, u, disc, low, timer, root_children, failed);
                    if *failed {
                        return;
                    }
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if parent != usize::MAX && low[v] >= disc[u] {
                        *failed = true;
                        return;
                    }
                } else if disc[v] < low[u] {
                    low[u] = disc[v];
                }
            }
        }

        dfs(
            &self.avail,
            0,
            usize::MAX,
            &mut disc,
            &mut low,
            &mut timer,
            &mut root_children,
            &mut failed,
        );
        !failed && (timer as usize) == n
    }

    fn extract_cycle(&self, n: usize) -> Vec<u8> {
        let mut cyc = Vec::with_capacity(n);
        let mut prev = usize::MAX;
        let mut cur = 0usize;
        for _ in 0..n {
            cyc.push(cur as u8);
            let mut nbrs = self.forced[cur];
            let mut nxt = usize::MAX;
            while nbrs != 0 {
                let v = nbrs.trailing_zeros() as usize;
                nbrs &= nbrs - 1;
                if v != prev {
                    nxt = v;
                    break;
                }
            }
            if nxt == usize::MAX {
                break;
            }
            prev = cur;
            cur = nxt;
        }
        cyc
    }
}

/// Deterministic Forced-Edge Branch-and-Reduce exact Hamiltonian cycle solver
/// for subcubic / general low-degree graphs (`n <= 64`, optimal for cubic graphs).
/// When `node_budget == 0`, runs exhaustively without budget limit.
pub fn exact_cubic_hamiltonian_bnr_u64(
    rows: &[u64; 64],
    n: usize,
    node_budget: u64,
) -> BnrResult {
    if n < 3 || n > 64 {
        return BnrResult::Absent { nodes: 0 };
    }
    let mut init = BnrState::new(rows, n);
    let mut nodes = 0u64;
    let mut hit_budget = false;

    fn solve(
        n: usize,
        mut st: BnrState,
        nodes: &mut u64,
        budget: u64,
        hit_budget: &mut bool,
    ) -> Option<Vec<u8>> {
        *nodes += 1;
        if budget != 0 && *nodes > budget {
            *hit_budget = true;
            return None;
        }
        match st.propagate(n) {
            Err(()) => return None,
            Ok(true) => return Some(st.extract_cycle(n)),
            Ok(false) => {}
        }
        if (st.forced_edges as usize) == n {
            return Some(st.extract_cycle(n));
        }
        if !st.is_avail_biconnected(n) {
            return None;
        }

        // Eppstein branching rule: pick an undecided edge (u, v) incident to a
        // vertex u with fd == 1 (so branching forces one edge AND deletes the
        // other on BOTH branches, maximizing propagation cascade!).
        let mut branch_edge: Option<(usize, usize)> = None;
        let mut best_score = 0u32;
        for u in 0..n {
            let undec = st.avail[u] & !st.forced[u];
            if undec == 0 {
                continue;
            }
            let fd_u = st.forced[u].count_ones();
            let ad_u = st.avail[u].count_ones();
            let mut bits = undec;
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                if u > v {
                    continue;
                }
                let fd_v = st.forced[v].count_ones();
                let ad_v = st.avail[v].count_ones();
                // Prioritize edges touching fd==1 endpoints with ad==3 (tightest cascade)
                let score = (if fd_u == 1 { 100 } else { 0 })
                    + (if fd_v == 1 { 100 } else { 0 })
                    + (if ad_u == 3 { 20 } else { 0 })
                    + (if ad_v == 3 { 20 } else { 0 })
                    + 1;
                if score > best_score {
                    best_score = score;
                    branch_edge = Some((u, v));
                }
            }
        }

        let Some((u, v)) = branch_edge else {
            return None;
        };

        // Branch 1: Force (u, v)
        let mut b_force = st;
        match b_force.force_edge(n, u, v) {
            Ok(true) => return Some(b_force.extract_cycle(n)),
            Ok(false) => {
                if let Some(cyc) = solve(n, b_force, nodes, budget, hit_budget) {
                    return Some(cyc);
                }
            }
            Err(()) => {}
        }
        if *hit_budget {
            return None;
        }

        // Branch 2: Delete (u, v)
        let mut b_del = st;
        if b_del.delete_edge(u, v) {
            if let Some(cyc) = solve(n, b_del, nodes, budget, hit_budget) {
                return Some(cyc);
            }
        }
        None
    }

    // Seed initial symmetry breaking on vertex 0 if all degrees == 3:
    // Vertex 0 has 3 incident edges (0, a), (0, b), (0, c). Exactly 2 are in any
    // Hamiltonian cycle, so either (0, a) is deleted (forcing b, c), or (0, a) is forced!
    // The general branching loop handles this directly, and checking `init.propagate`
    // first handles any degree-2 vertices immediately.
    match init.propagate(n) {
        Err(()) => return BnrResult::Absent { nodes: 1 },
        Ok(true) => {
            return BnrResult::Found {
                cycle: init.extract_cycle(n),
                nodes: 1,
            };
        }
        Ok(false) => {}
    }

    if let Some(cycle) = solve(n, init, &mut nodes, node_budget, &mut hit_budget) {
        BnrResult::Found { cycle, nodes }
    } else if hit_budget {
        BnrResult::BudgetExceeded { nodes }
    } else {
        BnrResult::Absent { nodes }
    }
}

/// Result of single-pass Frontier DP exact cycle spectrum computation.
#[derive(Clone, Debug)]
pub enum FrontierDpResult {
    Complete {
        /// Bit `L` (for `3 <= L <= 127`) is 1 iff graph contains a simple cycle of length `L`.
        spectrum: u128,
        /// Exact Hamiltonian cycle presence when `n == 128` (not needed for n <= 127).
        max_frontier: usize,
        peak_states: usize,
        elapsed_ms: f64,
    },
    TooWide {
        max_frontier: usize,
        peak_states: usize,
        elapsed_ms: f64,
    },
}

/// Compute a low-frontier-width edge ordering via multi-start greedy min-frontier
/// vertex ordering (trying all `n` start vertices; picks ordering minimizing max
/// active frontier size).
fn compute_edge_order(g: &BitGraph) -> (Vec<Edge>, usize) {
    let n = g.n;
    let mut adj: Vec<Vec<usize>> = vec![Vec::new(); n];
    let mut edge_count = 0usize;
    for u in 0..n {
        let mut bits = g.rows[u];
        while bits != 0 {
            let v = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            adj[u].push(v);
            if u < v {
                edge_count += 1;
            }
        }
    }

    let mut best_order: Vec<Edge> = Vec::with_capacity(edge_count);
    let mut best_width = usize::MAX;

    let mut used_v = vec![false; n];
    let mut deg_rem = vec![0usize; n];
    let mut active = vec![false; n];
    let mut order = Vec::with_capacity(edge_count);

    for start in 0..n {
        used_v.fill(false);
        active.fill(false);
        for u in 0..n {
            deg_rem[u] = adj[u].len();
        }
        order.clear();
        let mut cur_frontier = 0usize;
        let mut max_w = 0usize;

        // Expand vertex-by-vertex: adding vertex v emits all edges between v and
        // already-added vertices, immediately closing any vertex whose deg_rem hits 0.
        let mut added = 0usize;
        let mut next_v = start;
        while added < n {
            used_v[next_v] = true;
            added += 1;

            for &u in &adj[next_v] {
                if used_v[u] {
                    order.push((u.min(next_v) as u8, u.max(next_v) as u8));
                    if !active[u] {
                        active[u] = true;
                        cur_frontier += 1;
                    }
                    if !active[next_v] {
                        active[next_v] = true;
                        cur_frontier += 1;
                    }
                    if cur_frontier > max_w {
                        max_w = cur_frontier;
                    }
                    deg_rem[u] -= 1;
                    deg_rem[next_v] -= 1;
                    if deg_rem[u] == 0 && active[u] {
                        active[u] = false;
                        cur_frontier -= 1;
                    }
                    if deg_rem[next_v] == 0 && active[next_v] {
                        active[next_v] = false;
                        cur_frontier -= 1;
                    }
                }
            }
            if max_w >= best_width {
                break;
            }
            if added == n {
                break;
            }

            // Pick next unadded vertex minimizing frontier delta (preferring
            // vertices with maximum edges into current frontier and closing
            // active vertices immediately!).
            let mut pick = usize::MAX;
            let mut pick_key = (isize::MAX, isize::MAX, usize::MAX);
            for v in 0..n {
                if used_v[v] {
                    continue;
                }
                let mut edges_to_used = 0usize;
                let mut closes = 0usize;
                for &u in &adj[v] {
                    if used_v[u] {
                        edges_to_used += 1;
                        if deg_rem[u] == 1 {
                            closes += 1;
                        }
                    }
                }
                let v_stays = if edges_to_used > 0 && edges_to_used < adj[v].len() {
                    1isize
                } else {
                    0isize
                };
                let delta = v_stays - (closes as isize);
                // Prefer vertices connected to the already-placed component!
                let disconnected_pen = if edges_to_used == 0 { 1000isize } else { 0isize };
                let key = (disconnected_pen + delta, -(edges_to_used as isize), adj[v].len());
                if key < pick_key {
                    pick_key = key;
                    pick = v;
                }
            }
            next_v = pick;
        }

        if order.len() == edge_count && max_w < best_width {
            best_width = max_w;
            best_order.clear();
            best_order.extend_from_slice(&order);
            if best_width <= 6 {
                break;
            }
        }
    }

    (best_order, best_width)
}

#[inline(always)]
fn get_nib(state: u64, slot: usize) -> u8 {
    ((state >> (slot * 4)) & 0xF) as u8
}

#[inline(always)]
fn set_nib(state: u64, slot: usize, val: u8) -> u64 {
    let shift = slot * 4;
    (state & !(0xFu64 << shift)) | ((val as u64) << shift)
}

/// Single-pass exact Frontier DP (Simpath mate-array + u128 length bitmask)
/// computing the exact simple-cycle length spectrum of `g` (all lengths `3..=min(n, 127)`).
///
/// State encoding: 4 bits per frontier vertex (`slot in 0..F`, `F <= 14`):
/// - `0`: degree 0 (not yet touched by the partial cycle path)
/// - `15`: degree 2 (completed interior vertex of the path)
/// - `j + 1` (`1..=14`): degree 1, paired endpoint is frontier slot `j`
///
/// Closing a cycle (`mate[u] == v`) is accepted ONLY when no other frontier vertex
/// has degree 1, immediately recording `lengths_mask << 1` into `cycle_spectrum`
/// without re-inserting into the DP table (guaranteeing strictly single simple cycles).
pub fn exact_spectrum_frontier_dp(
    g: &BitGraph,
    max_width_cap: usize,
    max_states_cap: usize,
) -> FrontierDpResult {
    let started = Instant::now();
    if g.n < 3 {
        return FrontierDpResult::Complete {
            spectrum: 0,
            max_frontier: 0,
            peak_states: 0,
            elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
        };
    }

    let (edges, max_w) = compute_edge_order(g);
    let effective_w_cap = max_width_cap.min(14);
    if max_w > effective_w_cap {
        return FrontierDpResult::TooWide {
            max_frontier: max_w,
            peak_states: 0,
            elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
        };
    }

    let m = edges.len();
    let mut last_occ = vec![0usize; g.n];
    for (idx, &(u, v)) in edges.iter().enumerate() {
        last_occ[u as usize] = idx;
        last_occ[v as usize] = idx;
    }

    let mut cur_frontier: Vec<usize> = Vec::with_capacity(16);
    let mut dp: HashMap<u64, u128> = HashMap::with_capacity(1024);
    let mut next_dp: HashMap<u64, u128> = HashMap::with_capacity(1024);
    dp.insert(0u64, 1u128); // empty path of length 0

    let mut cycle_spectrum: u128 = 0;
    let mut peak_states = 1usize;

    for (step, &(u_u8, v_u8)) in edges.iter().enumerate() {
        let u = u_u8 as usize;
        let v = v_u8 as usize;

        // Build post-insertion frontier (add u, v if not already present)
        let mut work_frontier = cur_frontier.clone();
        let u_pos = match work_frontier.iter().position(|&x| x == u) {
            Some(p) => p,
            None => {
                work_frontier.push(u);
                work_frontier.len() - 1
            }
        };
        let v_pos = match work_frontier.iter().position(|&x| x == v) {
            Some(p) => p,
            None => {
                work_frontier.push(v);
                work_frontier.len() - 1
            }
        };
        let wf_len = work_frontier.len();
        debug_assert!(wf_len <= 14);

        // Determine which vertices leave the frontier after this edge
        let mut keep_slots: [usize; 16] = [0; 16];
        let mut keep_len = 0usize;
        let mut drop_slots: [usize; 16] = [0; 16];
        let mut drop_len = 0usize;
        let mut slot_remap: [u8; 16] = [0; 16];
        for (idx, &vert) in work_frontier.iter().enumerate() {
            if last_occ[vert] > step {
                slot_remap[idx] = keep_len as u8;
                keep_slots[keep_len] = idx;
                keep_len += 1;
            } else {
                drop_slots[drop_len] = idx;
                drop_len += 1;
            }
        }

        // Helper closure to validate dropped slots & compress state to next_frontier
        let compress_and_insert = |st: u64, mask: u128, target: &mut HashMap<u64, u128>| {
            if mask == 0 {
                return;
            }
            for d_i in 0..drop_len {
                let code = get_nib(st, drop_slots[d_i]);
                // Dropped vertex MUST be degree 0 or degree 2 (15), never dangling degree 1!
                if code != 0 && code != 15 {
                    return;
                }
            }
            let mut packed = 0u64;
            for new_slot in 0..keep_len {
                let old_slot = keep_slots[new_slot];
                let code = get_nib(st, old_slot);
                let new_code = if code == 0 || code == 15 {
                    code
                } else {
                    let old_mate = (code - 1) as usize;
                    slot_remap[old_mate] + 1
                };
                packed |= (new_code as u64) << (new_slot * 4);
            }
            *target.entry(packed).or_insert(0) |= mask;
        };

        next_dp.clear();

        for (&st, &lmask) in &dp {
            // Branch 0: Skip edge (u, v)
            compress_and_insert(st, lmask, &mut next_dp);

            // Branch 1: Take edge (u, v)
            let cu = get_nib(st, u_pos);
            let cv = get_nib(st, v_pos);
            if cu == 15 || cv == 15 {
                continue; // degree > 2 forbidden
            }
            let shifted = lmask << 1;
            if shifted == 0 {
                continue;
            }

            if cu == 0 && cv == 0 {
                // Start a new path segment u -- v
                let mut ns = set_nib(st, u_pos, (v_pos as u8) + 1);
                ns = set_nib(ns, v_pos, (u_pos as u8) + 1);
                compress_and_insert(ns, shifted, &mut next_dp);
            } else if cu == 0 {
                // Extend path ending at v (mate = m_v) to u: u -- ... -- m_v, v becomes deg 2
                let mv = (cv - 1) as usize;
                let mut ns = set_nib(st, v_pos, 15);
                ns = set_nib(ns, u_pos, (mv as u8) + 1);
                ns = set_nib(ns, mv, (u_pos as u8) + 1);
                compress_and_insert(ns, shifted, &mut next_dp);
            } else if cv == 0 {
                // Extend path ending at u (mate = m_u) to v
                let mu = (cu - 1) as usize;
                let mut ns = set_nib(st, u_pos, 15);
                ns = set_nib(ns, v_pos, (mu as u8) + 1);
                ns = set_nib(ns, mu, (v_pos as u8) + 1);
                compress_and_insert(ns, shifted, &mut next_dp);
            } else {
                // Both u and v have degree 1
                let mu = (cu - 1) as usize;
                let mv = (cv - 1) as usize;
                if mu == v_pos {
                    // Closing a cycle! Valid ONLY if NO other frontier vertex has degree 1
                    // (otherwise there is another open path component, which would form a
                    // disconnected 2-factor rather than a single simple cycle!).
                    let mut other_open = false;
                    for slot in 0..wf_len {
                        if slot == u_pos || slot == v_pos {
                            continue;
                        }
                        let c = get_nib(st, slot);
                        if c != 0 && c != 15 {
                            other_open = true;
                            break;
                        }
                    }
                    if !other_open {
                        cycle_spectrum |= shifted;
                    }
                } else {
                    // Merge two distinct paths: mu -- u -- v -- mv
                    let mut ns = set_nib(st, u_pos, 15);
                    ns = set_nib(ns, v_pos, 15);
                    ns = set_nib(ns, mu, (mv as u8) + 1);
                    ns = set_nib(ns, mv, (mu as u8) + 1);
                    compress_and_insert(ns, shifted, &mut next_dp);
                }
            }
        }

        std::mem::swap(&mut dp, &mut next_dp);
        cur_frontier.clear();
        for i in 0..keep_len {
            cur_frontier.push(work_frontier[keep_slots[i]]);
        }
        if dp.len() > peak_states {
            peak_states = dp.len();
        }
        if dp.len() > max_states_cap {
            return FrontierDpResult::TooWide {
                max_frontier: max_w,
                peak_states,
                elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
            };
        }
        let _ = m;
    }

    // Clear low bits < 3 just in case
    cycle_spectrum &= !0b111u128;

    FrontierDpResult::Complete {
        spectrum: cycle_spectrum,
        max_frontier: max_w,
        peak_states,
        elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cycles::{DfsScratch, count_cycles, score_graph_fast};
    use crate::graph::BitGraph64;
    use crate::mutation::{
        GraphMode, build_markstrom24, build_petersen, generate_h7_expansion_seed, generate_seed,
    };
    use crate::rng::Rng;

    /// Build Flower Snark J_k (odd k >= 3, order 4k, cubic, non-Hamiltonian for all odd k >= 3).
    fn build_flower_snark(k: usize) -> BitGraph {
        let n = 4 * k;
        let mut g = BitGraph::empty(n);
        for i in 0..k {
            let a = 4 * i;
            let b = 4 * i + 1;
            let c = 4 * i + 2;
            let d = 4 * i + 3;
            g.add_edge(a, b);
            g.add_edge(a, c);
            g.add_edge(a, d);
            let ni = (i + 1) % k;
            let nb = 4 * ni + 1;
            let nc = 4 * ni + 2;
            let nd = 4 * ni + 3;
            g.add_edge(b, nb);
            if i + 1 < k {
                g.add_edge(c, nc);
                g.add_edge(d, nd);
            } else {
                // Twisted closing edges for odd k
                g.add_edge(c, nd);
                g.add_edge(d, nc);
            }
        }
        g
    }

    #[test]
    fn bnr_exact_cubic_hamiltonian_matches_dfs_and_certifies_snarks() {
        let mut rng = Rng::new(2026112605);
        let mut scratch = DfsScratch::new();

        // 1) Known non-Hamiltonian cubic graphs: Petersen (n=10), Flower snarks J5 (20), J7 (28), J9 (36), J15 (60)
        for (name, g) in [
            ("Petersen", build_petersen()),
            ("J5", build_flower_snark(5)),
            ("J7", build_flower_snark(7)),
            ("J9", build_flower_snark(9)),
            ("J15", build_flower_snark(15)),
        ] {
            let g64 = BitGraph64::from_graph(&g);
            match exact_cubic_hamiltonian_bnr_u64(&g64.rows, g64.n, 0) {
                BnrResult::Absent { nodes } => {
                    assert!(nodes > 0, "{name} expected positive node count");
                }
                other => panic!("{name} (n={}) is non-Hamiltonian, got {other:?}", g.n),
            }
        }

        // 2) Random cubic graphs n=8, 12, 16, 20, 24: B&R agrees 100% with exact parity DFS!
        for &n in &[8usize, 12, 16, 20, 24] {
            for _ in 0..8 {
                let g = generate_seed(&mut rng, n, GraphMode::CubicFirst).unwrap();
                let g64 = BitGraph64::from_graph(&g);
                let dfs_has = count_cycles(&g, n as u16, 1, 0, 0, &mut scratch, false).count > 0;
                match exact_cubic_hamiltonian_bnr_u64(&g64.rows, n, 0) {
                    BnrResult::Found { cycle, .. } => {
                        assert!(dfs_has, "B&R false positive on n={n}");
                        assert_eq!(cycle.len(), n);
                        let mut seen = 0u64;
                        for i in 0..n {
                            let u = cycle[i] as usize;
                            let v = cycle[(i + 1) % n] as usize;
                            assert!(g64.has_edge(u, v), "invalid cycle edge ({u},{v})");
                            seen |= 1u64 << u;
                        }
                        assert_eq!(seen.count_ones() as usize, n);
                    }
                    BnrResult::Absent { .. } => {
                        assert!(!dfs_has, "B&R false negative on n={n}");
                    }
                    BnrResult::BudgetExceeded { .. } => panic!("unbounded B&R exceeded budget"),
                }
            }
        }
    }

    #[test]
    fn frontier_dp_certifies_exact_spectrum_on_markstrom24_petersen_and_h7_n64() {
        let mut scratch = DfsScratch::new();

        // 1) Petersen (n=10): cycle spectrum is exactly {5, 6, 8, 9} (no 3, 4, 7, 10)
        let pet = build_petersen();
        match exact_spectrum_frontier_dp(&pet, 14, 2_000_000) {
            FrontierDpResult::Complete { spectrum, .. } => {
                let expected: u128 = (1u128 << 5) | (1u128 << 6) | (1u128 << 8) | (1u128 << 9);
                assert_eq!(spectrum, expected, "Petersen spectrum mismatch: {spectrum:#x}");
            }
            other => panic!("Petersen Frontier DP failed: {other:?}"),
        }

        // 2) Markstrom-24 (n=24): C4=0, C8=0, C16>0
        let m24 = build_markstrom24();
        match exact_spectrum_frontier_dp(&m24, 14, 2_000_000) {
            FrontierDpResult::Complete { spectrum, .. } => {
                assert_eq!(spectrum & (1u128 << 4), 0, "Markstrom-24 must have no C4");
                assert_eq!(spectrum & (1u128 << 8), 0, "Markstrom-24 must have no C8");
                assert_ne!(spectrum & (1u128 << 16), 0, "Markstrom-24 must have C16");
                // Cross-check EVERY length 3..=24 against exact parity DFS!
                for len in 3..=24usize {
                    let dfs_has = count_cycles(&m24, len as u16, 1, 0, 0, &mut scratch, false).count > 0;
                    let dp_has = (spectrum & (1u128 << len)) != 0;
                    assert_eq!(dp_has, dfs_has, "Markstrom-24 spectrum mismatch at L={len}");
                }
            }
            other => panic!("Markstrom-24 Frontier DP failed: {other:?}"),
        }

        // 3) Petersen + 9*H7 at n=64 (modular H7 graph): Frontier DP certifies ENTIRE
        //    {C4, C8, C16, C32, C64} spectrum in one pass AND agrees with B&R on C64!
        let mut rng = Rng::new(2026112606);
        let h64 = generate_h7_expansion_seed(&mut rng, 64, GraphMode::CubicFirst).unwrap();
        let g64 = BitGraph64::from_graph(&h64);
        let sc = score_graph_fast(&h64, 512, 500_000, None, &mut scratch).unwrap();
        let bnr = exact_cubic_hamiltonian_bnr_u64(&g64.rows, 64, 0);
        let bnr_has_c64 = matches!(bnr, BnrResult::Found { .. });

        match exact_spectrum_frontier_dp(&h64, 14, 2_000_000) {
            FrontierDpResult::Complete { spectrum, max_frontier, .. } => {
                assert!(max_frontier <= 12, "expected small pathwidth for H7 n=64, got {max_frontier}");
                assert_eq!((spectrum & (1u128 << 4)) != 0, sc.count_of(4) > 0);
                assert_eq!((spectrum & (1u128 << 8)) != 0, sc.count_of(8) > 0);
                assert_eq!((spectrum & (1u128 << 16)) != 0, sc.count_of(16) > 0);
                assert_eq!((spectrum & (1u128 << 64)) != 0, bnr_has_c64);
            }
            other => panic!("H7 n=64 Frontier DP failed: {other:?}"),
        }
    }
}

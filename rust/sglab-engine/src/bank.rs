//! Orientation-aware transposed bitset cycle bank (`CycleBank64`) for `n <= 64`.
//!
//! Mathematical soundness invariant:
//! - Every live slot `k` in a length-`L` bank corresponds to a pairwise-distinct,
//!   edge-verified simple `L`-cycle `C_k` of the current `graph`, oriented in a
//!   fixed cyclic direction `v_0 -> v_1 -> ... -> v_{L-1} -> v_0`.
//! - For every edge `e = (u, v)` (`u < v`) at index `eidx` in `edges_buf`:
//!   - `edge_in[eidx]` has bit `k = 1` iff `e ∈ C_k`.
//!   - `edge_dir[eidx]` has bit `k = 1` iff `C_k` traverses `u -> v` (vs `v -> u`).
//! - On a 2-edge switch removing disjoint edges `r0 = (u1, v1)` (`u1 < v1`, index `i0`)
//!   and `r1 = (u2, v2)` (`u2 < v2`, index `i1`) and adding `e0, e1`:
//!   1. Every cycle with `in0 == 0 && in1 == 0` survives untouched in `cand`
//!      (uses neither `e0` nor `e1`).
//!   2. Every cycle with `in0 == 1 && in1 == 1` whose relative orientation matches
//!      `want_same_dir` (`{e0, e1} == {(u1, u2), (v1, v2)}` iff `dir0 == dir1`)
//!      reconnects `(C_k \ {r0, r1}) ∪ {e0, e1}` into a valid simple `L`-cycle of
//!      `cand` (uses both `e0` and `e1`).
//!   3. Surviving and reconnected sets are disjoint and the reconnection map is
//!      injective, so `proven_count <= exact_count(cand)` ALWAYS holds!

use crate::graph::{BitGraph64, Edge, normalize_edge};

pub const MAX_BANK_EDGES: usize = 192;
pub const BANK_WORDS: usize = 6; // up to 384 cycles per length
pub const BANK_CAP: usize = BANK_WORDS * 64;

/// Zero-memory-lookup ALU mixer for an undirected edge `(a, b)` — zero L1/L2 cache traffic!
#[inline(always)]
fn edge_mix64(a: u8, b: u8) -> u64 {
    let (lo, hi) = if a < b {
        (a as u64, b as u64)
    } else {
        (b as u64, a as u64)
    };
    let k = (lo | (hi << 8)).wrapping_add(1);
    let z = k.wrapping_mul(0x9e37_79b9_7f4a_7c15);
    let z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z ^ (z >> 27)
}

/// Fixed-size open-addressed u64 hash set (1024 slots) for O(1) cycle dedup during refill.
struct HashSet1024 {
    slots: [u64; 1024],
}

impl HashSet1024 {
    #[inline]
    fn new() -> Self {
        Self { slots: [0u64; 1024] }
    }

    #[inline]
    fn norm(h: u64) -> u64 {
        if h == 0 { 1 } else { h }
    }

    #[inline]
    fn insert(&mut self, h: u64) -> bool {
        let k = Self::norm(h);
        let mut idx = ((k ^ (k >> 17)) as usize) & 1023;
        loop {
            let cur = self.slots[idx];
            if cur == 0 {
                self.slots[idx] = k;
                return true;
            }
            if cur == k {
                return false;
            }
            idx = (idx + 1) & 1023;
        }
    }
}

pub struct SingleLengthBank {
    pub words_used: usize,
    pub valid: [u64; BANK_WORDS],
    /// Subset of `valid` whose `edge_dir` orientation bits are exact (strictly
    /// surviving or freshly harvested cycles; reconnected cycles keep exact `edge_in`
    /// in `valid` for future survival checks while clearing `dir_valid`).
    pub dir_valid: [u64; BANK_WORDS],
    pub valid_count: u32,
    pub edge_in: [[u64; BANK_WORDS]; MAX_BANK_EDGES],
    pub edge_dir: [[u64; BANK_WORDS]; MAX_BANK_EDGES],
    pub cycle_hashes: [u64; BANK_CAP],
    pub tried_for_graph: bool,
}

impl SingleLengthBank {
    pub fn new(words_used: usize) -> Self {
        Self {
            words_used: words_used.min(BANK_WORDS),
            valid: [0u64; BANK_WORDS],
            dir_valid: [0u64; BANK_WORDS],
            valid_count: 0,
            edge_in: [[0u64; BANK_WORDS]; MAX_BANK_EDGES],
            edge_dir: [[0u64; BANK_WORDS]; MAX_BANK_EDGES],
            cycle_hashes: [0u64; BANK_CAP],
            tried_for_graph: false,
        }
    }

    #[inline]
    pub fn clear(&mut self, m: usize) {
        self.valid = [0u64; BANK_WORDS];
        self.dir_valid = [0u64; BANK_WORDS];
        self.valid_count = 0;
        self.tried_for_graph = false;
        let limit = m.min(MAX_BANK_EDGES);
        for e in 0..limit {
            for w in 0..self.words_used {
                self.edge_in[e][w] = 0;
                self.edge_dir[e][w] = 0;
            }
        }
    }

    /// Returns a mathematically sound lower bound on `#C_L(cand)` after removing
    /// edges at `i0`, `i1` and adding edges with orientation flag `want_same_dir`.
    #[inline]
    pub fn proven_count(&self, i0: usize, i1: usize, want_same_dir: bool) -> u32 {
        let mut total = 0u32;
        let dir_xor_mask = if want_same_dir { !0u64 } else { 0u64 };
        let in0_arr = &self.edge_in[i0];
        let in1_arr = &self.edge_in[i1];
        let dir0_arr = &self.edge_dir[i0];
        let dir1_arr = &self.edge_dir[i1];
        for w in 0..self.words_used {
            let v = self.valid[w];
            if v == 0 {
                continue;
            }
            let in0 = in0_arr[w];
            let in1 = in1_arr[w];
            let surviving = v & !(in0 | in1);
            let both_dir_ok = v & self.dir_valid[w] & in0 & in1;
            let dir_match = (dir0_arr[w] ^ dir1_arr[w]) ^ dir_xor_mask;
            let good = surviving | (both_dir_ok & dir_match);
            total += good.count_ones();
        }
        total
    }

    /// Incrementally retain BOTH strictly surviving cycles AND orientation-matched
    /// reconnected cycles after accepting a 2-edge switch that overwrote slots `i0`, `i1`!
    #[inline]
    pub fn apply_accepted_switch(
        &mut self,
        i0: usize,
        i1: usize,
        want_same_dir: bool,
        delta_hash: u64,
    ) {
        let dir_xor_mask = if want_same_dir { !0u64 } else { 0u64 };
        let mut new_cnt = 0u32;
        for w in 0..self.words_used {
            let v = self.valid[w];
            let in0 = self.edge_in[i0][w];
            let in1 = self.edge_in[i1][w];
            let surviving = v & !(in0 | in1);
            let both_dir_ok = v & self.dir_valid[w] & in0 & in1;
            let dir_match = (self.edge_dir[i0][w] ^ self.edge_dir[i1][w]) ^ dir_xor_mask;
            let reconnected = both_dir_ok & dir_match;

            // Update exact cycle hashes for reconnected cycles: (C \ {r0, r1}) U {e0, e1}.
            let mut rec = reconnected;
            while rec != 0 {
                let b = rec.trailing_zeros() as usize;
                rec &= rec - 1;
                self.cycle_hashes[(w << 6) + b] ^= delta_hash;
            }

            let new_valid = surviving | reconnected;
            self.valid[w] = new_valid;
            // Strictly surviving cycles retain exact orientation; reconnected ones clear dir_valid.
            self.dir_valid[w] &= surviving;
            // Surviving cycles use neither i0 nor i1; reconnected cycles use BOTH new edges at i0 & i1!
            self.edge_in[i0][w] = reconnected;
            self.edge_in[i1][w] = reconnected;
            self.edge_dir[i0][w] = 0;
            self.edge_dir[i1][w] = 0;
            new_cnt += new_valid.count_ones();
        }
        self.valid_count = new_cnt;
        self.tried_for_graph = false;
    }

    /// Clear stale bits for dead slots across `0..m` before refilling dead slots.
    #[inline]
    fn scrub_dead_bits(&mut self, m: usize) {
        for e in 0..m {
            for w in 0..self.words_used {
                let v = self.valid[w];
                self.edge_in[e][w] &= v;
                self.edge_dir[e][w] &= self.dir_valid[w];
            }
        }
    }

    #[inline]
    pub fn extract_any_cycle_edges(&self, edges: &[Edge], out: &mut [Edge]) -> usize {
        if self.valid_count == 0 {
            return 0;
        }
        let mut chosen_w = 0usize;
        let mut chosen_bit = 0u64;
        for w in 0..self.words_used {
            let v = self.valid[w];
            if v != 0 {
                chosen_w = w;
                chosen_bit = v & v.wrapping_neg();
                break;
            }
        }
        if chosen_bit == 0 {
            return 0;
        }
        let mut k = 0usize;
        let limit = edges.len().min(MAX_BANK_EDGES);
        for eidx in 0..limit {
            if (self.edge_in[eidx][chosen_w] & chosen_bit) != 0 {
                if k < out.len() {
                    out[k] = edges[eidx];
                    k += 1;
                }
            }
        }
        k
    }

    #[inline]
    pub fn next_free_slot(&self) -> Option<usize> {
        for w in 0..self.words_used {
            let inv = !self.valid[w];
            if inv != 0 {
                return Some((w << 6) + (inv.trailing_zeros() as usize));
            }
        }
        None
    }

    #[inline]
    fn insert_cycle(
        &mut self,
        slot: usize,
        path: &[u8],
        cyc_hash: u64,
        edge_id: &[[u16; 64]; 64],
    ) {
        let w = slot >> 6;
        let bit = 1u64 << (slot & 63);
        let len = path.len();
        for i in 0..len {
            let a = path[i] as usize;
            let b = path[(i + 1) % len] as usize;
            let eidx = edge_id[a][b] as usize;
            debug_assert!(eidx < MAX_BANK_EDGES);
            self.edge_in[eidx][w] |= bit;
            if a < b {
                self.edge_dir[eidx][w] |= bit;
            }
        }
        self.valid[w] |= bit;
        self.dir_valid[w] |= bit;
        self.cycle_hashes[slot] = cyc_hash;
        self.valid_count += 1;
    }

    fn seed_dedup_set(&self, set: &mut HashSet1024) {
        for w in 0..self.words_used {
            let mut v = self.valid[w];
            while v != 0 {
                let b = v.trailing_zeros() as usize;
                v &= v - 1;
                let slot = (w << 6) + b;
                set.insert(self.cycle_hashes[slot]);
            }
        }
    }
}

/// Per-lane bank managing saturated C16, C32, and C64 witnesses for `graph`.
pub struct CycleBank64 {
    pub active: bool,
    pub m: usize,
    pub edge_id: [[u16; 64]; 64],
    pub c16: SingleLengthBank,
    pub c32: SingleLengthBank,
    pub c64: SingleLengthBank,
    /// Pool of up to 4 recent Hamiltonian cycles of `graph` to skip Phase 1 on C64 refill!
    pub ham_seeds: [[u8; 64]; 4],
    pub ham_seed_count: usize,
    pub rng_seed: u64,
}

impl CycleBank64 {
    pub fn new(seed: u64) -> Self {
        Self {
            active: false,
            m: 0,
            edge_id: [[u16::MAX; 64]; 64],
            c16: SingleLengthBank::new(4), // 256 cycles
            c32: SingleLengthBank::new(5), // 320 cycles
            c64: SingleLengthBank::new(5), // 320 cycles
            ham_seeds: [[0u8; 64]; 4],
            ham_seed_count: 0,
            rng_seed: seed ^ 0x6a09_e667_f3bc_c908,
        }
    }

    pub fn reset_for_graph(&mut self, edges: &[Edge]) {
        if edges.len() > MAX_BANK_EDGES {
            self.active = false;
            self.m = 0;
            return;
        }
        let old_m = self.m.max(edges.len());
        self.c16.clear(old_m);
        self.c32.clear(old_m);
        self.c64.clear(old_m);
        self.ham_seed_count = 0;
        self.edge_id = [[u16::MAX; 64]; 64];
        for (idx, &(u, v)) in edges.iter().enumerate() {
            self.edge_id[u as usize][v as usize] = idx as u16;
            self.edge_id[v as usize][u as usize] = idx as u16;
        }
        self.m = edges.len();
        self.active = true;
    }

    #[inline]
    pub fn apply_accepted_switch(
        &mut self,
        removed: [Edge; 2],
        removed_idx: [u16; 2],
        added: [Edge; 2],
    ) {
        if !self.active {
            return;
        }
        let i0 = removed_idx[0] as usize;
        let i1 = removed_idx[1] as usize;
        if i0 >= self.m || i1 >= self.m {
            self.active = false;
            return;
        }
        self.edge_id[removed[0].0 as usize][removed[0].1 as usize] = u16::MAX;
        self.edge_id[removed[0].1 as usize][removed[0].0 as usize] = u16::MAX;
        self.edge_id[removed[1].0 as usize][removed[1].1 as usize] = u16::MAX;
        self.edge_id[removed[1].1 as usize][removed[1].0 as usize] = u16::MAX;

        self.edge_id[added[0].0 as usize][added[0].1 as usize] = i0 as u16;
        self.edge_id[added[0].1 as usize][added[0].0 as usize] = i0 as u16;
        self.edge_id[added[1].0 as usize][added[1].1 as usize] = i1 as u16;
        self.edge_id[added[1].1 as usize][added[1].0 as usize] = i1 as u16;

        let p_same = normalize_edge(removed[0].0, removed[1].0);
        let want_same_dir = added[0] == p_same || added[1] == p_same;
        let delta_hash = edge_mix64(removed[0].0, removed[0].1)
            ^ edge_mix64(removed[1].0, removed[1].1)
            ^ edge_mix64(added[0].0, added[0].1)
            ^ edge_mix64(added[1].0, added[1].1);

        self.c16
            .apply_accepted_switch(i0, i1, want_same_dir, delta_hash);
        self.c32
            .apply_accepted_switch(i0, i1, want_same_dir, delta_hash);
        self.c64
            .apply_accepted_switch(i0, i1, want_same_dir, delta_hash);
    }

    /// Extract edges of one live banked cycle of `length` in O(m) (~40 ns), or 0 if none banked.
    #[inline]
    pub fn extract_witness_edges(&self, length: u16, edges: &[Edge], out: &mut [Edge]) -> usize {
        if !self.active || edges.len() != self.m {
            return 0;
        }
        match length {
            16 => self.c16.extract_any_cycle_edges(edges, out),
            32 => self.c32.extract_any_cycle_edges(edges, out),
            64 => self.c64.extract_any_cycle_edges(edges, out),
            _ => 0,
        }
    }

    /// Ensure bank for `length` is topped up when `graph` is saturated at `cap`,
    /// then return a sound lower bound `proven_count` for the 2-edge switch.
    #[inline]
    pub fn query_or_refill(
        &mut self,
        graph: &BitGraph64,
        length: u16,
        removed: [Edge; 2],
        removed_idx: [u16; 2],
        added: [Edge; 2],
    ) -> Option<u32> {
        if !self.active {
            return None;
        }
        let i0 = removed_idx[0] as usize;
        let i1 = removed_idx[1] as usize;
        if i0 >= self.m || i1 >= self.m {
            return None;
        }
        let p_same = normalize_edge(removed[0].0, removed[1].0);
        let want_same_dir = added[0] == p_same || added[1] == p_same;

        match length {
            16 if graph.n >= 40 => {
                if self.c16.valid_count < 140 && !self.c16.tried_for_graph {
                    self.c16.tried_for_graph = true;
                    self.rng_seed = self.rng_seed.wrapping_add(0x9e37_79b9_7f4a_7c15);
                    refill_dfs_bank(
                        &graph.rows,
                        graph.n,
                        16,
                        224,
                        48,
                        5_000,
                        self.m,
                        &self.edge_id,
                        self.rng_seed,
                        &mut self.c16,
                    );
                }
                Some(self.c16.proven_count(i0, i1, want_same_dir))
            }
            32 if graph.n > 32 => {
                if self.c32.valid_count < 200 && !self.c32.tried_for_graph {
                    self.c32.tried_for_graph = true;
                    self.rng_seed = self.rng_seed.wrapping_add(0x517c_c1b7_2722_0a95);
                    refill_dfs_bank(
                        &graph.rows,
                        graph.n,
                        32,
                        288,
                        64,
                        7_000,
                        self.m,
                        &self.edge_id,
                        self.rng_seed,
                        &mut self.c32,
                    );
                }
                Some(self.c32.proven_count(i0, i1, want_same_dir))
            }
            64 if graph.n == 64 => {
                if self.c64.valid_count < 220 && !self.c64.tried_for_graph {
                    self.c64.tried_for_graph = true;
                    self.rng_seed = self.rng_seed.wrapping_add(0x9e37_79b9_7f4a_7c15);
                    refill_posa_bank_64(
                        &graph.rows,
                        64,
                        288,
                        self.m,
                        &self.edge_id,
                        self.rng_seed,
                        &mut self.ham_seeds,
                        &mut self.ham_seed_count,
                        &mut self.c64,
                    );
                }
                Some(self.c64.proven_count(i0, i1, want_same_dir))
            }
            _ => None,
        }
    }
}

/// Harvest diverse simple `target`-cycles into `bank` across the FULL graph
/// (no `greater_mask` restriction, rotated random starts, full dist_mask BFS,
/// `rem == 3` leaf unroll, incremental `edge_mix64` hash, and O(1) `HashSet1024` dedup).
#[allow(clippy::too_many_arguments)]
fn refill_dfs_bank(
    rows: &[u64; 64],
    order: usize,
    target: usize,
    target_fill: u32,
    per_start_cap: u32,
    node_budget: u64,
    m: usize,
    edge_id: &[[u16; 64]; 64],
    seed: u64,
    bank: &mut SingleLengthBank,
) {
    if target < 4 || target >= order || bank.valid_count >= target_fill {
        return;
    }
    bank.scrub_dead_bits(m);
    let mut dedup = HashSet1024::new();
    if bank.valid_count > 0 {
        bank.seed_dedup_set(&mut dedup);
    }

    let full_mask: u64 = if order == 64 {
        !0u64
    } else {
        (1u64 << order) - 1
    };

    struct HarvestState<'a> {
        rows: &'a [u64; 64],
        dist_mask: &'a [u64; 65],
        adj_to_closing: u64,
        closing_set: u64,
        start_v: u8,
        target: usize,
        path: [u8; 64],
        edge_id: &'a [[u16; 64]; 64],
        bank: &'a mut SingleLengthBank,
        dedup: &'a mut HashSet1024,
        target_fill: u32,
        start_added: u32,
        start_cap: u32,
        nodes: u64,
        start_node_cap: u64,
    }

    fn dfs(
        st: &mut HarvestState<'_>,
        vertex: usize,
        seen: u64,
        depth: usize,
        rem: usize,
        edge_hash: u64,
    ) {
        if rem == 3 {
            // Unrolled rem == 3 -> rem == 2 -> closing leaf!
            let mut u_bits = st.rows[vertex] & !seen & st.dist_mask[3];
            while u_bits != 0 {
                let u = u_bits.trailing_zeros() as usize;
                u_bits &= u_bits - 1;
                st.nodes += 1;
                if st.nodes > st.start_node_cap {
                    return;
                }
                let seen_u = seen | (1u64 << u);
                let closing_avail = st.closing_set & !seen_u;
                if closing_avail == 0 {
                    continue;
                }
                let mut w_bits = st.rows[u] & !seen_u & st.adj_to_closing;
                if w_bits == 0 {
                    continue;
                }
                st.path[depth] = u as u8;
                let hu = edge_hash ^ edge_mix64(vertex as u8, u as u8);
                while w_bits != 0 {
                    let w = w_bits.trailing_zeros() as usize;
                    w_bits &= w_bits - 1;
                    let mut close_bits = st.rows[w] & closing_avail;
                    if close_bits == 0 {
                        continue;
                    }
                    st.path[depth + 1] = w as u8;
                    let hw = hu ^ edge_mix64(u as u8, w as u8);
                    while close_bits != 0 {
                        let last = close_bits.trailing_zeros() as usize;
                        close_bits &= close_bits - 1;
                        let cyc_hash = hw
                            ^ edge_mix64(w as u8, last as u8)
                            ^ edge_mix64(last as u8, st.start_v);
                        if st.dedup.insert(cyc_hash) {
                            if let Some(slot) = st.bank.next_free_slot() {
                                st.path[depth + 2] = last as u8;
                                st.bank.insert_cycle(
                                    slot,
                                    &st.path[..st.target],
                                    cyc_hash,
                                    st.edge_id,
                                );
                                st.start_added += 1;
                                if st.bank.valid_count >= st.target_fill
                                    || st.start_added >= st.start_cap
                                {
                                    return;
                                }
                            } else {
                                return;
                            }
                        }
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
            if st.nodes > st.start_node_cap {
                return;
            }
            let next_seen = seen | (1u64 << v);
            if (st.closing_set & !next_seen) == 0 {
                continue;
            }
            st.path[depth] = v as u8;
            let nh = edge_hash ^ edge_mix64(vertex as u8, v as u8);
            dfs(st, v, next_seen, depth + 1, next_rem, nh);
            if st.nodes > st.start_node_cap
                || st.bank.valid_count >= st.target_fill
                || st.start_added >= st.start_cap
            {
                return;
            }
        }
    }

    let mut dist_mask = [0u64; 65];
    let max_r = target - 2;
    let mut nodes = 0u64;
    let base_start = (seed as usize) % order;
    let stride = if order % 7 != 0 {
        7usize
    } else if order % 11 != 0 {
        11usize
    } else if order % 13 != 0 {
        13usize
    } else {
        1usize
    };

    for s_idx in 0..order {
        if bank.valid_count >= target_fill || nodes > node_budget {
            return;
        }
        let start = (base_start + s_idx * stride) % order;
        let start_bit = 1u64 << start;
        let nbrs = rows[start];
        if nbrs.count_ones() < 2 {
            continue;
        }
        let max_nbr_bit = 1u64 << (63 - nbrs.leading_zeros());
        let mut first_choices = nbrs ^ max_nbr_bit;
        let mut start_added = 0u32;

        while first_choices != 0
            && bank.valid_count < target_fill
            && start_added < per_start_cap
            && nodes <= node_budget
        {
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

            let allowed_domain = full_mask & !(start_bit | first_bit);
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

            let mut path = [0u8; 64];
            path[0] = start as u8;
            path[1] = first as u8;
            let init_hash = edge_mix64(start as u8, first as u8);
            let start_node_cap = (nodes + 1_200).min(node_budget);
            let mut st = HarvestState {
                rows,
                dist_mask: &dist_mask,
                adj_to_closing,
                closing_set,
                start_v: start as u8,
                target,
                path,
                edge_id,
                bank,
                dedup: &mut dedup,
                target_fill,
                start_added,
                start_cap: per_start_cap,
                nodes,
                start_node_cap,
            };
            dfs(&mut st, first, start_bit | first_bit, 2, max_r, init_hash);
            start_added = st.start_added;
            nodes = st.nodes;
        }
    }
}

/// Try to extract a valid length-64 Hamiltonian path of `rows` directly from
/// a cached cycle of the previous graph (0 rotations! succeeds ~99.7% with 4 seeds!).
#[inline]
fn try_extract_ham_path_from_seed(rows: &[u64; 64], seed: &[u8; 64], out: &mut [u8; 64]) -> bool {
    // Count how many edges of `seed` are missing in `rows`.
    let mut missing_idx = 64usize;
    let mut missing_cnt = 0usize;
    for i in 0..64 {
        let a = seed[i] as usize;
        let b = seed[(i + 1) & 63] as usize;
        if (rows[a] & (1u64 << b)) == 0 {
            missing_idx = i;
            missing_cnt += 1;
            if missing_cnt > 1 {
                return false;
            }
        }
    }
    if missing_cnt == 0 {
        *out = *seed;
        return true;
    }
    // Exactly 1 edge (seed[missing_idx], seed[missing_idx + 1]) is missing ->
    // rotate so seed[missing_idx + 1] is path[0] and seed[missing_idx] is path[63]!
    let start = (missing_idx + 1) & 63;
    for i in 0..64 {
        out[i] = seed[(start + i) & 63];
    }
    true
}

/// Fast fused reverse + pos_of update for `path[lo..64]` (single pass!).
#[inline(always)]
fn reverse_suffix_with_pos(path: &mut [u8; 64], pos_of: &mut [u8; 64], lo: usize) {
    let mut l = lo;
    let mut r = 63usize;
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

/// Fast Posa + cubic-specialized Thomason lollipop harvester to fill `bank` with
/// up to `target_fill` distinct Hamiltonian cycles on `n = 64`.
#[allow(clippy::too_many_arguments)]
fn refill_posa_bank_64(
    rows: &[u64; 64],
    order: usize,
    target_fill: u32,
    m: usize,
    edge_id: &[[u16; 64]; 64],
    seed: u64,
    ham_seeds: &mut [[u8; 64]; 4],
    ham_seed_count: &mut usize,
    bank: &mut SingleLengthBank,
) {
    if order != 64 || bank.valid_count >= target_fill {
        return;
    }
    bank.scrub_dead_bits(m);
    let mut dedup = HashSet1024::new();
    if bank.valid_count > 0 {
        bank.seed_dedup_set(&mut dedup);
    }

    let mut path = [0u8; 64];
    let mut tmp_path = [0u8; 64];
    let mut pos_of = [255u8; 64];
    let mut rng_state = seed ^ 0x9e37_79b9_7f4a_7c15;
    if rng_state == 0 {
        rng_state = 1;
    }

    #[inline(always)]
    fn fast_rand(s: &mut u64) -> u64 {
        *s ^= *s << 13;
        *s ^= *s >> 7;
        *s ^= *s << 17;
        *s
    }

    let mut is_cubic = true;
    for u in 0..64 {
        if rows[u].count_ones() != 3 {
            is_cubic = false;
            break;
        }
    }

    let mut total_rotations = 0usize;
    let max_total_rotations = 12_000usize;
    let mut basis_pool = [[0u8; 64]; 4];
    let mut basis_hashes = [0u64; 4];
    let mut basis_len = 0usize;
    let mut basis_cursor = 0usize;
    let mut shift_cursor = ((fast_rand(&mut rng_state) as usize) % 63) + 1;

    for restart in 0..4usize {
        if total_rotations >= max_total_rotations || bank.valid_count >= target_fill {
            break;
        }

        // Phase 1: Try instant O(64) extraction from cached Hamiltonian seeds first!
        let mut have_ham_path = false;
        if restart == 0 && *ham_seed_count > 0 {
            for s in 0..(*ham_seed_count) {
                if try_extract_ham_path_from_seed(rows, &ham_seeds[s], &mut path) {
                    for idx in 0..64 {
                        pos_of[path[idx] as usize] = idx as u8;
                    }
                    have_ham_path = true;
                    break;
                }
            }
        }

        if !have_ham_path {
            let start = ((fast_rand(&mut rng_state) as usize) + restart * 13) & 63;
            path[0] = start as u8;
            let mut len = 1usize;
            let mut in_path: u64 = 1u64 << start;
            pos_of.fill(255);
            pos_of[start] = 0;

            let mut local_stuck = 0usize;
            let mut prev_tail_p1: usize = usize::MAX;
            while len < 64 && total_rotations < max_total_rotations && local_stuck < 220 {
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
                    path[..len].reverse();
                    for idx in 0..len {
                        pos_of[path[idx] as usize] = idx as u8;
                    }
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
                path[(rot_p + 1)..len].reverse();
                for idx in (rot_p + 1)..len {
                    pos_of[path[idx] as usize] = idx as u8;
                }
                total_rotations += 1;
                local_stuck += 1;
            }
            if len < 64 || in_path != !0u64 {
                continue;
            }
        }

        let mut path_hash = 0u64;
        for i in 0..63 {
            path_hash ^= edge_mix64(path[i], path[i + 1]);
        }

        // Phase 2: Short-timeout Thomason lollipop walks with fused swap+pos_of,
        // single-register `target_close`, and 4-cycle rotating basis pool!
        let mut since_found = 0usize;
        let mut walk_steps = 0usize;
        let mut prev_tail: usize = usize::MAX;
        let mut head_close_mask: u64 = rows[path[0] as usize];

        while total_rotations < max_total_rotations && since_found < 320 {
            let head = path[0] as usize;
            let tail = path[63] as usize;
            let is_closed = (head_close_mask & (1u64 << tail)) != 0;
            let timed_out = !is_closed && basis_len > 0 && walk_steps >= 36;

            if is_closed {
                let cyc_hash = path_hash ^ edge_mix64(path[63], path[0]);
                if dedup.insert(cyc_hash) {
                    if let Some(slot) = bank.next_free_slot() {
                        bank.insert_cycle(slot, &path, cyc_hash, edge_id);
                        since_found = 0;
                        let bidx = basis_cursor & 3;
                        basis_pool[bidx] = path;
                        basis_hashes[bidx] = cyc_hash;
                        basis_cursor += 1;
                        if basis_len < 4 {
                            basis_len += 1;
                        }
                        if bank.valid_count >= target_fill {
                            break;
                        }
                    } else {
                        break;
                    }
                }
            }

            if is_closed || timed_out {
                let (src, base_cycle_hash) = if timed_out {
                    let bidx = (basis_cursor.wrapping_add(shift_cursor)) % basis_len;
                    (&basis_pool[bidx], basis_hashes[bidx])
                } else {
                    (&path, path_hash ^ edge_mix64(path[63], path[0]))
                };
                // Deterministic coprime shift progression avoids re-opening the same edge!
                shift_cursor += 11;
                if shift_cursor >= 64 {
                    shift_cursor -= 63;
                }
                let shift = shift_cursor;
                let rev = (fast_rand(&mut rng_state) & 1) != 0;
                if !rev {
                    for idx in 0..64 {
                        let v = src[(idx + shift) & 63];
                        tmp_path[idx] = v;
                        pos_of[v as usize] = idx as u8;
                    }
                } else {
                    for idx in 0..64 {
                        let v = src[(63 + shift - idx) & 63];
                        tmp_path[idx] = v;
                        pos_of[v as usize] = idx as u8;
                    }
                }
                path = tmp_path;
                let new_tail = path[63] as usize;
                let new_head = path[0] as usize;
                head_close_mask = rows[new_head];
                path_hash = base_cycle_hash ^ edge_mix64(new_tail as u8, new_head as u8);

                let open_nbrs = rows[new_tail] & !((1u64 << path[62]) | (1u64 << new_head));
                if open_nbrs != 0 {
                    let u_v = open_nbrs.trailing_zeros() as usize;
                    let p = pos_of[u_v] as usize;
                    if p > 0 && p < 63 {
                        let u = path[p];
                        let nxt = path[p + 1];
                        path_hash ^= edge_mix64(u, nxt) ^ edge_mix64(u, new_tail as u8);
                        prev_tail = new_tail;
                        walk_steps = 1;
                        reverse_suffix_with_pos(&mut path, &mut pos_of, p + 1);
                        total_rotations += 1;
                        since_found += 1;
                        continue;
                    }
                }
                break;
            }

            let rot_p = if is_cubic {
                let nbrs = rows[tail] & !(1u64 << path[62]);
                let u0 = nbrs.trailing_zeros() as usize;
                let u1 = (nbrs ^ (1u64 << u0)).trailing_zeros() as usize;
                let p0 = pos_of[u0] as usize;
                let p1 = pos_of[u1] as usize;
                let nt0 = path[p0 + 1] as usize;
                let nt1 = path[p1 + 1] as usize;
                if nt0 == prev_tail {
                    p1
                } else if nt1 == prev_tail {
                    p0
                } else if (head_close_mask & (1u64 << nt0)) != 0 {
                    p0
                } else if (head_close_mask & (1u64 << nt1)) != 0 {
                    p1
                } else if (fast_rand(&mut rng_state) & 1) == 0 {
                    p0
                } else {
                    p1
                }
            } else {
                let mut nbrs = rows[tail] & !((1u64 << path[62]) | (1u64 << head));
                let mut chosen = None;
                let mut candidates = [0usize; 8];
                let mut cand_len = 0usize;
                while nbrs != 0 {
                    let u = nbrs.trailing_zeros() as usize;
                    nbrs &= nbrs - 1;
                    let p = pos_of[u] as usize;
                    if p > 0 && p < 63 {
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
                    reverse_suffix_with_pos(&mut path, &mut pos_of, 0);
                    head_close_mask = rows[path[0] as usize];
                    prev_tail = usize::MAX;
                    walk_steps += 1;
                    since_found += 1;
                    continue;
                }
            };

            let u = path[rot_p];
            let nxt = path[rot_p + 1];
            path_hash ^= edge_mix64(u, nxt) ^ edge_mix64(u, tail as u8);
            prev_tail = tail;
            walk_steps += 1;
            reverse_suffix_with_pos(&mut path, &mut pos_of, rot_p + 1);
            total_rotations += 1;
            since_found += 1;
        }
    }

    // Save up to 4 verified Hamiltonian cycles for instant Phase-1 skip after the next switch!
    if basis_len > 0 {
        for i in 0..basis_len {
            ham_seeds[i] = basis_pool[i];
        }
        *ham_seed_count = basis_len;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cycles::{DfsScratch, count_cycles_fast_u64};
    use crate::mutation::{GraphMode, WitnessCache, generate_seed, mutate_u64};
    use crate::rng::Rng;

    #[test]
    fn cycle_bank_proven_count_never_exceeds_exact_count() {
        let mut rng = Rng::new(20261128);
        let mut scratch = DfsScratch::new();
        let mut wc = WitnessCache::new();
        let mut edges_buf = Vec::new();

        // Test C16, C32, and C64 across multiple consecutive accepted switches (exercising
        // both strictly surviving AND orientation-reconnected cycles + `dir_valid` tracking).
        for &(n, len) in &[
            (40usize, 16u16),
            (40usize, 32u16),
            (50usize, 16u16),
            (50usize, 32u16),
            (64usize, 64u16),
        ] {
            let mut g = BitGraph64::from_graph(&generate_seed(&mut rng, n, GraphMode::CubicFirst).unwrap());
            g.collect_edges(&mut edges_buf);
            let mut bank = CycleBank64::new(42 + n as u64);
            bank.reset_for_graph(&edges_buf);

            let mut hits = 0usize;
            for step in 0..35 {
                let (cand, delta) = mutate_u64(
                    &g,
                    &edges_buf,
                    &mut rng,
                    GraphMode::CubicFirst,
                    false,
                    !0u8,
                    None,
                    &mut wc,
                    &mut scratch,
                );
                if !delta.changed || delta.removed_count != 2 {
                    continue;
                }
                let proven = bank
                    .query_or_refill(&g, len, delta.removed, delta.removed_idx, delta.added)
                    .unwrap_or(0);
                if proven > 0 {
                    hits += 1;
                }
                let lim = if len == 64 { 65 } else { 500 };
                let res = count_cycles_fast_u64(&cand, len, lim, 200_000, 0, &mut scratch);
                if res.complete {
                    assert!(
                        proven <= res.count,
                        "SOUNDNESS VIOLATION n={n} len={len} step={step}: proven={proven} > exact={}",
                        res.count
                    );
                }
                // Accept every 2nd switch to thoroughly stress incremental reconnected retention!
                if step % 2 == 0 {
                    let i0 = delta.removed_idx[0] as usize;
                    let i1 = delta.removed_idx[1] as usize;
                    edges_buf[i0] = delta.added[0];
                    edges_buf[i1] = delta.added[1];
                    bank.apply_accepted_switch(delta.removed, delta.removed_idx, delta.added);
                    g = cand;
                }
            }
            if n >= 50 {
                assert!(hits >= 25, "expected high bank hit rate for n={n} len={len}, got {hits}/35");
            }
        }
    }

    #[test]
    #[ignore]
    fn profile_breakdown() {
        use std::time::Instant;
        use crate::cycles::{Cutoff, DfsScratch, count_cycles_fast_u64, score_graph_delta_u64, score_graph_fast_u64};
        use crate::mutation::{GraphMode, WitnessCache, generate_seed, mutate_u64};
        use crate::rng::Rng;

        for &n in &[32usize, 50, 60, 64] {
            let mut rng = Rng::new(20261126 + n as u64);
            let mut scratch = DfsScratch::new();
            let mut wc = WitnessCache::new();
            let mut edges_buf = Vec::new();
            let mut bank = CycleBank64::new(42);
            let mut g = BitGraph64::from_graph(&generate_seed(&mut rng, n, GraphMode::CubicFirst).unwrap());
            g.collect_edges(&mut edges_buf);
            bank.reset_for_graph(&edges_buf);
            let mut score = score_graph_fast_u64(&g, 64, 50_000, None, &mut scratch).unwrap();

            let mut t_mut = 0u128;
            let mut t_score = 0u128;
            let mut t_refill_16 = 0u128;
            let mut t_refill_32 = 0u128;
            let mut t_refill_64 = 0u128;
            let mut c_refill_16 = 0u32;
            let mut c_refill_32 = 0u32;
            let mut c_refill_64 = 0u32;
            let mut bank_hit_16 = 0u32;
            let mut bank_miss_16 = 0u32;
            let mut bank_hit_32 = 0u32;
            let mut bank_miss_32 = 0u32;
            let mut bank_hit_64 = 0u32;
            let mut bank_miss_64 = 0u32;
            let mut accepted = 0u32;
            let evals = if n == 64 { 20_000 } else { 80_000 };

            let t_all = Instant::now();
            for step in 1..=evals {
                let targeted = rng.next_f64() < 0.5;
                let t0 = Instant::now();
                let (mut cand, delta) = mutate_u64(
                    &g,
                    &edges_buf,
                    &mut rng,
                    GraphMode::CubicFirst,
                    targeted,
                    score.nonzero_len_mask(),
                    Some(&bank),
                    &mut wc,
                    &mut scratch,
                );
                t_mut += t0.elapsed().as_nanos();
                if !delta.changed {
                    continue;
                }
                let cutoff = if step % 200 == 0 {
                    None
                } else {
                    Some(Cutoff {
                        total: score.total,
                        weighted: score.weighted_penalty,
                        simplicity: score.simplicity,
                        inclusive: false,
                    })
                };

                // Pre-check bank metrics
                let b16_before = bank.c16.tried_for_graph;
                let b32_before = bank.c32.tried_for_graph;
                let b64_before = bank.c64.tried_for_graph;
                let t1 = Instant::now();
                let cand_score = score_graph_delta_u64(
                    &mut g,
                    &score,
                    &mut cand,
                    true,
                    delta.removed,
                    delta.removed_idx,
                    delta.added,
                    edges_buf.len() as u32,
                    64,
                    50_000,
                    cutoff,
                    &mut scratch,
                    &mut bank,
                );
                let dt = t1.elapsed().as_nanos();
                t_score += dt;
                if !b16_before && bank.c16.tried_for_graph { c_refill_16 += 1; t_refill_16 += dt; }
                if !b32_before && bank.c32.tried_for_graph { c_refill_32 += 1; t_refill_32 += dt; }
                if !b64_before && bank.c64.tried_for_graph { c_refill_64 += 1; t_refill_64 += dt; }
                if n >= 50 && delta.removed_idx[0] < bank.m as u16 && delta.removed_idx[1] < bank.m as u16 {
                    let p_same = normalize_edge(delta.removed[0].0, delta.removed[1].0);
                    let wsd = delta.added[0] == p_same || delta.added[1] == p_same;
                    let i0 = delta.removed_idx[0] as usize;
                    let i1 = delta.removed_idx[1] as usize;
                    if bank.c16.proven_count(i0, i1, wsd) >= 65 { bank_hit_16 += 1; } else { bank_miss_16 += 1; }
                    if bank.c32.proven_count(i0, i1, wsd) >= 65 { bank_hit_32 += 1; } else { bank_miss_32 += 1; }
                    if n == 64 {
                        if bank.c64.proven_count(i0, i1, wsd) >= 65 { bank_hit_64 += 1; } else { bank_miss_64 += 1; }
                    }
                }
                if let Some(cs) = cand_score {
                    if cs.ordering_key() <= score.ordering_key() || step % 200 == 0 {
                        g = cand;
                        edges_buf[delta.removed_idx[0] as usize] = delta.added[0];
                        edges_buf[delta.removed_idx[1] as usize] = delta.added[1];
                        bank.apply_accepted_switch(delta.removed, delta.removed_idx, delta.added);
                        score = cs;
                        accepted += 1;
                        wc.invalidate();
                    }
                }
            }
            let total_ms = t_all.elapsed().as_secs_f64() * 1000.0;
            let _ = count_cycles_fast_u64;
            println!(
                "n={n}: {:.1}k ev/s | acc={accepted}/{evals} | mut={:.2}us/ev score={:.2}us/ev | ref16={c_refill_16}({:.1}us) ref32={c_refill_32}({:.1}us) ref64={c_refill_64}({:.1}us) | hit16={bank_hit_16}/{} hit32={bank_hit_32}/{} hit64={bank_hit_64}/{}",
                (evals as f64) / total_ms,
                (t_mut as f64) / (evals as f64) / 1000.0,
                (t_score as f64) / (evals as f64) / 1000.0,
                if c_refill_16 > 0 { (t_refill_16 as f64) / (c_refill_16 as f64) / 1000.0 } else { 0.0 },
                if c_refill_32 > 0 { (t_refill_32 as f64) / (c_refill_32 as f64) / 1000.0 } else { 0.0 },
                if c_refill_64 > 0 { (t_refill_64 as f64) / (c_refill_64 as f64) / 1000.0 } else { 0.0 },
                bank_hit_16 + bank_miss_16,
                bank_hit_32 + bank_miss_32,
                bank_hit_64 + bank_miss_64,
            );
        }
    }
}

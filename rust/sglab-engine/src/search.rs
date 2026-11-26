//! Native Rust micro-batch search engine (SA, ILS-tabu, random-restart)
//! with specialized L1-resident u64 loop (n <= 64), O(1) TabuRing, cached edge
//! list, zero-allocation scoring, and lock-free multi-threaded execution.

use std::thread;
use std::time::Instant;

use crate::bank::CycleBank64;
use crate::cycles::{
    Cutoff, DfsScratch, ScoreResult, score_graph_delta_u64, score_graph_fast, score_graph_fast_u64,
};
use crate::graph::{BitGraph, BitGraph64, Edge, zobrist_edge, zobrist_edge64};
use crate::mutation::{
    GraphMode, MutationDelta, SeedStyle, WitnessCache, generate_seed,
    generate_two_block_ducoffe_seed, mutate, mutate_u64,
};
use crate::rng::Rng;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Algorithm {
    SimulatedAnnealing,
    IteratedLocalSearchTabu,
    RandomRestart,
}

impl Algorithm {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "simulated_annealing" | "sa" => Ok(Self::SimulatedAnnealing),
            "iterated_local_search_tabu" | "iterated_local_search" | "ils" => {
                Ok(Self::IteratedLocalSearchTabu)
            }
            "random_restart" => Ok(Self::RandomRestart),
            _ => Err(format!("unsupported algorithm: {s}")),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::SimulatedAnnealing => "simulated_annealing",
            Self::IteratedLocalSearchTabu => "iterated_local_search_tabu",
            Self::RandomRestart => "random_restart",
        }
    }
}

#[derive(Clone, Debug)]
pub struct SearchParams {
    pub order: usize,
    pub mode: GraphMode,
    pub seed_style: SeedStyle,
    pub algorithm: Algorithm,
    pub evaluations_per_worker: usize,
    pub witness_cap: u32,
    pub adaptive_cap_max: u32,
    pub node_budget: u32,
    pub targeted_prob: f64,
    pub temperature: f64,
    pub cooling: f64,
    pub restart_threshold: usize,
    pub tabu_tenure: usize,
    pub perturbation_interval: usize,
    pub initial_graph: Option<BitGraph>,
    pub max_wall_seconds: Option<f64>,
}

impl SearchParams {
    pub fn default_node_budget(witness_cap: u32) -> u32 {
        (witness_cap.saturating_mul(1_024)).min(50_000).max(4_096)
    }
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct LaneSummary {
    pub seed: u64,
    pub evaluated: usize,
    pub accepted: usize,
    pub improvements: usize,
    pub cutoffs: usize,
    pub effective_cap: u32,
    pub wall_seconds: f64,
    pub final_graph: BitGraph,
    pub final_score: ScoreResult,
    pub best_graph: BitGraph,
    pub best_score: ScoreResult,
}

/// Flat zero-SipHash O(1) tabu ring indexed directly by Zobrist u128 key.
struct TabuRing {
    capacity: usize,
    ring: Vec<u128>,
    ring_head: usize,
    ring_len: usize,
    // Open-addressed table: (key, refcount). Key 0 is mapped to 1 so 0 means empty.
    table: Vec<(u128, u32)>,
    mask: usize,
}

impl TabuRing {
    fn new(capacity: usize) -> Self {
        let cap = capacity.max(1);
        let table_len = (cap * 4).next_power_of_two().max(16);
        Self {
            capacity: cap,
            ring: vec![0u128; cap],
            ring_head: 0,
            ring_len: 0,
            table: vec![(0u128, 0u32); table_len],
            mask: table_len - 1,
        }
    }

    #[inline]
    fn norm(key: u128) -> u128 {
        if key == 0 { 1 } else { key }
    }

    #[inline]
    fn contains(&self, key: u128) -> bool {
        let k = Self::norm(key);
        let mut idx = (k as usize) & self.mask;
        loop {
            let (slot_k, cnt) = self.table[idx];
            if slot_k == 0 {
                return false;
            }
            if slot_k == k {
                return cnt > 0;
            }
            idx = (idx + 1) & self.mask;
        }
    }

    #[inline]
    fn inc(&mut self, k: u128) {
        let mut idx = (k as usize) & self.mask;
        loop {
            let (slot_k, cnt) = self.table[idx];
            if slot_k == 0 {
                self.table[idx] = (k, 1);
                return;
            }
            if slot_k == k {
                self.table[idx].1 = cnt + 1;
                return;
            }
            idx = (idx + 1) & self.mask;
        }
    }

    #[inline]
    fn dec(&mut self, k: u128) {
        let mut idx = (k as usize) & self.mask;
        loop {
            let (slot_k, cnt) = self.table[idx];
            if slot_k == 0 {
                return;
            }
            if slot_k == k {
                if cnt > 1 {
                    self.table[idx].1 = cnt - 1;
                    return;
                }
                // Backward-shift deletion: zero tombstones ever!
                let mut hole = idx;
                let mut next = (hole + 1) & self.mask;
                loop {
                    let (nk, nc) = self.table[next];
                    if nk == 0 {
                        self.table[hole] = (0, 0);
                        return;
                    }
                    let natural = (nk as usize) & self.mask;
                    let dist_hole = hole.wrapping_sub(natural) & self.mask;
                    let dist_next = next.wrapping_sub(natural) & self.mask;
                    if dist_hole < dist_next {
                        self.table[hole] = (nk, nc);
                        hole = next;
                    }
                    next = (next + 1) & self.mask;
                }
            }
            idx = (idx + 1) & self.mask;
        }
    }

    #[inline]
    fn push(&mut self, key: u128) {
        let k = Self::norm(key);
        if self.ring_len == self.capacity {
            let old = self.ring[self.ring_head];
            self.dec(old);
            self.ring[self.ring_head] = k;
            self.ring_head += 1;
            if self.ring_head == self.capacity {
                self.ring_head = 0;
            }
        } else {
            let pos = (self.ring_head + self.ring_len) % self.capacity;
            self.ring[pos] = k;
            self.ring_len += 1;
        }
        self.inc(k);
    }
}

/// Flat zero-SipHash O(1) tabu ring indexed directly by Zobrist u64 key (n <= 64).
struct TabuRing64 {
    capacity: usize,
    ring: Vec<u64>,
    ring_head: usize,
    ring_len: usize,
    table: Vec<(u64, u32)>,
    mask: usize,
}

impl TabuRing64 {
    fn new(capacity: usize) -> Self {
        let cap = capacity.max(1);
        let table_len = (cap * 4).next_power_of_two().max(16);
        Self {
            capacity: cap,
            ring: vec![0u64; cap],
            ring_head: 0,
            ring_len: 0,
            table: vec![(0u64, 0u32); table_len],
            mask: table_len - 1,
        }
    }

    #[inline]
    fn norm(key: u64) -> u64 {
        if key == 0 { 1 } else { key }
    }

    #[inline]
    fn contains(&self, key: u64) -> bool {
        let k = Self::norm(key);
        let mut idx = (k as usize) & self.mask;
        loop {
            let (slot_k, cnt) = self.table[idx];
            if slot_k == 0 {
                return false;
            }
            if slot_k == k {
                return cnt > 0;
            }
            idx = (idx + 1) & self.mask;
        }
    }

    #[inline]
    fn inc(&mut self, k: u64) {
        let mut idx = (k as usize) & self.mask;
        loop {
            let (slot_k, cnt) = self.table[idx];
            if slot_k == 0 {
                self.table[idx] = (k, 1);
                return;
            }
            if slot_k == k {
                self.table[idx].1 = cnt + 1;
                return;
            }
            idx = (idx + 1) & self.mask;
        }
    }

    #[inline]
    fn dec(&mut self, k: u64) {
        let mut idx = (k as usize) & self.mask;
        loop {
            let (slot_k, cnt) = self.table[idx];
            if slot_k == 0 {
                return;
            }
            if slot_k == k {
                if cnt > 1 {
                    self.table[idx].1 = cnt - 1;
                    return;
                }
                let mut hole = idx;
                let mut next = (hole + 1) & self.mask;
                loop {
                    let (nk, nc) = self.table[next];
                    if nk == 0 {
                        self.table[hole] = (0, 0);
                        return;
                    }
                    let natural = (nk as usize) & self.mask;
                    let dist_hole = hole.wrapping_sub(natural) & self.mask;
                    let dist_next = next.wrapping_sub(natural) & self.mask;
                    if dist_hole < dist_next {
                        self.table[hole] = (nk, nc);
                        hole = next;
                    }
                    next = (next + 1) & self.mask;
                }
            }
            idx = (idx + 1) & self.mask;
        }
    }

    #[inline]
    fn push(&mut self, key: u64) {
        let k = Self::norm(key);
        if self.ring_len == self.capacity {
            let old = self.ring[self.ring_head];
            self.dec(old);
            self.ring[self.ring_head] = k;
            self.ring_head += 1;
            if self.ring_head == self.capacity {
                self.ring_head = 0;
            }
        } else {
            let pos = (self.ring_head + self.ring_len) % self.capacity;
            self.ring[pos] = k;
            self.ring_len += 1;
        }
        self.inc(k);
    }
}

#[inline]
fn patch_edges_in_place(edges_buf: &mut Vec<Edge>, delta: &MutationDelta) {
    if delta.removed_count == 2 && delta.added_count == 2 {
        let i0 = delta.removed_idx[0] as usize;
        let i1 = delta.removed_idx[1] as usize;
        if i0 < edges_buf.len() && i1 < edges_buf.len() {
            edges_buf[i0] = delta.added[0];
            edges_buf[i1] = delta.added[1];
            return;
        }
        let r0 = delta.removed[0];
        let r1 = delta.removed[1];
        let mut replaced = 0u8;
        for e in edges_buf.iter_mut() {
            if *e == r0 {
                *e = delta.added[0];
                replaced += 1;
                if replaced == 2 {
                    return;
                }
            } else if *e == r1 {
                *e = delta.added[1];
                replaced += 1;
                if replaced == 2 {
                    return;
                }
            }
        }
    } else if delta.removed_count == 0 && delta.added_count == 1 {
        edges_buf.push(delta.added[0]);
    } else if delta.removed_count == 1 && delta.added_count == 0 {
        let i0 = delta.removed_idx[0] as usize;
        if i0 < edges_buf.len() && edges_buf[i0] == delta.removed[0] {
            edges_buf.swap_remove(i0);
            return;
        }
        if let Some(pos) = edges_buf.iter().position(|&e| e == delta.removed[0]) {
            edges_buf.swap_remove(pos);
        }
    }
}

#[inline]
fn update_key(mut key: u128, delta: &MutationDelta) -> u128 {
    for i in 0..(delta.removed_count as usize) {
        key ^= zobrist_edge(delta.removed[i]);
    }
    for i in 0..(delta.added_count as usize) {
        key ^= zobrist_edge(delta.added[i]);
    }
    key
}

#[inline]
fn update_key64(mut key: u64, delta: &MutationDelta) -> u64 {
    for i in 0..(delta.removed_count as usize) {
        key ^= zobrist_edge64(delta.removed[i]);
    }
    for i in 0..(delta.added_count as usize) {
        key ^= zobrist_edge64(delta.added[i]);
    }
    key
}

fn make_lane_seed(
    rng: &mut Rng,
    params: &SearchParams,
    use_two_block: bool,
) -> Result<(BitGraph, u64), String> {
    if use_two_block {
        generate_two_block_ducoffe_seed(rng, params.order)
    } else {
        Ok((generate_seed(rng, params.order, params.mode)?, 0u64))
    }
}

fn lane_uses_two_block(params: &SearchParams, worker_idx: usize) -> bool {
    params.initial_graph.is_none()
        && params.mode == GraphMode::MinimalStructureMixedDegree
        && match params.seed_style {
            SeedStyle::TwoBlock => true,
            SeedStyle::Mixed => (worker_idx & 1) == 0,
            SeedStyle::Random => false,
        }
}

fn run_lane_u64(params: &SearchParams, seed: u64, worker_idx: usize) -> Result<LaneSummary, String> {
    let started = Instant::now();
    let mut rng = Rng::new(seed);
    let mut scratch = DfsScratch::new();
    let mut witness_cache = WitnessCache::new();
    let mut edges_buf: Vec<Edge> = Vec::with_capacity(params.order * 3);
    let mut cycle_bank = CycleBank64::new(seed);
    let use_two_block = lane_uses_two_block(params, worker_idx);

    let (init_g, mut block1_inner_mask) = match params.initial_graph {
        Some(g) => (BitGraph64::from_graph(&g), 0u64),
        None => {
            let (g, mask) = make_lane_seed(&mut rng, params, use_two_block)?;
            (BitGraph64::from_graph(&g), mask)
        }
    };
    let mut active_cap = params.witness_cap;
    let mut active_budget = params.node_budget;
    let mut graph = init_g;
    graph.collect_edges(&mut edges_buf);
    cycle_bank.reset_for_graph(&edges_buf);
    let mut key = graph.zobrist_key64();
    let mut score = score_graph_fast_u64(
        &graph,
        active_cap,
        active_budget,
        None,
        &mut scratch,
    )
    .expect("initial score has no cutoff");

    let mut best_graph = graph;
    let mut best_score = score;

    let mut tabu = TabuRing64::new(params.tabu_tenure);
    tabu.push(key);

    let mut evaluated = 0usize;
    let mut accepted = 0usize;
    let mut improvements = 0usize;
    let mut cutoffs = 0usize;
    let mut stagnant_evals = 0usize;
    let mut sa_temp = params.temperature;
    let threshold = params.restart_threshold.max(1);

    while evaluated < params.evaluations_per_worker {
        if let Some(limit_s) = params.max_wall_seconds {
            if (evaluated & 63) == 0 && started.elapsed().as_secs_f64() >= limit_s {
                break;
            }
        }
        evaluated += 1;

        if params.algorithm == Algorithm::RandomRestart {
            let (seed_g, mask) = make_lane_seed(&mut rng, params, use_two_block)?;
            let cand = BitGraph64::from_graph(&seed_g);
            block1_inner_mask = mask;
            let cand_score = score_graph_fast_u64(
                &cand,
                active_cap,
                active_budget,
                None,
                &mut scratch,
            )
            .expect("random restart has no cutoff");
            accepted += 1;
            if cand_score.ordering_key() < best_score.ordering_key() {
                best_graph = cand;
                best_score = cand_score;
                improvements += 1;
            }
            graph = cand;
            score = cand_score;
            continue;
        }

        if params.algorithm == Algorithm::SimulatedAnnealing
            && params.restart_threshold > 0
            && evaluated % params.restart_threshold == 0
        {
            let (seed_g, mask) = make_lane_seed(&mut rng, params, use_two_block)?;
            graph = BitGraph64::from_graph(&seed_g);
            block1_inner_mask = mask;
            graph.collect_edges(&mut edges_buf);
            cycle_bank.reset_for_graph(&edges_buf);
            key = graph.zobrist_key64();
            score = score_graph_fast_u64(
                &graph,
                active_cap,
                active_budget,
                None,
                &mut scratch,
            )
            .expect("reseed has no cutoff");
            witness_cache.invalidate();
            sa_temp = params.temperature;
        }

        if params.adaptive_cap_max > active_cap
            && (evaluated & 255) == 0
            && score.has_saturated_length(active_cap)
            && (score.c4_c8_zero() || stagnant_evals >= 4_000)
        {
            active_cap = active_cap.saturating_mul(2).min(params.adaptive_cap_max);
            active_budget = active_budget.max(
                SearchParams::default_node_budget(active_cap)
                    .max(active_cap.saturating_mul(512)),
            );
            score = score_graph_fast_u64(
                &graph,
                active_cap,
                active_budget,
                None,
                &mut scratch,
            )
            .expect("adaptive re-score has no cutoff");
            best_score = score_graph_fast_u64(
                &best_graph,
                active_cap,
                active_budget,
                None,
                &mut scratch,
            )
            .expect("adaptive best re-score has no cutoff");
            if score.ordering_key() < best_score.ordering_key() {
                best_graph = graph;
                best_score = score;
            }
            stagnant_evals = 0;
        }

        let targeted = params.targeted_prob > 0.0 && rng.next_f64() < params.targeted_prob;
        let (mut cand, delta) = mutate_u64(
            &graph,
            &edges_buf,
            &mut rng,
            params.mode,
            targeted,
            score.nonzero_len_mask(),
            block1_inner_mask,
            Some(&cycle_bank),
            &mut witness_cache,
            &mut scratch,
        );
        if !delta.changed {
            continue;
        }

        let cand_key = update_key64(key, &delta);
        let is_tabu = params.algorithm == Algorithm::IteratedLocalSearchTabu
            && tabu.contains(cand_key);
        let cutoff = if params.algorithm == Algorithm::IteratedLocalSearchTabu {
            let perturb = params.perturbation_interval.max(1);
            if evaluated % perturb == 0 {
                None
            } else if is_tabu {
                Some(Cutoff {
                    total: best_score.total,
                    weighted: best_score.weighted_penalty,
                    simplicity: best_score.simplicity,
                    inclusive: true,
                })
            } else {
                Some(Cutoff {
                    total: score.total,
                    weighted: score.weighted_penalty,
                    simplicity: score.simplicity,
                    inclusive: false,
                })
            }
        } else {
            None
        };

        let is_two_edge_switch = delta.removed_count == 2 && delta.added_count == 2;
        let cand_simplicity =
            (edges_buf.len() + delta.added_count as usize - delta.removed_count as usize) as u32;
        let Some(cand_score) = score_graph_delta_u64(
            &mut graph,
            &score,
            &mut cand,
            is_two_edge_switch,
            delta.removed,
            delta.removed_idx,
            delta.added,
            cand_simplicity,
            active_cap,
            active_budget,
            cutoff,
            &mut scratch,
            &mut cycle_bank,
        ) else {
            cutoffs += 1;
            stagnant_evals += 1;
            continue;
        };

        let is_global_record = cand_score.ordering_key() < best_score.ordering_key();
        let accept = match params.algorithm {
            Algorithm::SimulatedAnnealing => {
                if evaluated % threshold == 0 {
                    sa_temp = params.temperature;
                } else {
                    sa_temp *= params.cooling;
                }
                let temp = sa_temp.max(0.001);
                let delta_s = cand_score.scalar() - score.scalar();
                delta_s <= 0.0 || rng.next_f64() < (-delta_s.min(700.0) / temp).exp()
            }
            Algorithm::IteratedLocalSearchTabu => {
                let perturb = params.perturbation_interval.max(1);
                let ok = (!is_tabu && cand_score.ordering_key() <= score.ordering_key())
                    || (evaluated % perturb == 0);
                if ok {
                    tabu.push(cand_key);
                }
                ok
            }
            Algorithm::RandomRestart => true,
        };

        if is_global_record {
            best_graph = cand;
            best_score = cand_score;
            improvements += 1;
            stagnant_evals = 0;
        } else {
            stagnant_evals += 1;
        }
        if accept {
            graph = cand;
            patch_edges_in_place(&mut edges_buf, &delta);
            if is_two_edge_switch {
                cycle_bank.apply_accepted_switch(delta.removed, delta.removed_idx, delta.added);
            } else {
                cycle_bank.reset_for_graph(&edges_buf);
            }
            key = cand_key;
            score = cand_score;
            accepted += 1;
            witness_cache.invalidate();
        }
    }

    Ok(LaneSummary {
        seed,
        evaluated,
        accepted,
        improvements,
        cutoffs,
        effective_cap: active_cap,
        wall_seconds: started.elapsed().as_secs_f64(),
        final_graph: graph.to_graph(),
        final_score: score,
        best_graph: best_graph.to_graph(),
        best_score,
    })
}

pub fn run_lane(params: &SearchParams, seed: u64, worker_idx: usize) -> Result<LaneSummary, String> {
    if params.order <= 64 {
        return run_lane_u64(params, seed, worker_idx);
    }

    let started = Instant::now();
    let mut rng = Rng::new(seed);
    let mut scratch = DfsScratch::new();
    let mut witness_cache = WitnessCache::new();
    let mut edges_buf: Vec<Edge> = Vec::with_capacity(params.order * 3);
    let use_two_block = lane_uses_two_block(params, worker_idx);

    let mut graph = match params.initial_graph {
        Some(g) => g,
        None => make_lane_seed(&mut rng, params, use_two_block)?.0,
    };
    graph.collect_edges(&mut edges_buf);
    let mut key = graph.zobrist_key();
    let mut score = score_graph_fast(
        &graph,
        params.witness_cap,
        params.node_budget,
        None,
        &mut scratch,
    )
    .expect("initial score has no cutoff");

    let mut best_graph = graph;
    let mut best_score = score;

    let mut tabu = TabuRing::new(params.tabu_tenure);
    tabu.push(key);

    let mut evaluated = 0usize;
    let mut accepted = 0usize;
    let mut improvements = 0usize;
    let mut cutoffs = 0usize;
    let mut sa_temp = params.temperature;
    let threshold = params.restart_threshold.max(1);

    while evaluated < params.evaluations_per_worker {
        if let Some(limit_s) = params.max_wall_seconds {
            if (evaluated & 31) == 0 && started.elapsed().as_secs_f64() >= limit_s {
                break;
            }
        }
        evaluated += 1;

        if params.algorithm == Algorithm::RandomRestart {
            let cand = generate_seed(&mut rng, params.order, params.mode)?;
            let cand_score = score_graph_fast(
                &cand,
                params.witness_cap,
                params.node_budget,
                None,
                &mut scratch,
            )
            .expect("random restart has no cutoff");
            accepted += 1;
            if cand_score.ordering_key() < best_score.ordering_key() {
                best_graph = cand;
                best_score = cand_score;
                improvements += 1;
            }
            graph = cand;
            score = cand_score;
            continue;
        }

        if params.algorithm == Algorithm::SimulatedAnnealing
            && params.restart_threshold > 0
            && evaluated % params.restart_threshold == 0
        {
            graph = generate_seed(&mut rng, params.order, params.mode)?;
            graph.collect_edges(&mut edges_buf);
            key = graph.zobrist_key();
            score = score_graph_fast(
                &graph,
                params.witness_cap,
                params.node_budget,
                None,
                &mut scratch,
            )
            .expect("reseed has no cutoff");
            witness_cache.invalidate();
            sa_temp = params.temperature;
        }

        let targeted = params.targeted_prob > 0.0 && rng.next_f64() < params.targeted_prob;
        let (cand, delta) = mutate(
            &graph,
            &edges_buf,
            &mut rng,
            params.mode,
            targeted,
            &mut witness_cache,
            &mut scratch,
        );
        if !delta.changed {
            continue;
        }

        let cand_key = update_key(key, &delta);
        let cutoff = if params.algorithm == Algorithm::IteratedLocalSearchTabu {
            let perturb = params.perturbation_interval.max(1);
            if evaluated % perturb == 0 {
                None
            } else if tabu.contains(cand_key) {
                Some(Cutoff {
                    total: best_score.total,
                    weighted: best_score.weighted_penalty,
                    simplicity: best_score.simplicity,
                    inclusive: true,
                })
            } else {
                Some(Cutoff {
                    total: score.total,
                    weighted: score.weighted_penalty,
                    simplicity: score.simplicity,
                    inclusive: false,
                })
            }
        } else {
            None
        };

        let Some(cand_score) = score_graph_fast(
            &cand,
            params.witness_cap,
            params.node_budget,
            cutoff,
            &mut scratch,
        ) else {
            cutoffs += 1;
            continue;
        };

        let is_global_record = cand_score.ordering_key() < best_score.ordering_key();
        let accept = match params.algorithm {
            Algorithm::SimulatedAnnealing => {
                if evaluated % threshold == 0 {
                    sa_temp = params.temperature;
                } else {
                    sa_temp *= params.cooling;
                }
                let temp = sa_temp.max(0.001);
                let delta_s = cand_score.scalar() - score.scalar();
                delta_s <= 0.0 || rng.next_f64() < (-delta_s.min(700.0) / temp).exp()
            }
            Algorithm::IteratedLocalSearchTabu => {
                let perturb = params.perturbation_interval.max(1);
                let ok = (!tabu.contains(cand_key)
                    && cand_score.ordering_key() <= score.ordering_key())
                    || (evaluated % perturb == 0);
                if ok {
                    tabu.push(cand_key);
                }
                ok
            }
            Algorithm::RandomRestart => true,
        };

        if is_global_record {
            best_graph = cand;
            best_score = cand_score;
            improvements += 1;
        }
        if accept {
            graph = cand;
            patch_edges_in_place(&mut edges_buf, &delta);
            key = cand_key;
            score = cand_score;
            accepted += 1;
            witness_cache.invalidate();
        }
    }

    Ok(LaneSummary {
        seed,
        evaluated,
        accepted,
        improvements,
        cutoffs,
        effective_cap: params.witness_cap,
        wall_seconds: started.elapsed().as_secs_f64(),
        final_graph: graph,
        final_score: score,
        best_graph,
        best_score,
    })
}

pub fn run_parallel(
    params: &SearchParams,
    workers: usize,
    base_seed: u64,
) -> Result<(Vec<LaneSummary>, f64), String> {
    let n_workers = workers.max(1);
    let started = Instant::now();
    if n_workers == 1 {
        let one = run_lane(params, base_seed, 0)?;
        return Ok((vec![one], started.elapsed().as_secs_f64()));
    }

    let results: Vec<Result<LaneSummary, String>> = thread::scope(|scope| {
        let handles: Vec<_> = (0..n_workers)
            .map(|i| {
                let seed = base_seed.wrapping_add(i as u64);
                scope.spawn(move || run_lane(params, seed, i))
            })
            .collect();
        handles
            .into_iter()
            .map(|h| h.join().expect("worker thread panicked"))
            .collect()
    });

    let mut out = Vec::with_capacity(n_workers);
    for r in results {
        out.push(r?);
    }
    let max_cap = out
        .iter()
        .map(|l| l.effective_cap)
        .max()
        .unwrap_or(params.witness_cap);
    if out.iter().any(|l| l.effective_cap < max_cap) {
        let max_budget = params
            .node_budget
            .max(SearchParams::default_node_budget(max_cap).max(max_cap.saturating_mul(512)));
        let mut scratch = DfsScratch::new();
        for lane in &mut out {
            if lane.effective_cap < max_cap {
                lane.best_score = score_graph_fast(
                    &lane.best_graph,
                    max_cap,
                    max_budget,
                    None,
                    &mut scratch,
                )
                .expect("reconcile cap score");
                lane.effective_cap = max_cap;
            }
        }
    }
    Ok((out, started.elapsed().as_secs_f64()))
}

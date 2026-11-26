//! Seed generators and zero-allocation mutation operators matching
//! `sglab.targets.erdos_gyarfas` (including Ducoffe-Dumitru structural prior).

use crate::bank::CycleBank64;
use crate::cycles::{
    DfsScratch, StackWitnesses, find_witness_edge_groups, find_witness_edge_groups_u64,
};
use crate::graph::{BitGraph, BitGraph64, Edge, normalize_edge};
use crate::rng::Rng;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GraphMode {
    CubicFirst,
    MinimalStructureMixedDegree,
    UnrestrictedMinDegree3,
}

impl GraphMode {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "cubic_first" | "connected_cubic" => Ok(Self::CubicFirst),
            "minimal_structure_mixed_degree" | "predominantly_cubic" => {
                Ok(Self::MinimalStructureMixedDegree)
            }
            "unrestricted_min_degree_3" => Ok(Self::UnrestrictedMinDegree3),
            _ => Err(format!("unsupported mode: {s}")),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::CubicFirst => "cubic_first",
            Self::MinimalStructureMixedDegree => "minimal_structure_mixed_degree",
            Self::UnrestrictedMinDegree3 => "unrestricted_min_degree_3",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SeedStyle {
    Random,
    TwoBlock,
    Mixed,
}

impl SeedStyle {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "random" => Ok(Self::Random),
            "two_block" | "two-block" | "ducoffe_two_block" => Ok(Self::TwoBlock),
            "mixed" => Ok(Self::Mixed),
            _ => Err(format!("unsupported seed style: {s}")),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Random => "random",
            Self::TwoBlock => "two_block",
            Self::Mixed => "mixed",
        }
    }
}

/// Build one 2-connected block of size `verts.len() >= 6` where `verts[0]` is
/// the shared cut-vertex (degree 2 inside this block), internal vertices have
/// degree 3, and if `verts.len()` is even one internal vertex not adjacent to
/// `verts[0]` has degree 4 so the block degree sum is even.
fn fill_biconnected_block(rng: &mut Rng, g: &mut BitGraph, verts: &[usize]) -> bool {
    let k = verts.len();
    if k < 6 {
        return false;
    }
    let mut ring = Vec::with_capacity(k);
    ring.push(verts[0]);
    let mut internal: Vec<usize> = verts[1..].to_vec();
    let mut stubs = Vec::with_capacity(k + 2);

    for _attempt in 0..256 {
        ring.truncate(1);
        rng.shuffle(&mut internal);
        ring.extend_from_slice(&internal);

        // Clear any edges from previous failed attempt on this block.
        for &u in &ring {
            for &v in &ring {
                if u < v && g.has_edge(u, v) {
                    g.remove_edge(u, v);
                }
            }
        }

        // Hamiltonian cycle on the block: guarantees 2-connectivity and gives
        // cut-vertex `ring[0]` exact degree 2 (adjacent only to degree-3 vertices).
        for idx in 0..k {
            g.add_edge(ring[idx], ring[(idx + 1) % k]);
        }

        stubs.clear();
        let high_pos = if k % 2 == 0 {
            Some(2 + rng.gen_range(k - 3))
        } else {
            None
        };
        for pos in 1..k {
            stubs.push(ring[pos]);
            if Some(pos) == high_pos {
                stubs.push(ring[pos]);
            }
        }
        rng.shuffle(&mut stubs);

        let mut ok = true;
        while let Some(u) = stubs.pop() {
            let mut chosen_idx = None;
            let mut seen_valid = 0usize;
            for (idx, &v) in stubs.iter().enumerate() {
                if u != v && !g.has_edge(u, v) {
                    seen_valid += 1;
                    if rng.gen_range(seen_valid) == 0 {
                        chosen_idx = Some(idx);
                    }
                }
            }
            if let Some(idx) = chosen_idx {
                let v = stubs.swap_remove(idx);
                g.add_edge(u, v);
            } else {
                ok = false;
                break;
            }
        }
        if ok {
            return true;
        }
    }
    false
}

/// Generate a Ducoffe-Dumitru legal 2-block 1-clique-sum seed of order `n`.
/// For `11 <= n <= 61`, both blocks have size `<= 31`, which mathematically
/// guarantees zero 32-cycles (`C32 == 0`) while keeping zero bridges, at most
/// 3 independent degree-4 vertices, and strictly > 2/3 degree-3 vertices.
/// Returns `(graph, block1_inner_mask)` where `block1_inner_mask` marks the
/// internal (non-cut) vertices of block 1 when `n <= 64` (0 otherwise).
pub fn generate_two_block_ducoffe_seed(rng: &mut Rng, n: usize) -> Result<(BitGraph, u64), String> {
    if n < 11 {
        let g = generate_seed(rng, n, GraphMode::MinimalStructureMixedDegree)?;
        return Ok((g, 0));
    }
    if n > 128 {
        return Err("order must be between 4 and 128".to_string());
    }

    let half = (n + 1) / 2;
    let max_block = if n <= 61 { 31 } else { (n + 1) - 6 };
    let lo = half
        .saturating_sub(2)
        .max(6)
        .max((n + 1).saturating_sub(max_block));
    let hi = (half + 2).min(max_block).min((n + 1) - 6);
    let n1 = if lo < hi {
        lo + rng.gen_range(hi - lo + 1)
    } else {
        lo
    };

    let mut perm: Vec<usize> = (0..n).collect();
    for _attempt in 0..64 {
        rng.shuffle(&mut perm);
        let cut = perm[0];
        let mut block1 = Vec::with_capacity(n1);
        block1.push(cut);
        block1.extend_from_slice(&perm[1..n1]);

        let mut block2 = Vec::with_capacity(n + 1 - n1);
        block2.push(cut);
        block2.extend_from_slice(&perm[n1..n]);

        let mut g = BitGraph::empty(n);
        if fill_biconnected_block(rng, &mut g, &block1)
            && fill_biconnected_block(rng, &mut g, &block2)
            && g.is_connected()
            && g.minimal_structure_valid()
        {
            let mut b1_mask = 0u64;
            if n <= 64 {
                for &v in &perm[1..n1] {
                    b1_mask |= 1u64 << v;
                }
            }
            return Ok((g, b1_mask));
        }
    }
    Err("failed to generate 2-block Ducoffe-Dumitru seed within retry budget".to_string())
}

pub fn generate_seed(rng: &mut Rng, n: usize, mode: GraphMode) -> Result<BitGraph, String> {
    if !(4..=128).contains(&n) {
        return Err("order must be between 4 and 128".to_string());
    }
    if mode == GraphMode::CubicFirst && n % 2 != 0 {
        return Err("cubic_first requires an even order".to_string());
    }
    if mode == GraphMode::MinimalStructureMixedDegree && n < 5 {
        return Err("minimal_structure_mixed_degree requires order >= 5".to_string());
    }
    let effective = if mode == GraphMode::UnrestrictedMinDegree3 && n % 2 != 0 {
        GraphMode::MinimalStructureMixedDegree
    } else {
        mode
    };

    match effective {
        GraphMode::MinimalStructureMixedDegree => {
            let (high_count, high_deg) = if n == 6 {
                (1usize, 5usize)
            } else {
                let mut hc = if n % 2 == 0 { 2usize } else { 1usize };
                let sum_deg = 4 * hc + 3 * (n - hc);
                if sum_deg % 2 != 0 {
                    hc += 1;
                }
                (hc, 4usize)
            };
            let mut stubs = Vec::with_capacity(4 * n + 2);
            for _attempt in 0..2_000 {
                stubs.clear();
                for v in 0..n {
                    let deg = if v < high_count { high_deg } else { 3 };
                    for _ in 0..deg {
                        stubs.push(v);
                    }
                }
                rng.shuffle(&mut stubs);
                let mut g = BitGraph::empty(n);
                let mut valid = true;
                while let Some(u) = stubs.pop() {
                    let mut chosen_idx = None;
                    let mut seen_valid = 0usize;
                    for (idx, &v) in stubs.iter().enumerate() {
                        if u != v
                            && !g.has_edge(u, v)
                            && !(u < high_count && v < high_count)
                        {
                            seen_valid += 1;
                            if rng.gen_range(seen_valid) == 0 {
                                chosen_idx = Some(idx);
                            }
                        }
                    }
                    if let Some(idx) = chosen_idx {
                        let v = stubs.swap_remove(idx);
                        g.add_edge(u, v);
                    } else {
                        valid = false;
                        break;
                    }
                }
                if valid && g.is_connected() && g.minimal_structure_valid() {
                    return Ok(g);
                }
            }
            Err("failed to generate mixed-degree seed within retry budget".to_string())
        }
        GraphMode::CubicFirst | GraphMode::UnrestrictedMinDegree3 => {
            let mut vertices: Vec<usize> = (0..n).collect();
            for _attempt in 0..200 {
                let mut g = BitGraph::empty(n);
                for u in 0..n {
                    g.add_edge(u, (u + 1) % n);
                }
                vertices.clear();
                vertices.extend(0..n);
                rng.shuffle(&mut vertices);
                let mut matched = 0usize;
                while let Some(u) = vertices.pop() {
                    let mut chosen_idx = None;
                    let mut seen_valid = 0usize;
                    for (idx, &v) in vertices.iter().enumerate() {
                        if !g.has_edge(u, v) {
                            seen_valid += 1;
                            if rng.gen_range(seen_valid) == 0 {
                                chosen_idx = Some(idx);
                            }
                        }
                    }
                    if let Some(idx) = chosen_idx {
                        let v = vertices.swap_remove(idx);
                        g.add_edge(u, v);
                        matched += 1;
                    } else {
                        break;
                    }
                }
                if vertices.is_empty() && matched == n / 2 {
                    return Ok(g);
                }
            }
            Err("failed to generate cubic seed within retry budget".to_string())
        }
    }
}

pub struct WitnessCache {
    pub valid: bool,
    pub data: StackWitnesses,
}

impl WitnessCache {
    pub fn new() -> Self {
        Self {
            valid: false,
            data: StackWitnesses::new(),
        }
    }

    #[inline]
    pub fn invalidate(&mut self) {
        self.valid = false;
    }

    #[inline]
    pub fn get_or_compute(
        &mut self,
        graph: &BitGraph,
        scratch: &mut DfsScratch,
    ) -> &StackWitnesses {
        if !self.valid {
            find_witness_edge_groups(graph, 4_096, scratch, &mut self.data);
            self.valid = true;
        }
        &self.data
    }

    #[inline]
    pub fn get_or_compute_u64(
        &mut self,
        graph: &BitGraph64,
        edges: &[Edge],
        nonzero_len_mask: u8,
        bank: Option<&CycleBank64>,
        scratch: &mut DfsScratch,
    ) -> &StackWitnesses {
        if !self.valid {
            find_witness_edge_groups_u64(
                graph,
                edges,
                nonzero_len_mask,
                bank,
                4_096,
                scratch,
                &mut self.data,
            );
            self.valid = true;
        }
        &self.data
    }
}

#[derive(Clone, Copy, Debug)]
pub struct MutationDelta {
    pub changed: bool,
    pub removed_count: u8,
    pub removed: [Edge; 2],
    pub removed_idx: [u16; 2],
    pub added_count: u8,
    pub added: [Edge; 2],
}

impl MutationDelta {
    pub const NONE: Self = Self {
        changed: false,
        removed_count: 0,
        removed: [(0, 0); 2],
        removed_idx: [u16::MAX; 2],
        added_count: 0,
        added: [(0, 0); 2],
    };
}

#[inline]
fn try_two_edge_switch_u64(
    graph: &BitGraph64,
    first: Edge,
    first_idx: u16,
    second: Edge,
    second_idx: u16,
    rng: &mut Rng,
    mode: GraphMode,
) -> Option<(BitGraph64, MutationDelta)> {
    let (a, b) = (first.0 as usize, first.1 as usize);
    let (c, d) = (second.0 as usize, second.1 as usize);
    if a == c || a == d || b == c || b == d {
        return None;
    }
    let pairings = if (rng.next_u64() & 1) == 0 {
        [((a, c), (b, d)), ((a, d), (b, c))]
    } else {
        [((a, d), (b, c)), ((a, c), (b, d))]
    };
    for &((u1, v1), (u2, v2)) in &pairings {
        let e1 = normalize_edge(u1 as u8, v1 as u8);
        let e2 = normalize_edge(u2 as u8, v2 as u8);
        if e1 == e2 || graph.has_edge(u1, v1) || graph.has_edge(u2, v2) {
            continue;
        }
        let mut cand = *graph;
        cand.remove_edge(a, b);
        cand.remove_edge(c, d);
        cand.add_edge(u1, v1);
        cand.add_edge(u2, v2);
        if !cand.are_connected(a, b) {
            continue;
        }
        if mode == GraphMode::MinimalStructureMixedDegree && !cand.minimal_structure_valid() {
            continue;
        }
        return Some((
            cand,
            MutationDelta {
                changed: true,
                removed_count: 2,
                removed: [normalize_edge(first.0, first.1), normalize_edge(second.0, second.1)],
                removed_idx: [first_idx, second_idx],
                added_count: 2,
                added: [e1, e2],
            },
        ));
    }
    None
}

#[inline]
fn edge_in_block1(e: Edge, block1_inner_mask: u64) -> bool {
    (((1u64 << e.0) | (1u64 << e.1)) & block1_inner_mask) != 0
}

/// Mutate a 64-vertex graph using a pre-cached edge list (`edges_buf` is owned
/// by the lane and only rebuilt when `graph` changes).
/// When `block1_inner_mask != 0`, 2-edge switches only pair edges from the same
/// block, preserving the 2-block 1-clique-sum decomposition in O(1).
#[allow(clippy::too_many_arguments)]
pub fn mutate_u64(
    graph: &BitGraph64,
    edges: &[Edge],
    rng: &mut Rng,
    mode: GraphMode,
    targeted: bool,
    nonzero_len_mask: u8,
    block1_inner_mask: u64,
    bank: Option<&CycleBank64>,
    witness_cache: &mut WitnessCache,
    scratch: &mut DfsScratch,
) -> (BitGraph64, MutationDelta) {
    if mode == GraphMode::UnrestrictedMinDegree3 {
        if rng.next_f64() < 0.55 {
            let n = graph.n;
            for _ in 0..32 {
                let u = rng.gen_range(n);
                let v = rng.gen_range(n);
                if u != v && !graph.has_edge(u, v) {
                    let mut cand = *graph;
                    cand.add_edge(u, v);
                    let e = normalize_edge(u as u8, v as u8);
                    return (
                        cand,
                        MutationDelta {
                            changed: true,
                            removed_count: 0,
                            removed: [(0, 0); 2],
                            removed_idx: [u16::MAX; 2],
                            added_count: 1,
                            added: [e, (0, 0)],
                        },
                    );
                }
            }
        } else {
            let mut chosen = None;
            let mut seen = 0usize;
            for (idx, &e) in edges.iter().enumerate() {
                if graph.degree(e.0 as usize) > 3 && graph.degree(e.1 as usize) > 3 {
                    seen += 1;
                    if rng.gen_range(seen) == 0 {
                        chosen = Some((e, idx as u16));
                    }
                }
            }
            if let Some((e, idx)) = chosen {
                let mut cand = *graph;
                cand.remove_edge(e.0 as usize, e.1 as usize);
                if cand.is_connected() {
                    return (
                        cand,
                        MutationDelta {
                            changed: true,
                            removed_count: 1,
                            removed: [e, (0, 0)],
                            removed_idx: [idx, u16::MAX],
                            added_count: 0,
                            added: [(0, 0); 2],
                        },
                    );
                }
            }
        }
    }

    let m = edges.len();
    if m < 2 {
        return (*graph, MutationDelta::NONE);
    }

    if targeted {
        let w = witness_cache.get_or_compute_u64(graph, edges, nonzero_len_mask, bank, scratch);
        if w.count == 0 {
            return (*graph, MutationDelta::NONE);
        }
        let g_idx = rng.gen_range(w.count);
        let g_len = w.lens[g_idx] as usize;
        if g_len == 0 {
            return (*graph, MutationDelta::NONE);
        }
        let group = &w.groups[g_idx][..g_len];
        for _ in 0..64 {
            let first = group[rng.gen_range(g_len)];
            let j = rng.gen_range(m);
            let remote = edges[j];
            if block1_inner_mask != 0
                && edge_in_block1(first, block1_inner_mask)
                    != edge_in_block1(remote, block1_inner_mask)
            {
                continue;
            }
            if let Some((cand, mut delta)) =
                try_two_edge_switch_u64(graph, first, u16::MAX, remote, j as u16, rng, mode)
            {
                if let Some(pos) = edges.iter().position(|&e| e == delta.removed[0]) {
                    delta.removed_idx[0] = pos as u16;
                }
                return (cand, delta);
            }
        }
        return (*graph, MutationDelta::NONE);
    }

    for _ in 0..64 {
        let i = rng.gen_range(m);
        let mut j = rng.gen_range(m - 1);
        if j >= i {
            j += 1;
        }
        if block1_inner_mask != 0
            && edge_in_block1(edges[i], block1_inner_mask)
                != edge_in_block1(edges[j], block1_inner_mask)
        {
            continue;
        }
        if let Some(res) =
            try_two_edge_switch_u64(graph, edges[i], i as u16, edges[j], j as u16, rng, mode)
        {
            return res;
        }
    }
    (*graph, MutationDelta::NONE)
}

#[inline]
fn try_two_edge_switch(
    graph: &BitGraph,
    first: Edge,
    second: Edge,
    rng: &mut Rng,
    mode: GraphMode,
) -> Option<(BitGraph, MutationDelta)> {
    let (a, b) = (first.0 as usize, first.1 as usize);
    let (c, d) = (second.0 as usize, second.1 as usize);
    if a == c || a == d || b == c || b == d {
        return None;
    }
    let pairings = if (rng.next_u64() & 1) == 0 {
        [((a, c), (b, d)), ((a, d), (b, c))]
    } else {
        [((a, d), (b, c)), ((a, c), (b, d))]
    };
    for &((u1, v1), (u2, v2)) in &pairings {
        let e1 = normalize_edge(u1 as u8, v1 as u8);
        let e2 = normalize_edge(u2 as u8, v2 as u8);
        if e1 == e2 || graph.has_edge(u1, v1) || graph.has_edge(u2, v2) {
            continue;
        }
        let mut cand = *graph;
        cand.remove_edge(a, b);
        cand.remove_edge(c, d);
        cand.add_edge(u1, v1);
        cand.add_edge(u2, v2);
        if !cand.are_connected(a, b) {
            continue;
        }
        if mode == GraphMode::MinimalStructureMixedDegree && !cand.minimal_structure_valid() {
            continue;
        }
        return Some((
            cand,
            MutationDelta {
                changed: true,
                removed_count: 2,
                removed: [normalize_edge(first.0, first.1), normalize_edge(second.0, second.1)],
                removed_idx: [u16::MAX; 2],
                added_count: 2,
                added: [e1, e2],
            },
        ));
    }
    None
}

pub fn mutate(
    graph: &BitGraph,
    edges: &[Edge],
    rng: &mut Rng,
    mode: GraphMode,
    targeted: bool,
    witness_cache: &mut WitnessCache,
    scratch: &mut DfsScratch,
) -> (BitGraph, MutationDelta) {
    if mode == GraphMode::UnrestrictedMinDegree3 {
        if rng.next_f64() < 0.55 {
            let n = graph.n;
            for _ in 0..32 {
                let u = rng.gen_range(n);
                let v = rng.gen_range(n);
                if u != v && !graph.has_edge(u, v) {
                    let mut cand = *graph;
                    cand.add_edge(u, v);
                    let e = normalize_edge(u as u8, v as u8);
                    return (
                        cand,
                        MutationDelta {
                            changed: true,
                            removed_count: 0,
                            removed: [(0, 0); 2],
                            removed_idx: [u16::MAX; 2],
                            added_count: 1,
                            added: [e, (0, 0)],
                        },
                    );
                }
            }
        } else {
            let mut chosen = None;
            let mut seen = 0usize;
            for &e in edges {
                if graph.degree(e.0 as usize) > 3 && graph.degree(e.1 as usize) > 3 {
                    seen += 1;
                    if rng.gen_range(seen) == 0 {
                        chosen = Some(e);
                    }
                }
            }
            if let Some(e) = chosen {
                let mut cand = *graph;
                cand.remove_edge(e.0 as usize, e.1 as usize);
                if cand.is_connected() {
                    return (
                        cand,
                        MutationDelta {
                            changed: true,
                            removed_count: 1,
                            removed: [e, (0, 0)],
                            removed_idx: [u16::MAX; 2],
                            added_count: 0,
                            added: [(0, 0); 2],
                        },
                    );
                }
            }
        }
    }

    let m = edges.len();
    if m < 2 {
        return (*graph, MutationDelta::NONE);
    }

    if targeted {
        let w = witness_cache.get_or_compute(graph, scratch);
        if w.count == 0 {
            return (*graph, MutationDelta::NONE);
        }
        let g_idx = rng.gen_range(w.count);
        let g_len = w.lens[g_idx] as usize;
        if g_len == 0 {
            return (*graph, MutationDelta::NONE);
        }
        let group = &w.groups[g_idx][..g_len];
        for _ in 0..64 {
            let first = group[rng.gen_range(g_len)];
            let remote = edges[rng.gen_range(m)];
            if let Some(res) = try_two_edge_switch(graph, first, remote, rng, mode) {
                return res;
            }
        }
        return (*graph, MutationDelta::NONE);
    }

    for _ in 0..64 {
        let i = rng.gen_range(m);
        let mut j = rng.gen_range(m - 1);
        if j >= i {
            j += 1;
        }
        if let Some(res) = try_two_edge_switch(graph, edges[i], edges[j], rng, mode) {
            return res;
        }
    }
    (*graph, MutationDelta::NONE)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cycles::score_graph_fast;

    #[test]
    fn two_block_ducoffe_seed_valid_and_c32_free_up_to_61() {
        let mut rng = Rng::new(2026112601);
        let mut scratch = DfsScratch::new();
        for &n in &[11usize, 12, 20, 32, 36, 40, 44, 48, 50, 55, 60, 61, 64] {
            let (g, b1_mask) = generate_two_block_ducoffe_seed(&mut rng, n)
                .unwrap_or_else(|e| panic!("seed failed for n={n}: {e}"));
            assert!(g.is_connected(), "n={n} not connected");
            assert!(g.minimum_degree() >= 3, "n={n} min_deg < 3");
            assert!(
                g.minimal_structure_valid(),
                "n={n} failed minimal_structure_valid"
            );
            assert_ne!(b1_mask, 0, "n={n} expected non-zero block1 mask");

            let score = score_graph_fast(&g, 64, 50_000, None, &mut scratch)
                .expect("unbounded score");
            if n <= 61 {
                for &(len, cnt) in score.counts_slice() {
                    if len == 32 {
                        assert_eq!(cnt, 0, "n={n} 2-block seed unexpectedly had C32={cnt}");
                    }
                }
            }
            if n == 64 {
                for &(len, cnt) in score.counts_slice() {
                    if len == 64 {
                        assert_eq!(cnt, 0, "n=64 2-block seed unexpectedly had C64={cnt}");
                    }
                }
            }
        }
    }

    #[test]
    fn within_block_mutations_preserve_two_block_and_c32_zero() {
        let mut rng = Rng::new(2026112602);
        let mut scratch = DfsScratch::new();
        let mut wc = WitnessCache::new();
        let (init, b1_mask) = generate_two_block_ducoffe_seed(&mut rng, 50).unwrap();
        let mut g = BitGraph64::from_graph(&init);
        let mut edges = Vec::new();
        g.collect_edges(&mut edges);

        let mut accepted = 0usize;
        for step in 0..300 {
            let targeted = (step & 1) == 0;
            let (cand, delta) = mutate_u64(
                &g,
                &edges,
                &mut rng,
                GraphMode::MinimalStructureMixedDegree,
                targeted,
                0x3f,
                b1_mask,
                None,
                &mut wc,
                &mut scratch,
            );
            if delta.changed {
                assert!(cand.is_connected());
                assert!(cand.minimal_structure_valid());
                g = cand;
                g.collect_edges(&mut edges);
                wc.invalidate();
                accepted += 1;
            }
        }
        assert!(accepted >= 50, "expected >= 50 valid within-block mutations, got {accepted}");
        let score = score_graph_fast(&g.to_graph(), 64, 50_000, None, &mut scratch).unwrap();
        for &(len, cnt) in score.counts_slice() {
            if len == 32 {
                assert_eq!(cnt, 0, "within-block mutations must preserve C32==0, got {cnt}");
            }
        }
    }
}

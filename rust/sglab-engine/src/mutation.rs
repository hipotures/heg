//! Seed generators and zero-allocation mutation operators matching
//! `sglab.targets.erdos_gyarfas` (including Ducoffe-Dumitru structural prior).

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
        scratch: &mut DfsScratch,
    ) -> &StackWitnesses {
        if !self.valid {
            find_witness_edge_groups_u64(graph, 4_096, scratch, &mut self.data);
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

/// Mutate a 64-vertex graph using a pre-cached edge list (`edges_buf` is owned
/// by the lane and only rebuilt when `graph` changes).
pub fn mutate_u64(
    graph: &BitGraph64,
    edges: &[Edge],
    rng: &mut Rng,
    mode: GraphMode,
    targeted: bool,
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
        let w = witness_cache.get_or_compute_u64(graph, scratch);
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

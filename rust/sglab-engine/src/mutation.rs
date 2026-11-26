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
    SingleBlock41,
}

impl GraphMode {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "cubic_first" | "connected_cubic" => Ok(Self::CubicFirst),
            "minimal_structure_mixed_degree" | "predominantly_cubic" => {
                Ok(Self::MinimalStructureMixedDegree)
            }
            "unrestricted_min_degree_3" => Ok(Self::UnrestrictedMinDegree3),
            "single_block_41" | "conjecture_4_1" | "single_block" => Ok(Self::SingleBlock41),
            _ => Err(format!("unsupported mode: {s}")),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::CubicFirst => "cubic_first",
            Self::MinimalStructureMixedDegree => "minimal_structure_mixed_degree",
            Self::UnrestrictedMinDegree3 => "unrestricted_min_degree_3",
            Self::SingleBlock41 => "single_block_41",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SeedStyle {
    Random,
    TwoBlock,
    Mixed,
    Markstrom,
    H7Expansion,
}

impl SeedStyle {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "random" => Ok(Self::Random),
            "two_block" | "two-block" | "ducoffe_two_block" => Ok(Self::TwoBlock),
            "mixed" => Ok(Self::Mixed),
            "markstrom" | "markstrom24" | "markstrom_subdiv" => Ok(Self::Markstrom),
            "h7_expansion" | "h7" | "exoo" => Ok(Self::H7Expansion),
            _ => Err(format!("unsupported seed style: {s}")),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Random => "random",
            Self::TwoBlock => "two_block",
            Self::Mixed => "mixed",
            Self::Markstrom => "markstrom",
            Self::H7Expansion => "h7_expansion",
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

/// Exact 7-vertex 3-port gadget H7 (Exoo 2014 / Garcia 2026 Prop. 6.2):
/// ports 0 (distinguished u), 1 (v), 2 (w) have degree 2; internal 3..=6 have degree 3;
/// path lengths S(0,1)=S(0,2)={2..6}, S(1,2)={3..6}, internal cycles {3,5,6,7} (no C4, no C8).
pub const H7_EDGES: [(usize, usize); 9] = [
    (0, 3),
    (0, 4),
    (1, 3),
    (1, 5),
    (2, 4),
    (2, 6),
    (3, 5),
    (4, 6),
    (5, 6),
];

/// Build the 10-vertex Petersen cubic graph (girth 5).
pub fn build_petersen() -> BitGraph {
    let mut g = BitGraph::empty(10);
    for i in 0..5 {
        g.add_edge(i, (i + 1) % 5);
        g.add_edge(i, i + 5);
        g.add_edge(i + 5, 5 + ((i + 2) % 5));
    }
    g
}

/// Build the 12-vertex cubic graph obtained by expanding vertex 0 of Petersen into a triangle K3.
pub fn build_petersen_k3() -> BitGraph {
    let p = build_petersen();
    let mut g = BitGraph::empty(12);
    // Keep all edges not incident to 0
    for u in 1..10 {
        for v in (u + 1)..10 {
            if p.has_edge(u, v) {
                g.add_edge(u, v);
            }
        }
    }
    // Triangle on {0, 10, 11} attached to the 3 neighbors of 0 in Petersen: 1, 4, 5
    g.add_edge(0, 10);
    g.add_edge(0, 11);
    g.add_edge(10, 11);
    g.add_edge(0, 1);
    g.add_edge(10, 4);
    g.add_edge(11, 5);
    g
}

/// Build the 14-vertex Heawood bipartite cubic graph (girth 6, LCF [5, -5]^7).
pub fn build_heawood() -> BitGraph {
    let mut g = BitGraph::empty(14);
    for i in 0..14 {
        g.add_edge(i, (i + 1) % 14);
        if i % 2 == 0 {
            g.add_edge(i, (i + 5) % 14);
        }
    }
    g
}

/// Build the 16-vertex cubic graph obtained by expanding vertex 0 of Heawood into a triangle K3.
pub fn build_heawood_k3() -> BitGraph {
    let h = build_heawood();
    let mut g = BitGraph::empty(16);
    for u in 1..14 {
        for v in (u + 1)..14 {
            if h.has_edge(u, v) {
                g.add_edge(u, v);
            }
        }
    }
    // Neighbors of 0 in Heawood are 1, 5, 13
    g.add_edge(0, 14);
    g.add_edge(0, 15);
    g.add_edge(14, 15);
    g.add_edge(0, 1);
    g.add_edge(14, 5);
    g.add_edge(15, 13);
    g
}

/// Replace `expanded[v] == true` vertices of cubic `base` by 7-vertex H7 gadgets,
/// attaching each gadget's distinguished port 0 (u) to neighbor `u_choice[v] in 0..3`.
fn expand_cubic_with_h7(base: &BitGraph, expanded: &[bool], u_choice: &[usize]) -> BitGraph {
    let n0 = base.n;
    let mut nbrs = vec![[0usize; 3]; n0];
    for v in 0..n0 {
        let mut bits = base.rows[v];
        let mut idx = 0usize;
        while bits != 0 {
            let nb = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            nbrs[v][idx] = nb;
            idx += 1;
        }
        debug_assert_eq!(idx, 3);
    }

    let mut offsets = vec![0usize; n0];
    let mut cur = 0usize;
    for v in 0..n0 {
        offsets[v] = cur;
        cur += if expanded[v] { 7 } else { 1 };
    }
    let mut g = BitGraph::empty(cur);
    for v in 0..n0 {
        if expanded[v] {
            let off = offsets[v];
            for &(a, b) in &H7_EDGES {
                g.add_edge(off + a, off + b);
            }
        }
    }

    let port_of = |v: usize, other: usize| -> usize {
        if !expanded[v] {
            return offsets[v];
        }
        let idx = nbrs[v].iter().position(|&x| x == other).unwrap();
        let u_idx = u_choice[v] % 3;
        if idx == u_idx {
            return offsets[v];
        }
        let rem0 = if u_idx == 0 { 1 } else { 0 };
        offsets[v] + if idx == rem0 { 1 } else { 2 }
    };

    for u in 0..n0 {
        for &v in &nbrs[u] {
            if u < v {
                let pu = port_of(u, v);
                let pv = port_of(v, u);
                g.add_edge(pu, pv);
            }
        }
    }
    g
}

/// Fast (C4, C8, C16) evaluation key for H7 port orientation search.
fn eval_c4_c8_c16(g: &BitGraph, scratch: &mut DfsScratch) -> (u32, u32, u32) {
    let (_dom, res) = crate::cycles::evaluate_lengths(
        g,
        &[4, 8, 16],
        512,
        150_000,
        None,
        false,
        scratch,
        false,
    );
    let c4 = if res[0].complete { res[0].count } else { 512 };
    let c8 = if res[1].complete { res[1].count } else { 512 };
    let c16 = if res[2].complete { res[2].count } else { 512 };
    (c4, c8, c16)
}

/// Generate a non-random H7-gadget expansion cubic seed for even `n in [16, 112]`
/// (Exoo 2014 / Garcia arXiv:2609.04686) with fast coordinate-descent port-orientation
/// optimization targeting C4 = C8 = 0 and minimal C16:
///   n % 6 == 4: Petersen + r*H7 (n=16..70) or Heawood+K3 + r*H7 (n=76..112)
///   n % 6 == 0: Petersen+K3 + r*H7 (n=18..78, including Exoo G78 with C4=C8=C16=0)
///   n % 6 == 2: Heawood + r*H7 (n=20..98, including Heawood+14*H7 with C4=C8=C16=0)
pub fn generate_h7_expansion_seed(
    rng: &mut Rng,
    n: usize,
    mode: GraphMode,
) -> Result<BitGraph, String> {
    if mode == GraphMode::SingleBlock41 {
        if n < 17 || n % 2 == 0 {
            return generate_single_block_41_seed(rng, n);
        }
        let cubic = generate_h7_expansion_seed(rng, n - 1, GraphMode::CubicFirst)?;
        let mut edges = Vec::new();
        cubic.collect_edges(&mut edges);
        // Subdivide a random edge to create degree-2 vertex 0
        for _ in 0..32 {
            let chosen = edges[rng.gen_range(edges.len())];
            let mut g = BitGraph::empty(n);
            g.add_edge(0, chosen.0 as usize + 1);
            g.add_edge(0, chosen.1 as usize + 1);
            for &(u, v) in &edges {
                if (u, v) != chosen {
                    g.add_edge(u as usize + 1, v as usize + 1);
                }
            }
            if g.single_block_41_valid() {
                return Ok(g);
            }
        }
        return generate_single_block_41_seed(rng, n);
    }

    if n % 2 != 0 || !(16..=112).contains(&n) {
        return generate_seed(rng, n, mode);
    }
    let base = match n % 6 {
        4 => {
            if n <= 70 {
                build_petersen()
            } else {
                build_heawood_k3()
            }
        }
        0 => {
            if n <= 78 {
                build_petersen_k3()
            } else {
                return generate_seed(rng, n, mode);
            }
        }
        2 => {
            if n <= 98 {
                build_heawood()
            } else {
                return generate_seed(rng, n, mode);
            }
        }
        _ => unreachable!(),
    };
    let n0 = base.n;
    let r = (n - n0) / 6;
    if r == 0 || r > n0 {
        return generate_seed(rng, n, mode);
    }

    let mut scratch = DfsScratch::new();
    let mut best_graph = None;
    let mut best_key = (u32::MAX, u32::MAX, u32::MAX);
    let mut verts: Vec<usize> = (0..n0).collect();

    let restarts = if n >= 70 { 6 } else { 3 };
    for _restart in 0..restarts {
        rng.shuffle(&mut verts);
        let mut expanded = vec![false; n0];
        let mut exp_list = Vec::with_capacity(r);
        for &v in &verts[..r] {
            expanded[v] = true;
            exp_list.push(v);
        }
        let mut u_choice = vec![0usize; n0];
        for &v in &exp_list {
            u_choice[v] = rng.gen_range(3);
        }

        let mut g = expand_cubic_with_h7(&base, &expanded, &u_choice);
        let mut key = eval_c4_c8_c16(&g, &mut scratch);

        for _sweep in 0..4 {
            let mut improved = false;
            rng.shuffle(&mut exp_list);
            for &v in &exp_list {
                let orig = u_choice[v];
                let mut best_u = orig;
                let mut best_local = key;
                for alt in 0..3 {
                    if alt == orig {
                        continue;
                    }
                    u_choice[v] = alt;
                    let cand = expand_cubic_with_h7(&base, &expanded, &u_choice);
                    let ck = eval_c4_c8_c16(&cand, &mut scratch);
                    if ck < best_local {
                        best_local = ck;
                        best_u = alt;
                        g = cand;
                    }
                }
                u_choice[v] = best_u;
                if best_local < key {
                    key = best_local;
                    improved = true;
                    if key == (0, 0, 0) {
                        break;
                    }
                }
            }
            if !improved || key == (0, 0, 0) {
                break;
            }
        }

        if key < best_key {
            best_key = key;
            best_graph = Some(g);
            if best_key == (0, 0, 0) {
                break;
            }
        }
    }

    let g = best_graph.ok_or_else(|| "failed to build H7 expansion seed".to_string())?;
    if mode == GraphMode::MinimalStructureMixedDegree && !g.minimal_structure_valid() {
        return generate_seed(rng, n, mode);
    }
    Ok(g)
}

/// Exact Markstrom-24 cubic graph (K4 -> K3 + 3*H7 with port orientation u=(1,2,1)):
/// smallest graph with delta >= 3 and C4 = C8 = 0 (exact C16 = 228).
pub fn build_markstrom24() -> BitGraph {
    let mut g = BitGraph::empty(24);
    // Vertex 0 of K4 -> K3 on {0, 1, 2}
    g.add_edge(0, 1);
    g.add_edge(0, 2);
    g.add_edge(1, 2);
    // Vertices 1, 2, 3 of K4 -> H7 on offsets 3, 10, 17
    let offsets = [0usize, 3, 10, 17];
    for &off in &offsets[1..] {
        for &(a, b) in &H7_EDGES {
            g.add_edge(off + a, off + b);
        }
    }
    let nbrs: [[usize; 3]; 4] = [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]];
    let u_choice: [usize; 4] = [0, 1, 2, 1];
    let port_of = |v: usize, other: usize| -> usize {
        let idx = nbrs[v].iter().position(|&x| x == other).unwrap();
        if v == 0 {
            return idx;
        }
        let u_idx = u_choice[v];
        if idx == u_idx {
            return 0;
        }
        let mut rem0 = None;
        for k in 0..3 {
            if k != u_idx {
                if rem0.is_none() {
                    rem0 = Some(k);
                }
            }
        }
        if idx == rem0.unwrap() { 1 } else { 2 }
    };
    for &(a, b) in &[(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)] {
        let pa = offsets[a] + port_of(a, b);
        let pb = offsets[b] + port_of(b, a);
        g.add_edge(pa, pb);
    }
    g
}

/// Generate a 25-vertex Conjecture 4.1 single-block seed by subdividing one edge
/// of Markstrom-24 (new vertex 0 has degree 2, all 24 others have degree 3).
/// When `optimal_edge` is true, subdivides edge (3, 12) which yields exact
/// C4 = 0, C8 = 0, C16 = 187 (and gluing B +_0 B gives n = 49 with C4=C8=C32=0).
pub fn generate_markstrom25_single_block_seed(
    rng: &mut Rng,
    optimal_edge: bool,
) -> Result<BitGraph, String> {
    let m24 = build_markstrom24();
    let mut edges = Vec::with_capacity(36);
    m24.collect_edges(&mut edges);
    let chosen = if optimal_edge {
        (3u8, 12u8)
    } else {
        edges[rng.gen_range(edges.len())]
    };
    let mut g = BitGraph::empty(25);
    g.add_edge(0, chosen.0 as usize + 1);
    g.add_edge(0, chosen.1 as usize + 1);
    for &(u, v) in &edges {
        if (u, v) != chosen {
            g.add_edge(u as usize + 1, v as usize + 1);
        }
    }
    if !g.single_block_41_valid() {
        return Err("Markstrom-25 subdivision failed single_block_41_valid".to_string());
    }
    Ok(g)
}

/// Generate a Conjecture 4.1 / Theorem 4.2 single-block seed B of order `k`
/// (vertex 0 has degree 2 with degree-3 neighbors; all other vertices have
/// degree >= 3; B is 2-connected and 2-degenerate). Gluing B +_0 B produces a
/// legal Ducoffe-Dumitru odd graph of order n = 2k - 1.
pub fn generate_single_block_41_seed(rng: &mut Rng, k: usize) -> Result<BitGraph, String> {
    if !(6..=128).contains(&k) {
        return Err("single_block_41 requires order k between 6 and 128".to_string());
    }
    let verts: Vec<usize> = (0..k).collect();
    for _attempt in 0..256 {
        let mut g = BitGraph::empty(k);
        if fill_biconnected_block(rng, &mut g, &verts) && g.single_block_41_valid() {
            return Ok(g);
        }
    }
    Err(format!(
        "failed to generate single_block_41 seed for k={k} within retry budget"
    ))
}

/// Generate a strictly legal Ducoffe-Dumitru 2-block 1-clique-sum seed of odd
/// order `n >= 13` (Theorem 2.3 & Corollary 2.4): two equal-order, equal-edge,
/// 2-degenerate blocks of size `k = (n + 1) / 2` sharing one cut vertex of exact
/// degree 4. For `13 <= n <= 61`, both blocks have size `<= 31`, guaranteeing C32 == 0.
/// Returns `(graph, block1_inner_mask)` where `block1_inner_mask` marks the
/// internal (non-cut) vertices of block 1 when `n <= 64` (0 otherwise).
pub fn generate_two_block_ducoffe_seed(rng: &mut Rng, n: usize) -> Result<(BitGraph, u64), String> {
    if n % 2 == 0 {
        return Err(format!(
            "two_block 1-clique-sum is only legal for odd orders under Ducoffe-Dumitru Corollary 2.4 (got even n={n})"
        ));
    }
    if n < 13 || n > 127 {
        return Err("two_block Ducoffe-Dumitru seed requires odd order between 13 and 127".to_string());
    }

    let k = (n + 1) / 2;
    let mut perm: Vec<usize> = (0..n).collect();
    for _attempt in 0..128 {
        rng.shuffle(&mut perm);
        let cut = perm[0];
        let mut block1 = Vec::with_capacity(k);
        block1.push(cut);
        block1.extend_from_slice(&perm[1..k]);

        let mut block2 = Vec::with_capacity(k);
        block2.push(cut);
        block2.extend_from_slice(&perm[k..n]);

        let mut g = BitGraph::empty(n);
        if fill_biconnected_block(rng, &mut g, &block1)
            && fill_biconnected_block(rng, &mut g, &block2)
            && g.is_connected()
            && g.minimal_structure_valid()
        {
            let mut b1_mask = 0u64;
            if n <= 64 {
                for &v in &perm[1..k] {
                    b1_mask |= 1u64 << v;
                }
            }
            return Ok((g, b1_mask));
        }
    }
    Err("failed to generate symmetric 2-block Ducoffe-Dumitru seed within retry budget".to_string())
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
    if mode == GraphMode::SingleBlock41 {
        return generate_single_block_41_seed(rng, n);
    }
    let effective = if mode == GraphMode::UnrestrictedMinDegree3 && n % 2 != 0 {
        GraphMode::MinimalStructureMixedDegree
    } else {
        mode
    };

    match effective {
        GraphMode::SingleBlock41 => unreachable!(),
        GraphMode::MinimalStructureMixedDegree => {
            let (high_count, high_deg) = if n == 6 || n == 8 {
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
    pub removed: [Edge; 3],
    pub removed_idx: [u16; 3],
    pub added_count: u8,
    pub added: [Edge; 3],
}

impl MutationDelta {
    pub const NONE: Self = Self {
        changed: false,
        removed_count: 0,
        removed: [(0, 0); 3],
        removed_idx: [u16::MAX; 3],
        added_count: 0,
        added: [(0, 0); 3],
    };

    #[inline]
    pub fn removed2(&self) -> [Edge; 2] {
        [self.removed[0], self.removed[1]]
    }

    #[inline]
    pub fn removed_idx2(&self) -> [u16; 2] {
        [self.removed_idx[0], self.removed_idx[1]]
    }

    #[inline]
    pub fn added2(&self) -> [Edge; 2] {
        [self.added[0], self.added[1]]
    }
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
        if mode == GraphMode::SingleBlock41 && !cand.single_block_41_valid() {
            continue;
        }
        return Some((
            cand,
            MutationDelta {
                changed: true,
                removed_count: 2,
                removed: [
                    normalize_edge(first.0, first.1),
                    normalize_edge(second.0, second.1),
                    (0, 0),
                ],
                removed_idx: [first_idx, second_idx, u16::MAX],
                added_count: 2,
                added: [e1, e2, (0, 0)],
            },
        ));
    }
    None
}

/// Cyclic 3-edge switch on three pairwise-disjoint edges `(a,b), (c,d), (e,f)`:
/// replaces them with `(a,c), (d,e), (f,b)` (testing random endpoint orientations),
/// preserving the exact degree sequence and crossing C4=C8=0 barriers unreachable
/// by single 2-edge switches.
#[inline]
fn try_three_edge_switch_u64(
    graph: &BitGraph64,
    e0: Edge,
    i0: u16,
    e1: Edge,
    i1: u16,
    e2: Edge,
    i2: u16,
    rng: &mut Rng,
    mode: GraphMode,
) -> Option<(BitGraph64, MutationDelta)> {
    let (a0, b0) = (e0.0 as usize, e0.1 as usize);
    let (c0, d0) = (e1.0 as usize, e1.1 as usize);
    let (f0, g0) = (e2.0 as usize, e2.1 as usize);
    let m0 = (1u64 << a0) | (1u64 << b0);
    let m1 = (1u64 << c0) | (1u64 << d0);
    let m2 = (1u64 << f0) | (1u64 << g0);
    if (m0 & m1) != 0 || (m0 & m2) != 0 || (m1 & m2) != 0 {
        return None;
    }

    let rbits = rng.next_u64();
    let (a, b) = if (rbits & 1) == 0 { (a0, b0) } else { (b0, a0) };
    let (c, d) = if (rbits & 2) == 0 { (c0, d0) } else { (d0, c0) };
    let (f, g) = if (rbits & 4) == 0 { (f0, g0) } else { (g0, f0) };

    let candidates = [
        ((a, c), (d, f), (g, b)),
        ((a, d), (c, g), (f, b)),
        ((a, f), (g, c), (d, b)),
    ];
    for &((u1, v1), (u2, v2), (u3, v3)) in &candidates {
        let n1 = normalize_edge(u1 as u8, v1 as u8);
        let n2 = normalize_edge(u2 as u8, v2 as u8);
        let n3 = normalize_edge(u3 as u8, v3 as u8);
        if n1 == n2
            || n1 == n3
            || n2 == n3
            || graph.has_edge(u1, v1)
            || graph.has_edge(u2, v2)
            || graph.has_edge(u3, v3)
        {
            continue;
        }
        let mut cand = *graph;
        cand.remove_edge(a0, b0);
        cand.remove_edge(c0, d0);
        cand.remove_edge(f0, g0);
        cand.add_edge(u1, v1);
        cand.add_edge(u2, v2);
        cand.add_edge(u3, v3);
        if !cand.is_connected() {
            continue;
        }
        if mode == GraphMode::MinimalStructureMixedDegree && !cand.minimal_structure_valid() {
            continue;
        }
        if mode == GraphMode::SingleBlock41 && !cand.single_block_41_valid() {
            continue;
        }
        return Some((
            cand,
            MutationDelta {
                changed: true,
                removed_count: 3,
                removed: [
                    normalize_edge(e0.0, e0.1),
                    normalize_edge(e1.0, e1.1),
                    normalize_edge(e2.0, e2.1),
                ],
                removed_idx: [i0, i1, i2],
                added_count: 3,
                added: [n1, n2, n3],
            },
        ));
    }
    None
}

/// Select a high-participation ("hot") edge index from `CycleBank64` via
/// O(1) tournament sampling (zero allocation). Returns `None` if bank is empty.
#[inline]
fn select_hot_bank_edge(edges: &[Edge], bank: &CycleBank64, rng: &mut Rng) -> Option<usize> {
    let m = edges.len();
    if !bank.active || m == 0 {
        return None;
    }
    let mut best_idx = None;
    let mut best_heat = 0u32;
    for _ in 0..6 {
        let idx = rng.gen_range(m);
        let h = bank.edge_heat(idx);
        if h > best_heat {
            best_heat = h;
            best_idx = Some(idx);
        }
    }
    best_idx
}

#[inline]
fn edge_in_block1(e: Edge, block1_inner_mask: u64) -> bool {
    (((1u64 << e.0) | (1u64 << e.1)) & block1_inner_mask) != 0
}

/// Mutate a 64-vertex graph using a pre-cached edge list (`edges_buf` is owned
/// by the lane and only rebuilt when `graph` changes).
/// When `block1_inner_mask != 0`, switches only pair edges from the same block.
/// When `three_edge_prob > 0.0`, performs cyclic 3-edge switches with that
/// probability to jump across C4=C8=0 barriers.
/// When `targeted == true` and `bank` has live cycles, prefers high-participation
/// ("hot") edges by bank heat w(e).
#[allow(clippy::too_many_arguments)]
pub fn mutate_u64(
    graph: &BitGraph64,
    edges: &[Edge],
    rng: &mut Rng,
    mode: GraphMode,
    targeted: bool,
    nonzero_len_mask: u8,
    block1_inner_mask: u64,
    three_edge_prob: f64,
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
                            removed: [(0, 0); 3],
                            removed_idx: [u16::MAX; 3],
                            added_count: 1,
                            added: [e, (0, 0), (0, 0)],
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
                            removed: [e, (0, 0), (0, 0)],
                            removed_idx: [idx, u16::MAX, u16::MAX],
                            added_count: 0,
                            added: [(0, 0); 3],
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

    // Optional cyclic 3-edge switch (preserving degree sequence & block locality)
    if m >= 3 && three_edge_prob > 0.0 && rng.next_f64() < three_edge_prob {
        let hot_first = if targeted {
            bank.and_then(|b| select_hot_bank_edge(edges, b, rng))
        } else {
            None
        };
        for _ in 0..48 {
            let i0 = hot_first.unwrap_or_else(|| rng.gen_range(m));
            let i1 = rng.gen_range(m);
            let i2 = rng.gen_range(m);
            if i0 == i1 || i0 == i2 || i1 == i2 {
                continue;
            }
            if block1_inner_mask != 0 {
                let b0 = edge_in_block1(edges[i0], block1_inner_mask);
                if edge_in_block1(edges[i1], block1_inner_mask) != b0
                    || edge_in_block1(edges[i2], block1_inner_mask) != b0
                {
                    continue;
                }
            }
            if let Some(res) = try_three_edge_switch_u64(
                graph,
                edges[i0],
                i0 as u16,
                edges[i1],
                i1 as u16,
                edges[i2],
                i2 as u16,
                rng,
                mode,
            ) {
                return res;
            }
        }
    }

    if targeted {
        // Hot-edge tournament selection from CycleBank64 when C4/C8 are already zero
        // (or with 40% probability whenever the bank is active), focusing switches
        // directly on the highest-participation C16/C32 bottleneck edges.
        if let Some(b) = bank {
            let prefer_hot = (nonzero_len_mask & 0b11) == 0 || (rng.next_u64() & 3) == 0;
            if prefer_hot {
                if let Some(hot_i) = select_hot_bank_edge(edges, b, rng) {
                    let first = edges[hot_i];
                    for _ in 0..48 {
                        let j = rng.gen_range(m);
                        if j == hot_i {
                            continue;
                        }
                        if block1_inner_mask != 0
                            && edge_in_block1(first, block1_inner_mask)
                                != edge_in_block1(edges[j], block1_inner_mask)
                        {
                            continue;
                        }
                        if let Some(res) = try_two_edge_switch_u64(
                            graph,
                            first,
                            hot_i as u16,
                            edges[j],
                            j as u16,
                            rng,
                            mode,
                        ) {
                            return res;
                        }
                    }
                }
            }
        }

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
        if mode == GraphMode::SingleBlock41 && !cand.single_block_41_valid() {
            continue;
        }
        return Some((
            cand,
            MutationDelta {
                changed: true,
                removed_count: 2,
                removed: [
                    normalize_edge(first.0, first.1),
                    normalize_edge(second.0, second.1),
                    (0, 0),
                ],
                removed_idx: [u16::MAX; 3],
                added_count: 2,
                added: [e1, e2, (0, 0)],
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
                            removed: [(0, 0); 3],
                            removed_idx: [u16::MAX; 3],
                            added_count: 1,
                            added: [e, (0, 0), (0, 0)],
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
                            removed: [e, (0, 0), (0, 0)],
                            removed_idx: [u16::MAX; 3],
                            added_count: 0,
                            added: [(0, 0); 3],
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
    fn closed_ducoffe_filter_enforces_parity_symmetry_and_lemma35() {
        let mut rng = Rng::new(2026112601);
        let mut scratch = DfsScratch::new();

        // 1) Even orders must reject 2-block 1-clique-sum (Corollary 2.4).
        for &even_n in &[12usize, 36, 48, 50, 64] {
            assert!(
                generate_two_block_ducoffe_seed(&mut rng, even_n).is_err(),
                "even n={even_n} must reject two_block 1-clique-sum"
            );
            // Random 1-block even seeds must be strictly 2-connected and valid.
            let g = generate_seed(&mut rng, even_n, GraphMode::MinimalStructureMixedDegree)
                .unwrap_or_else(|e| panic!("even seed failed for n={even_n}: {e}"));
            assert!(g.is_biconnected(), "even n={even_n} seed must be 2-connected");
            assert!(g.minimal_structure_valid());
            assert!(BitGraph64::from_graph(&g).minimal_structure_valid());
        }

        // Construct an explicit illegal even 2-block graph (n=36, blocks [25, 12]):
        let mut illegal_even = BitGraph::empty(36);
        let b1: Vec<usize> = (0..25).collect();
        let mut b2: Vec<usize> = vec![0];
        b2.extend(25..36);
        assert!(fill_biconnected_block(&mut rng, &mut illegal_even, &b1));
        assert!(fill_biconnected_block(&mut rng, &mut illegal_even, &b2));
        assert!(
            !illegal_even.minimal_structure_valid(),
            "even 2-block [25,12] must be rejected by closed Ducoffe-Dumitru filter"
        );
        assert!(!BitGraph64::from_graph(&illegal_even).minimal_structure_valid());

        // Construct an explicit illegal asymmetric odd 2-block graph (n=37, blocks [25, 13]):
        let mut illegal_asym = BitGraph::empty(37);
        let b1_a: Vec<usize> = (0..25).collect();
        let mut b2_a: Vec<usize> = vec![0];
        b2_a.extend(25..37);
        assert!(fill_biconnected_block(&mut rng, &mut illegal_asym, &b1_a));
        assert!(fill_biconnected_block(&mut rng, &mut illegal_asym, &b2_a));
        assert!(
            !illegal_asym.minimal_structure_valid(),
            "asymmetric odd 2-block [25,13] must be rejected by Theorem 2.3"
        );
        assert!(!BitGraph64::from_graph(&illegal_asym).minimal_structure_valid());

        // 2) Odd orders >= 13 produce strictly symmetric 2-block seeds with C32==0 up to 61.
        for &n in &[13usize, 15, 25, 41, 49, 55, 61] {
            let (g, b1_mask) = generate_two_block_ducoffe_seed(&mut rng, n)
                .unwrap_or_else(|e| panic!("seed failed for n={n}: {e}"));
            assert!(g.is_connected(), "n={n} not connected");
            assert!(g.minimum_degree() >= 3, "n={n} min_deg < 3");
            assert!(g.minimal_structure_valid(), "n={n} failed minimal_structure_valid");
            assert!(BitGraph64::from_graph(&g).minimal_structure_valid());
            assert_ne!(b1_mask, 0, "n={n} expected non-zero block1 mask");

            let score = score_graph_fast(&g, 64, 50_000, None, &mut scratch)
                .expect("unbounded score");
            for &(len, cnt) in score.counts_slice() {
                if len == 32 {
                    assert_eq!(cnt, 0, "n={n} symmetric 2-block seed had C32={cnt}");
                }
            }
        }
    }

    #[test]
    fn within_block_mutations_preserve_symmetric_two_block_and_c32_zero() {
        let mut rng = Rng::new(2026112602);
        let mut scratch = DfsScratch::new();
        let mut wc = WitnessCache::new();
        let (init, b1_mask) = generate_two_block_ducoffe_seed(&mut rng, 49).unwrap();
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
                0.0,
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

    #[test]
    fn single_block_41_markstrom25_and_gluing_theorem42() {
        let mut rng = Rng::new(2026112603);
        let mut scratch = DfsScratch::new();

        // Verify Markstrom-24 exact counts: C4=0, C8=0, C16=228
        let m24 = build_markstrom24();
        assert_eq!(m24.n, 24);
        assert_eq!(m24.size(), 36);
        let m24_score = score_graph_fast(&m24, 500, 500_000, None, &mut scratch).unwrap();
        assert_eq!(m24_score.counts_slice(), &[(4, 0), (8, 0), (16, 228)]);

        // Verify optimal Markstrom-25 single-block seed: C4=0, C8=0, C16=187
        let b25 = generate_markstrom25_single_block_seed(&mut rng, true).unwrap();
        assert_eq!(b25.n, 25);
        assert!(b25.single_block_41_valid());
        assert!(BitGraph64::from_graph(&b25).single_block_41_valid());
        let b25_score = score_graph_fast(&b25, 500, 500_000, None, &mut scratch).unwrap();
        assert_eq!(b25_score.counts_slice(), &[(4, 0), (8, 0), (16, 187)]);

        // Glue B25 +_0 B25 -> n = 49 legal Ducoffe-Dumitru graph with C4=0, C8=0, C16=374, C32=0!
        let glued49 = b25.glue_symmetric_single_block().unwrap();
        assert_eq!(glued49.n, 49);
        assert!(glued49.minimal_structure_valid());
        assert!(BitGraph64::from_graph(&glued49).minimal_structure_valid());
        let g49_score = score_graph_fast(&glued49, 500, 500_000, None, &mut scratch).unwrap();
        assert_eq!(
            g49_score.counts_slice(),
            &[(4, 0), (8, 0), (16, 374), (32, 0)]
        );

        // Verify random single_block_41 seeds and mutations for k in 21..=31
        let mut wc = WitnessCache::new();
        for k in [21usize, 22, 25, 30, 31] {
            let seed = generate_single_block_41_seed(&mut rng, k).unwrap();
            assert!(seed.single_block_41_valid());
            let glued = seed.glue_symmetric_single_block().unwrap();
            assert_eq!(glued.n, 2 * k - 1);
            assert!(
                glued.minimal_structure_valid(),
                "glued B+_0 B for k={k} (n={}) must pass closed minimal_structure_valid",
                2 * k - 1
            );
            let mut g64 = BitGraph64::from_graph(&seed);
            let mut edges = Vec::new();
            g64.collect_edges(&mut edges);
            let mut moved = 0usize;
            for _ in 0..80 {
                let (cand, delta) = mutate_u64(
                    &g64,
                    &edges,
                    &mut rng,
                    GraphMode::SingleBlock41,
                    false,
                    0x3f,
                    0,
                    0.0,
                    None,
                    &mut wc,
                    &mut scratch,
                );
                if delta.changed {
                    assert!(cand.single_block_41_valid());
                    g64 = cand;
                    g64.collect_edges(&mut edges);
                    moved += 1;
                }
            }
            assert!(moved >= 10, "k={k} expected >= 10 single_block_41 moves, got {moved}");
        }
    }

    #[test]
    fn h7_expansion_seeds_break_c16_plateau_and_three_edge_switch_preserves_mode() {
        let mut rng = Rng::new(2026112604);
        let mut scratch = DfsScratch::new();

        // Petersen + 9*H7 at n=64 must have C4=0, C8=0, and C16 << random (~1400)
        let g64 = generate_h7_expansion_seed(&mut rng, 64, GraphMode::CubicFirst).unwrap();
        assert_eq!(g64.n, 64);
        assert_eq!(g64.size(), 96);
        assert!(g64.is_biconnected());
        let (c4_64, c8_64, c16_64) = eval_c4_c8_c16(&g64, &mut scratch);
        assert_eq!(c4_64, 0, "Petersen+9*H7 must avoid C4");
        assert_eq!(c8_64, 0, "Petersen+9*H7 must avoid C8");
        assert!(
            c16_64 <= 90,
            "Petersen+9*H7 expected C16 <= 90 (vs ~1403 random), got {c16_64}"
        );

        // Heawood + 6*H7 at n=50 must have C4=0, C8=0, low C16
        let g50 = generate_h7_expansion_seed(&mut rng, 50, GraphMode::CubicFirst).unwrap();
        assert_eq!(g50.n, 50);
        assert!(g50.is_biconnected());
        let (c4_50, c8_50, c16_50) = eval_c4_c8_c16(&g50, &mut scratch);
        assert_eq!(c4_50, 0);
        assert_eq!(c8_50, 0);
        assert!(c16_50 < 400, "Heawood+6*H7 expected C16 < 400, got {c16_50}");

        // Petersen + 10*H7 at n=70 must have C4=0, C8=0, ultra-low C16
        let g70 = generate_h7_expansion_seed(&mut rng, 70, GraphMode::CubicFirst).unwrap();
        assert_eq!(g70.n, 70);
        let (c4_70, c8_70, c16_70) = eval_c4_c8_c16(&g70, &mut scratch);
        assert_eq!(c4_70, 0);
        assert_eq!(c8_70, 0);
        assert!(c16_70 <= 25, "Petersen+10*H7 expected C16 <= 25, got {c16_70}");

        // 3-edge cyclic switch preserves cubic degree sequence & connectivity
        let mut cur = BitGraph64::from_graph(&g64);
        let mut edges = Vec::new();
        cur.collect_edges(&mut edges);
        let mut wc = WitnessCache::new();
        let mut three_moves = 0usize;
        for _ in 0..80 {
            let (cand, delta) = mutate_u64(
                &cur,
                &edges,
                &mut rng,
                GraphMode::CubicFirst,
                false,
                0x3f,
                0,
                1.0,
                None,
                &mut wc,
                &mut scratch,
            );
            if delta.changed && delta.removed_count == 3 {
                assert!(cand.is_connected());
                for u in 0..cand.n {
                    assert_eq!(cand.degree(u), 3);
                }
                cur = cand;
                cur.collect_edges(&mut edges);
                three_moves += 1;
            }
        }
        assert!(three_moves >= 20, "expected >= 20 valid 3-edge switches, got {three_moves}");
    }
}

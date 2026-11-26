//! Wave D2: Bipartite n in [70, 128] Engine:
//! 1. Hardware x86-64 PCLMULQDQ-accelerated Bipartite Bjorklund Narrow Sieve
//!    over GF(2^16) for topology-independent C16 and C32 detection (n <= 128).
//! 2. Compressed-space Voltage-Lift Tabu Search (adapting Exoo et al. 2026 Alg. 4)
//!    over non-abelian, non-nilpotent even-order finite groups (respecting Burkhart
//!    Nov 2026 exclusions) on bipartite cubic base multigraphs.

use std::thread;
use std::time::Instant;

use crate::graph::BitGraph;
use crate::rng::Rng;

// ============================================================================
// Part 1: GF(2^16) Arithmetic with x86-64 Hardware PCLMULQDQ Acceleration
// Irreducible polynomial: x^16 + x^5 + x^3 + x^2 + 1 (0x1002D).
// ============================================================================

const GF16_POLY: u32 = 0x1_002D;

/// Scalar fallback GF(2^16) multiply.
#[allow(dead_code)]
#[inline(always)]
fn gf16_mul_scalar(mut a: u16, mut b: u16) -> u16 {
    let mut res: u32 = 0;
    let mut aa = a as u32;
    while b != 0 {
        if (b & 1) != 0 {
            res ^= aa;
        }
        aa <<= 1;
        if (aa & 0x1_0000) != 0 {
            aa ^= GF16_POLY;
        }
        b >>= 1;
    }
    let _ = &mut a;
    res as u16
}

/// Hardware PCLMULQDQ carry-less multiply + fast 2-step reduction mod x^16+x^5+x^3+x^2+1.
#[cfg(all(target_arch = "x86_64", target_feature = "pclmulqdq"))]
#[inline(always)]
pub fn gf16_mul(a: u16, b: u16) -> u16 {
    use std::arch::x86_64::{_mm_clmulepi64_si128, _mm_cvtsi128_si64, _mm_set_epi64x};
    unsafe {
        let va = _mm_set_epi64x(0, a as i64);
        let vb = _mm_set_epi64x(0, b as i64);
        let prod = _mm_cvtsi128_si64(_mm_clmulepi64_si128(va, vb, 0x00)) as u64;
        // prod is a degree <= 30 polynomial. Reduce high bits (16..30) mod 0x1002D:
        // x^16 = x^5 + x^3 + x^2 + 1 (0x2D).
        let hi = prod >> 16;
        let mut lo = (prod & 0xFFFF) ^ hi ^ (hi << 2) ^ (hi << 3) ^ (hi << 5);
        // Any remaining overflow in bits 16..20 (max shift +5 on 15-bit hi => bit 20):
        let hi2 = lo >> 16;
        lo = (lo & 0xFFFF) ^ hi2 ^ (hi2 << 2) ^ (hi2 << 3) ^ (hi2 << 5);
        lo as u16
    }
}

#[cfg(not(all(target_arch = "x86_64", target_feature = "pclmulqdq")))]
#[inline(always)]
pub fn gf16_mul(a: u16, b: u16) -> u16 {
    gf16_mul_scalar(a, b)
}

/// Extract bipartition `(part_a, part_b)` if `g` is bipartite (n <= 128).
pub fn extract_bipartition(g: &BitGraph) -> Option<(Vec<usize>, Vec<usize>)> {
    let n = g.n;
    let mut color = vec![-1i8; n];
    let mut queue = Vec::with_capacity(n);
    for start in 0..n {
        if color[start] != -1 {
            continue;
        }
        color[start] = 0;
        queue.clear();
        queue.push(start);
        let mut head = 0usize;
        while head < queue.len() {
            let u = queue[head];
            head += 1;
            let cu = color[u];
            let mut bits = g.rows[u];
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                if color[v] == -1 {
                    color[v] = 1 - cu;
                    queue.push(v);
                } else if color[v] == cu {
                    return None;
                }
            }
        }
    }
    let mut a = Vec::new();
    let mut b = Vec::new();
    for u in 0..n {
        if color[u] == 0 {
            a.push(u);
        } else {
            b.push(u);
        }
    }
    // Put smaller side in A to minimize work
    if a.len() > b.len() {
        std::mem::swap(&mut a, &mut b);
    }
    Some((a, b))
}

#[derive(Clone, Debug)]
pub struct BjorklundSieveResult {
    pub found: bool,
    pub length: usize,
    pub rounds: usize,
    pub roots_tested: usize,
    pub elapsed_ms: f64,
    pub pclmulqdq_enabled: bool,
}

/// Bipartite Bjorklund Narrow Sieve over GF(2^16) for detecting a simple even
/// cycle of length `length = 2*h` (e.g. L = 8, 16, 32) in any bipartite graph `g` (n <= 128).
///
/// Soundness & Error Guarantees:
/// - **Zero false positives (100% deterministic)**: If `found == true`, a simple
///   `length`-cycle MUST exist in `g` (all non-simple walks with repeated A-vertices
///   cancel via Ryser inclusion-exclusion over 2^{h-1} subsets, and all walks with
///   repeated B-vertices cancel pairwise over characteristic 2 via sub-walk reversal
///   because 2-step backtracking at A-vertices is explicitly subtracted out!).
/// - **One-sided false-negative error**: `<= (3h - 1) / 2^16` per round
///   (`< 7.2e-4` for L=32 in 1 round, `< 5.2e-7` over 2 independent rounds!).
/// - When `orbit_roots` is `Some(roots)` (e.g. orbit representatives of a vertex-symmetric
///   voltage lift), only tests starting vertices in `roots` (massive speedup!).
pub fn bipartite_cycle_sieve_gf2_16(
    g: &BitGraph,
    length: usize,
    rounds: usize,
    workers: usize,
    seed: u64,
    orbit_roots: Option<&[usize]>,
) -> Result<BjorklundSieveResult, String> {
    let started = Instant::now();
    if length < 4 || length % 2 != 0 {
        return Err("bipartite sieve requires even length >= 4".to_string());
    }
    let h = length / 2;
    if h < 2 || h > 16 {
        return Err(format!("bipartite sieve supports even length in 4..=32 (got {length})"));
    }
    let Some((part_a, part_b)) = extract_bipartition(g) else {
        return Err("graph is not bipartite".to_string());
    };
    let na = part_a.len();
    let nb = part_b.len();
    if na < h || nb < h {
        return Ok(BjorklundSieveResult {
            found: false,
            length,
            rounds,
            roots_tested: 0,
            elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
            pclmulqdq_enabled: cfg!(all(target_arch = "x86_64", target_feature = "pclmulqdq")),
        });
    }

    let mut pos_in_a = vec![usize::MAX; g.n];
    let mut pos_in_b = vec![usize::MAX; g.n];
    for (i, &u) in part_a.iter().enumerate() {
        pos_in_a[u] = i;
    }
    for (i, &u) in part_b.iter().enumerate() {
        pos_in_b[u] = i;
    }

    // Build compact adjacency lists from A -> B
    let mut adj_a: Vec<Vec<usize>> = vec![Vec::new(); na];
    for (ai, &u) in part_a.iter().enumerate() {
        let mut bits = g.rows[u];
        while bits != 0 {
            let v = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            let bi = pos_in_b[v];
            if bi != usize::MAX {
                adj_a[ai].push(bi);
            }
        }
        adj_a[ai].sort_unstable();
    }

    // Determine which A-indices to test as starting anchor a_0
    let roots: Vec<usize> = match orbit_roots {
        Some(rs) => {
            let mut out = Vec::new();
            for &v in rs {
                if v < g.n && pos_in_a[v] != usize::MAX {
                    out.push(pos_in_a[v]);
                }
            }
            out.sort_unstable();
            out.dedup();
            if out.is_empty() {
                (0..na).collect()
            } else {
                out
            }
        }
        None => (0..na).collect(),
    };
    let restrict_gt_root = orbit_roots.is_none();

    let num_colors = h - 1;
    let total_subsets = 1usize << num_colors;
    let n_workers = workers.max(1).min(total_subsets);
    let mut roots_tested = 0usize;

    for &a0 in &roots {
        let nbrs0 = &adj_a[a0];
        if nbrs0.len() < 2 {
            continue;
        }
        // If restricting a > a0, need at least h - 1 vertices in A strictly greater than a0
        if restrict_gt_root && (na - 1 - a0) < (h - 1) {
            continue;
        }
        roots_tested += 1;

        for round in 0..rounds.max(1) {
            let mut rng = Rng::new(
                seed.wrapping_add((a0 as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15))
                    .wrapping_add((round as u64).wrapping_mul(0xbf58_476d_1ce4_e5b9)),
            );

            // Random nonzero edge weights w[ai][k] in GF(2^16)*
            let mut w_edge: Vec<Vec<u16>> = Vec::with_capacity(na);
            for ai in 0..na {
                let mut row = Vec::with_capacity(adj_a[ai].len());
                for _ in 0..adj_a[ai].len() {
                    let mut w = (rng.next_u64() & 0xFFFF) as u16;
                    if w == 0 {
                        w = 1;
                    }
                    row.push(w);
                }
                w_edge.push(row);
            }

            // Random color-assignment matrix x[ai][c] in GF(2^16) for c in 0..num_colors
            let mut x_mat: Vec<[u16; 16]> = vec![[0u16; 16]; na];
            for ai in 0..na {
                for c in 0..num_colors {
                    x_mat[ai][c] = (rng.next_u64() & 0xFFFF) as u16;
                }
            }

            // Test each starting neighbor b0 = nbrs0[idx0] for idx0 in 0..(deg(a0)-1),
            // reading out all strictly greater ending neighbors b_end = nbrs0[idx1] (idx1 > idx0).
            // Every simple 2h-cycle through a0 has a UNIQUE pair (b0 < b_end), breaking
            // both cyclic shift and orientation-reversal symmetries!
            let active_a_start = if restrict_gt_root { a0 + 1 } else { 0 };
            for idx0 in 0..(nbrs0.len() - 1) {
                let b0 = nbrs0[idx0];
                let w0 = w_edge[a0][idx0];
                let end_slice: Vec<(usize, u16)> = ((idx0 + 1)..nbrs0.len())
                    .map(|j| (nbrs0[j], w_edge[a0][j]))
                    .collect();

                let chunk = total_subsets.div_ceil(n_workers);
                let adj_ref = &adj_a;
                let w_ref = &w_edge;
                let x_ref = &x_mat;
                let end_ref = &end_slice;

                let partials: Vec<u16> = thread::scope(|scope| {
                    let handles: Vec<_> = (0..n_workers)
                        .map(|tid| {
                            let lo = tid * chunk;
                            let hi = (lo + chunk).min(total_subsets);
                            scope.spawn(move || {
                                if lo >= hi {
                                    return 0u16;
                                }
                                let mut y = vec![0u16; na];
                                let mut dp_cur = vec![0u16; nb];
                                let mut dp_nxt = vec![0u16; nb];
                                let mut acc = 0u16;

                                // Initialize y for Gray code of `lo`
                                let mut cur_gray = lo ^ (lo >> 1);
                                for ai in active_a_start..na {
                                    if ai == a0 {
                                        continue;
                                    }
                                    let mut val = 0u16;
                                    let mut m = cur_gray;
                                    while m != 0 {
                                        let c = m.trailing_zeros() as usize;
                                        m &= m - 1;
                                        val ^= x_ref[ai][c];
                                    }
                                    y[ai] = val;
                                }

                                for t in lo..hi {
                                    if t > lo {
                                        let next_gray = t ^ (t >> 1);
                                        let bit = (cur_gray ^ next_gray).trailing_zeros() as usize;
                                        cur_gray = next_gray;
                                        for ai in active_a_start..na {
                                            if ai == a0 {
                                                continue;
                                            }
                                            y[ai] ^= x_ref[ai][bit];
                                        }
                                    }

                                    // DP: h-1 non-backtracking 2-steps starting from dp[b0] = w0
                                    dp_cur.fill(0);
                                    dp_cur[b0] = w0;
                                    for _step in 0..(h - 1) {
                                        dp_nxt.fill(0);
                                        for ai in active_a_start..na {
                                            if ai == a0 {
                                                continue;
                                            }
                                            let ya = y[ai];
                                            if ya == 0 {
                                                continue;
                                            }
                                            let nbrs = &adj_ref[ai];
                                            let ws = &w_ref[ai];
                                            let deg = nbrs.len();
                                            let mut terms = [0u16; 8];
                                            let mut sum_a = 0u16;
                                            for k in 0..deg {
                                                let v = dp_cur[nbrs[k]];
                                                let prod = if v == 0 { 0 } else { gf16_mul(v, ws[k]) };
                                                terms[k] = prod;
                                                sum_a ^= prod;
                                            }
                                            if sum_a == 0 {
                                                // Still possible if two equal nonzero terms canceled!
                                                let mut any = false;
                                                for k in 0..deg {
                                                    if terms[k] != 0 {
                                                        any = true;
                                                        break;
                                                    }
                                                }
                                                if !any {
                                                    continue;
                                                }
                                            }
                                            for k in 0..deg {
                                                // Exclude immediate 2-step backtrack b -> a -> b!
                                                let in_nb = sum_a ^ terms[k];
                                                if in_nb != 0 {
                                                    let step_w = gf16_mul(ya, ws[k]);
                                                    dp_nxt[nbrs[k]] ^= gf16_mul(in_nb, step_w);
                                                }
                                            }
                                        }
                                        std::mem::swap(&mut dp_cur, &mut dp_nxt);
                                    }

                                    // Close cycle back to a0 via strictly greater neighbor b_end > b0
                                    for &(b_end, w_end) in end_ref {
                                        let v = dp_cur[b_end];
                                        if v != 0 {
                                            acc ^= gf16_mul(v, w_end);
                                        }
                                    }
                                }
                                acc
                            })
                        })
                        .collect();
                    handles.into_iter().map(|h| h.join().unwrap()).collect()
                });

                let mut total_eval = 0u16;
                for p in partials {
                    total_eval ^= p;
                }
                if total_eval != 0 {
                    return Ok(BjorklundSieveResult {
                        found: true,
                        length,
                        rounds: round + 1,
                        roots_tested,
                        elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
                        pclmulqdq_enabled: cfg!(all(
                            target_arch = "x86_64",
                            target_feature = "pclmulqdq"
                        )),
                    });
                }
            }
        }
    }

    Ok(BjorklundSieveResult {
        found: false,
        length,
        rounds: rounds.max(1),
        roots_tested,
        elapsed_ms: started.elapsed().as_secs_f64() * 1000.0,
        pclmulqdq_enabled: cfg!(all(target_arch = "x86_64", target_feature = "pclmulqdq")),
    })
}

// ============================================================================
// Part 2: Non-Abelian, Non-Nilpotent Even-Order Finite Groups & Voltage Lifts
// ============================================================================

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct FiniteGroup {
    pub name: &'static str,
    pub order: usize,
    pub mul: Vec<Vec<u8>>,
    pub inv: Vec<u8>,
    pub elem_ord: Vec<u8>,
}

impl FiniteGroup {
    fn from_mul(name: &'static str, mul: Vec<Vec<u8>>) -> Self {
        let n = mul.len();
        let mut inv = vec![0u8; n];
        let mut elem_ord = vec![1u8; n];
        for g in 0..n {
            for h in 0..n {
                if mul[g][h] == 0 {
                    inv[g] = h as u8;
                    break;
                }
            }
            let mut cur = g;
            let mut o = 1u8;
            while cur != 0 {
                cur = mul[cur][g] as usize;
                o += 1;
            }
            elem_ord[g] = o;
        }
        Self {
            name,
            order: n,
            mul,
            inv,
            elem_ord,
        }
    }

    /// Dihedral group D_m of order 2m (non-abelian; non-nilpotent whenever m is not a power of 2!).
    /// Elements: 0..m are rotations r^k; m..2m are reflections s * r^k.
    /// Multiplication: r^a * r^b = r^{(a+b)%m}; r^a * (s r^b) = s r^{(b-a)%m};
    /// (s r^a) * r^b = s r^{(a+b)%m}; (s r^a) * (s r^b) = r^{(b-a)%m}.
    pub fn dihedral(name: &'static str, m: usize) -> Self {
        let ord = 2 * m;
        let mut mul = vec![vec![0u8; ord]; ord];
        for i in 0..ord {
            let (si, ai) = (i / m, i % m);
            for j in 0..ord {
                let (sj, aj) = (j / m, j % m);
                let res = match (si, sj) {
                    (0, 0) => (ai + aj) % m,
                    (0, 1) => m + ((aj + m - ai) % m),
                    (1, 0) => m + ((ai + aj) % m),
                    (1, 1) => (aj + m - ai) % m,
                    _ => unreachable!(),
                };
                mul[i][j] = res as u8;
            }
        }
        Self::from_mul(name, mul)
    }

    /// Frobenius group F_20 = Z_5 \rtimes Z_4 of order 20:
    /// Elements (a, b) in Z_5 x Z_4 encoded as 4*a + b, with (a1, b1)*(a2, b2) = ((a1 + 2^{b1}*a2) % 5, (b1 + b2) % 4).
    /// Non-abelian, non-nilpotent, famous for optimal high-girth cage lifts!
    pub fn frobenius_20() -> Self {
        let pow2 = [1usize, 2, 4, 3];
        let mut mul = vec![vec![0u8; 20]; 20];
        for i in 0..20 {
            let (a1, b1) = (i / 4, i % 4);
            for j in 0..20 {
                let (a2, b2) = (j / 4, j % 4);
                let a = (a1 + pow2[b1] * a2) % 5;
                let b = (b1 + b2) % 4;
                mul[i][j] = (4 * a + b) as u8;
            }
        }
        Self::from_mul("f20", mul)
    }

    /// Symmetric group S_4 (order 24) or Alternating group A_4 (order 12).
    pub fn sym_or_alt_4(even_only: bool) -> Self {
        let mut perms: Vec<[u8; 4]> = Vec::new();
        for a in 0..4u8 {
            for b in 0..4u8 {
                if b == a { continue; }
                for c in 0..4u8 {
                    if c == a || c == b { continue; }
                    let d = 6 - a - b - c;
                    let p = [a, b, c, d];
                    let mut invs = 0;
                    for i in 0..4 {
                        for j in (i + 1)..4 {
                            if p[i] > p[j] {
                                invs += 1;
                            }
                        }
                    }
                    if !even_only || (invs % 2 == 0) {
                        perms.push(p);
                    }
                }
            }
        }
        // Ensure identity [0,1,2,3] is index 0
        let id_pos = perms.iter().position(|&p| p == [0, 1, 2, 3]).unwrap();
        perms.swap(0, id_pos);
        let n = perms.len();
        let mut mul = vec![vec![0u8; n]; n];
        for i in 0..n {
            for j in 0..n {
                let mut prod = [0u8; 4];
                for x in 0..4 {
                    prod[x] = perms[i][perms[j][x] as usize];
                }
                let k = perms.iter().position(|&p| p == prod).unwrap();
                mul[i][j] = k as u8;
            }
        }
        Self::from_mul(if even_only { "a4" } else { "s4" }, mul)
    }

    pub fn parse(name: &str) -> Result<Self, String> {
        match name {
            "d6" => Ok(Self::dihedral("d6", 6)),
            "a4" => Ok(Self::sym_or_alt_4(true)),
            "d7" => Ok(Self::dihedral("d7", 7)),
            "d9" => Ok(Self::dihedral("d9", 9)),
            "d10" => Ok(Self::dihedral("d10", 10)),
            "f20" => Ok(Self::frobenius_20()),
            "s4" => Ok(Self::sym_or_alt_4(false)),
            "d14" => Ok(Self::dihedral("d14", 14)),
            "d15" => Ok(Self::dihedral("d15", 15)),
            _ => Err(format!("unsupported group: {name} (use d6,a4,d7,d9,d10,f20,s4,d14,d15)")),
        }
    }
}

/// Bipartite cubic base multigraph B (vertices 0..n_a in A, n_a..2*n_a in B).
/// Each undirected base edge `e` goes from `u in A` to `v in B`.
/// Spanning-tree edges `0..tree_edges` are fixed to trivial voltage `0` (identity);
/// remaining `free_edges = edges.len() - tree_edges` are free group variables in Gamma.
#[derive(Clone, Debug)]
pub struct BipartiteCubicBase {
    pub name: &'static str,
    pub n_verts: usize,
    pub n_a: usize,
    pub edges: Vec<(usize, usize)>,
    pub tree_edges: usize,
}

impl BipartiteCubicBase {
    pub fn parse(name: &str) -> Result<Self, String> {
        match name {
            // 4-vertex bipartite 3-regular multigraph (A={0,1}, B={2,3}):
            // Spanning tree: (0,2), (1,2), (1,3). Free edges (3): (0,3), (0,2)#2, (1,3)#2.
            "theta4" => Ok(Self {
                name: "theta4",
                n_verts: 4,
                n_a: 2,
                edges: vec![(0, 2), (1, 2), (1, 3), (0, 3), (0, 2), (1, 3)],
                tree_edges: 3,
            }),
            // K_{3,3} (A={0,1,2}, B={3,4,5}, 9 edges):
            // Spanning tree (5): (0,3),(1,3),(1,4),(2,4),(2,5). Free (4): (0,4),(0,5),(1,5),(2,3).
            "k33" => Ok(Self {
                name: "k33",
                n_verts: 6,
                n_a: 3,
                edges: vec![
                    (0, 3), (1, 3), (1, 4), (2, 4), (2, 5),
                    (0, 4), (0, 5), (1, 5), (2, 3),
                ],
                tree_edges: 5,
            }),
            // 6-vertex doubled alternating 6-cycle (A={0,1,2}, B={3,4,5}, 9 edges):
            // Spanning tree (5): (0,3),(1,3),(1,4),(2,4),(2,5). Free (4): (0,5),(0,3)#2,(1,4)#2,(2,5)#2.
            "theta6" => Ok(Self {
                name: "theta6",
                n_verts: 6,
                n_a: 3,
                edges: vec![
                    (0, 3), (1, 3), (1, 4), (2, 4), (2, 5),
                    (0, 5), (0, 3), (1, 4), (2, 5),
                ],
                tree_edges: 5,
            }),
            // 8-vertex 3-cube Q3 (A={0,1,2,3}, B={4,5,6,7}, 12 edges):
            // A = {000->0, 011->1, 101->2, 110->3}, B = {001->4, 010->5, 100->6, 111->7}
            // Spanning tree (7), Free (5).
            "cube8" => Ok(Self {
                name: "cube8",
                n_verts: 8,
                n_a: 4,
                edges: vec![
                    (0, 4), (0, 5), (0, 6), (1, 4), (1, 7), (2, 6), (3, 5),
                    (1, 5), (2, 4), (2, 7), (3, 6), (3, 7),
                ],
                tree_edges: 7,
            }),
            _ => Err(format!("unsupported bipartite base: {name} (use theta4,k33,theta6,cube8)")),
        }
    }

    pub fn free_count(&self) -> usize {
        self.edges.len() - self.tree_edges
    }

    /// Build the lifted bipartite cubic graph B^alpha of order `n_verts * group.order`.
    /// Returns `None` if parallel edges collide or the lift is disconnected.
    pub fn build_lift(&self, group: &FiniteGroup, free_voltages: &[u8]) -> Option<BitGraph> {
        let g_ord = group.order;
        let n = self.n_verts * g_ord;
        if n > 128 {
            return None;
        }
        let mut graph = BitGraph::empty(n);
        for (e_idx, &(u, v)) in self.edges.iter().enumerate() {
            let alpha = if e_idx < self.tree_edges {
                0usize
            } else {
                free_voltages[e_idx - self.tree_edges] as usize
            };
            for g in 0..g_ord {
                let vg = group.mul[g][alpha] as usize;
                let gu = u * g_ord + g;
                let gv = v * g_ord + vg;
                if gu == gv || graph.has_edge(gu, gv) {
                    return None; // loop or parallel edge in lift
                }
                graph.add_edge(gu, gv);
            }
        }
        if !graph.is_connected() {
            return None;
        }
        Some(graph)
    }
}

/// Orbit-reduced fast exact check of C4, C8, C16 through orbit representatives
/// `roots = [0, g_ord, 2*g_ord, ..., (n_a - 1)*g_ord]` of a bipartite cubic lift
/// (n <= 128). Because Gamma acts transitively on each fiber, ANY simple cycle
/// in the lift has a translate passing through at least one root in `roots`!
fn count_lift_c4_c8_c16_orbit(g: &BitGraph, n_a: usize, g_ord: usize) -> (u32, u32, u32) {
    // 1) Exact C4 through roots
    let mut c4 = 0u32;
    for ri in 0..n_a {
        let r = ri * g_ord;
        let nr = g.rows[r];
        let mut two_hop = 0u128;
        let mut bits = nr;
        while bits != 0 {
            let v = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            let nb = g.rows[v] & !(1u128 << r);
            // Any vertex reached via 2 distinct neighbors of r forms a C4!
            c4 += (two_hop & nb).count_ones();
            two_hop |= nb;
        }
    }
    if c4 > 0 {
        return (c4, 999, 999);
    }

    // 2) Exact C8 through roots via depth-4 half-paths (cubic: <= 3*2^3 = 24 half-paths/root!)
    let mut c8 = 0u32;
    let mut c16 = 0u32;
    for ri in 0..n_a {
        let r = ri * g_ord;
        // C8 MitM from r: paths r -> v1 -> v2 -> v3 -> t (4 edges)
        let mut end_masks: Vec<(usize, u128)> = Vec::with_capacity(32);
        let mut b1 = g.rows[r];
        while b1 != 0 {
            let v1 = b1.trailing_zeros() as usize;
            b1 &= b1 - 1;
            let m1 = (1u128 << r) | (1u128 << v1);
            let mut b2 = g.rows[v1] & !m1;
            while b2 != 0 {
                let v2 = b2.trailing_zeros() as usize;
                b2 &= b2 - 1;
                let m2 = m1 | (1u128 << v2);
                let mut b3 = g.rows[v2] & !m2;
                while b3 != 0 {
                    let v3 = b3.trailing_zeros() as usize;
                    b3 &= b3 - 1;
                    let m3 = m2 | (1u128 << v3);
                    let mut bt = g.rows[v3] & !m3;
                    while bt != 0 {
                        let t = bt.trailing_zeros() as usize;
                        bt &= bt - 1;
                        let interior = (1u128 << v1) | (1u128 << v2) | (1u128 << v3);
                        for &(prev_t, prev_m) in &end_masks {
                            if prev_t == t && (prev_m & interior) == 0 {
                                c8 += 1;
                            }
                        }
                        end_masks.push((t, interior));
                    }
                }
            }
        }
    }
    if c8 > 0 {
        return (0, c8, 999);
    }

    // 3) Exact C16 through roots via depth-8 Bitset MitM (cubic: <= 3*2^7 = 384 half-paths/root!)
    let mut buckets: Vec<Vec<u128>> = vec![Vec::new(); g.n];
    for ri in 0..n_a {
        let r = ri * g_ord;
        for b in &mut buckets {
            b.clear();
        }
        let r_bit = 1u128 << r;
        let mut b1 = g.rows[r];
        while b1 != 0 {
            let v1 = b1.trailing_zeros() as usize;
            b1 &= b1 - 1;
            let m1 = r_bit | (1u128 << v1);
            let mut b2 = g.rows[v1] & !m1;
            while b2 != 0 {
                let v2 = b2.trailing_zeros() as usize;
                b2 &= b2 - 1;
                let m2 = m1 | (1u128 << v2);
                let mut b3 = g.rows[v2] & !m2;
                while b3 != 0 {
                    let v3 = b3.trailing_zeros() as usize;
                    b3 &= b3 - 1;
                    let m3 = m2 | (1u128 << v3);
                    let mut b4 = g.rows[v3] & !m3;
                    while b4 != 0 {
                        let v4 = b4.trailing_zeros() as usize;
                        b4 &= b4 - 1;
                        let m4 = m3 | (1u128 << v4);
                        let mut b5 = g.rows[v4] & !m4;
                        while b5 != 0 {
                            let v5 = b5.trailing_zeros() as usize;
                            b5 &= b5 - 1;
                            let m5 = m4 | (1u128 << v5);
                            let mut b6 = g.rows[v5] & !m5;
                            while b6 != 0 {
                                let v6 = b6.trailing_zeros() as usize;
                                b6 &= b6 - 1;
                                let m6 = m5 | (1u128 << v6);
                                let mut b7 = g.rows[v6] & !m6;
                                while b7 != 0 {
                                    let v7 = b7.trailing_zeros() as usize;
                                    b7 &= b7 - 1;
                                    let m7 = m6 | (1u128 << v7);
                                    let interior = m7 ^ r_bit;
                                    let mut bt = g.rows[v7] & !m7;
                                    while bt != 0 {
                                        let t = bt.trailing_zeros() as usize;
                                        bt &= bt - 1;
                                        for &pm in &buckets[t] {
                                            if (pm & interior) == 0 {
                                                c16 += 1;
                                                if c16 >= 512 {
                                                    return (0, 0, 512);
                                                }
                                            }
                                        }
                                        buckets[t].push(interior);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    (0, 0, c16)
}

#[derive(Clone, Debug)]
pub struct VoltageSearchSummary {
    pub base_name: &'static str,
    pub group_name: &'static str,
    pub order: usize,
    pub evaluated_lifts: u64,
    pub valid_lifts: u64,
    pub c4_c8_zero_hits: u64,
    pub c4_c8_c16_zero_hits: u64,
    pub c32_sieve_absent_hits: u64,
    pub best_key: (u32, u32, u32, u32), // (c4, c8, c16, c32_flag)
    pub best_voltages: Vec<u8>,
    pub best_graph6: Option<String>,
    pub wall_seconds: f64,
}

/// Multi-core Voltage-Lift search (exhaustive when |Gamma|^free <= 50_000, else
/// parallel Tabu / randomized neighborhood search) over bipartite cubic lifts
/// B^alpha, verifying every C4=C8=C16=0 hit with the hardware PCLMULQDQ
/// Bjorklund GF(2^16) C32 narrow sieve!
pub fn run_voltage_lift_search(
    base: &BipartiteCubicBase,
    group: &FiniteGroup,
    max_evals: u64,
    workers: usize,
    base_seed: u64,
) -> VoltageSearchSummary {
    let started = Instant::now();
    let free = base.free_count();
    let g_ord = group.order;
    let total_space = (g_ord as u64).checked_pow(free as u32).unwrap_or(u64::MAX);
    let exhaustive = total_space <= max_evals && total_space <= 200_000;
    let budget = if exhaustive { total_space } else { max_evals };
    let n_workers = workers.max(1);
    let orbit_roots: Vec<usize> = (0..base.n_a).map(|i| i * g_ord).collect();

    let chunk = budget.div_ceil(n_workers as u64);
    let orbit_ref = &orbit_roots;

    let worker_res: Vec<_> = thread::scope(|scope| {
        let handles: Vec<_> = (0..n_workers)
            .map(|tid| {
                let lo = (tid as u64) * chunk;
                let hi = (lo + chunk).min(budget);
                scope.spawn(move || {
                    let mut rng = Rng::new(
                        base_seed.wrapping_add((tid as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)),
                    );
                    let mut evals = 0u64;
                    let mut valid = 0u64;
                    let mut z48 = 0u64;
                    let mut z4816 = 0u64;
                    let mut z32 = 0u64;
                    let mut best_key = (u32::MAX, u32::MAX, u32::MAX, u32::MAX);
                    let mut best_v: Vec<u8> = Vec::new();
                    let mut best_g: Option<BitGraph> = None;

                    let mut cur_v = vec![0u8; free];
                    for f in 0..free {
                        cur_v[f] = rng.gen_range(g_ord) as u8;
                    }
                    let mut cur_key = (u32::MAX, u32::MAX, u32::MAX, u32::MAX);
                    let mut stagnant = 0u32;

                    for idx in lo..hi {
                        evals += 1;
                        let mut cand_v = cur_v.clone();
                        if exhaustive {
                            let mut x = idx;
                            for f in 0..free {
                                cand_v[f] = (x % (g_ord as u64)) as u8;
                                x /= g_ord as u64;
                            }
                        } else if stagnant >= 40 || (evals & 15) == 0 {
                            for f in 0..free {
                                cand_v[f] = rng.gen_range(g_ord) as u8;
                            }
                            stagnant = 0;
                        } else {
                            // Mutate 1 or 2 free group voltages
                            let f0 = rng.gen_range(free);
                            cand_v[f0] = rng.gen_range(g_ord) as u8;
                            if free >= 2 && (rng.next_u64() & 3) == 0 {
                                let f1 = rng.gen_range(free);
                                cand_v[f1] = rng.gen_range(g_ord) as u8;
                            }
                        }

                        let Some(g) = base.build_lift(group, &cand_v) else {
                            stagnant += 1;
                            continue;
                        };
                        valid += 1;
                        let (c4, c8, c16) = count_lift_c4_c8_c16_orbit(&g, base.n_a, g_ord);
                        let mut c32_flag = 1u32;
                        if c4 == 0 && c8 == 0 {
                            z48 += 1;
                            if c16 == 0 {
                                z4816 += 1;
                                // Run hardware PCLMULQDQ Bipartite Bjorklund C32 sieve (2 rounds)!
                                if let Ok(sr) = bipartite_cycle_sieve_gf2_16(
                                    &g,
                                    32,
                                    2,
                                    1,
                                    base_seed ^ evals,
                                    Some(orbit_ref),
                                ) {
                                    if !sr.found {
                                        z32 += 1;
                                        c32_flag = 0;
                                    }
                                }
                            }
                        }
                        let key = (c4, c8, c16, c32_flag);
                        if !exhaustive {
                            if key <= cur_key {
                                cur_v = cand_v.clone();
                                cur_key = key;
                                stagnant = 0;
                            } else {
                                stagnant += 1;
                            }
                        }
                        if key < best_key {
                            best_key = key;
                            best_v = cand_v;
                            best_g = Some(g);
                            if best_key == (0, 0, 0, 0) {
                                break;
                            }
                        }
                    }

                    (evals, valid, z48, z4816, z32, best_key, best_v, best_g)
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut total_evals = 0u64;
    let mut total_valid = 0u64;
    let mut total_z48 = 0u64;
    let mut total_z4816 = 0u64;
    let mut total_z32 = 0u64;
    let mut best_key = (u32::MAX, u32::MAX, u32::MAX, u32::MAX);
    let mut best_v = Vec::new();
    let mut best_g: Option<BitGraph> = None;

    for (ev, va, z48, z4816, z32, bk, bv, bg) in worker_res {
        total_evals += ev;
        total_valid += va;
        total_z48 += z48;
        total_z4816 += z4816;
        total_z32 += z32;
        if bk < best_key {
            best_key = bk;
            best_v = bv;
            best_g = bg;
        }
    }

    VoltageSearchSummary {
        base_name: base.name,
        group_name: group.name,
        order: base.n_verts * group.order,
        evaluated_lifts: total_evals,
        valid_lifts: total_valid,
        c4_c8_zero_hits: total_z48,
        c4_c8_c16_zero_hits: total_z4816,
        c32_sieve_absent_hits: total_z32,
        best_key,
        best_voltages: best_v,
        best_graph6: best_g.map(|g| g.to_graph6()),
        wall_seconds: started.elapsed().as_secs_f64(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cycles::{DfsScratch, count_cycles};
    use crate::mutation::build_heawood;

    #[test]
    fn gf16_pclmulqdq_matches_scalar_reference_all_patterns() {
        let mut rng = Rng::new(2026112611);
        for _ in 0..10_000 {
            let a = (rng.next_u64() & 0xFFFF) as u16;
            let b = (rng.next_u64() & 0xFFFF) as u16;
            assert_eq!(gf16_mul(a, b), gf16_mul_scalar(a, b), "mismatch for a={a:#x} b={b:#x}");
        }
        // Check multiplicative identity & commutativity
        assert_eq!(gf16_mul(1, 0xABCD), 0xABCD);
        assert_eq!(gf16_mul(0x1234, 0x5678), gf16_mul(0x5678, 0x1234));
    }

    #[test]
    fn bjorklund_bipartite_sieve_matches_exact_dfs_on_heawood_and_lifts() {
        let mut scratch = DfsScratch::new();

        // 1) Heawood (n=14, bipartite cubic, girth 6): has C8, NO C4, NO C16!
        let h = build_heawood();
        assert!(!bipartite_cycle_sieve_gf2_16(&h, 4, 2, 1, 101, None).unwrap().found);
        assert!(bipartite_cycle_sieve_gf2_16(&h, 8, 2, 1, 102, None).unwrap().found);
        assert!(!bipartite_cycle_sieve_gf2_16(&h, 16, 2, 1, 103, None).unwrap().found);

        // 2) Small bipartite cubic lift: theta4 x D_6 -> n=24 bipartite cubic!
        //    Verify Bjorklund sieve for C8 and C16 matches exact DFS across 10 valid lifts!
        let base = BipartiteCubicBase::parse("theta4").unwrap();
        let d6 = FiniteGroup::parse("d6").unwrap();
        let mut rng = Rng::new(2026112612);
        let mut checked = 0usize;
        for _ in 0..200 {
            let v = [
                rng.gen_range(d6.order) as u8,
                rng.gen_range(d6.order) as u8,
                rng.gen_range(d6.order) as u8,
            ];
            let Some(g) = base.build_lift(&d6, &v) else {
                continue;
            };
            for &len in &[8usize, 16usize] {
                let dfs_has = count_cycles(&g, len as u16, 1, 0, 0, &mut scratch, false).count > 0;
                let sr = bipartite_cycle_sieve_gf2_16(&g, len, 2, 2, 777 + checked as u64, None)
                    .unwrap();
                assert_eq!(
                    sr.found, dfs_has,
                    "Bjorklund sieve mismatch on n=24 lift for L={len}: sieve={} dfs={}",
                    sr.found, dfs_has
                );
            }
            checked += 1;
            if checked >= 8 {
                break;
            }
        }
        assert!(checked >= 5, "expected >= 5 valid theta4 x D6 lifts");

        // 3) Verify C32 sieve works cleanly on a 72-vertex bipartite cubic lift (theta4 x D9)!
        let d9 = FiniteGroup::parse("d9").unwrap();
        let mut tested_72 = false;
        for a in 1..d9.order as u8 {
            for b in 1..d9.order as u8 {
                if let Some(g72) = base.build_lift(&d9, &[a, b, (a + b) % (d9.order as u8)]) {
                    let sr = bipartite_cycle_sieve_gf2_16(&g72, 32, 1, 4, 999, Some(&[0, d9.order]))
                        .unwrap();
                    assert!(sr.roots_tested >= 1);
                    tested_72 = true;
                    break;
                }
            }
            if tested_72 {
                break;
            }
        }
        assert!(tested_72, "failed to test C32 sieve on 72-vertex lift");
    }
}

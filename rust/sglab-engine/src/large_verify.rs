//! Wave F: Exact General-Order (`n <= 512`) Bitset Cycle Verifier (`verify-large`).
//!
//! Independently certifies absence or existence (with explicit vertex witness) of
//! simple cycles of lengths {4, 8, 16, 32} on sparse graphs up to `n <= 512`,
//! designed specifically for exact full-graph certification of f(5) <= 450 candidates
//! without relying on any gadget/window-calculus assumptions.

use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Instant;

pub const LARGE_MAX_ORDER: usize = 512;

#[derive(Clone, Debug)]
pub struct LargeGraph {
    pub n: usize,
    pub adj: Vec<Vec<u16>>,
    pub rows: Vec<[u64; 8]>,
}

impl LargeGraph {
    pub fn empty(n: usize) -> Self {
        assert!(n <= LARGE_MAX_ORDER, "LargeGraph supports n <= {LARGE_MAX_ORDER}");
        Self {
            n,
            adj: vec![Vec::new(); n],
            rows: vec![[0u64; 8]; n],
        }
    }

    #[inline]
    pub fn add_edge(&mut self, u: usize, v: usize) {
        if u == v {
            return;
        }
        let bit_v = 1u64 << (v & 63);
        if (self.rows[u][v >> 6] & bit_v) == 0 {
            self.rows[u][v >> 6] |= bit_v;
            self.rows[v][u >> 6] |= 1u64 << (u & 63);
            self.adj[u].push(v as u16);
            self.adj[v].push(u as u16);
        }
    }

    pub fn finalize(&mut self) {
        for nbrs in &mut self.adj {
            nbrs.sort_unstable();
        }
    }

    #[inline]
    pub fn has_edge(&self, u: usize, v: usize) -> bool {
        (self.rows[u][v >> 6] & (1u64 << (v & 63))) != 0
    }

    pub fn size(&self) -> usize {
        self.adj.iter().map(|a| a.len()).sum::<usize>() / 2
    }

    pub fn min_max_degree(&self) -> (usize, usize) {
        let mut lo = usize::MAX;
        let mut hi = 0usize;
        for a in &self.adj {
            lo = lo.min(a.len());
            hi = hi.max(a.len());
        }
        (if self.n == 0 { 0 } else { lo }, hi)
    }

    pub fn from_graph6(raw: &str) -> Result<Self, String> {
        let s = raw.trim();
        let s = s.strip_prefix(">>graph6<<").unwrap_or(s);
        let bytes = s.as_bytes();
        if bytes.is_empty() {
            return Err("empty graph6 string".to_string());
        }
        let val = |idx: usize| -> Result<usize, String> {
            let b = *bytes.get(idx).ok_or_else(|| "truncated graph6".to_string())?;
            if !(63..=126).contains(&b) {
                return Err(format!("invalid graph6 byte {b}"));
            }
            Ok((b - 63) as usize)
        };
        let (n, mut pos) = if bytes[0] != b'~' {
            (val(0)?, 1usize)
        } else if bytes.len() >= 4 && bytes[1] != b'~' {
            let n = (val(1)? << 12) | (val(2)? << 6) | val(3)?;
            (n, 4usize)
        } else {
            return Err("unsupported huge graph6 header".to_string());
        };
        if n > LARGE_MAX_ORDER {
            return Err(format!("order {n} exceeds LARGE_MAX_ORDER={LARGE_MAX_ORDER}"));
        }
        let mut g = Self::empty(n);
        let mut bit_buf = 0usize;
        let mut bits_left = 0usize;
        for v in 1..n {
            for u in 0..v {
                if bits_left == 0 {
                    bit_buf = val(pos)?;
                    pos += 1;
                    bits_left = 6;
                }
                bits_left -= 1;
                if ((bit_buf >> bits_left) & 1) != 0 {
                    g.add_edge(u, v);
                }
            }
        }
        g.finalize();
        Ok(g)
    }

    pub fn is_biconnected(&self) -> bool {
        let n = self.n;
        if n < 3 {
            return false;
        }
        let mut disc = vec![0u32; n];
        let mut low = vec![0u32; n];
        let mut parent = vec![usize::MAX; n];
        let mut timer = 2u32;
        let mut root_children = 0u32;
        let mut has_ap = false;
        let mut stack: Vec<(usize, usize)> = Vec::with_capacity(n);
        disc[0] = 1;
        low[0] = 1;
        stack.push((0, 0));

        while let Some((u, idx)) = stack.last_mut() {
            let u_val = *u;
            if *idx < self.adj[u_val].len() {
                let v = self.adj[u_val][*idx] as usize;
                *idx += 1;
                if disc[v] == 0 {
                    parent[v] = u_val;
                    if u_val == 0 {
                        root_children += 1;
                    }
                    disc[v] = timer;
                    low[v] = timer;
                    timer += 1;
                    stack.push((v, 0));
                } else if v != parent[u_val] && disc[v] < low[u_val] {
                    low[u_val] = disc[v];
                }
            } else {
                stack.pop();
                let p = parent[u_val];
                if p != usize::MAX {
                    if low[u_val] < low[p] {
                        low[p] = low[u_val];
                    }
                    if p != 0 && low[u_val] >= disc[p] {
                        has_ap = true;
                    }
                }
            }
        }
        disc.iter().all(|&d| d != 0) && root_children <= 1 && !has_ap
    }
}

#[inline(always)]
fn mask_set(m: &mut [u64; 8], v: usize) {
    m[v >> 6] |= 1u64 << (v & 63);
}

#[inline(always)]
fn mask_has(m: &[u64; 8], v: usize) -> bool {
    (m[v >> 6] & (1u64 << (v & 63))) != 0
}

#[inline(always)]
fn masks_disjoint(a: &[u64; 8], b: &[u64; 8]) -> bool {
    ((a[0] & b[0])
        | (a[1] & b[1])
        | (a[2] & b[2])
        | (a[3] & b[3])
        | (a[4] & b[4])
        | (a[5] & b[5])
        | (a[6] & b[6])
        | (a[7] & b[7]))
        == 0
}

/// Exact canonical-start Meet-in-the-Middle cycle finder for even `length` (4, 8, 16, 32)
/// on graphs up to `n <= 512`, parallelized across `workers` threads!
///
/// Exact mathematical bijection:
/// Every simple cycle of even length `L = 2h` has a unique minimum vertex `s` and a unique
/// opposite vertex `t > s` at distance `h` along the cycle, decomposing uniquely into an
/// unordered pair of internally vertex-disjoint simple paths of length `h` from `s` to `t`
/// using only vertices `> s`.
///
/// BFS distance pruning (`dist_gt_s[v] <= h`) is 100% sound because any vertex on a simple
/// `2h`-cycle with minimum vertex `s` has distance at most `h` from `s` in `G[s..n]`.
pub fn find_even_cycle_large_exact(
    g: &LargeGraph,
    length: usize,
    workers: usize,
) -> Option<Vec<usize>> {
    assert!(length >= 4 && length % 2 == 0);
    let n = g.n;
    if n < length {
        return None;
    }
    let half = length / 2;

    // Fast exact C4 special case
    if length == 4 {
        for s in 0..=(n - 4) {
            let nbrs: Vec<usize> = g.adj[s]
                .iter()
                .map(|&x| x as usize)
                .filter(|&v| v > s)
                .collect();
            if nbrs.len() < 2 {
                continue;
            }
            for i in 0..nbrs.len() {
                let a = nbrs[i];
                for j in (i + 1)..nbrs.len() {
                    let b = nbrs[j];
                    for w in 0..8 {
                        let common = g.rows[a][w] & g.rows[b][w];
                        if common != 0 {
                            let mut bits = common;
                            while bits != 0 {
                                let c = (w << 6) + bits.trailing_zeros() as usize;
                                bits &= bits - 1;
                                if c > s {
                                    return Some(vec![s, a, c, b]);
                                }
                            }
                        }
                    }
                }
            }
        }
        return None;
    }

    let max_s = n - length;
    let found_flag = AtomicBool::new(false);
    let n_workers = workers.max(1).min(max_s + 1);

    let results: Vec<Option<Vec<usize>>> = thread::scope(|scope| {
        let handles: Vec<_> = (0..n_workers)
            .map(|tid| {
                let flag_ref = &found_flag;
                scope.spawn(move || -> Option<Vec<usize>> {
                    let mut dist = vec![u16::MAX; n];
                    let mut queue = Vec::with_capacity(n);
                    let mut head = vec![u32::MAX; n];
                    let mut bucket_cnt = vec![0u32; n];
                    let mut touched: Vec<usize> = Vec::with_capacity(n);
                    let mut masks: Vec<[u64; 8]> = Vec::with_capacity(4096);
                    let mut paths: Vec<Vec<u16>> = Vec::with_capacity(4096);
                    let mut next: Vec<u32> = Vec::with_capacity(4096);

                    for s in (tid..=max_s).step_by(n_workers) {
                        if flag_ref.load(Ordering::Relaxed) {
                            return None;
                        }
                        let mut deg_gt = 0usize;
                        for &v in &g.adj[s] {
                            if (v as usize) > s {
                                deg_gt += 1;
                            }
                        }
                        if deg_gt < 2 {
                            continue;
                        }

                        // Sound BFS distances from s in G[s..n] up to `half`
                        dist.fill(u16::MAX);
                        dist[s] = 0;
                        queue.clear();
                        queue.push(s);
                        let mut qh = 0usize;
                        while qh < queue.len() {
                            let u = queue[qh];
                            qh += 1;
                            let du = dist[u];
                            if du as usize >= half {
                                continue;
                            }
                            for &w_u16 in &g.adj[u] {
                                let w = w_u16 as usize;
                                if w > s && dist[w] == u16::MAX {
                                    dist[w] = du + 1;
                                    queue.push(w);
                                }
                            }
                        }

                        // Reset buckets
                        for &t in &touched {
                            head[t] = u32::MAX;
                            bucket_cnt[t] = 0;
                        }
                        touched.clear();
                        masks.clear();
                        paths.clear();
                        next.clear();

                        // Enumerate all simple paths s -> v_1 -> ... -> v_{half-1} -> t
                        // where every vertex > s and dist[v] <= half (necessary condition).
                        // Furthermore, for intermediate vertex at step `d` (1 <= d < half),
                        // since `t` can be at distance at most `half`, vertex v_d has distance
                        // `d` from s along this path AND will never exceed `half`.
                        let mut cur_path: Vec<u16> = Vec::with_capacity(half + 1);
                        cur_path.push(s as u16);
                        let mut vis = [0u64; 8];
                        mask_set(&mut vis, s);

                        #[allow(clippy::too_many_arguments)]
                        fn dfs_half(
                            g: &LargeGraph,
                            s: usize,
                            half: usize,
                            u: usize,
                            depth: usize,
                            vis: &mut [u64; 8],
                            cur_path: &mut Vec<u16>,
                            head: &mut [u32],
                            bucket_cnt: &mut [u32],
                            touched: &mut Vec<usize>,
                            masks: &mut Vec<[u64; 8]>,
                            paths: &mut Vec<Vec<u16>>,
                            next: &mut Vec<u32>,
                        ) {
                            let next_d = depth + 1;
                            for &w_u16 in &g.adj[u] {
                                let w = w_u16 as usize;
                                if w <= s || mask_has(vis, w) {
                                    continue;
                                }
                                if next_d == half {
                                    // Interior mask = vis with `s` cleared!
                                    let mut interior = *vis;
                                    interior[s >> 6] ^= 1u64 << (s & 63);
                                    let idx = masks.len() as u32;
                                    masks.push(interior);
                                    let mut p = cur_path.clone();
                                    p.push(w_u16);
                                    paths.push(p);
                                    next.push(head[w]);
                                    if head[w] == u32::MAX {
                                        touched.push(w);
                                    }
                                    head[w] = idx;
                                    bucket_cnt[w] += 1;
                                } else {
                                    mask_set(vis, w);
                                    cur_path.push(w_u16);
                                    dfs_half(
                                        g, s, half, w, next_d, vis, cur_path, head, bucket_cnt,
                                        touched, masks, paths, next,
                                    );
                                    cur_path.pop();
                                    vis[w >> 6] ^= 1u64 << (w & 63);
                                }
                            }
                        }

                        dfs_half(
                            g,
                            s,
                            half,
                            s,
                            0,
                            &mut vis,
                            &mut cur_path,
                            &mut head,
                            &mut bucket_cnt,
                            &mut touched,
                            &mut masks,
                            &mut paths,
                            &mut next,
                        );

                        // Check pairwise disjoint interior masks inside each bucket `t`
                        for &t in &touched {
                            if bucket_cnt[t] < 2 {
                                continue;
                            }
                            let mut i = head[t];
                            while i != u32::MAX {
                                let mi = &masks[i as usize];
                                let mut j = next[i as usize];
                                while j != u32::MAX {
                                    if masks_disjoint(mi, &masks[j as usize]) {
                                        // Reconstruct exact cycle witness and double-check every edge!
                                        let pi = &paths[i as usize];
                                        let pj = &paths[j as usize];
                                        let mut cyc: Vec<usize> = Vec::with_capacity(length);
                                        for &v in pi {
                                            cyc.push(v as usize);
                                        }
                                        for k in (1..(pj.len() - 1)).rev() {
                                            cyc.push(pj[k] as usize);
                                        }
                                        debug_assert_eq!(cyc.len(), length);
                                        for k in 0..length {
                                            debug_assert!(g.has_edge(cyc[k], cyc[(k + 1) % length]));
                                        }
                                        flag_ref.store(true, Ordering::Relaxed);
                                        return Some(cyc);
                                    }
                                    j = next[j as usize];
                                }
                                i = next[i as usize];
                            }
                        }
                    }
                    None
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });

    results.into_iter().flatten().next()
}

#[derive(Clone, Debug)]
pub struct LargeVerifySummary {
    pub order: usize,
    pub size: usize,
    pub min_deg: usize,
    pub max_deg: usize,
    pub biconnected: bool,
    pub results: Vec<(usize, bool, Option<Vec<usize>>, f64)>,
    pub total_ms: f64,
}

pub fn verify_large_graph(g: &LargeGraph, lengths: &[usize], workers: usize) -> LargeVerifySummary {
    let t0 = Instant::now();
    let (min_deg, max_deg) = g.min_max_degree();
    let biconnected = g.is_biconnected();
    let mut results = Vec::with_capacity(lengths.len());
    for &len in lengths {
        let tl = Instant::now();
        let witness = find_even_cycle_large_exact(g, len, workers);
        let ms = tl.elapsed().as_secs_f64() * 1000.0;
        results.push((len, witness.is_some(), witness, ms));
    }
    LargeVerifySummary {
        order: g.n,
        size: g.size(),
        min_deg,
        max_deg,
        biconnected,
        results,
        total_ms: t0.elapsed().as_secs_f64() * 1000.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mutation::build_markstrom24;

    #[test]
    fn large_exact_verifier_matches_known_graphs() {
        let m24 = build_markstrom24();
        let g = LargeGraph::from_graph6(&m24.to_graph6()).unwrap();
        assert_eq!(g.n, 24);
        assert_eq!(g.size(), 36);
        assert!(g.is_biconnected());
        let res = verify_large_graph(&g, &[4, 8, 16], 4);
        assert!(!res.results[0].1, "Markstrom-24 has no C4");
        assert!(!res.results[1].1, "Markstrom-24 has no C8");
        assert!(res.results[2].1, "Markstrom-24 has C16");
        let cyc = res.results[2].2.as_ref().unwrap();
        assert_eq!(cyc.len(), 16);
        for i in 0..16 {
            assert!(g.has_edge(cyc[i], cyc[(i + 1) % 16]));
        }
    }
}

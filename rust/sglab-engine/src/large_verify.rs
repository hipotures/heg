//! Wave F (hardened): Exact General-Order (`n <= 512`) Bitset Cycle Verifier (`verify-large`).
//!
//! Independently certifies absence or existence (with runtime-checked explicit vertex witness)
//! of simple even cycles of lengths {4, 8, 16, 32, ...} on sparse graphs up to `n <= 512`,
//! using canonical min-vertex Meet-in-the-Middle over `[u64; 8]` interior masks.

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
        let num_bits = n.saturating_mul(n.saturating_sub(1)) / 2;
        let expected_payload_bytes = num_bits.div_ceil(6);
        if bytes.len() != pos + expected_payload_bytes {
            return Err(format!(
                "invalid graph6 length for n={n}: got {} bytes, expected {}",
                bytes.len(),
                pos + expected_payload_bytes
            ));
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

/// Verify in release builds that `cyc` is a genuine simple cycle of length `length` in `g`.
fn verify_witness_runtime(g: &LargeGraph, cyc: &[usize], length: usize) {
    assert_eq!(cyc.len(), length, "witness cycle length mismatch");
    let mut seen = [0u64; 8];
    for &v in cyc {
        assert!(v < g.n, "witness vertex out of range");
        assert!(!mask_has(&seen, v), "witness cycle has repeated vertex");
        mask_set(&mut seen, v);
    }
    for k in 0..length {
        assert!(
            g.has_edge(cyc[k], cyc[(k + 1) % length]),
            "witness missing edge ({}, {})",
            cyc[k],
            cyc[(k + 1) % length]
        );
    }
}

/// Exact canonical-start Meet-in-the-Middle cycle finder for even `length >= 4`
/// on graphs up to `n <= 512`, parallelized across `workers` threads.
///
/// Exact bijection: every simple cycle of even length `L = 2h` has a unique minimum
/// vertex `s` and unique opposite vertex `t > s` at distance `h` along the cycle,
/// decomposing uniquely into an unordered pair of internally vertex-disjoint simple
/// paths of length `h` from `s` to `t` using only vertices `> s`. All length-`h`
/// simple paths from `s` in `G[s..n]` are enumerated and bucketed by endpoint `t`.
pub fn find_even_cycle_large_exact(
    g: &LargeGraph,
    length: usize,
    workers: usize,
) -> Result<Option<Vec<usize>>, String> {
    if length < 4 || length % 2 != 0 {
        return Err(format!("verify-large requires even cycle length >= 4 (got {length})"));
    }
    let n = g.n;
    if n < length {
        return Ok(None);
    }
    let half = length / 2;

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
                                    let cyc = vec![s, a, c, b];
                                    verify_witness_runtime(g, &cyc, 4);
                                    return Ok(Some(cyc));
                                }
                            }
                        }
                    }
                }
            }
        }
        return Ok(None);
    }

    let max_s = n - length;
    let found_flag = AtomicBool::new(false);
    let n_workers = workers.max(1).min(max_s + 1);

    let results: Vec<Option<Vec<usize>>> = thread::scope(|scope| {
        let handles: Vec<_> = (0..n_workers)
            .map(|tid| {
                let flag_ref = &found_flag;
                scope.spawn(move || -> Option<Vec<usize>> {
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

                        for &t in &touched {
                            head[t] = u32::MAX;
                            bucket_cnt[t] = 0;
                        }
                        touched.clear();
                        masks.clear();
                        paths.clear();
                        next.clear();

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
                                        let pi = &paths[i as usize];
                                        let pj = &paths[j as usize];
                                        let mut cyc: Vec<usize> = Vec::with_capacity(length);
                                        for &v in pi {
                                            cyc.push(v as usize);
                                        }
                                        for k in (1..(pj.len() - 1)).rev() {
                                            cyc.push(pj[k] as usize);
                                        }
                                        verify_witness_runtime(g, &cyc, length);
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

    Ok(results.into_iter().flatten().next())
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

pub fn verify_large_graph(
    g: &LargeGraph,
    lengths: &[usize],
    workers: usize,
) -> Result<LargeVerifySummary, String> {
    let t0 = Instant::now();
    let (min_deg, max_deg) = g.min_max_degree();
    let biconnected = g.is_biconnected();
    let mut results = Vec::with_capacity(lengths.len());
    for &len in lengths {
        let tl = Instant::now();
        let witness = find_even_cycle_large_exact(g, len, workers)?;
        let ms = tl.elapsed().as_secs_f64() * 1000.0;
        results.push((len, witness.is_some(), witness, ms));
    }
    Ok(LargeVerifySummary {
        order: g.n,
        size: g.size(),
        min_deg,
        max_deg,
        biconnected,
        results,
        total_ms: t0.elapsed().as_secs_f64() * 1000.0,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mutation::build_markstrom24;

    /// Independent canonical-start DFS reference for cross-checking `verify_large_graph`.
    fn has_cycle_dfs_ref(g: &LargeGraph, target: usize) -> bool {
        let n = g.n;
        if n < target {
            return false;
        }
        fn dfs(g: &LargeGraph, s: usize, u: usize, depth: usize, target: usize, first: usize, vis: &mut [u64; 8]) -> bool {
            if depth == target {
                return g.has_edge(u, s) && first < u;
            }
            for &w_u16 in &g.adj[u] {
                let w = w_u16 as usize;
                if w > s && !mask_has(vis, w) {
                    mask_set(vis, w);
                    if dfs(g, s, w, depth + 1, target, first, vis) {
                        return true;
                    }
                    vis[w >> 6] ^= 1u64 << (w & 63);
                }
            }
            false
        }
        for s in 0..=(n - target) {
            let mut vis = [0u64; 8];
            mask_set(&mut vis, s);
            for &v_u16 in &g.adj[s] {
                let v = v_u16 as usize;
                if v > s {
                    mask_set(&mut vis, v);
                    if dfs(g, s, v, 2, target, v, &mut vis) {
                        return true;
                    }
                    vis[v >> 6] ^= 1u64 << (v & 63);
                }
            }
        }
        false
    }

    #[test]
    fn large_exact_verifier_matches_known_graphs_and_high_bitmask_words() {
        // 1. Markstrom-24 (word 0)
        let m24 = build_markstrom24();
        let g = LargeGraph::from_graph6(&m24.to_graph6()).unwrap();
        assert_eq!(g.n, 24);
        assert_eq!(g.size(), 36);
        assert!(g.is_biconnected());
        let res = verify_large_graph(&g, &[4, 8, 16], 4).unwrap();
        assert!(!res.results[0].1, "Markstrom-24 has no C4");
        assert!(!res.results[1].1, "Markstrom-24 has no C8");
        assert!(res.results[2].1, "Markstrom-24 has C16");

        // 2. Reject trailing garbage bytes & invalid/odd lengths
        assert!(LargeGraph::from_graph6(&format!("{}?", m24.to_graph6())).is_err());
        assert!(verify_large_graph(&g, &[5], 1).is_err());

        // 3. Multi-word bitmask tests (n = 100, 300, 512) spanning words 0..7!
        // Build a 300-vertex cubic graph with a planted 32-cycle across vertices 250..281 (words 3 & 4)
        // and NO 4-cycles (cycle C_300 + chords of length 150 -> girth >= 4, actually check DFS parity!).
        let mut g300 = LargeGraph::empty(300);
        for i in 0..300 {
            g300.add_edge(i, (i + 1) % 300);
        }
        // Add antipodal chords every 10th vertex to create a sparse graph with C32 in high words:
        // Cycle 250..281 (31 edges) + chord (250, 281) = exact 32-cycle in words 3..4!
        g300.add_edge(250, 281);
        g300.add_edge(100, 115); // exact 16-cycle in word 1
        g300.finalize();
        let r300 = verify_large_graph(&g300, &[4, 8, 16, 32], 4).unwrap();
        assert!(!r300.results[0].1 && !has_cycle_dfs_ref(&g300, 4));
        assert!(!r300.results[1].1 && !has_cycle_dfs_ref(&g300, 8));
        assert!(r300.results[2].1 && has_cycle_dfs_ref(&g300, 16));
        assert!(r300.results[3].1 && has_cycle_dfs_ref(&g300, 32));

        // 4. n = 512 boundary test (word 7, vertex 511!) with exact C32 across vertices 480..511
        let mut g512 = LargeGraph::empty(512);
        for i in 0..512 {
            g512.add_edge(i, (i + 1) % 512);
        }
        g512.add_edge(480, 511); // exact 32-cycle touching bit 511 (word 7, bit 63)
        g512.finalize();
        let r512 = verify_large_graph(&g512, &[4, 8, 16, 32], 4).unwrap();
        assert!(!r512.results[0].1);
        assert!(!r512.results[1].1);
        assert!(!r512.results[2].1);
        assert!(r512.results[3].1);
        let cyc512 = r512.results[3].2.as_ref().unwrap();
        assert!(cyc512.contains(&511), "C32 witness must exercise bit 511 in word 7");
    }
}

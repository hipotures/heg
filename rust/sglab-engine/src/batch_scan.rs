//! High-throughput parallel batch cycle scanner for graph6, sparse6, PSV TSV, and Conder edge-list
//! censuses, with exact Meet-in-the-Middle detection for C4/C8/C16/C32, guided MitM for C64+,
//! vertex-transitive single-root acceleration, runtime witness certification, and witness streams.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InputFormat {
    Graph6,
    Sparse6,
    PsvTsv,
    ConderEdges,
}

impl InputFormat {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "g6" | "graph6" => Ok(Self::Graph6),
            "s6" | "sparse6" => Ok(Self::Sparse6),
            "psv-tsv" | "psv" => Ok(Self::PsvTsv),
            "conder-edges" | "conder" => Ok(Self::ConderEdges),
            other => Err(format!(
                "unknown --format '{other}' (expected: g6, s6, psv-tsv, conder-edges)"
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScanMode {
    General,
    VertexTransitive,
}

impl ScanMode {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "general" => Ok(Self::General),
            "vertex-transitive" | "vt" => Ok(Self::VertexTransitive),
            other => Err(format!(
                "unknown --mode '{other}' (expected: general, vertex-transitive)"
            )),
        }
    }
}

#[derive(Clone, Debug)]
pub struct SparseGraph {
    pub id: String,
    pub n: usize,
    pub adj: Vec<Vec<u16>>,
    pub meta_girth: Option<usize>,
    pub meta_bipartite: Option<bool>,
    pub meta_cayley: Option<bool>,
    pub meta_arc_transitive: Option<bool>,
}

impl SparseGraph {
    pub fn empty(id: String, n: usize) -> Self {
        Self {
            id,
            n,
            adj: vec![Vec::new(); n],
            meta_girth: None,
            meta_bipartite: None,
            meta_cayley: None,
            meta_arc_transitive: None,
        }
    }

    pub fn add_edge(&mut self, u: usize, v: usize) -> Result<(), String> {
        if u >= self.n || v >= self.n {
            return Err(format!(
                "graph {}: edge ({u}, {v}) out of range n={}",
                self.id, self.n
            ));
        }
        if u == v {
            return Err(format!("graph {}: self-loop at {u}", self.id));
        }
        let vu = v as u16;
        if !self.adj[u].contains(&vu) {
            self.adj[u].push(vu);
            self.adj[v].push(u as u16);
        }
        Ok(())
    }

    pub fn finalize(&mut self) {
        for a in &mut self.adj {
            a.sort_unstable();
        }
    }

    pub fn has_edge(&self, u: usize, v: usize) -> bool {
        self.adj[u].binary_search(&(v as u16)).is_ok()
    }

    pub fn is_cubic(&self) -> bool {
        self.n >= 4 && self.adj.iter().all(|a| a.len() == 3)
    }

    pub fn from_graph6(id: String, raw: &str) -> Result<Self, String> {
        let s = raw.trim();
        let s = s.strip_prefix(">>graph6<<").unwrap_or(s);
        let bytes = s.as_bytes();
        if bytes.is_empty() {
            return Err("empty graph6".to_string());
        }
        let val = |idx: usize| -> Result<usize, String> {
            let b = *bytes
                .get(idx)
                .ok_or_else(|| format!("graph {id}: truncated graph6"))?;
            if !(63..=126).contains(&b) {
                return Err(format!("graph {id}: invalid graph6 byte {b}"));
            }
            Ok((b - 63) as usize)
        };
        let (n, mut pos) = if bytes[0] != b'~' {
            (val(0)?, 1usize)
        } else if bytes.len() >= 4 && bytes[1] != b'~' {
            ((val(1)? << 12) | (val(2)? << 6) | val(3)?, 4usize)
        } else {
            return Err(format!("graph {id}: unsupported huge graph6 header"));
        };
        let num_bits = n.saturating_mul(n.saturating_sub(1)) / 2;
        let expected_payload = num_bits.div_ceil(6);
        if bytes.len() != pos + expected_payload {
            return Err(format!(
                "graph {id}: invalid graph6 length for n={n} (got {}, expected {})",
                bytes.len(),
                pos + expected_payload
            ));
        }
        let mut g = Self::empty(id.clone(), n);
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
                    g.adj[u].push(v as u16);
                    g.adj[v].push(u as u16);
                }
            }
        }
        g.finalize();
        Ok(g)
    }

    pub fn from_sparse6(id: String, raw: &str) -> Result<Self, String> {
        let s = raw.trim();
        let s = s.strip_prefix(">>sparse6<<").unwrap_or(s);
        let bytes = s.as_bytes();
        if bytes.len() < 2 || bytes[0] != b':' {
            return Err(format!("graph {id}: sparse6 must start with ':'"));
        }
        let val = |idx: usize| -> Result<usize, String> {
            let b = *bytes
                .get(idx)
                .ok_or_else(|| format!("graph {id}: truncated sparse6"))?;
            if !(63..=126).contains(&b) {
                return Err(format!("graph {id}: invalid sparse6 byte {b}"));
            }
            Ok((b - 63) as usize)
        };
        let (n, pos) = if bytes[1] != b'~' {
            (val(1)?, 2usize)
        } else if bytes.len() >= 5 && bytes[2] != b'~' {
            ((val(2)? << 12) | (val(3)? << 6) | val(4)?, 5usize)
        } else {
            return Err(format!("graph {id}: unsupported huge sparse6 header"));
        };
        let mut g = Self::empty(id.clone(), n);
        if n <= 1 {
            return Ok(g);
        }
        let k = (usize::BITS - (n - 1).leading_zeros()) as usize;
        let payload = &bytes[pos..];
        let total_bits = payload.len() * 6;
        let mut bit_idx = 0usize;
        let read_bit = |bi: &mut usize| -> Result<usize, String> {
            let byte_i = *bi / 6;
            let shift = 5 - (*bi % 6);
            *bi += 1;
            let b = payload[byte_i];
            if !(63..=126).contains(&b) {
                return Err(format!("graph {id}: invalid sparse6 payload byte {b}"));
            }
            Ok((((b - 63) as usize) >> shift) & 1)
        };
        let mut v = 0usize;
        while bit_idx + 1 + k <= total_bits {
            let b_flag = read_bit(&mut bit_idx)?;
            let mut x = 0usize;
            for _ in 0..k {
                x = (x << 1) | read_bit(&mut bit_idx)?;
            }
            if b_flag == 1 {
                v += 1;
            }
            if v >= n || x >= n {
                break;
            }
            if x > v {
                v = x;
            } else if x < v {
                g.add_edge(x, v)?;
            }
        }
        g.finalize();
        Ok(g)
    }

    pub fn from_psv_tsv_line(line: &str) -> Result<Option<Self>, String> {
        let s = line.trim();
        if s.is_empty() || s.starts_with("id|") {
            return Ok(None);
        }
        let cols = split_pipe_quoted(s);
        if cols.len() < 11 {
            return Err(format!("malformed PSV TSV line (cols={}): {:.60}", cols.len(), s));
        }
        let id = format!("psv:{}", cols[0]);
        let order: usize = cols[2]
            .parse()
            .map_err(|_| format!("PSV {id}: bad graph_order '{}'", cols[2]))?;
        let s6 = &cols[3];
        let mut g = Self::from_sparse6(id.clone(), s6)?;
        if g.n != order {
            return Err(format!(
                "PSV {id}: decoded sparse6 order {} != graph_order {order}",
                g.n
            ));
        }
        g.meta_girth = cols[7].parse::<usize>().ok();
        g.meta_arc_transitive = match cols[8].as_str() {
            "1" => Some(true),
            "0" => Some(false),
            _ => None,
        };
        g.meta_bipartite = match cols[9].as_str() {
            "1" => Some(true),
            "0" => Some(false),
            _ => None,
        };
        g.meta_cayley = match cols[10].as_str() {
            "1" => Some(true),
            "0" => Some(false),
            _ => None,
        };
        Ok(Some(g))
    }
}

/// Split a `|`-delimited CSV line honoring standard `"..."` quoting (needed because sparse6
/// payloads can contain literal `|` = ASCII 124). Only needs the first 12 columns.
fn split_pipe_quoted(line: &str) -> Vec<String> {
    let mut cols = Vec::with_capacity(12);
    let mut cur = String::new();
    let bytes = line.as_bytes();
    let mut i = 0;
    let mut in_quotes = false;
    while i < bytes.len() {
        let b = bytes[i];
        if in_quotes {
            if b == b'"' {
                if i + 1 < bytes.len() && bytes[i + 1] == b'"' {
                    cur.push('"');
                    i += 2;
                    continue;
                } else {
                    in_quotes = false;
                }
            } else {
                cur.push(b as char);
            }
        } else if b == b'"' && cur.is_empty() {
            in_quotes = true;
        } else if b == b'|' {
            cols.push(std::mem::take(&mut cur));
            if cols.len() >= 12 {
                return cols;
            }
        } else {
            cur.push(b as char);
        }
        i += 1;
    }
    cols.push(cur);
    cols
}

/// Stream parser for Marston Conder's `AllSymmCubic-OrderUpTo10000-ByEdgeSets.txt`.
pub fn load_conder_graphs<R: BufRead>(reader: R, max_order: Option<usize>) -> Result<Vec<SparseGraph>, String> {
    let mut out = Vec::new();
    let mut cur_id = String::new();
    let mut cur_girth: Option<usize> = None;
    let mut cur_bip: Option<bool> = None;
    let mut in_graph = false;
    let mut cur_graph: Option<SparseGraph> = None;
    let mut skip_current = false;

    for (lineno, line_res) in reader.lines().enumerate() {
        let line = line_res.map_err(|e| format!("I/O error at line {}: {e}", lineno + 1))?;
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        if t.starts_with("//") {
            // e.g.: // C10.1 : |Aut(X)| = 120 : Type 3 : Girth 5 : Diameter 2 : Non-bipartite
            let rest = t.trim_start_matches('/').trim();
            if let Some(first_tok) = rest.split_whitespace().next() {
                if first_tok.starts_with('C') {
                    cur_id = first_tok.to_string();
                }
            }
            cur_girth = None;
            cur_bip = None;
            for part in rest.split(':') {
                let p = part.trim();
                if let Some(gstr) = p.strip_prefix("Girth ") {
                    cur_girth = gstr.trim().parse::<usize>().ok();
                } else if p.eq_ignore_ascii_case("Bipartite") {
                    cur_bip = Some(true);
                } else if p.eq_ignore_ascii_case("Non-bipartite") {
                    cur_bip = Some(false);
                }
            }
            continue;
        }
        if !in_graph {
            if let Some(gpos) = t.find("Graph<") {
                let after = &t[gpos + 6..];
                let bar = after
                    .find('|')
                    .ok_or_else(|| format!("Conder line {}: missing '|' in Graph<", lineno + 1))?;
                let n: usize = after[..bar]
                    .trim()
                    .parse()
                    .map_err(|_| format!("Conder line {}: bad order", lineno + 1))?;
                let id = if !cur_id.is_empty() {
                    cur_id.clone()
                } else {
                    format!("C{n}.{}", out.len() + 1)
                };
                in_graph = true;
                if max_order.is_some_and(|m| n > m) {
                    skip_current = true;
                    cur_graph = None;
                } else {
                    skip_current = false;
                    let mut g = SparseGraph::empty(id, n);
                    g.meta_girth = cur_girth;
                    g.meta_bipartite = cur_bip;
                    g.meta_arc_transitive = Some(true);
                    cur_graph = Some(g);
                }
                // Parse any edges on the same line after '|'
                let edge_part = &after[bar + 1..];
                if !skip_current {
                    parse_conder_edge_pairs(edge_part, cur_graph.as_mut().unwrap(), lineno + 1)?;
                }
                if t.contains(">;") {
                    in_graph = false;
                    if let Some(mut g) = cur_graph.take() {
                        g.finalize();
                        out.push(g);
                    }
                    skip_current = false;
                }
            }
        } else {
            if !skip_current {
                parse_conder_edge_pairs(t, cur_graph.as_mut().unwrap(), lineno + 1)?;
            }
            if t.contains(">;") {
                in_graph = false;
                if let Some(mut g) = cur_graph.take() {
                    g.finalize();
                    out.push(g);
                }
                skip_current = false;
            }
        }
    }
    Ok(out)
}

fn parse_conder_edge_pairs(s: &str, g: &mut SparseGraph, lineno: usize) -> Result<(), String> {
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'{' {
            // Check if this is an edge `{u,v}` (starts with digit after optional spaces)
            let mut j = i + 1;
            while j < bytes.len() && bytes[j].is_ascii_whitespace() {
                j += 1;
            }
            if j < bytes.len() && bytes[j].is_ascii_digit() {
                let close = s[j..]
                    .find('}')
                    .ok_or_else(|| format!("Conder line {lineno}: unclosed '{{'"))?
                    + j;
                let inner = &s[j..close];
                let comma = inner
                    .find(',')
                    .ok_or_else(|| format!("Conder line {lineno}: missing ',' in '{inner}'"))?;
                let u1: usize = inner[..comma]
                    .trim()
                    .parse()
                    .map_err(|_| format!("Conder line {lineno}: bad vertex in '{inner}'"))?;
                let v1: usize = inner[comma + 1..]
                    .trim()
                    .parse()
                    .map_err(|_| format!("Conder line {lineno}: bad vertex in '{inner}'"))?;
                if u1 == 0 || v1 == 0 {
                    return Err(format!("Conder line {lineno}: expected 1-based vertex, got ({u1},{v1})"));
                }
                g.add_edge(u1 - 1, v1 - 1)?;
                i = close + 1;
                continue;
            }
        }
        i += 1;
    }
    Ok(())
}

/// Mandatory runtime witness verifier (runs in release builds too).
pub fn verify_cycle_witness(g: &SparseGraph, cyc: &[u16], expected_len: usize) {
    assert_eq!(
        cyc.len(),
        expected_len,
        "graph {}: witness length mismatch (got {}, expected {})",
        g.id,
        cyc.len(),
        expected_len
    );
    for (idx, &v) in cyc.iter().enumerate() {
        let vu = v as usize;
        assert!(vu < g.n, "graph {}: witness vertex {vu} >= n={}", g.id, g.n);
        for &w in &cyc[idx + 1..] {
            assert_ne!(v, w, "graph {}: witness repeats vertex {v}", g.id);
        }
        let next = cyc[(idx + 1) % expected_len] as usize;
        assert!(
            g.has_edge(vu, next),
            "graph {}: witness missing edge ({vu}, {next})",
            g.id
        );
    }
}

/// Compact path entry for Meet-in-the-Middle half-paths of length `half <= 16`.
/// Stores `interior` vertices (length `half - 1`) and a 64-bit bloom signature of interior vertices.
#[derive(Clone)]
struct HalfPath16 {
    bloom: u64,
    interior: [u16; 15],
}

#[inline(always)]
fn interior_disjoint_16(a: &HalfPath16, b: &HalfPath16, int_len: usize) -> bool {
    if (a.bloom & b.bloom) == 0 {
        return true;
    }
    for i in 0..int_len {
        let x = a.interior[i];
        for j in 0..int_len {
            if x == b.interior[j] {
                return false;
            }
        }
    }
    true
}

/// Reusable scratch memory per worker thread (zero inner-loop allocations for sparse graphs).
pub struct WorkerScratch {
    vis_gen: Vec<u32>,
    cur_gen: u32,
    bucket_gen: Vec<u32>,
    cur_bgen: u32,
    buckets16: Vec<Vec<HalfPath16>>,
    buckets_dyn: Vec<Vec<(u64, Vec<u16>)>>,
    u64_buckets: Vec<Vec<(u64, [u8; 8])>>,
}

impl WorkerScratch {
    pub fn new() -> Self {
        Self {
            vis_gen: Vec::new(),
            cur_gen: 1,
            bucket_gen: Vec::new(),
            cur_bgen: 1,
            buckets16: Vec::new(),
            buckets_dyn: Vec::new(),
            u64_buckets: vec![Vec::new(); 64],
        }
    }

    fn ensure_n(&mut self, n: usize) {
        if self.vis_gen.len() < n {
            self.vis_gen.resize(n, 0);
            self.bucket_gen.resize(n, 0);
            self.buckets16.resize_with(n, Vec::new);
            self.buckets_dyn.resize_with(n, Vec::new);
        }
    }

    fn next_vis_gen(&mut self, n: usize) -> u32 {
        self.ensure_n(n);
        self.cur_gen = self.cur_gen.wrapping_add(1);
        if self.cur_gen == 0 {
            self.vis_gen.fill(0);
            self.cur_gen = 1;
        }
        self.cur_gen
    }

    fn next_bucket_gen(&mut self, n: usize) -> u32 {
        self.ensure_n(n);
        self.cur_bgen = self.cur_bgen.wrapping_add(1);
        if self.cur_bgen == 0 {
            self.bucket_gen.fill(0);
            self.cur_bgen = 1;
        }
        self.cur_bgen
    }
}

/// Fast exact u64 MitM cycle finder for `n <= 64`, `length in {4, 8, 16}` (general mode).
fn find_even_cycle_u64_exact(
    rows: &[u64; 64],
    n: usize,
    length: usize,
    scratch: &mut WorkerScratch,
) -> Option<Vec<u16>> {
    if n < length || length < 4 || length % 2 != 0 {
        return None;
    }
    let half = length / 2;
    if length == 4 {
        for s in 0..=(n - 4) {
            let hi = !0u64 << (s + 1);
            let mut m1 = rows[s] & hi;
            while m1 != 0 {
                let a = m1.trailing_zeros() as usize;
                m1 &= m1 - 1;
                let mut m2 = m1;
                while m2 != 0 {
                    let b = m2.trailing_zeros() as usize;
                    m2 &= m2 - 1;
                    let common = rows[a] & rows[b] & hi;
                    if common != 0 {
                        let t = common.trailing_zeros() as usize;
                        return Some(vec![s as u16, a as u16, t as u16, b as u16]);
                    }
                }
            }
        }
        return None;
    }

    assert!(half <= 8, "u64 fast path supports length <= 16");
    for s in 0..=(n - length) {
        let hi = if s + 1 < 64 { !0u64 << (s + 1) } else { 0u64 };
        for t in (s + 1)..n {
            scratch.u64_buckets[t].clear();
        }
        let mut path = [0u8; 8];
        let found = dfs_u64_half(
            rows,
            s,
            s,
            0,
            half,
            hi,
            0u64,
            &mut path,
            &mut scratch.u64_buckets,
        );
        if found.is_some() {
            return found;
        }
    }
    None
}

#[allow(clippy::too_many_arguments)]
fn dfs_u64_half(
    rows: &[u64; 64],
    s: usize,
    u: usize,
    depth: usize,
    half: usize,
    hi: u64,
    int_mask: u64,
    path: &mut [u8; 8],
    buckets: &mut [Vec<(u64, [u8; 8])>],
) -> Option<Vec<u16>> {
    let mut cand = rows[u] & hi & !int_mask;
    if depth + 1 == half {
        while cand != 0 {
            let t = cand.trailing_zeros() as usize;
            cand &= cand - 1;
            let b = &mut buckets[t];
            for (other_mask, other_path) in b.iter() {
                if (other_mask & int_mask) == 0 {
                    let mut cyc = Vec::with_capacity(half * 2);
                    cyc.push(s as u16);
                    for i in 0..(half - 1) {
                        cyc.push(path[i] as u16);
                    }
                    cyc.push(t as u16);
                    for i in (0..(half - 1)).rev() {
                        cyc.push(other_path[i] as u16);
                    }
                    return Some(cyc);
                }
            }
            b.push((int_mask, *path));
        }
        return None;
    }
    while cand != 0 {
        let w = cand.trailing_zeros() as usize;
        cand &= cand - 1;
        path[depth] = w as u8;
        if let Some(cyc) = dfs_u64_half(
            rows,
            s,
            w,
            depth + 1,
            half,
            hi,
            int_mask | (1u64 << w),
            path,
            buckets,
        ) {
            return Some(cyc);
        }
    }
    None
}

/// Exact MitM cycle finder for `length in {4, 8, 16, 32}` (`half <= 16`) on ANY `SparseGraph` (`n <= 65535`).
/// If `min_vertex_only` is true (vertex-transitive mode), checks ONLY cycles containing vertex `0`.
/// Otherwise, checks every canonical min-vertex `s in 0..=n-length` using only vertices `> s`.
pub fn find_even_cycle_mitm_le32(
    g: &SparseGraph,
    length: usize,
    only_root_zero: bool,
    scratch: &mut WorkerScratch,
) -> Option<Vec<u16>> {
    let n = g.n;
    if n < length || length < 4 || length % 2 != 0 || length > 32 {
        return None;
    }
    let half = length / 2;
    let int_len = half - 1;
    let max_s = if only_root_zero { 0 } else { n - length };

    for s in 0..=max_s {
        let vgen = scratch.next_vis_gen(n);
        let bgen = scratch.next_bucket_gen(n);
        scratch.vis_gen[s] = vgen;

        let mut interior = [0u16; 15];
        let found = dfs_mitm_le32(
            g,
            s,
            s,
            0,
            half,
            int_len,
            only_root_zero,
            0u64,
            &mut interior,
            vgen,
            bgen,
            &mut scratch.vis_gen,
            &mut scratch.bucket_gen,
            &mut scratch.buckets16,
        );
        if found.is_some() {
            return found;
        }
    }
    None
}

#[allow(clippy::too_many_arguments)]
fn dfs_mitm_le32(
    g: &SparseGraph,
    s: usize,
    u: usize,
    depth: usize,
    half: usize,
    int_len: usize,
    only_root_zero: bool,
    bloom: u64,
    interior: &mut [u16; 15],
    vgen: u32,
    bgen: u32,
    vis_gen: &mut [u32],
    bucket_gen: &mut [u32],
    buckets: &mut [Vec<HalfPath16>],
) -> Option<Vec<u16>> {
    if depth + 1 == half {
        for &w16 in &g.adj[u] {
            let t = w16 as usize;
            if (!only_root_zero && t <= s) || vis_gen[t] == vgen {
                continue;
            }
            if bucket_gen[t] != bgen {
                bucket_gen[t] = bgen;
                buckets[t].clear();
            }
            let cur = HalfPath16 {
                bloom,
                interior: *interior,
            };
            for other in &buckets[t] {
                if interior_disjoint_16(&cur, other, int_len) {
                    let mut cyc = Vec::with_capacity(half * 2);
                    cyc.push(s as u16);
                    for i in 0..int_len {
                        cyc.push(cur.interior[i]);
                    }
                    cyc.push(t as u16);
                    for i in (0..int_len).rev() {
                        cyc.push(other.interior[i]);
                    }
                    return Some(cyc);
                }
            }
            buckets[t].push(cur);
        }
        return None;
    }

    for &w16 in &g.adj[u] {
        let w = w16 as usize;
        if (!only_root_zero && w <= s) || vis_gen[w] == vgen {
            continue;
        }
        vis_gen[w] = vgen;
        interior[depth] = w16;
        let next_bloom = bloom | (1u64 << (w & 63));
        let res = dfs_mitm_le32(
            g,
            s,
            w,
            depth + 1,
            half,
            int_len,
            only_root_zero,
            next_bloom,
            interior,
            vgen,
            bgen,
            vis_gen,
            bucket_gen,
            buckets,
        );
        vis_gen[w] = 0;
        if res.is_some() {
            return res;
        }
    }
    None
}

/// Guided/budgeted Meet-in-the-Middle for large even cycle lengths `L >= 64` (e.g. C64, C128, C256, ...).
/// Uses randomized DFS half-paths of length `L / 2` from `s = 0` (or several roots in general mode),
/// bucketed by endpoint `t` with immediate exact disjointness verification.
/// Any returned witness is 100% certified by `verify_cycle_witness`; `None` means not found within budget.
pub fn find_even_cycle_large_guided(
    g: &SparseGraph,
    length: usize,
    only_root_zero: bool,
    path_budget: usize,
    scratch: &mut WorkerScratch,
) -> Option<Vec<u16>> {
    let n = g.n;
    if n < length || length < 4 || length % 2 != 0 {
        return None;
    }
    let half = length / 2;
    let roots: Vec<usize> = if only_root_zero {
        vec![0]
    } else {
        (0..n.min(8)).collect()
    };
    let budget_per_root = (path_budget / roots.len().max(1)).max(4096);

    let mut rng_state = 0x9e37_79b9_7f4a_7c15u64 ^ ((n as u64) << 17) ^ (length as u64);
    let mut next_u64 = || -> u64 {
        rng_state ^= rng_state << 13;
        rng_state ^= rng_state >> 7;
        rng_state ^= rng_state << 17;
        rng_state
    };

    for s in roots {
        let bgen = scratch.next_bucket_gen(n);
        let mut path = Vec::with_capacity(half);
        for _ in 0..budget_per_root {
            let vgen = scratch.next_vis_gen(n);
            scratch.vis_gen[s] = vgen;
            path.clear();
            let mut u = s;
            let mut bloom = 0u64;
            let mut ok = true;
            for step in 0..half {
                let nbrs = &g.adj[u];
                let mut choices = [0u16; 16];
                let mut nc = 0usize;
                for &w16 in nbrs {
                    if scratch.vis_gen[w16 as usize] != vgen {
                        if nc < choices.len() {
                            choices[nc] = w16;
                            nc += 1;
                        }
                    }
                }
                if nc == 0 {
                    ok = false;
                    break;
                }
                let pick = choices[(next_u64() as usize) % nc];
                scratch.vis_gen[pick as usize] = vgen;
                if step + 1 < half {
                    path.push(pick);
                    bloom |= 1u64 << ((pick as usize) & 63);
                }
                u = pick as usize;
            }
            if !ok {
                continue;
            }
            let t = u;
            if scratch.bucket_gen[t] != bgen {
                scratch.bucket_gen[t] = bgen;
                scratch.buckets_dyn[t].clear();
            }
            // Check disjointness against stored paths to endpoint t
            for (obloom, opath) in &scratch.buckets_dyn[t] {
                let mut disj = (obloom & bloom) == 0;
                if !disj {
                    disj = true;
                    'outer: for &a in &path {
                        for &b in opath {
                            if a == b {
                                disj = false;
                                break 'outer;
                            }
                        }
                    }
                }
                if disj {
                    let mut cyc = Vec::with_capacity(length);
                    cyc.push(s as u16);
                    cyc.extend_from_slice(&path);
                    cyc.push(t as u16);
                    for &v in opath.iter().rev() {
                        cyc.push(v);
                    }
                    return Some(cyc);
                }
            }
            if scratch.buckets_dyn[t].len() < 64 {
                scratch.buckets_dyn[t].push((bloom, path.clone()));
            }
        }
    }
    None
}

/// Find the shortest cycle in `lengths` (sorted ascending) for `g`.
/// Returns `Some((len, witness))` (already runtime-verified) or `None`.
pub fn find_first_cycle(
    g: &SparseGraph,
    lengths: &[usize],
    mode: ScanMode,
    scratch: &mut WorkerScratch,
) -> Option<(usize, Vec<u16>)> {
    let only_root_zero = mode == ScanMode::VertexTransitive;

    // Ultra-fast u64 path for general mode on n <= 64 and length <= 16
    let mut rows_u64 = [0u64; 64];
    let use_u64 = !only_root_zero && g.n <= 64;
    if use_u64 {
        for u in 0..g.n {
            let mut m = 0u64;
            for &v in &g.adj[u] {
                m |= 1u64 << (v as usize);
            }
            rows_u64[u] = m;
        }
    }

    for &len in lengths {
        if len > g.n {
            break;
        }
        let found = if use_u64 && len <= 16 {
            find_even_cycle_u64_exact(&rows_u64, g.n, len, scratch)
        } else if len <= 32 {
            find_even_cycle_mitm_le32(g, len, only_root_zero, scratch)
        } else {
            find_even_cycle_large_guided(g, len, only_root_zero, 200_000, scratch)
        };
        if let Some(cyc) = found {
            verify_cycle_witness(g, &cyc, len);
            return Some((len, cyc));
        }
    }
    None
}

pub struct BatchScanConfig {
    pub input: String,
    pub format: InputFormat,
    pub mode: ScanMode,
    pub lengths: Vec<usize>,
    pub workers: usize,
    pub expect_cubic: bool,
    pub max_order: Option<usize>,
    pub witness_out: Option<String>,
    pub exceptions_out: Option<String>,
    pub exception_min_len: usize,
    pub summary_json: Option<String>,
}

struct GraphOutcome {
    id: String,
    n: usize,
    found_len: Option<usize>,
    witness: Option<Vec<u16>>,
    meta_girth: Option<usize>,
    meta_bipartite: Option<bool>,
    meta_cayley: Option<bool>,
    meta_arc_transitive: Option<bool>,
}

pub fn run_batch_scan(cfg: &BatchScanConfig) -> Result<(), String> {
    let t0 = Instant::now();
    let workers = cfg.workers.max(1);

    let mut lengths = cfg.lengths.clone();
    lengths.sort_unstable();
    lengths.dedup();

    // Open input (file path or "-" for stdin)
    let reader: Box<dyn BufRead> = if cfg.input == "-" {
        Box::new(BufReader::with_capacity(1 << 20, io::stdin()))
    } else {
        let f = File::open(&cfg.input)
            .map_err(|e| format!("failed to open '{}': {e}", cfg.input))?;
        Box::new(BufReader::with_capacity(1 << 20, f))
    };

    let mut witness_writer = match &cfg.witness_out {
        Some(p) => {
            let f = File::create(p).map_err(|e| format!("failed to create '{p}': {e}"))?;
            Some(BufWriter::with_capacity(1 << 20, f))
        }
        None => None,
    };
    let mut exc_writer = match &cfg.exceptions_out {
        Some(p) => {
            let f = File::create(p).map_err(|e| format!("failed to create '{p}': {e}"))?;
            Some(BufWriter::with_capacity(1 << 16, f))
        }
        None => None,
    };

    let mut total_graphs = 0usize;
    let mut cubic_violations = 0usize;
    let mut counts_by_len: BTreeMap<String, usize> = BTreeMap::new();
    let mut counts_by_order: BTreeMap<usize, BTreeMap<String, usize>> = BTreeMap::new();
    let mut counts_by_girth: BTreeMap<usize, BTreeMap<String, usize>> = BTreeMap::new();
    let mut counts_bip: BTreeMap<String, BTreeMap<String, usize>> = BTreeMap::new();
    let mut counts_cayley: BTreeMap<String, BTreeMap<String, usize>> = BTreeMap::new();
    let mut none_ids: Vec<(String, usize)> = Vec::new();
    let mut high_len_examples: Vec<(String, usize, usize)> = Vec::new();

    let process_chunk = |chunk: Vec<SparseGraph>,
                         witness_writer: &mut Option<BufWriter<File>>,
                         exc_writer: &mut Option<BufWriter<File>>,
                         total_graphs: &mut usize,
                         cubic_violations: &mut usize,
                         counts_by_len: &mut BTreeMap<String, usize>,
                         counts_by_order: &mut BTreeMap<usize, BTreeMap<String, usize>>,
                         counts_by_girth: &mut BTreeMap<usize, BTreeMap<String, usize>>,
                         counts_bip: &mut BTreeMap<String, BTreeMap<String, usize>>,
                         counts_cayley: &mut BTreeMap<String, BTreeMap<String, usize>>,
                         none_ids: &mut Vec<(String, usize)>,
                         high_len_examples: &mut Vec<(String, usize, usize)>|
     -> Result<(), String> {
        if chunk.is_empty() {
            return Ok(());
        }
        let n_items = chunk.len();
        let next_idx = AtomicUsize::new(0);
        let results: Mutex<Vec<Option<GraphOutcome>>> =
            Mutex::new((0..n_items).map(|_| None).collect());
        let first_err: Mutex<Option<String>> = Mutex::new(None);
        let expect_cubic = cfg.expect_cubic;
        let mode = cfg.mode;
        let lengths_ref = &lengths;

        thread::scope(|scope| {
            for _ in 0..workers {
                scope.spawn(|| {
                    let mut scratch = WorkerScratch::new();
                    loop {
                        let idx = next_idx.fetch_add(1, Ordering::Relaxed);
                        if idx >= n_items {
                            break;
                        }
                        let g = &chunk[idx];
                        if expect_cubic && !g.is_cubic() {
                            let mut err = first_err.lock().unwrap();
                            if err.is_none() {
                                *err = Some(format!(
                                    "graph {} (n={}) failed --expect-cubic check",
                                    g.id, g.n
                                ));
                            }
                            continue;
                        }
                        let found = find_first_cycle(g, lengths_ref, mode, &mut scratch);
                        let (found_len, witness) = match found {
                            Some((l, w)) => (Some(l), Some(w)),
                            None => (None, None),
                        };
                        let outcome = GraphOutcome {
                            id: g.id.clone(),
                            n: g.n,
                            found_len,
                            witness,
                            meta_girth: g.meta_girth,
                            meta_bipartite: g.meta_bipartite,
                            meta_cayley: g.meta_cayley,
                            meta_arc_transitive: g.meta_arc_transitive,
                        };
                        results.lock().unwrap()[idx] = Some(outcome);
                    }
                });
            }
        });

        if let Some(err) = first_err.into_inner().unwrap() {
            *cubic_violations += 1;
            return Err(err);
        }

        let outcomes = results.into_inner().unwrap();
        for item in outcomes {
            let out = item.unwrap();
            *total_graphs += 1;
            let key = match out.found_len {
                Some(l) => l.to_string(),
                None => "NONE".to_string(),
            };
            *counts_by_len.entry(key.clone()).or_insert(0) += 1;
            *counts_by_order
                .entry(out.n)
                .or_default()
                .entry(key.clone())
                .or_insert(0) += 1;
            if let Some(mg) = out.meta_girth {
                *counts_by_girth
                    .entry(mg)
                    .or_default()
                    .entry(key.clone())
                    .or_insert(0) += 1;
            }
            if let Some(mb) = out.meta_bipartite {
                let bk = if mb { "bipartite" } else { "non_bipartite" }.to_string();
                *counts_bip
                    .entry(bk)
                    .or_default()
                    .entry(key.clone())
                    .or_insert(0) += 1;
            }
            if let Some(mc) = out.meta_cayley {
                let ck = if mc { "cayley" } else { "non_cayley" }.to_string();
                *counts_cayley
                    .entry(ck)
                    .or_default()
                    .entry(key.clone())
                    .or_insert(0) += 1;
            }
            if let Some(w) = witness_writer.as_mut() {
                if let (Some(l), Some(cyc)) = (out.found_len, out.witness.as_ref()) {
                    write!(w, "{}\t{}\t{}\t", out.id, out.n, l)
                        .map_err(|e| format!("write witness error: {e}"))?;
                    for (ci, &v) in cyc.iter().enumerate() {
                        if ci > 0 {
                            w.write_all(b",").map_err(|e| format!("write witness error: {e}"))?;
                        }
                        write!(w, "{v}").map_err(|e| format!("write witness error: {e}"))?;
                    }
                    w.write_all(b"\n").map_err(|e| format!("write witness error: {e}"))?;
                } else {
                    writeln!(w, "{}\t{}\tNONE\t", out.id, out.n)
                        .map_err(|e| format!("write witness error: {e}"))?;
                }
            }
            let is_exc = match out.found_len {
                None => true,
                Some(l) => l >= cfg.exception_min_len,
            };
            if is_exc {
                if out.found_len.is_none() {
                    if none_ids.len() < 100 {
                        none_ids.push((out.id.clone(), out.n));
                    }
                } else if let Some(l) = out.found_len {
                    if high_len_examples.len() < 100 {
                        high_len_examples.push((out.id.clone(), out.n, l));
                    }
                }
                if let Some(ew) = exc_writer.as_mut() {
                    let gstr = out
                        .meta_girth
                        .map(|x| x.to_string())
                        .unwrap_or_else(|| "-".to_string());
                    let bstr = out
                        .meta_bipartite
                        .map(|x| if x { "1" } else { "0" })
                        .unwrap_or("-");
                    let astr = out
                        .meta_arc_transitive
                        .map(|x| if x { "1" } else { "0" })
                        .unwrap_or("-");
                    writeln!(
                        ew,
                        "{}\tn={}\tlen={}\tgirth={}\tbip={}\tat={}",
                        out.id, out.n, key, gstr, bstr, astr
                    )
                    .map_err(|e| format!("write exception error: {e}"))?;
                }
            }
        }
        Ok(())
    };

    const CHUNK_SIZE: usize = 4096;
    match cfg.format {
        InputFormat::ConderEdges => {
            let graphs = load_conder_graphs(reader, cfg.max_order)?;
            for slice in graphs.chunks(CHUNK_SIZE) {
                process_chunk(
                    slice.to_vec(),
                    &mut witness_writer,
                    &mut exc_writer,
                    &mut total_graphs,
                    &mut cubic_violations,
                    &mut counts_by_len,
                    &mut counts_by_order,
                    &mut counts_by_girth,
                    &mut counts_bip,
                    &mut counts_cayley,
                    &mut none_ids,
                    &mut high_len_examples,
                )?;
            }
        }
        InputFormat::Graph6 | InputFormat::Sparse6 | InputFormat::PsvTsv => {
            let mut chunk = Vec::with_capacity(CHUNK_SIZE);
            let mut seq = 0usize;
            for line_res in reader.lines() {
                let line = line_res.map_err(|e| format!("I/O error: {e}"))?;
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let parsed = match cfg.format {
                    InputFormat::Graph6 => {
                        seq += 1;
                        Some(SparseGraph::from_graph6(seq.to_string(), trimmed)?)
                    }
                    InputFormat::Sparse6 => {
                        seq += 1;
                        Some(SparseGraph::from_sparse6(seq.to_string(), trimmed)?)
                    }
                    InputFormat::PsvTsv => SparseGraph::from_psv_tsv_line(trimmed)?,
                    InputFormat::ConderEdges => unreachable!(),
                };
                if let Some(g) = parsed {
                    if cfg.max_order.is_some_and(|m| g.n > m) {
                        continue;
                    }
                    chunk.push(g);
                    if chunk.len() >= CHUNK_SIZE {
                        let batch = std::mem::replace(&mut chunk, Vec::with_capacity(CHUNK_SIZE));
                        process_chunk(
                            batch,
                            &mut witness_writer,
                            &mut exc_writer,
                            &mut total_graphs,
                            &mut cubic_violations,
                            &mut counts_by_len,
                            &mut counts_by_order,
                            &mut counts_by_girth,
                            &mut counts_bip,
                            &mut counts_cayley,
                            &mut none_ids,
                            &mut high_len_examples,
                        )?;
                    }
                }
            }
            if !chunk.is_empty() {
                process_chunk(
                    chunk,
                    &mut witness_writer,
                    &mut exc_writer,
                    &mut total_graphs,
                    &mut cubic_violations,
                    &mut counts_by_len,
                    &mut counts_by_order,
                    &mut counts_by_girth,
                    &mut counts_bip,
                    &mut counts_cayley,
                    &mut none_ids,
                    &mut high_len_examples,
                )?;
            }
        }
    }

    if let Some(mut w) = witness_writer {
        w.flush().map_err(|e| format!("flush witness error: {e}"))?;
    }
    if let Some(mut ew) = exc_writer {
        ew.flush().map_err(|e| format!("flush exception error: {e}"))?;
    }

    let elapsed = t0.elapsed().as_secs_f64();
    let rate = if elapsed > 0.0 {
        (total_graphs as f64) / elapsed
    } else {
        0.0
    };

    let fmt_map = |m: &BTreeMap<String, usize>| -> String {
        let parts: Vec<String> = m.iter().map(|(k, v)| format!("\"{k}\":{v}")).collect();
        format!("{{{}}}", parts.join(","))
    };
    let fmt_nested_usize = |m: &BTreeMap<usize, BTreeMap<String, usize>>| -> String {
        let parts: Vec<String> = m
            .iter()
            .map(|(k, v)| format!("\"{k}\":{}", fmt_map(v)))
            .collect();
        format!("{{{}}}", parts.join(","))
    };
    let fmt_nested_str = |m: &BTreeMap<String, BTreeMap<String, usize>>| -> String {
        let parts: Vec<String> = m
            .iter()
            .map(|(k, v)| format!("\"{k}\":{}", fmt_map(v)))
            .collect();
        format!("{{{}}}", parts.join(","))
    };
    let none_json: Vec<String> = none_ids
        .iter()
        .map(|(id, n)| format!("{{\"id\":\"{id}\",\"n\":{n}}}"))
        .collect();
    let high_json: Vec<String> = high_len_examples
        .iter()
        .map(|(id, n, l)| format!("{{\"id\":\"{id}\",\"n\":{n},\"len\":{l}}}"))
        .collect();

    let summary = format!(
        "{{\"total_graphs\":{total_graphs},\"cubic_violations\":{cubic_violations},\"mode\":\"{}\",\"workers\":{workers},\"elapsed_seconds\":{elapsed:.3},\"graphs_per_second\":{rate:.1},\"counts_by_shortest_len\":{},\"counts_by_girth\":{},\"counts_by_bipartite\":{},\"counts_by_cayley\":{},\"counts_by_order\":{},\"none_examples\":[{}],\"high_len_examples\":[{}]}}",
        match cfg.mode {
            ScanMode::General => "general",
            ScanMode::VertexTransitive => "vertex-transitive",
        },
        fmt_map(&counts_by_len),
        fmt_nested_usize(&counts_by_girth),
        fmt_nested_str(&counts_bip),
        fmt_nested_str(&counts_cayley),
        fmt_nested_usize(&counts_by_order),
        none_json.join(","),
        high_json.join(","),
    );

    if let Some(p) = &cfg.summary_json {
        std::fs::write(p, format!("{summary}\n"))
            .map_err(|e| format!("failed to write summary '{p}': {e}"))?;
    }
    println!("{summary}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sparse6_k4_and_prism() {
        let k4 = SparseGraph::from_sparse6("k4".to_string(), ":CcKI").unwrap();
        assert_eq!(k4.n, 4);
        assert!(k4.is_cubic());
        let mut sc = WorkerScratch::new();
        let (l_gen, w_gen) = find_first_cycle(&k4, &[4, 8], ScanMode::General, &mut sc).unwrap();
        assert_eq!(l_gen, 4);
        verify_cycle_witness(&k4, &w_gen, 4);
        let (l_vt, w_vt) =
            find_first_cycle(&k4, &[4, 8], ScanMode::VertexTransitive, &mut sc).unwrap();
        assert_eq!(l_vt, 4);
        verify_cycle_witness(&k4, &w_vt, 4);

        let prism = SparseGraph::from_sparse6("prism".to_string(), ":Ea@aRgs").unwrap();
        assert_eq!(prism.n, 6);
        assert!(prism.is_cubic());
        let (lp, wp) = find_first_cycle(&prism, &[4, 8], ScanMode::General, &mut sc).unwrap();
        assert_eq!(lp, 4);
        verify_cycle_witness(&prism, &wp, 4);
    }

    #[test]
    fn test_petersen_and_tutte_coxeter_general_vs_vt() {
        // Petersen graph (n=10, girth 5, has C8, no C4)
        let pet = SparseGraph::from_graph6("petersen".to_string(), "IheA@GUAo").unwrap();
        assert_eq!(pet.n, 10);
        assert!(pet.is_cubic());
        let mut sc = WorkerScratch::new();
        let (lg, wg) = find_first_cycle(&pet, &[4, 8], ScanMode::General, &mut sc).unwrap();
        let (lv, wv) = find_first_cycle(&pet, &[4, 8], ScanMode::VertexTransitive, &mut sc).unwrap();
        assert_eq!(lg, 8);
        assert_eq!(lv, 8);
        verify_cycle_witness(&pet, &wg, 8);
        verify_cycle_witness(&pet, &wv, 8);

        // Tutte-Coxeter (n=30, girth 8, has C8, no C4)
        let lcf = [-13isize, -9, 7, -7, 9, 13];
        let mut tc = SparseGraph::empty("tc".to_string(), 30);
        for i in 0..30usize {
            tc.add_edge(i, (i + 1) % 30).unwrap();
            let j = ((i as isize + lcf[i % 6]).rem_euclid(30)) as usize;
            tc.add_edge(i, j).unwrap();
        }
        tc.finalize();
        assert!(tc.is_cubic());
        let (l1, _) = find_first_cycle(&tc, &[4, 8, 16], ScanMode::General, &mut sc).unwrap();
        let (l2, _) =
            find_first_cycle(&tc, &[4, 8, 16], ScanMode::VertexTransitive, &mut sc).unwrap();
        assert_eq!(l1, 8);
        assert_eq!(l2, 8);
        // Also check C16 exists in TC
        let (l16g, w16g) = find_first_cycle(&tc, &[16], ScanMode::General, &mut sc).unwrap();
        let (l16v, w16v) =
            find_first_cycle(&tc, &[16], ScanMode::VertexTransitive, &mut sc).unwrap();
        assert_eq!(l16g, 16);
        assert_eq!(l16v, 16);
        verify_cycle_witness(&tc, &w16g, 16);
        verify_cycle_witness(&tc, &w16v, 16);
    }

    #[test]
    fn test_conder_parser() {
        let sample = r#"
// C6.1 : |Aut(X)| = 72 : Type 3 : Girth 4 : Diameter 2 : Bipartite
CubicAT[6,1] := Graph< 6 | {
  {1,2}, {1,3}, {1,4}, {2,5}, {2,6}, {3,5}, {3,6},
  {4,5}, {4,6} } >;
"#;
        let graphs = load_conder_graphs(sample.as_bytes(), None).unwrap();
        assert_eq!(graphs.len(), 1);
        assert_eq!(graphs[0].id, "C6.1");
        assert_eq!(graphs[0].n, 6);
        assert_eq!(graphs[0].meta_girth, Some(4));
        assert_eq!(graphs[0].meta_bipartite, Some(true));
        assert!(graphs[0].is_cubic());
    }

    #[test]
    fn test_f5_n370_absent_c4_c8_c16_c32() {
        let g6_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6");
        let raw = std::fs::read_to_string(g6_path).unwrap();
        let g = SparseGraph::from_graph6("n370".to_string(), raw.trim()).unwrap();
        assert_eq!(g.n, 370);
        assert!(g.is_cubic());
        let mut sc = WorkerScratch::new();
        // Verify C4/C8/C16/C32 absent via root 0 check (necessary condition) and C4/C8/C16 general
        assert!(find_first_cycle(&g, &[4, 8, 16], ScanMode::General, &mut sc).is_none());
        assert!(find_first_cycle(&g, &[4, 8, 16, 32], ScanMode::VertexTransitive, &mut sc).is_none());
        // Verify C64 IS found by guided MitM
        let (l64, w64) = find_first_cycle(&g, &[64], ScanMode::General, &mut sc).unwrap();
        assert_eq!(l64, 64);
        verify_cycle_witness(&g, &w64, 64);
    }
}

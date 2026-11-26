//! Stack-allocated BitGraph (128-vertex general + 64-vertex L1-resident fast path)
//! with graph6 I/O, Tarjan block counting, and Zobrist hashing.

use std::sync::OnceLock;

pub const MAX_ORDER: usize = 128;

pub type Edge = (u8, u8);

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct BitGraph {
    pub n: usize,
    pub rows: [u128; MAX_ORDER],
}

/// Compact 512-byte (8 cache lines) adjacency representation for n <= 64.
/// Every bitset operation compiles to single native x86_64/BMI1 instructions.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct BitGraph64 {
    pub n: usize,
    pub rows: [u64; 64],
}

impl BitGraph64 {
    #[allow(dead_code)]
    #[inline]
    pub fn empty(n: usize) -> Self {
        debug_assert!(n <= 64);
        Self { n, rows: [0u64; 64] }
    }

    #[inline]
    pub fn from_graph(g: &BitGraph) -> Self {
        debug_assert!(g.n <= 64);
        let mut rows = [0u64; 64];
        for u in 0..g.n {
            rows[u] = g.rows[u] as u64;
        }
        Self { n: g.n, rows }
    }

    #[inline]
    pub fn to_graph(&self) -> BitGraph {
        let mut g = BitGraph::empty(self.n);
        for u in 0..self.n {
            g.rows[u] = self.rows[u] as u128;
        }
        g
    }

    #[inline]
    pub fn add_edge(&mut self, u: usize, v: usize) {
        self.rows[u] |= 1u64 << v;
        self.rows[v] |= 1u64 << u;
    }

    #[inline]
    pub fn remove_edge(&mut self, u: usize, v: usize) {
        self.rows[u] &= !(1u64 << v);
        self.rows[v] &= !(1u64 << u);
    }

    #[inline]
    pub fn has_edge(&self, u: usize, v: usize) -> bool {
        (self.rows[u] & (1u64 << v)) != 0
    }

    #[inline]
    pub fn degree(&self, u: usize) -> u32 {
        self.rows[u].count_ones()
    }

    #[inline]
    pub fn size(&self) -> u32 {
        let mut total = 0u32;
        for u in 0..self.n {
            total += self.rows[u].count_ones();
        }
        total / 2
    }

    #[inline]
    pub fn is_connected(&self) -> bool {
        if self.n <= 1 {
            return true;
        }
        let mut seen: u64 = 1u64;
        let mut frontier: u64 = 1u64;
        while frontier != 0 {
            let mut next: u64 = 0;
            let mut f = frontier;
            while f != 0 {
                let u = f.trailing_zeros() as usize;
                f &= f - 1;
                next |= self.rows[u];
            }
            frontier = next & !seen;
            seen |= frontier;
        }
        seen.count_ones() as usize == self.n
    }

    /// Fast bidirectional reachability check: after removing (a,b),(c,d) and
    /// adding (a,c),(b,d) on a connected graph, the result is connected iff
    /// `a` can reach `b`. Typically terminates in 2 expansions!
    #[inline]
    pub fn are_connected(&self, a: usize, b: usize) -> bool {
        let mut seen_a: u64 = 1u64 << a;
        let mut front_a: u64 = seen_a;
        let mut seen_b: u64 = 1u64 << b;
        let mut front_b: u64 = seen_b;
        while front_a != 0 && front_b != 0 {
            let mut next_a: u64 = 0;
            let mut f = front_a;
            while f != 0 {
                let u = f.trailing_zeros() as usize;
                f &= f - 1;
                next_a |= self.rows[u];
            }
            if (next_a & seen_b) != 0 {
                return true;
            }
            front_a = next_a & !seen_a;
            seen_a |= front_a;

            let mut next_b: u64 = 0;
            let mut f = front_b;
            while f != 0 {
                let u = f.trailing_zeros() as usize;
                f &= f - 1;
                next_b |= self.rows[u];
            }
            if (next_b & seen_a) != 0 {
                return true;
            }
            front_b = next_b & !seen_b;
            seen_b |= front_b;
        }
        false
    }

    #[inline]
    pub fn collect_edges(&self, out: &mut Vec<Edge>) {
        out.clear();
        for u in 0..self.n {
            let higher_mask: u64 = if u >= 63 { 0 } else { !((1u64 << (u + 1)) - 1) };
            let mut bits = self.rows[u] & higher_mask;
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                out.push((u as u8, v as u8));
                bits &= bits - 1;
            }
        }
    }

    pub fn has_at_most_two_blocks(&self) -> bool {
        let n = self.n;
        if n < 3 {
            return true;
        }
        let mut disc = [0u8; 64];
        let mut low = [0u8; 64];
        let mut timer = 0u8;
        let mut blocks = 0u8;

        fn dfs(
            rows: &[u64; 64],
            u: usize,
            parent: usize,
            disc: &mut [u8; 64],
            low: &mut [u8; 64],
            timer: &mut u8,
            blocks: &mut u8,
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
                    dfs(rows, v, u, disc, low, timer, blocks);
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if low[v] >= disc[u] {
                        *blocks += 1;
                        if *blocks > 2 {
                            return;
                        }
                    }
                } else if disc[v] < low[u] {
                    low[u] = disc[v];
                }
                if *blocks > 2 {
                    return;
                }
            }
        }

        dfs(
            &self.rows,
            0,
            usize::MAX,
            &mut disc,
            &mut low,
            &mut timer,
            &mut blocks,
        );
        (timer as usize) == n && blocks <= 2
    }

    #[inline]
    pub fn minimal_structure_valid(&self) -> bool {
        let mut degree_three = 0usize;
        let mut high_mask: u64 = 0;
        let mut deg3_mask: u64 = 0;
        for u in 0..self.n {
            let d = self.rows[u].count_ones();
            if d == 3 {
                degree_three += 1;
                deg3_mask |= 1u64 << u;
            } else if d >= 4 {
                high_mask |= 1u64 << u;
            }
        }
        if 3 * degree_three <= 2 * self.n {
            return false;
        }
        for u in 0..self.n {
            let row = self.rows[u];
            if (high_mask & (1u64 << u)) != 0 && (row & high_mask) != 0 {
                return false;
            }
            if (row & deg3_mask) == 0 {
                return false;
            }
        }
        self.has_at_most_two_blocks()
    }

    pub fn zobrist_key(&self) -> u128 {
        let table = zobrist_table();
        let mut h = 0u128;
        for u in 0..self.n {
            let higher_mask: u64 = if u >= 63 { 0 } else { !((1u64 << (u + 1)) - 1) };
            let mut bits = self.rows[u] & higher_mask;
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                h ^= table[u * MAX_ORDER + v];
                bits &= bits - 1;
            }
        }
        h
    }

    #[inline]
    pub fn zobrist_key64(&self) -> u64 {
        self.zobrist_key() as u64
    }
}

impl BitGraph {
    #[inline]
    pub fn empty(n: usize) -> Self {
        assert!(n <= MAX_ORDER, "order must be <= 128");
        Self {
            n,
            rows: [0u128; MAX_ORDER],
        }
    }

    #[allow(dead_code)]
    #[inline]
    pub fn from_rows(n: usize, rows: &[u128]) -> Result<Self, String> {
        if n > MAX_ORDER || rows.len() != n {
            return Err("invalid order or row count".to_string());
        }
        let mask: u128 = if n == 128 { !0u128 } else { (1u128 << n) - 1 };
        let mut g = Self::empty(n);
        for (u, &row) in rows.iter().enumerate() {
            if (row & !mask) != 0 {
                return Err("row has out-of-range bit".to_string());
            }
            if (row & (1u128 << u)) != 0 {
                return Err("loops are not allowed".to_string());
            }
            g.rows[u] = row;
        }
        for u in 0..n {
            let mut bits = g.rows[u];
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                if (g.rows[v] & (1u128 << u)) == 0 {
                    return Err("adjacency must be symmetric".to_string());
                }
                bits &= bits - 1;
            }
        }
        Ok(g)
    }

    #[inline]
    pub fn add_edge(&mut self, u: usize, v: usize) {
        debug_assert!(u < self.n && v < self.n && u != v);
        self.rows[u] |= 1u128 << v;
        self.rows[v] |= 1u128 << u;
    }

    #[inline]
    pub fn remove_edge(&mut self, u: usize, v: usize) {
        debug_assert!(u < self.n && v < self.n && u != v);
        self.rows[u] &= !(1u128 << v);
        self.rows[v] &= !(1u128 << u);
    }

    #[inline]
    pub fn has_edge(&self, u: usize, v: usize) -> bool {
        (self.rows[u] & (1u128 << v)) != 0
    }

    #[inline]
    pub fn degree(&self, u: usize) -> u32 {
        self.rows[u].count_ones()
    }

    #[allow(dead_code)]
    #[inline]
    pub fn minimum_degree(&self) -> u32 {
        if self.n == 0 {
            return 0;
        }
        let mut m = u32::MAX;
        for u in 0..self.n {
            let d = self.rows[u].count_ones();
            if d < m {
                m = d;
            }
        }
        m
    }

    #[inline]
    pub fn size(&self) -> u32 {
        let mut total = 0u32;
        for u in 0..self.n {
            total += self.rows[u].count_ones();
        }
        total / 2
    }

    #[inline]
    pub fn is_connected(&self) -> bool {
        if self.n <= 1 {
            return true;
        }
        let mut seen: u128 = 1u128;
        let mut frontier: u128 = 1u128;
        while frontier != 0 {
            let mut next: u128 = 0;
            let mut f = frontier;
            while f != 0 {
                let u = f.trailing_zeros() as usize;
                f &= f - 1;
                next |= self.rows[u];
            }
            frontier = next & !seen;
            seen |= frontier;
        }
        seen.count_ones() as usize == self.n
    }

    #[inline]
    pub fn are_connected(&self, a: usize, b: usize) -> bool {
        let mut seen_a: u128 = 1u128 << a;
        let mut front_a: u128 = seen_a;
        let mut seen_b: u128 = 1u128 << b;
        let mut front_b: u128 = seen_b;
        while front_a != 0 && front_b != 0 {
            let mut next_a: u128 = 0;
            let mut f = front_a;
            while f != 0 {
                let u = f.trailing_zeros() as usize;
                f &= f - 1;
                next_a |= self.rows[u];
            }
            if (next_a & seen_b) != 0 {
                return true;
            }
            front_a = next_a & !seen_a;
            seen_a |= front_a;

            let mut next_b: u128 = 0;
            let mut f = front_b;
            while f != 0 {
                let u = f.trailing_zeros() as usize;
                f &= f - 1;
                next_b |= self.rows[u];
            }
            if (next_b & seen_a) != 0 {
                return true;
            }
            front_b = next_b & !seen_b;
            seen_b |= front_b;
        }
        false
    }

    #[inline]
    pub fn collect_edges(&self, out: &mut Vec<Edge>) {
        out.clear();
        for u in 0..self.n {
            let higher_mask: u128 = if u >= 127 {
                0
            } else {
                !((1u128 << (u + 1)) - 1)
            };
            let mut bits = self.rows[u] & higher_mask;
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                out.push((u as u8, v as u8));
                bits &= bits - 1;
            }
        }
    }

    pub fn has_at_most_two_blocks(&self) -> bool {
        let n = self.n;
        if n < 3 {
            return true;
        }
        let mut disc = [0u16; MAX_ORDER];
        let mut low = [0u16; MAX_ORDER];
        let mut timer = 0u16;
        let mut blocks = 0u16;

        fn dfs(
            rows: &[u128; MAX_ORDER],
            u: usize,
            parent: usize,
            disc: &mut [u16; MAX_ORDER],
            low: &mut [u16; MAX_ORDER],
            timer: &mut u16,
            blocks: &mut u16,
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
                    dfs(rows, v, u, disc, low, timer, blocks);
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if low[v] >= disc[u] {
                        *blocks += 1;
                        if *blocks > 2 {
                            return;
                        }
                    }
                } else if disc[v] < low[u] {
                    low[u] = disc[v];
                }
                if *blocks > 2 {
                    return;
                }
            }
        }

        dfs(
            &self.rows,
            0,
            usize::MAX,
            &mut disc,
            &mut low,
            &mut timer,
            &mut blocks,
        );
        (timer as usize) == n && blocks <= 2
    }

    #[inline]
    pub fn minimal_structure_valid(&self) -> bool {
        let mut degree_three = 0usize;
        let mut high_mask: u128 = 0;
        let mut deg3_mask: u128 = 0;
        for u in 0..self.n {
            let d = self.rows[u].count_ones();
            if d == 3 {
                degree_three += 1;
                deg3_mask |= 1u128 << u;
            } else if d >= 4 {
                high_mask |= 1u128 << u;
            }
        }
        if 3 * degree_three <= 2 * self.n {
            return false;
        }
        for u in 0..self.n {
            let row = self.rows[u];
            if (high_mask & (1u128 << u)) != 0 && (row & high_mask) != 0 {
                return false;
            }
            if (row & deg3_mask) == 0 {
                return false;
            }
        }
        self.has_at_most_two_blocks()
    }

    pub fn to_graph6(&self) -> String {
        let mut out = Vec::with_capacity(4 + (self.n * self.n) / 12 + 2);
        if self.n <= 62 {
            out.push((self.n as u8) + 63);
        } else {
            out.push(126);
            out.push((((self.n >> 12) & 63) as u8) + 63);
            out.push((((self.n >> 6) & 63) as u8) + 63);
            out.push(((self.n & 63) as u8) + 63);
        }
        let mut value = 0u8;
        let mut width = 0u8;
        for v in 1..self.n {
            let row_bit = 1u128 << v;
            for u in 0..v {
                value = (value << 1) | (((self.rows[u] & row_bit) != 0) as u8);
                width += 1;
                if width == 6 {
                    out.push(value + 63);
                    value = 0;
                    width = 0;
                }
            }
        }
        if width > 0 {
            out.push((value << (6 - width)) + 63);
        }
        String::from_utf8(out).expect("graph6 is valid ASCII")
    }

    pub fn from_graph6(raw_str: &str) -> Result<Self, String> {
        let mut raw = raw_str.trim().as_bytes();
        if raw.starts_with(b">>graph6<<") {
            raw = &raw[10..];
        }
        if raw.is_empty() {
            return Err("empty graph6 input".to_string());
        }
        let (n, offset) = if raw[0] != 126 {
            ((raw[0] as isize - 63) as usize, 1usize)
        } else if raw.len() >= 4 && raw[1] != 126 {
            let n = (((raw[1] - 63) as usize) << 12)
                | (((raw[2] - 63) as usize) << 6)
                | ((raw[3] - 63) as usize);
            (n, 4usize)
        } else {
            return Err("large graph6 order encoding is unsupported".to_string());
        };
        if n > MAX_ORDER {
            return Err(format!("graph order {n} exceeds 128"));
        }
        let encoded = &raw[offset..];
        if encoded.iter().any(|&b| !(63..=126).contains(&b)) {
            return Err("invalid graph6 byte".to_string());
        }
        let required = n * n.saturating_sub(1) / 2;
        let required_bytes = required.div_ceil(6);
        if encoded.len() != required_bytes {
            return Err("graph6 length mismatch".to_string());
        }
        let mut g = Self::empty(n);
        let mut pos = 0usize;
        for v in 1..n {
            for u in 0..v {
                let byte = encoded[pos / 6] - 63;
                if (byte & (1u8 << (5 - (pos % 6)))) != 0 {
                    g.add_edge(u, v);
                }
                pos += 1;
            }
        }
        Ok(g)
    }

    pub fn zobrist_key(&self) -> u128 {
        let table = zobrist_table();
        let mut h = 0u128;
        for u in 0..self.n {
            let higher_mask: u128 = if u >= 127 {
                0
            } else {
                !((1u128 << (u + 1)) - 1)
            };
            let mut bits = self.rows[u] & higher_mask;
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                h ^= table[u * MAX_ORDER + v];
                bits &= bits - 1;
            }
        }
        h
    }
}

#[inline]
pub fn normalize_edge(a: u8, b: u8) -> Edge {
    if a < b { (a, b) } else { (b, a) }
}

#[inline]
pub fn zobrist_edge(e: Edge) -> u128 {
    let (u, v) = normalize_edge(e.0, e.1);
    zobrist_table()[(u as usize) * MAX_ORDER + (v as usize)]
}

#[inline]
pub fn zobrist_edge64(e: Edge) -> u64 {
    zobrist_edge(e) as u64
}

fn zobrist_table() -> &'static [u128; MAX_ORDER * MAX_ORDER] {
    static TABLE: OnceLock<Box<[u128; MAX_ORDER * MAX_ORDER]>> = OnceLock::new();
    TABLE.get_or_init(|| {
        let mut rng = crate::rng::Rng::new(0x5347_4c41_425f_5a4f);
        let mut arr = Box::new([0u128; MAX_ORDER * MAX_ORDER]);
        for u in 0..MAX_ORDER {
            for v in (u + 1)..MAX_ORDER {
                let lo = rng.next_u64() as u128;
                let hi = rng.next_u64() as u128;
                let val = lo | (hi << 64);
                arr[u * MAX_ORDER + v] = val;
                arr[v * MAX_ORDER + u] = val;
            }
        }
        arr
    })
}

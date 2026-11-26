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

    #[allow(dead_code)]
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

    /// Compute all biconnected components (blocks) as vertex bitmasks via
    /// Hopcroft-Tarjan DFS. Returns `(block_count, block_masks, max_block_size)`.
    /// Every simple cycle of length L >= 3 lies entirely within a unique block
    /// of size >= L.
    pub fn biconnected_blocks(&self) -> (usize, [u64; 64], usize) {
        let n = self.n;
        let mut blocks = [0u64; 64];
        if n < 3 {
            return (0, blocks, n);
        }
        let mut disc = [0u8; 64];
        let mut low = [0u8; 64];
        let mut timer = 0u8;
        let mut block_count = 0usize;
        let mut max_block = 0usize;
        let mut edge_stack: [(u8, u8); 2048] = [(0, 0); 2048];
        let mut sp = 0usize;

        #[allow(clippy::too_many_arguments)]
        fn dfs(
            rows: &[u64; 64],
            u: usize,
            parent: usize,
            disc: &mut [u8; 64],
            low: &mut [u8; 64],
            timer: &mut u8,
            edge_stack: &mut [(u8, u8); 2048],
            sp: &mut usize,
            blocks: &mut [u64; 64],
            block_count: &mut usize,
            max_block: &mut usize,
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
                    edge_stack[*sp] = (u as u8, v as u8);
                    *sp += 1;
                    dfs(
                        rows,
                        v,
                        u,
                        disc,
                        low,
                        timer,
                        edge_stack,
                        sp,
                        blocks,
                        block_count,
                        max_block,
                    );
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if low[v] >= disc[u] {
                        let mut mask = 0u64;
                        while *sp > 0 {
                            *sp -= 1;
                            let (a, b) = edge_stack[*sp];
                            mask |= (1u64 << a) | (1u64 << b);
                            if a == u as u8 && b == v as u8 {
                                break;
                            }
                        }
                        let sz = mask.count_ones() as usize;
                        if sz > *max_block {
                            *max_block = sz;
                        }
                        if *block_count < 64 {
                            blocks[*block_count] = mask;
                            *block_count += 1;
                        }
                    }
                } else if disc[v] < disc[u] {
                    edge_stack[*sp] = (u as u8, v as u8);
                    *sp += 1;
                    if disc[v] < low[u] {
                        low[u] = disc[v];
                    }
                }
            }
        }

        for root in 0..n {
            if disc[root] == 0 {
                dfs(
                    &self.rows,
                    root,
                    usize::MAX,
                    &mut disc,
                    &mut low,
                    &mut timer,
                    &mut edge_stack,
                    &mut sp,
                    &mut blocks,
                    &mut block_count,
                    &mut max_block,
                );
            }
        }
        (block_count, blocks, max_block)
    }

    /// Fast Tarjan 2-connectivity check (strictly 1 biconnected component,
    /// zero cut vertices, zero bridges). Returns early on first articulation point.
    pub fn is_biconnected(&self) -> bool {
        let n = self.n;
        if n < 3 {
            return false;
        }
        let mut disc = [0u8; 64];
        let mut low = [0u8; 64];
        let mut timer = 0u8;
        let mut root_children = 0u8;
        let mut failed = false;

        fn dfs(
            rows: &[u64; 64],
            u: usize,
            parent: usize,
            disc: &mut [u8; 64],
            low: &mut [u8; 64],
            timer: &mut u8,
            root_children: &mut u8,
            failed: &mut bool,
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
                    if parent == usize::MAX {
                        *root_children += 1;
                        if *root_children > 1 {
                            *failed = true;
                            return;
                        }
                    }
                    dfs(rows, v, u, disc, low, timer, root_children, failed);
                    if *failed {
                        return;
                    }
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if parent != usize::MAX && low[v] >= disc[u] {
                        *failed = true;
                        return;
                    }
                } else if disc[v] < low[u] {
                    low[u] = disc[v];
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
            &mut root_children,
            &mut failed,
        );
        !failed && (timer as usize) == n
    }

    /// Check whether the induced subgraph `G[mask]` is 2-degenerate (peeling
    /// vertices of induced degree <= 2 removes every vertex in `mask`).
    #[inline]
    pub fn is_two_degenerate_induced(&self, mask: u64) -> bool {
        let mut alive = mask;
        loop {
            let mut removed_any = false;
            let mut cur = alive;
            while cur != 0 {
                let u = cur.trailing_zeros() as usize;
                cur &= cur - 1;
                if (self.rows[u] & alive).count_ones() <= 2 {
                    alive &= !(1u64 << u);
                    removed_any = true;
                }
            }
            if !removed_any {
                return alive == 0;
            }
        }
    }

    #[inline]
    fn edge_count_in_mask(&self, mask: u64) -> u32 {
        let mut deg_sum = 0u32;
        let mut cur = mask;
        while cur != 0 {
            let u = cur.trailing_zeros() as usize;
            cur &= cur - 1;
            deg_sum += (self.rows[u] & mask).count_ones();
        }
        deg_sum / 2
    }

    /// Ducoffe-Dumitru Lemma 3.5 (doubling reduction): build auxiliary graph M
    /// on high-degree set `high_mask` whose edges correspond to L2 vertices
    /// (degree-3 vertices having 2 neighbors in `high_mask`). M must be simple
    /// (parallel edge => C4 in G), satisfy |L2| <= max(0, 2h - 3), and be 2-degenerate.
    #[inline]
    fn auxiliary_m_valid(&self, high_mask: u64, deg3_mask: u64) -> bool {
        let h = high_mask.count_ones() as usize;
        if h <= 1 {
            return true;
        }
        let mut m_adj = [0u64; 64];
        let mut l2_count = 0usize;
        let mut cur = deg3_mask;
        while cur != 0 {
            let u = cur.trailing_zeros() as usize;
            cur &= cur - 1;
            let hn = self.rows[u] & high_mask;
            let cnt = hn.count_ones();
            if cnt >= 2 {
                if cnt > 2 {
                    return false;
                }
                let x = hn.trailing_zeros() as usize;
                let y = (hn & (hn - 1)).trailing_zeros() as usize;
                if (m_adj[x] & (1u64 << y)) != 0 {
                    return false;
                }
                m_adj[x] |= 1u64 << y;
                m_adj[y] |= 1u64 << x;
                l2_count += 1;
            }
        }
        if l2_count > 2 * h - 3 {
            return false;
        }
        if l2_count < 3 {
            return true;
        }
        let mut alive = high_mask;
        loop {
            let mut removed_any = false;
            let mut scan = alive;
            while scan != 0 {
                let x = scan.trailing_zeros() as usize;
                scan &= scan - 1;
                if (m_adj[x] & alive).count_ones() <= 2 {
                    alive &= !(1u64 << x);
                    removed_any = true;
                }
            }
            if !removed_any {
                return alive == 0;
            }
        }
    }

    /// Closed Ducoffe-Dumitru (arXiv:2609.28594) structural filter:
    /// - delta >= 3, strictly > 2n/3 degree-3 vertices, independent H = {d >= 4},
    ///   domination by degree-3 vertices;
    /// - Thm 3.7 (for n >= 13): h <= floor(n/3) - 1 and m <= 2n - 2;
    /// - Lemma 3.5: auxiliary graph M on H is simple, |L2| <= max(0, 2h-3), 2-degenerate;
    /// - Cor 2.2 / Thm 2.3 / Cor 2.4: zero bridges; even n MUST be strictly 2-connected;
    ///   odd n is either strictly 2-connected or a symmetric 1-clique-sum of two equal-order,
    ///   equal-size, 2-degenerate blocks sharing one cut vertex of exact degree 4.
    #[inline]
    pub fn minimal_structure_valid(&self) -> bool {
        let n = self.n;
        let mut degree_three = 0usize;
        let mut high_mask: u64 = 0;
        let mut deg3_mask: u64 = 0;
        let mut deg_sum = 0u32;
        for u in 0..n {
            let d = self.rows[u].count_ones();
            if d < 3 {
                return false;
            }
            deg_sum += d;
            if d == 3 {
                degree_three += 1;
                deg3_mask |= 1u64 << u;
            } else {
                high_mask |= 1u64 << u;
            }
        }
        if 3 * degree_three <= 2 * n {
            return false;
        }
        if n >= 13 {
            let h = high_mask.count_ones() as usize;
            let m = (deg_sum / 2) as usize;
            if h > (n / 3).saturating_sub(1) || m > 2 * n - 2 {
                return false;
            }
        }
        for u in 0..n {
            let row = self.rows[u];
            if (high_mask & (1u64 << u)) != 0 && (row & high_mask) != 0 {
                return false;
            }
            if (row & deg3_mask) == 0 {
                return false;
            }
        }
        if !self.auxiliary_m_valid(high_mask, deg3_mask) {
            return false;
        }
        if n % 2 == 0 {
            return self.is_biconnected();
        }
        let (block_count, blocks, _max_block) = self.biconnected_blocks();
        let all_mask = if n == 64 { !0u64 } else { (1u64 << n) - 1 };
        if block_count == 1 {
            return blocks[0] == all_mask;
        }
        if block_count != 2 {
            return false;
        }
        let b0 = blocks[0];
        let b1 = blocks[1];
        if (b0 | b1) != all_mask {
            return false;
        }
        let expected_sz = ((n + 1) / 2) as u32;
        if b0.count_ones() != expected_sz || b1.count_ones() != expected_sz {
            return false;
        }
        let cut_mask = b0 & b1;
        if cut_mask.count_ones() != 1 {
            return false;
        }
        let cut = cut_mask.trailing_zeros() as usize;
        if self.rows[cut].count_ones() != 4 {
            return false;
        }
        if self.edge_count_in_mask(b0) != self.edge_count_in_mask(b1) {
            return false;
        }
        self.is_two_degenerate_induced(b0) && self.is_two_degenerate_induced(b1)
    }

    /// Ducoffe-Dumitru Conjecture 4.1 / Theorem 4.2 single-block filter:
    /// Searches a single 2-connected, 2-degenerate block B of order k where
    /// vertex 0 has exact degree 2 (both neighbors of degree 3), all other
    /// vertices have degree >= 3 with independent H = {v >= 1 : d(v) >= 4},
    /// and gluing two copies B +_0 B produces a legal odd counterexample of
    /// order n = 2k - 1 satisfying all Ducoffe-Dumitru invariants.
    #[inline]
    pub fn single_block_41_valid(&self) -> bool {
        let k = self.n;
        if k < 6 {
            return false;
        }
        if self.rows[0].count_ones() != 2 {
            return false;
        }
        let mut deg3_mask: u64 = 0;
        let mut high_mask: u64 = 1u64; // vertex 0 becomes degree-4 cut vertex in B +_0 B
        let mut degree_three = 0usize;
        for u in 1..k {
            let d = self.rows[u].count_ones();
            if d < 3 {
                return false;
            }
            if d == 3 {
                degree_three += 1;
                deg3_mask |= 1u64 << u;
            } else {
                high_mask |= 1u64 << u;
            }
        }
        // Both neighbors of cut vertex 0 must have degree 3 (H union {0} independent)
        if (self.rows[0] & deg3_mask) != self.rows[0] {
            return false;
        }
        // In B +_0 B (order 2k-1), total degree-3 count is 2*degree_three; require > 2*(2k-1)/3
        if 3 * degree_three < 2 * k {
            return false;
        }
        for u in 1..k {
            let row = self.rows[u];
            if (high_mask & (1u64 << u)) != 0 && (row & high_mask) != 0 {
                return false;
            }
            if (row & deg3_mask) == 0 {
                return false;
            }
        }
        if !self.auxiliary_m_valid(high_mask, deg3_mask) {
            return false;
        }
        if !self.is_biconnected() {
            return false;
        }
        let all_mask = if k == 64 { !0u64 } else { (1u64 << k) - 1 };
        self.is_two_degenerate_induced(all_mask)
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

    #[allow(dead_code)]
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

    pub fn is_biconnected(&self) -> bool {
        let n = self.n;
        if n < 3 {
            return false;
        }
        let mut disc = [0u16; MAX_ORDER];
        let mut low = [0u16; MAX_ORDER];
        let mut timer = 0u16;
        let mut root_children = 0u16;
        let mut failed = false;

        fn dfs(
            rows: &[u128; MAX_ORDER],
            u: usize,
            parent: usize,
            disc: &mut [u16; MAX_ORDER],
            low: &mut [u16; MAX_ORDER],
            timer: &mut u16,
            root_children: &mut u16,
            failed: &mut bool,
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
                    if parent == usize::MAX {
                        *root_children += 1;
                        if *root_children > 1 {
                            *failed = true;
                            return;
                        }
                    }
                    dfs(rows, v, u, disc, low, timer, root_children, failed);
                    if *failed {
                        return;
                    }
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if parent != usize::MAX && low[v] >= disc[u] {
                        *failed = true;
                        return;
                    }
                } else if disc[v] < low[u] {
                    low[u] = disc[v];
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
            &mut root_children,
            &mut failed,
        );
        !failed && (timer as usize) == n
    }

    pub fn biconnected_blocks(&self) -> (usize, [u128; MAX_ORDER], usize) {
        let n = self.n;
        let mut blocks = [0u128; MAX_ORDER];
        if n < 3 {
            return (0, blocks, n);
        }
        let mut disc = [0u16; MAX_ORDER];
        let mut low = [0u16; MAX_ORDER];
        let mut timer = 0u16;
        let mut block_count = 0usize;
        let mut max_block = 0usize;
        let mut edge_stack: Vec<(u8, u8)> = Vec::with_capacity(n * 4);

        #[allow(clippy::too_many_arguments)]
        fn dfs(
            rows: &[u128; MAX_ORDER],
            u: usize,
            parent: usize,
            disc: &mut [u16; MAX_ORDER],
            low: &mut [u16; MAX_ORDER],
            timer: &mut u16,
            edge_stack: &mut Vec<(u8, u8)>,
            blocks: &mut [u128; MAX_ORDER],
            block_count: &mut usize,
            max_block: &mut usize,
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
                    edge_stack.push((u as u8, v as u8));
                    dfs(
                        rows,
                        v,
                        u,
                        disc,
                        low,
                        timer,
                        edge_stack,
                        blocks,
                        block_count,
                        max_block,
                    );
                    if low[v] < low[u] {
                        low[u] = low[v];
                    }
                    if low[v] >= disc[u] {
                        let mut mask = 0u128;
                        while let Some((a, b)) = edge_stack.pop() {
                            mask |= (1u128 << a) | (1u128 << b);
                            if a == u as u8 && b == v as u8 {
                                break;
                            }
                        }
                        let sz = mask.count_ones() as usize;
                        if sz > *max_block {
                            *max_block = sz;
                        }
                        if *block_count < MAX_ORDER {
                            blocks[*block_count] = mask;
                            *block_count += 1;
                        }
                    }
                } else if disc[v] < disc[u] {
                    edge_stack.push((u as u8, v as u8));
                    if disc[v] < low[u] {
                        low[u] = disc[v];
                    }
                }
            }
        }

        for root in 0..n {
            if disc[root] == 0 {
                dfs(
                    &self.rows,
                    root,
                    usize::MAX,
                    &mut disc,
                    &mut low,
                    &mut timer,
                    &mut edge_stack,
                    &mut blocks,
                    &mut block_count,
                    &mut max_block,
                );
            }
        }
        (block_count, blocks, max_block)
    }

    #[inline]
    pub fn is_two_degenerate_induced(&self, mask: u128) -> bool {
        let mut alive = mask;
        loop {
            let mut removed_any = false;
            let mut cur = alive;
            while cur != 0 {
                let u = cur.trailing_zeros() as usize;
                cur &= cur - 1;
                if (self.rows[u] & alive).count_ones() <= 2 {
                    alive &= !(1u128 << u);
                    removed_any = true;
                }
            }
            if !removed_any {
                return alive == 0;
            }
        }
    }

    #[inline]
    fn edge_count_in_mask(&self, mask: u128) -> u32 {
        let mut deg_sum = 0u32;
        let mut cur = mask;
        while cur != 0 {
            let u = cur.trailing_zeros() as usize;
            cur &= cur - 1;
            deg_sum += (self.rows[u] & mask).count_ones();
        }
        deg_sum / 2
    }

    #[inline]
    fn auxiliary_m_valid(&self, high_mask: u128, deg3_mask: u128) -> bool {
        let h = high_mask.count_ones() as usize;
        if h <= 1 {
            return true;
        }
        let mut m_adj = [0u128; MAX_ORDER];
        let mut l2_count = 0usize;
        let mut cur = deg3_mask;
        while cur != 0 {
            let u = cur.trailing_zeros() as usize;
            cur &= cur - 1;
            let hn = self.rows[u] & high_mask;
            let cnt = hn.count_ones();
            if cnt >= 2 {
                if cnt > 2 {
                    return false;
                }
                let x = hn.trailing_zeros() as usize;
                let y = (hn & (hn - 1)).trailing_zeros() as usize;
                if (m_adj[x] & (1u128 << y)) != 0 {
                    return false;
                }
                m_adj[x] |= 1u128 << y;
                m_adj[y] |= 1u128 << x;
                l2_count += 1;
            }
        }
        if l2_count > 2 * h - 3 {
            return false;
        }
        if l2_count < 3 {
            return true;
        }
        let mut alive = high_mask;
        loop {
            let mut removed_any = false;
            let mut scan = alive;
            while scan != 0 {
                let x = scan.trailing_zeros() as usize;
                scan &= scan - 1;
                if (m_adj[x] & alive).count_ones() <= 2 {
                    alive &= !(1u128 << x);
                    removed_any = true;
                }
            }
            if !removed_any {
                return alive == 0;
            }
        }
    }

    #[inline]
    pub fn minimal_structure_valid(&self) -> bool {
        let n = self.n;
        let mut degree_three = 0usize;
        let mut high_mask: u128 = 0;
        let mut deg3_mask: u128 = 0;
        let mut deg_sum = 0u32;
        for u in 0..n {
            let d = self.rows[u].count_ones();
            if d < 3 {
                return false;
            }
            deg_sum += d;
            if d == 3 {
                degree_three += 1;
                deg3_mask |= 1u128 << u;
            } else {
                high_mask |= 1u128 << u;
            }
        }
        if 3 * degree_three <= 2 * n {
            return false;
        }
        if n >= 13 {
            let h = high_mask.count_ones() as usize;
            let m = (deg_sum / 2) as usize;
            if h > (n / 3).saturating_sub(1) || m > 2 * n - 2 {
                return false;
            }
        }
        for u in 0..n {
            let row = self.rows[u];
            if (high_mask & (1u128 << u)) != 0 && (row & high_mask) != 0 {
                return false;
            }
            if (row & deg3_mask) == 0 {
                return false;
            }
        }
        if !self.auxiliary_m_valid(high_mask, deg3_mask) {
            return false;
        }
        if n % 2 == 0 {
            return self.is_biconnected();
        }
        let (block_count, blocks, _max_block) = self.biconnected_blocks();
        let all_mask = if n == 128 { !0u128 } else { (1u128 << n) - 1 };
        if block_count == 1 {
            return blocks[0] == all_mask;
        }
        if block_count != 2 {
            return false;
        }
        let b0 = blocks[0];
        let b1 = blocks[1];
        if (b0 | b1) != all_mask {
            return false;
        }
        let expected_sz = ((n + 1) / 2) as u32;
        if b0.count_ones() != expected_sz || b1.count_ones() != expected_sz {
            return false;
        }
        let cut_mask = b0 & b1;
        if cut_mask.count_ones() != 1 {
            return false;
        }
        let cut = cut_mask.trailing_zeros() as usize;
        if self.rows[cut].count_ones() != 4 {
            return false;
        }
        if self.edge_count_in_mask(b0) != self.edge_count_in_mask(b1) {
            return false;
        }
        self.is_two_degenerate_induced(b0) && self.is_two_degenerate_induced(b1)
    }

    #[inline]
    pub fn single_block_41_valid(&self) -> bool {
        let k = self.n;
        if k < 6 {
            return false;
        }
        if self.rows[0].count_ones() != 2 {
            return false;
        }
        let mut deg3_mask: u128 = 0;
        let mut high_mask: u128 = 1u128;
        let mut degree_three = 0usize;
        for u in 1..k {
            let d = self.rows[u].count_ones();
            if d < 3 {
                return false;
            }
            if d == 3 {
                degree_three += 1;
                deg3_mask |= 1u128 << u;
            } else {
                high_mask |= 1u128 << u;
            }
        }
        if (self.rows[0] & deg3_mask) != self.rows[0] {
            return false;
        }
        if 3 * degree_three < 2 * k {
            return false;
        }
        for u in 1..k {
            let row = self.rows[u];
            if (high_mask & (1u128 << u)) != 0 && (row & high_mask) != 0 {
                return false;
            }
            if (row & deg3_mask) == 0 {
                return false;
            }
        }
        if !self.auxiliary_m_valid(high_mask, deg3_mask) {
            return false;
        }
        if !self.is_biconnected() {
            return false;
        }
        let all_mask = if k == 128 { !0u128 } else { (1u128 << k) - 1 };
        self.is_two_degenerate_induced(all_mask)
    }

    /// Materialize the symmetric 1-clique-sum B +_0 B of order 2k - 1 from a
    /// Conjecture 4.1 single-block graph B of order k <= 64 (vertex 0 is shared).
    #[allow(dead_code)]
    pub fn glue_symmetric_single_block(&self) -> Result<BitGraph, String> {
        let k = self.n;
        if k < 6 || 2 * k - 1 > MAX_ORDER {
            return Err(format!("single-block order {k} out of range for gluing"));
        }
        let n = 2 * k - 1;
        let mut g = BitGraph::empty(n);
        for u in 0..k {
            let mut bits = self.rows[u] & !((1u128 << (u + 1)) - 1);
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                g.add_edge(u, v);
                let u2 = if u == 0 { 0 } else { k - 1 + u };
                let v2 = k - 1 + v;
                g.add_edge(u2, v2);
            }
        }
        Ok(g)
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

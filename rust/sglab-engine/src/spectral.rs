//! Hashimoto non-backtracking matrix trace Tr(B^k) via Ihara-Bass (cubic)
//! and exact sparse directed-edge walk powers (general degree), plus algebraic
//! connectivity lambda_2(L) for escaping C16/C32 cap-saturation plateaus.

use crate::graph::BitGraph64;

/// Symmetric cyclic-Jacobi eigenvalues of an `n x n` real symmetric matrix
/// stored in row-major `a[i * n + j]` (for `n <= 64`). Returns sorted descending
/// eigenvalues `evals[0..n]`.
pub fn symmetric_eigenvalues_64(n: usize, a_in: &[f64]) -> [f64; 64] {
    debug_assert!(n <= 64 && a_in.len() >= n * n);
    let mut a = [0.0f64; 64 * 64];
    for i in 0..n {
        let row = i * n;
        for j in 0..n {
            a[row + j] = a_in[row + j];
        }
    }

    for _sweep in 0..12 {
        let mut max_off = 0.0f64;
        for p in 0..n {
            let rp = p * n;
            for q in (p + 1)..n {
                let apq = a[rp + q];
                let abs_apq = apq.abs();
                if abs_apq > max_off {
                    max_off = abs_apq;
                }
                if abs_apq < 1e-12 {
                    continue;
                }
                let app = a[rp + p];
                let aqq = a[q * n + q];
                let tau = (aqq - app) / (2.0 * apq);
                let t = if tau >= 0.0 {
                    1.0 / (tau + (1.0 + tau * tau).sqrt())
                } else {
                    -1.0 / (-tau + (1.0 + tau * tau).sqrt())
                };
                let c = 1.0 / (1.0 + t * t).sqrt();
                let s = t * c;

                a[rp + p] = app - t * apq;
                a[q * n + q] = aqq + t * apq;
                a[rp + q] = 0.0;
                a[q * n + p] = 0.0;

                for r in 0..n {
                    if r == p || r == q {
                        continue;
                    }
                    let arp = a[r * n + p];
                    let arq = a[r * n + q];
                    let new_rp = c * arp - s * arq;
                    let new_rq = s * arp + c * arq;
                    a[r * n + p] = new_rp;
                    a[p * n + r] = new_rp;
                    a[r * n + q] = new_rq;
                    a[q * n + r] = new_rq;
                }
            }
        }
        if max_off < 1e-10 {
            break;
        }
    }

    let mut evals = [0.0f64; 64];
    for i in 0..n {
        evals[i] = a[i * n + i];
    }
    evals[..n].sort_by(|x, y| y.total_cmp(x));
    evals
}

/// Exact Hashimoto trace Tr(B^k) for a cubic graph (D = 3 I_n) from adjacency
/// eigenvalues `evals[0..n]` via the Ihara-Bass theorem:
///   mu_+/-(lambda) = (lambda +/- sqrt(lambda^2 - 8)) / 2
///   Tr(B^k) = (m - n) * (1 + (-1)^k) + sum_i (mu_+^k + mu_-^k).
/// For |lambda| < sqrt(8), mu_+/- = sqrt(2) * exp(+/- i theta) with
/// cos(theta) = lambda / (2 * sqrt(2)), so mu_+^k + mu_-^k = 2 * 2^(k/2) * cos(k * theta).
#[inline]
pub fn hashimoto_trace_cubic_from_evals(n: usize, evals: &[f64], k: u32) -> f64 {
    let m = (3 * n) / 2;
    let trivial = if (k & 1) == 0 {
        2.0 * ((m - n) as f64)
    } else {
        0.0
    };
    let sqrt8 = 8.0f64.sqrt();
    let rad_pow = 2.0f64.powf(0.5 * (k as f64));
    let mut sum = trivial;
    for &lam in &evals[..n] {
        let disc = lam * lam - 8.0;
        if disc >= 0.0 {
            let s = disc.sqrt();
            let mp = 0.5 * (lam + s);
            let mm = 0.5 * (lam - s);
            sum += mp.powi(k as i32) + mm.powi(k as i32);
        } else {
            let cos_t = (lam / sqrt8).clamp(-1.0, 1.0);
            let theta = cos_t.acos();
            sum += 2.0 * rad_pow * ((k as f64) * theta).cos();
        }
    }
    sum
}

/// Exact non-backtracking Hashimoto trace Tr(B^k) for arbitrary-degree graphs
/// (`n <= 64`, even `k >= 2`) by computing half-step directed-edge walk vectors
/// `v = B^(k/2) e_i` and summing `<B^(k/2) e_i, (B^T)^(k/2) e_i>` (using the
/// reversal symmetry of undirected graphs: `(B^T)_e,f = B_{rev(f), rev(e)}`).
pub fn hashimoto_trace_general_u64(g: &BitGraph64, k: u32) -> f64 {
    debug_assert!(k >= 2 && (k & 1) == 0);
    let n = g.n;
    // Enumerate directed edges: e_id = 2*idx (u->v) and 2*idx+1 (v->u), rev(e) = e ^ 1.
    let mut head = [0u8; 384];
    let mut tail = [0u8; 384];
    let mut out_start = [0u16; 65];
    let mut out_edges = [0u16; 384];
    let mut dir_count = 0usize;

    let mut deg = [0u16; 64];
    for u in 0..n {
        deg[u] = g.rows[u].count_ones() as u16;
    }
    out_start[0] = 0;
    for u in 0..n {
        out_start[u + 1] = out_start[u] + deg[u];
    }
    let total_dir = out_start[n] as usize;
    if total_dir == 0 || total_dir > 384 {
        return 0.0;
    }
    let mut cursor = [0u16; 64];
    for u in 0..n {
        cursor[u] = out_start[u];
    }
    for u in 0..n {
        let higher = if u >= 63 { 0 } else { !((1u64 << (u + 1)) - 1) };
        let mut bits = g.rows[u] & higher;
        while bits != 0 {
            let v = bits.trailing_zeros() as usize;
            bits &= bits - 1;
            let e_uv = dir_count;
            let e_vu = dir_count + 1;
            dir_count += 2;
            tail[e_uv] = u as u8;
            head[e_uv] = v as u8;
            tail[e_vu] = v as u8;
            head[e_vu] = u as u8;
            out_edges[cursor[u] as usize] = e_uv as u16;
            cursor[u] += 1;
            out_edges[cursor[v] as usize] = e_vu as u16;
            cursor[v] += 1;
        }
    }

    // Half-step propagation: Tr(B^{2h}) = sum_{e, f} (B^h)_{f, e} * (B^h)_{e, f}.
    // Wait: using reversal involution J (J e = e^1), B^T = J B J, so
    // (B^h)_{e, f} = ((B^T)^h)_{f, e} = (J B^h J)_{f, e} = (B^h)_{f^1, e^1}.
    // Even simpler: compute single column v = B^h e_start AND u = B^h e_{start^1};
    // wait: Tr(B^{2h}) = sum_{start} (B^{2h})_{start, start}
    //   = sum_{start} sum_f (B^h)_{start, f} (B^h)_{f, start}
    //   = sum_{start} sum_f (B^h)_{f^1, start^1} (B^h)_{f, start}!
    // So for each undirected edge pair (e = 2*i, e_rev = 2*i+1):
    //   propagate v = B^h e_e and w = B^h e_{e_rev};
    //   contribution of BOTH start=e and start=e_rev is 2 * sum_f v[f] * w[f^1]!
    let half = (k / 2) as usize;
    let mut v_cur = [0.0f64; 384];
    let mut v_nxt = [0.0f64; 384];
    let mut w_cur = [0.0f64; 384];
    let mut w_nxt = [0.0f64; 384];
    let mut trace = 0.0f64;

    let propagate = |start_e: usize, cur: &mut [f64; 384], nxt: &mut [f64; 384]| {
        cur[..dir_count].fill(0.0);
        cur[start_e] = 1.0;
        for _ in 0..half {
            nxt[..dir_count].fill(0.0);
            for e in 0..dir_count {
                let val = cur[e];
                if val == 0.0 {
                    continue;
                }
                let v = head[e] as usize;
                let rev_e = (e ^ 1) as u16;
                let s = out_start[v] as usize;
                let t = out_start[v + 1] as usize;
                for &f_u16 in &out_edges[s..t] {
                    if f_u16 != rev_e {
                        nxt[f_u16 as usize] += val;
                    }
                }
            }
            cur[..dir_count].copy_from_slice(&nxt[..dir_count]);
        }
    };

    for pair in 0..(dir_count / 2) {
        let e0 = 2 * pair;
        let e1 = e0 + 1;
        propagate(e0, &mut v_cur, &mut v_nxt);
        propagate(e1, &mut w_cur, &mut w_nxt);
        let mut dot = 0.0f64;
        for f in 0..dir_count {
            dot += v_cur[f] * w_cur[f ^ 1];
        }
        trace += 2.0 * dot;
    }
    trace
}

#[allow(dead_code)]
#[derive(Clone, Copy, Debug)]
pub struct HashimotoMetrics {
    pub tr_b16: f64,
    pub tr_b32: f64,
    pub lambda2_laplacian: f64,
    pub potential: f64,
}

/// Compute Hashimoto non-backtracking macro-gradient potential for `g` (`n <= 64`).
/// Uses exact O(n^3) Ihara-Bass eigendecomposition for cubic graphs (~35 us)
/// and exact sparse non-backtracking walk powers for mixed-degree graphs.
/// Lower `potential` = fewer non-backtracking 16/32 walks & weaker expander.
pub fn hashimoto_metrics_u64(g: &BitGraph64) -> HashimotoMetrics {
    let n = g.n;
    let mut is_cubic = true;
    for u in 0..n {
        if g.rows[u].count_ones() != 3 {
            is_cubic = false;
            break;
        }
    }

    if is_cubic {
        let mut adj = [0.0f64; 64 * 64];
        for u in 0..n {
            let mut bits = g.rows[u];
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                adj[u * n + v] = 1.0;
            }
        }
        let evals = symmetric_eigenvalues_64(n, &adj);
        let tr16 = hashimoto_trace_cubic_from_evals(n, &evals, 16);
        let tr32 = if n >= 32 {
            hashimoto_trace_cubic_from_evals(n, &evals, 32)
        } else {
            0.0
        };
        let lambda2_l = if n >= 2 {
            (3.0 - evals[1]).max(0.0)
        } else {
            0.0
        };
        let pot = tr16.max(1.0).ln()
            + if n >= 32 {
                0.25 * tr32.max(1.0).ln()
            } else {
                0.0
            }
            + 0.35 * lambda2_l;
        HashimotoMetrics {
            tr_b16: tr16,
            tr_b32: tr32,
            lambda2_laplacian: lambda2_l,
            potential: pot,
        }
    } else {
        let tr16 = hashimoto_trace_general_u64(g, 16);
        let tr32 = if n >= 32 {
            hashimoto_trace_general_u64(g, 32)
        } else {
            0.0
        };
        // Laplacian matrix L = D - A for algebraic connectivity lambda_2(L)
        let mut lap = [0.0f64; 64 * 64];
        for u in 0..n {
            lap[u * n + u] = g.rows[u].count_ones() as f64;
            let mut bits = g.rows[u];
            while bits != 0 {
                let v = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                lap[u * n + v] = -1.0;
            }
        }
        let evals_l = symmetric_eigenvalues_64(n, &lap);
        // Sorted descending, so smallest is evals_l[n-1] ~= 0, second smallest is evals_l[n-2]
        let lambda2_l = if n >= 2 {
            evals_l[n - 2].max(0.0)
        } else {
            0.0
        };
        let pot = tr16.max(1.0).ln()
            + if n >= 32 {
                0.25 * tr32.max(1.0).ln()
            } else {
                0.0
            }
            + 0.35 * lambda2_l;
        HashimotoMetrics {
            tr_b16: tr16,
            tr_b32: tr32,
            lambda2_laplacian: lambda2_l,
            potential: pot,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cycles::{DfsScratch, score_graph_fast};
    use crate::graph::BitGraph;

    /// Exact McGee (3, 7)-cage on 24 vertices (LCF notation [12, 7, -7]^8).
    fn build_mcgee_cage() -> BitGraph {
        let mut g = BitGraph::empty(24);
        let shifts = [12isize, 7, -7];
        for i in 0..24usize {
            g.add_edge(i, (i + 1) % 24);
            let s = shifts[i % 3];
            let j = ((i as isize + s).rem_euclid(24)) as usize;
            g.add_edge(i, j);
        }
        g
    }

    #[test]
    fn ihara_bass_and_general_hashimoto_match_mcgee_reference_exact() {
        let mcgee = build_mcgee_cage();
        assert_eq!(mcgee.size(), 36);
        let mut scratch = DfsScratch::new();
        let sc = score_graph_fast(&mcgee, 1_000, 1_000_000, None, &mut scratch).unwrap();
        assert_eq!(sc.counts_slice(), &[(4, 0), (8, 34), (16, 492)]);

        let g64 = BitGraph64::from_graph(&mcgee);
        let m = hashimoto_metrics_u64(&g64);
        // Exact reference values from Deep Research PDF p. 23:
        // Tr(B^16) = 66_336, Tr(B^32) = 4_296_496_672 (for McGee cage, even though n=24 < 32).
        assert!(
            (m.tr_b16 - 66_336.0).abs() < 1e-3,
            "McGee Ihara-Bass Tr(B^16) mismatch: got {}",
            m.tr_b16
        );
        // Also check Tr(B^32) via cubic evals directly:
        let mut adj = [0.0f64; 64 * 64];
        for u in 0..24 {
            for v in 0..24 {
                if g64.has_edge(u, v) {
                    adj[u * 24 + v] = 1.0;
                }
            }
        }
        let evals = symmetric_eigenvalues_64(24, &adj);
        let tr32_cubic = hashimoto_trace_cubic_from_evals(24, &evals, 32);
        assert!(
            (tr32_cubic - 4_296_496_672.0).abs() < 10.0,
            "McGee Ihara-Bass Tr(B^32) mismatch: got {}",
            tr32_cubic
        );

        // Verify general non-backtracking walk-power implementation matches exact integers!
        let tr16_gen = hashimoto_trace_general_u64(&g64, 16);
        let tr32_gen = hashimoto_trace_general_u64(&g64, 32);
        assert!(
            (tr16_gen - 66_336.0).abs() < 1e-6,
            "McGee general Tr(B^16) mismatch: got {}",
            tr16_gen
        );
        assert!(
            (tr32_gen - 4_296_496_672.0).abs() < 1e-2,
            "McGee general Tr(B^32) mismatch: got {}",
            tr32_gen
        );
    }
}

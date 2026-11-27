// Reproducible cross-check of incremental creates_c8 pruning and lossless symmetry
// breaking used by exhaustive_gadget_enum.cpp and exhaustive_gadget_enum_deep.cpp.
// Compares symmetry-broken (SB) vs full labeled brute-force (NO_SB) at n = 7, 8, 9
// and tests creates_c8 against exact has_cycle_len(8) over 5,000 random edge insertions.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <set>
#include <vector>

static bool is_connected(int n, const std::array<uint32_t, 20>& rows) {
    uint32_t vis = 1u, q = 1u;
    while (q) {
        int u = __builtin_ctz(q); q &= q - 1;
        uint32_t nxt = rows[u] & ~vis;
        vis |= nxt; q |= nxt;
    }
    return vis == ((1u << n) - 1u);
}

static inline bool creates_c4(const std::array<uint32_t, 20>& rows, int u, int v) {
    uint32_t nu = rows[u] & ~(1u << v), nv = rows[v] & ~(1u << u);
    while (nu) {
        int a = __builtin_ctz(nu); nu &= nu - 1;
        if (rows[a] & nv & ~(1u << a)) return true;
    }
    return false;
}

static bool has_cycle_len(int n, const std::array<uint32_t, 20>& rows, int target) {
    for (int s = 0; s <= n - target; ++s) {
        uint32_t gt = ~((1u << (s + 1)) - 1u);
        uint32_t nbrs = rows[s] & gt;
        if (__builtin_popcount(nbrs) < 2) continue;
        auto dfs = [&](auto&& self, int u, int depth, uint32_t vis, int first) -> bool {
            if (depth == target) return ((rows[u] >> s) & 1u) && first < u;
            uint32_t avail = rows[u] & gt & ~vis;
            while (avail) {
                int w = __builtin_ctz(avail); avail &= avail - 1;
                if (self(self, w, depth + 1, vis | (1u << w), first)) return true;
            }
            return false;
        };
        uint32_t b = nbrs;
        while (b) {
            int v = __builtin_ctz(b); b &= b - 1;
            if (dfs(dfs, v, 2, (1u << s) | (1u << v), v)) return true;
        }
    }
    return false;
}

static inline bool creates_c8(const std::array<uint32_t, 20>& rows, int u, int v) {
    uint32_t forbid = (1u << u) | (1u << v);
    uint32_t u_masks[64]; int u_end[64]; int uc = 0;
    uint32_t m1 = rows[u] & ~forbid;
    while (m1) {
        int a = __builtin_ctz(m1); m1 &= m1 - 1;
        uint32_t f1 = forbid | (1u << a);
        uint32_t m2 = rows[a] & ~f1;
        while (m2) {
            int b = __builtin_ctz(m2); m2 &= m2 - 1;
            uint32_t f2 = f1 | (1u << b);
            uint32_t m3 = rows[b] & ~f2;
            while (m3) {
                int c = __builtin_ctz(m3); m3 &= m3 - 1;
                if (uc < 64) { u_end[uc] = c; u_masks[uc] = (1u << a) | (1u << b) | (1u << c); ++uc; }
            }
        }
    }
    if (uc == 0) return false;
    uint32_t v1 = rows[v] & ~forbid;
    while (v1) {
        int f = __builtin_ctz(v1); v1 &= v1 - 1;
        uint32_t vf1 = forbid | (1u << f);
        uint32_t v2 = rows[f] & ~vf1;
        while (v2) {
            int e = __builtin_ctz(v2); v2 &= v2 - 1;
            uint32_t vf2 = vf1 | (1u << e);
            uint32_t v3 = rows[e] & ~vf2;
            while (v3) {
                int d = __builtin_ctz(v3); v3 &= v3 - 1;
                uint32_t vm = (1u << f) | (1u << e) | (1u << d);
                uint32_t rd = rows[d];
                for (int i = 0; i < uc; ++i)
                    if (((rd >> u_end[i]) & 1u) && ((vm & u_masks[i]) == 0)) return true;
            }
        }
    }
    return false;
}

static uint32_t path_mask(const std::array<uint32_t, 20>& rows, int src, int dst) {
    uint32_t mask = 0;
    auto dfs = [&](auto&& self, int u, int d, uint32_t vis) -> void {
        if (u == dst) { mask |= (1u << d); return; }
        uint32_t avail = rows[u] & ~vis;
        while (avail) { int w = __builtin_ctz(avail); avail &= avail - 1; self(self, w, d + 1, vis | (1u << w)); }
    };
    dfs(dfs, src, 0, 1u << src);
    return mask;
}

int main() {
    // 1. Cross-check creates_c8 vs exact has_cycle_len(8) on 5,000 random graphs
    std::array<uint32_t, 20> rows{};
    int mismatches = 0;
    uint64_t rng = 12345;
    auto nxt = [&]() { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; };
    for (int trial = 0; trial < 5000; ++trial) {
        rows.fill(0);
        int n = 13;
        int deg[20] = {};
        for (int step = 0; step < 20; ++step) {
            int u = nxt() % n, v = nxt() % n;
            if (u == v || ((rows[u] >> v) & 1u) || deg[u] >= 3 || deg[v] >= 3) continue;
            bool before = has_cycle_len(n, rows, 8);
            bool pred = creates_c8(rows, u, v);
            rows[u] |= (1u << v); rows[v] |= (1u << u);
            bool after = has_cycle_len(n, rows, 8);
            if (!before && (pred != after)) mismatches++;
            if (after) { rows[u] ^= (1u << v); rows[v] ^= (1u << u); }
            else { deg[u]++; deg[v]++; }
        }
    }
    std::cout << "creates_c8 mismatches over 5000 random trials: " << mismatches << "\n";
    if (mismatches != 0) return 1;

    // 2. Compare distinct window sets WITH vs WITHOUT symmetry breaking on n=7, 8, 9
    auto run_sig = [&](const std::string& lbl, std::vector<int> td) {
        int n = (int)td.size();
        auto enum_set = [&](bool use_sb) {
            std::array<uint32_t, 20> r{};
            std::vector<int> cd(n, 0);
            uint64_t leaves = 0, valid = 0;
            std::set<std::array<uint32_t, 3>> types;
            auto bt = [&](auto&& self, int u, int next_v) -> void {
                while (u < n && cd[u] == td[u]) { ++u; next_v = u + 1; }
                if (u == n) {
                    leaves++;
                    if (is_connected(n, r) && !has_cycle_len(n, r, 8)) {
                        valid++;
                        std::array<uint32_t, 3> ps{path_mask(r, 0, 1), path_mask(r, 0, 2), path_mask(r, 1, 2)};
                        std::sort(ps.begin(), ps.end());
                        types.insert(ps);
                    }
                    return;
                }
                int need = td[u] - cd[u];
                int start_v = std::max(next_v, u + 1);
                int avail = 0;
                for (int v = start_v; v < n; ++v) if (cd[v] < td[v]) ++avail;
                if (avail < need) return;
                uint32_t tried_d = 0; bool tried_p = false;
                for (int v = start_v; v < n; ++v) {
                    if (cd[v] >= td[v]) continue;
                    if (use_sb) {
                        if (v < 3) { if (cd[v] == 0) { if (tried_p) continue; tried_p = true; } }
                        else { if (cd[v] == 0) { uint32_t b = 1u << td[v]; if (tried_d & b) continue; tried_d |= b; } }
                    }
                    if (creates_c4(r, u, v)) continue;
                    r[u] |= (1u << v); r[v] |= (1u << u); cd[u]++; cd[v]++;
                    self(self, u, v + 1);
                    cd[u]--; cd[v]--; r[u] ^= (1u << v); r[v] ^= (1u << u);
                }
            };
            bt(bt, 0, 1);
            return std::tuple{leaves, valid, types};
        };
        auto [l_sb, v_sb, t_sb] = enum_set(true);
        auto [l_no, v_no, t_no] = enum_set(false);
        bool match = (t_sb == t_no);
        std::cout << lbl << ": SB=(leaves=" << l_sb << ", valid=" << v_sb << ", types=" << t_sb.size()
                  << ") NO_SB=(leaves=" << l_no << ", valid=" << v_no << ", types=" << t_no.size()
                  << ") types_identical=" << (match ? "YES" : "NO") << "\n";
        if (!match) std::exit(1);
    };

    run_sig("n=7 cubic ", {2,2,2, 3,3,3,3});
    run_sig("n=8 1xdeg4", {2,2,2, 3,3,3,3, 4});
    run_sig("n=9 cubic ", {2,2,2, 3,3,3,3,3,3});
    return 0;
}

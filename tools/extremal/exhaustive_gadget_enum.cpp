// 100% EXHAUSTIVE canonical enumeration of simple connected {C4, C8}-free 3-port
// (and 4-port) gadgets with port internal degree 2 and specified internal degrees.
//
// Enumerates BOTH:
//   - UNRESTRICTED (port-port edges allowed; e.g., K_3 at n=3!)
//   - NO-PORT-EDGE (no direct edge between any two ports; standard gadget class)
//
// Proves exact completeness (NOT randomized sampling!) for every listed signature,
// including full exact path-length bitmasks S(p_i, p_j) and internal cycle sets.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>

struct GadgetRecord {
    std::vector<std::pair<int, int>> edges;
    uint32_t int_cycles = 0;
    bool has_port_edge = false;
};

struct EnumCtx {
    int n;
    int n_ports;
    bool allow_port_edges;
    std::vector<int> target_deg;
    std::vector<int> cur_deg;
    std::array<uint32_t, 20> rows{};
    uint64_t leaves = 0;
    uint64_t valid_graphs = 0;
    uint64_t valid_no_pe = 0;
    // Key: sorted vector of (min_len, path_mask) across all C(n_ports, 2) port pairs, plus has_port_edge
    std::map<std::pair<bool, std::vector<std::pair<int, uint32_t>>>, GadgetRecord> found;
};

static bool is_connected(int n, const std::array<uint32_t, 20>& rows) {
    uint32_t vis = 1u, q = 1u;
    while (q) {
        int u = __builtin_ctz(q); q &= q - 1;
        uint32_t nxt = rows[u] & ~vis;
        vis |= nxt; q |= nxt;
    }
    return vis == ((1u << n) - 1u);
}

static bool creates_c4(const std::array<uint32_t, 20>& rows, int u, int v) {
    uint32_t nu = rows[u] & ~(1u << v);
    uint32_t nv = rows[v] & ~(1u << u);
    while (nu) {
        int a = __builtin_ctz(nu); nu &= nu - 1;
        if (rows[a] & nv & ~(1u << a)) return true;
    }
    return false;
}

static bool has_cycle_len(int n, const std::array<uint32_t, 20>& rows, int target) {
    if (n < target) return false;
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

static uint32_t all_cycle_lengths(int n, const std::array<uint32_t, 20>& rows) {
    uint32_t cmask = 0;
    for (int s = 0; s <= n - 3; ++s) {
        uint32_t gt = ~((1u << (s + 1)) - 1u);
        uint32_t nbrs = rows[s] & gt;
        if (__builtin_popcount(nbrs) < 2) continue;
        auto dfs = [&](auto&& self, int u, int depth, uint32_t vis, int first) -> void {
            if (depth >= 3 && ((rows[u] >> s) & 1u) && first < u) {
                cmask |= (1u << depth);
            }
            uint32_t avail = rows[u] & gt & ~vis;
            while (avail) {
                int w = __builtin_ctz(avail); avail &= avail - 1;
                self(self, w, depth + 1, vis | (1u << w), first);
            }
        };
        uint32_t b = nbrs;
        while (b) {
            int v = __builtin_ctz(b); b &= b - 1;
            dfs(dfs, v, 2, (1u << s) | (1u << v), v);
        }
    }
    return cmask;
}

static uint32_t path_mask(const std::array<uint32_t, 20>& rows, int src, int dst) {
    uint32_t mask = 0;
    auto dfs = [&](auto&& self, int u, int d, uint32_t vis) -> void {
        if (u == dst) { mask |= (1u << d); return; }
        uint32_t avail = rows[u] & ~vis;
        while (avail) {
            int w = __builtin_ctz(avail); avail &= avail - 1;
            self(self, w, d + 1, vis | (1u << w));
        }
    };
    dfs(dfs, src, 0, 1u << src);
    return mask;
}

// Exhaustive backtracking filling vertices in order 0, 1, ..., n-1.
// Exact symmetry breaking:
//   Among vertices v >= n_ports that currently have cur_deg[v] == 0 and share the same
//   target_deg[v], they are completely interchangeable (automorphic in the partial graph),
//   so trying only the smallest-index unused vertex of each degree class is 100% lossless!
//   Similarly, when allow_port_edges is true, unused ports v < n_ports with cur_deg == 0
//   are interchangeable among themselves as well.
static void bt_fill(EnumCtx& ctx, int u, int next_v) {
    const int n = ctx.n;
    const int np = ctx.n_ports;
    while (u < n && ctx.cur_deg[u] == ctx.target_deg[u]) {
        ++u;
        next_v = u + 1;
    }
    if (u == n) {
        ctx.leaves++;
        if (!is_connected(n, ctx.rows)) return;
        if (has_cycle_len(n, ctx.rows, 8)) return;
        ctx.valid_graphs++;
        bool hpe = false;
        uint32_t pmask = (1u << np) - 1u;
        for (int p = 0; p < np; ++p) {
            if (ctx.rows[p] & pmask) { hpe = true; break; }
        }
        if (!hpe) ctx.valid_no_pe++;

        std::vector<std::pair<int, uint32_t>> ps;
        ps.reserve(np * (np - 1) / 2);
        for (int i = 0; i < np; ++i) {
            for (int j = i + 1; j < np; ++j) {
                uint32_t m = path_mask(ctx.rows, i, j);
                ps.push_back({__builtin_ctz(m), m});
            }
        }
        std::sort(ps.begin(), ps.end());
        auto key = std::make_pair(hpe, ps);
        if (ctx.found.find(key) == ctx.found.end()) {
            GadgetRecord rec;
            rec.has_port_edge = hpe;
            rec.int_cycles = all_cycle_lengths(n, ctx.rows);
            for (int a = 0; a < n; ++a)
                for (int b = a + 1; b < n; ++b)
                    if ((ctx.rows[a] >> b) & 1u) rec.edges.push_back({a, b});
            ctx.found[key] = std::move(rec);
        }
        return;
    }

    int need = ctx.target_deg[u] - ctx.cur_deg[u];
    int start_v = std::max(next_v, (!ctx.allow_port_edges && u < np) ? np : (u + 1));

    int avail_cnt = 0;
    for (int v = start_v; v < n; ++v)
        if (ctx.cur_deg[v] < ctx.target_deg[v]) ++avail_cnt;
    if (avail_cnt < need) return;

    uint32_t tried_fresh_int_deg = 0;
    bool tried_fresh_port = false;

    for (int v = start_v; v < n; ++v) {
        if (ctx.cur_deg[v] >= ctx.target_deg[v]) continue;
        if (v < np) {
            if (ctx.cur_deg[v] == 0) {
                if (tried_fresh_port) continue;
                tried_fresh_port = true;
            }
        } else {
            if (ctx.cur_deg[v] == 0) {
                uint32_t dbit = 1u << ctx.target_deg[v];
                if (tried_fresh_int_deg & dbit) continue;
                tried_fresh_int_deg |= dbit;
            }
        }
        if (creates_c4(ctx.rows, u, v)) continue;

        ctx.rows[u] |= (1u << v);
        ctx.rows[v] |= (1u << u);
        ctx.cur_deg[u]++;
        ctx.cur_deg[v]++;

        bt_fill(ctx, u, v + 1);

        ctx.cur_deg[u]--;
        ctx.cur_deg[v]--;
        ctx.rows[u] ^= (1u << v);
        ctx.rows[v] ^= (1u << u);
    }
}

static std::string mask_str(uint32_t m) {
    std::string s = "["; bool f = true;
    for (int i = 0; i < 20; ++i) if ((m >> i) & 1u) { if (!f) s += ","; s += std::to_string(i); f = false; }
    return s + "]";
}

static void run_exhaustive(const std::string& name, int n_ports, const std::vector<int>& degs, bool allow_pe = true) {
    auto t0 = std::chrono::steady_clock::now();
    EnumCtx ctx;
    ctx.n = (int)degs.size();
    ctx.n_ports = n_ports;
    ctx.allow_port_edges = allow_pe;
    ctx.target_deg = degs;
    ctx.cur_deg.assign(ctx.n, 0);
    ctx.rows.fill(0);
    bt_fill(ctx, 0, allow_pe ? 1 : n_ports);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::cout << "[EXHAUSTIVE] " << name << " | C4-free leaves=" << ctx.leaves
              << " | valid {C4,C8}-free=" << ctx.valid_graphs
              << " (no-PE=" << ctx.valid_no_pe << ")"
              << " | distinct types=" << ctx.found.size()
              << " (" << ms << " ms)\n";
    for (const auto& [key, rec] : ctx.found) {
        const auto& [hpe, ps] = key;
        std::cout << "  " << (hpe ? "[PE]  " : "[noPE]") << " mins=(";
        for (size_t i = 0; i < ps.size(); ++i) { if (i) std::cout << ","; std::cout << ps[i].first; }
        std::cout << ") S=";
        for (size_t i = 0; i < ps.size(); ++i) { if (i) std::cout << ","; std::cout << mask_str(ps[i].second); }
        std::cout << " cyc=" << mask_str(rec.int_cycles) << " edges=";
        for (size_t i = 0; i < rec.edges.size(); ++i) {
            if (i) std::cout << ",";
            std::cout << rec.edges[i].first << "-" << rec.edges[i].second;
        }
        std::cout << "\n";
    }
    std::cout << std::flush;
}

int main() {
    std::cout << "=== PART A: 3-PORT {C4, C8}-FREE GADGETS (UNRESTRICTED: PE & noPE) ===\n";
    run_exhaustive("3p n=3  cubic   (2,2,2)",                  3, {2,2,2});
    run_exhaustive("3p n=5  cubic   (2,2,2 + 3,3)",            3, {2,2,2, 3,3});
    run_exhaustive("3p n=6  1xdeg4  (2,2,2 + 3,3,4)",          3, {2,2,2, 3,3, 4});
    run_exhaustive("3p n=7  cubic   (2,2,2 + 4x3)",            3, {2,2,2, 3,3,3,3});
    run_exhaustive("3p n=7  2xdeg4  (2,2,2 + 3,3,4,4)",        3, {2,2,2, 3,3, 4,4});
    run_exhaustive("3p n=7  1xdeg5  (2,2,2 + 3,3,3,5)",        3, {2,2,2, 3,3,3, 5});
    run_exhaustive("3p n=8  1xdeg4  (2,2,2 + 4x3 + 4)",        3, {2,2,2, 3,3,3,3, 4});
    run_exhaustive("3p n=8  3xdeg4  (2,2,2 + 3,3,4,4,4)",      3, {2,2,2, 3,3, 4,4,4});
    run_exhaustive("3p n=9  cubic   (2,2,2 + 6x3)",            3, {2,2,2, 3,3,3,3,3,3});
    run_exhaustive("3p n=9  2xdeg4  (2,2,2 + 4x3 + 4,4)",      3, {2,2,2, 3,3,3,3, 4,4});
    run_exhaustive("3p n=9  1xdeg5  (2,2,2 + 5x3 + 5)",        3, {2,2,2, 3,3,3,3,3, 5});
    run_exhaustive("3p n=10 1xdeg4  (2,2,2 + 6x3 + 4)",        3, {2,2,2, 3,3,3,3,3,3, 4});
    run_exhaustive("3p n=11 cubic   (2,2,2 + 8x3)",            3, {2,2,2, 3,3,3,3,3,3,3,3});

    std::cout << "\n=== PART B: 4-PORT {C4, C8}-FREE GADGETS (ports deg 2, internal deg >= 3) ===\n";
    run_exhaustive("4p n=6  cubic   (4x2 + 3,3)",              4, {2,2,2,2, 3,3});
    run_exhaustive("4p n=7  1xdeg4  (4x2 + 3,3,4)",            4, {2,2,2,2, 3,3, 4});
    run_exhaustive("4p n=8  cubic   (4x2 + 4x3)",              4, {2,2,2,2, 3,3,3,3});
    run_exhaustive("4p n=9  1xdeg4  (4x2 + 4x3 + 4)",          4, {2,2,2,2, 3,3,3,3, 4});
    run_exhaustive("4p n=10 cubic   (4x2 + 6x3)",              4, {2,2,2,2, 3,3,3,3,3,3});
    return 0;
}

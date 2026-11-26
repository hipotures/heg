// Deep 100% EXHAUSTIVE canonical enumeration of {C4, C8}-free 3-port (n=11..15)
// and 4-port (n=10..12) gadgets with 16-core parallel root splitting and exact
// symmetry breaking!
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

struct GadgetRecord {
    std::vector<std::pair<int, int>> edges;
    uint32_t int_cycles = 0;
    bool has_port_edge = false;
};

struct State {
    int n;
    int n_ports;
    bool allow_port_edges;
    std::vector<int> target_deg;
    std::vector<int> cur_deg;
    std::array<uint32_t, 20> rows{};
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

static inline bool creates_c4(const std::array<uint32_t, 20>& rows, int u, int v) {
    uint32_t nu = rows[u] & ~(1u << v);
    uint32_t nv = rows[v] & ~(1u << u);
    while (nu) {
        int a = __builtin_ctz(nu); nu &= nu - 1;
        if (rows[a] & nv & ~(1u << a)) return true;
    }
    return false;
}

// Incremental check: does adding edge (u, v) create a C8 (i.e. a length-7 simple path between u and v)?
// Using Meet-in-the-Middle (depth 3 from u + depth 4 from v, or depth 3 from both + 1 edge):
// Actually 3 steps from u, 3 steps from v, check edge between endpoints -> ultra fast for max deg <= 4!
static inline bool creates_c8(const std::array<uint32_t, 20>& rows, int u, int v) {
    // Check if there is a simple path u - a - b - c - d - e - f - v (7 edges, 8 vertices)
    // Enumerate 3-edge paths from u: (c, mask_u) where mask_u = {u,a,b,c}
    // Wait: degree <= 4, so at most 3*3*3 = 27 paths from u and 27 from v!
    uint32_t forbid = (1u << u) | (1u << v);
    uint32_t u_masks[64];
    int u_end[64];
    int uc = 0;
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
                if (uc < 64) {
                    u_end[uc] = c;
                    u_masks[uc] = (1u << a) | (1u << b) | (1u << c);
                    ++uc;
                }
            }
        }
    }
    if (uc == 0) return false;
    // Now 3-edge paths from v: v - f - e - d, check if (rows[d] >> c) & 1 and masks disjoint!
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
                for (int i = 0; i < uc; ++i) {
                    if (((rd >> u_end[i]) & 1u) && ((vm & u_masks[i]) == 0)) return true;
                }
            }
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
            if (depth >= 3 && ((rows[u] >> s) & 1u) && first < u) cmask |= (1u << depth);
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

using Key = std::pair<bool, std::vector<std::pair<int, uint32_t>>>;

struct WorkerResult {
    uint64_t leaves = 0;
    uint64_t valid = 0;
    uint64_t valid_no_pe = 0;
    std::map<Key, GadgetRecord> found;
};

static void bt_worker(State& st, int u, int next_v, WorkerResult& res) {
    const int n = st.n;
    const int np = st.n_ports;
    while (u < n && st.cur_deg[u] == st.target_deg[u]) {
        ++u;
        next_v = u + 1;
    }
    if (u == n) {
        res.leaves++;
        if (!is_connected(n, st.rows)) return;
        uint32_t icyc = (n >= 16) ? all_cycle_lengths(n, st.rows) : 0;
        if ((icyc >> 16) & 1u) return;
        res.valid++;
        bool hpe = false;
        uint32_t pmask = (1u << np) - 1u;
        for (int p = 0; p < np; ++p) if (st.rows[p] & pmask) { hpe = true; break; }
        if (!hpe) res.valid_no_pe++;

        std::vector<std::pair<int, uint32_t>> ps;
        ps.reserve(np * (np - 1) / 2);
        for (int i = 0; i < np; ++i)
            for (int j = i + 1; j < np; ++j) {
                uint32_t m = path_mask(st.rows, i, j);
                ps.push_back({__builtin_ctz(m), m});
            }
        std::sort(ps.begin(), ps.end());
        Key key{hpe, std::move(ps)};
        if (res.found.find(key) == res.found.end()) {
            GadgetRecord rec;
            rec.has_port_edge = hpe;
            rec.int_cycles = all_cycle_lengths(n, st.rows);
            for (int a = 0; a < n; ++a)
                for (int b = a + 1; b < n; ++b)
                    if ((st.rows[a] >> b) & 1u) rec.edges.push_back({a, b});
            res.found[std::move(key)] = std::move(rec);
        }
        return;
    }

    int need = st.target_deg[u] - st.cur_deg[u];
    int start_v = std::max(next_v, (!st.allow_port_edges && u < np) ? np : (u + 1));
    int avail_cnt = 0;
    for (int v = start_v; v < n; ++v)
        if (st.cur_deg[v] < st.target_deg[v]) ++avail_cnt;
    if (avail_cnt < need) return;

    uint32_t tried_fresh_int_deg = 0;
    bool tried_fresh_port = false;

    for (int v = start_v; v < n; ++v) {
        if (st.cur_deg[v] >= st.target_deg[v]) continue;
        if (v < np) {
            if (st.cur_deg[v] == 0) {
                if (tried_fresh_port) continue;
                tried_fresh_port = true;
            }
        } else {
            if (st.cur_deg[v] == 0) {
                uint32_t dbit = 1u << st.target_deg[v];
                if (tried_fresh_int_deg & dbit) continue;
                tried_fresh_int_deg |= dbit;
            }
        }
        if (creates_c4(st.rows, u, v)) continue;
        if (u >= np && creates_c8(st.rows, u, v)) continue;

        st.rows[u] |= (1u << v);
        st.rows[v] |= (1u << u);
        st.cur_deg[u]++;
        st.cur_deg[v]++;
        bt_worker(st, u, v + 1, res);
        st.cur_deg[u]--;
        st.cur_deg[v]--;
        st.rows[u] ^= (1u << v);
        st.rows[v] ^= (1u << u);
    }
}

struct Task {
    State st;
    int u;
    int next_v;
};

static void collect_tasks(State& st, int u, int next_v, int split_u, std::vector<Task>& tasks) {
    const int n = st.n;
    const int np = st.n_ports;
    while (u < n && st.cur_deg[u] == st.target_deg[u]) {
        ++u;
        next_v = u + 1;
    }
    if (u >= split_u || u == n) {
        tasks.push_back({st, u, next_v});
        return;
    }
    int need = st.target_deg[u] - st.cur_deg[u];
    int start_v = std::max(next_v, (!st.allow_port_edges && u < np) ? np : (u + 1));
    int avail_cnt = 0;
    for (int v = start_v; v < n; ++v)
        if (st.cur_deg[v] < st.target_deg[v]) ++avail_cnt;
    if (avail_cnt < need) return;

    uint32_t tried_fresh_int_deg = 0;
    bool tried_fresh_port = false;
    for (int v = start_v; v < n; ++v) {
        if (st.cur_deg[v] >= st.target_deg[v]) continue;
        if (v < np) {
            if (st.cur_deg[v] == 0) {
                if (tried_fresh_port) continue;
                tried_fresh_port = true;
            }
        } else {
            if (st.cur_deg[v] == 0) {
                uint32_t dbit = 1u << st.target_deg[v];
                if (tried_fresh_int_deg & dbit) continue;
                tried_fresh_int_deg |= dbit;
            }
        }
        if (creates_c4(st.rows, u, v)) continue;
        if (u >= np && creates_c8(st.rows, u, v)) continue;

        st.rows[u] |= (1u << v);
        st.rows[v] |= (1u << u);
        st.cur_deg[u]++;
        st.cur_deg[v]++;
        collect_tasks(st, u, v + 1, split_u, tasks);
        st.cur_deg[u]--;
        st.cur_deg[v]--;
        st.rows[u] ^= (1u << v);
        st.rows[v] ^= (1u << u);
    }
}

static std::string mask_str(uint32_t m) {
    std::string s = "["; bool f = true;
    for (int i = 0; i < 20; ++i) if ((m >> i) & 1u) { if (!f) s += ","; s += std::to_string(i); f = false; }
    return s + "]";
}

static void run_parallel_exhaustive(
    const std::string& name, int n_ports, const std::vector<int>& degs, bool allow_pe = true, int split_u = 5
) {
    auto t0 = std::chrono::steady_clock::now();
    State init;
    init.n = (int)degs.size();
    init.n_ports = n_ports;
    init.allow_port_edges = allow_pe;
    init.target_deg = degs;
    init.cur_deg.assign(init.n, 0);
    init.rows.fill(0);

    std::vector<Task> tasks;
    collect_tasks(init, 0, allow_pe ? 1 : n_ports, split_u, tasks);

    std::atomic<size_t> next_idx{0};
    const int nthreads = 16;
    std::vector<WorkerResult> wres(nthreads);
    std::vector<std::thread> ths;
    for (int t = 0; t < nthreads; ++t) {
        ths.emplace_back([&, t]() {
            while (true) {
                size_t idx = next_idx.fetch_add(1, std::memory_order_relaxed);
                if (idx >= tasks.size()) break;
                State st = tasks[idx].st;
                bt_worker(st, tasks[idx].u, tasks[idx].next_v, wres[t]);
            }
        });
    }
    for (auto& th : ths) th.join();

    WorkerResult tot;
    for (auto& r : wres) {
        tot.leaves += r.leaves;
        tot.valid += r.valid;
        tot.valid_no_pe += r.valid_no_pe;
        for (auto& [k, v] : r.found) {
            if (tot.found.find(k) == tot.found.end()) tot.found[k] = std::move(v);
        }
    }
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::cout << "[EXHAUSTIVE-16C] " << name << " (tasks=" << tasks.size() << ")"
              << " | {C4,C8}-free leaves=" << tot.leaves
              << " | connected=" << tot.valid << " (no-PE=" << tot.valid_no_pe << ")"
              << " | distinct types=" << tot.found.size()
              << " (" << ms << " ms)\n";
    int shown = 0;
    for (const auto& [key, rec] : tot.found) {
        const auto& [hpe, ps] = key;
        // Always show noPE, or top 20 PE, or any with mins[0] >= 2
        if (hpe && shown >= 20 && ps[0].first < 2) continue;
        ++shown;
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
    if ((int)tot.found.size() > shown) {
        std::cout << "  ... (" << (tot.found.size() - shown) << " more [PE] types omitted)\n";
    }
    std::cout << std::flush;
}

int main() {
    std::cout << "=== DEEP EXHAUSTIVE 3-PORT {C4, C8, C16}-FREE GADGETS (n=11..17) ===\n";
    run_parallel_exhaustive("3p n=11 2xdeg4  (2,2,2 + 6x3 + 4,4)",          3, {2,2,2, 3,3,3,3,3,3, 4,4}, true, 5);
    run_parallel_exhaustive("3p n=12 1xdeg4  (2,2,2 + 8x3 + 4)",            3, {2,2,2, 3,3,3,3,3,3,3,3, 4}, true, 5);
    run_parallel_exhaustive("3p n=13 cubic   (2,2,2 + 10x3)",               3, {2,2,2, 3,3,3,3,3,3,3,3,3,3}, true, 6);
    run_parallel_exhaustive("3p n=14 1xdeg4  (2,2,2 + 10x3 + 4) noPE",      3, {2,2,2, 3,3,3,3,3,3,3,3,3,3, 4}, false, 6);
    run_parallel_exhaustive("3p n=14 2xdeg4  (2,2,2 + 9x3 + 4,4) noPE",     3, {2,2,2, 3,3,3,3,3,3,3,3,3, 4,4}, false, 6);
    run_parallel_exhaustive("3p n=15 cubic   (2,2,2 + 12x3) noPE",          3, {2,2,2, 3,3,3,3,3,3,3,3,3,3,3,3}, false, 7);
    run_parallel_exhaustive("3p n=15 2xdeg4  (2,2,2 + 10x3 + 4,4) noPE",    3, {2,2,2, 3,3,3,3,3,3,3,3,3,3, 4,4}, false, 6);
    run_parallel_exhaustive("3p n=16 1xdeg4  (2,2,2 + 12x3 + 4) noPE",      3, {2,2,2, 3,3,3,3,3,3,3,3,3,3,3,3, 4}, false, 7);
    run_parallel_exhaustive("3p n=17 cubic   (2,2,2 + 14x3) noPE",          3, {2,2,2, 3,3,3,3,3,3,3,3,3,3,3,3,3,3}, false, 7);

    std::cout << "\n=== DEEP EXHAUSTIVE 4-PORT {C4, C8, C16}-FREE GADGETS (n=11..14) ===\n";
    run_parallel_exhaustive("4p n=11 1xdeg4  (4x2 + 6x3 + 4)",              4, {2,2,2,2, 3,3,3,3,3,3, 4}, true, 5);
    run_parallel_exhaustive("4p n=12 cubic   (4x2 + 8x3)",                  4, {2,2,2,2, 3,3,3,3,3,3,3,3}, true, 6);
    run_parallel_exhaustive("4p n=13 1xdeg4  (4x2 + 8x3 + 4) noPE",         4, {2,2,2,2, 3,3,3,3,3,3,3,3, 4}, false, 6);
    run_parallel_exhaustive("4p n=14 cubic   (4x2 + 10x3) noPE",            4, {2,2,2,2, 3,3,3,3,3,3,3,3,3,3}, false, 7);
    return 0;
}

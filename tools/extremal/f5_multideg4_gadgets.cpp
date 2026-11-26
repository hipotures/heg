// Fast 16-core C++17 hunter for {C4,C8,C16}-free 3-port gadgets allowing multiple deg-4 internals
// AND checking high-minimum-distance gadgets at n = 7, 8, 9, 10, 11, 12, 13, 14, 15!
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <random>
#include <set>
#include <thread>
#include <tuple>
#include <vector>

struct Gadget {
    int n;
    std::array<uint32_t, 16> rows{};
};

static bool is_connected(const Gadget& g) {
    uint32_t vis = 1u, q = 1u;
    while (q) {
        int u = __builtin_ctz(q); q &= q - 1;
        uint32_t nxt = g.rows[u] & ~vis;
        vis |= nxt; q |= nxt;
    }
    return vis == ((1u << g.n) - 1u);
}

static bool has_cycle_len(const Gadget& g, int target) {
    if (g.n < target) return false;
    const int n = g.n;
    for (int s = 0; s <= n - target; ++s) {
        uint32_t gt = ~((1u << (s + 1)) - 1u);
        uint32_t nbrs = g.rows[s] & gt;
        if (__builtin_popcount(nbrs) < 2) continue;
        auto dfs = [&](auto&& self, int u, int depth, uint32_t vis, int first) -> bool {
            if (depth == target) return ((g.rows[u] >> s) & 1u) && first < u;
            uint32_t avail = g.rows[u] & gt & ~vis;
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

static uint32_t path_lengths_mask(const Gadget& g, int src, int dst) {
    uint32_t mask = 0;
    auto dfs = [&](auto&& self, int u, int d, uint32_t vis) -> void {
        if (u == dst) { mask |= (1u << d); return; }
        uint32_t avail = g.rows[u] & ~vis;
        while (avail) {
            int w = __builtin_ctz(avail); avail &= avail - 1;
            self(self, w, d + 1, vis | (1u << w));
        }
    };
    dfs(dfs, src, 0, 1u << src);
    return mask;
}

static int penalty(const Gadget& g) {
    int c4 = 0;
    for (int s = 0; s <= g.n - 4; ++s) {
        uint32_t gt = ~((1u << (s + 1)) - 1u);
        uint32_t nb = g.rows[s] & gt;
        while (nb) {
            int a = __builtin_ctz(nb); nb &= nb - 1;
            uint32_t r = nb, ra = g.rows[a] & gt;
            while (r) { int b = __builtin_ctz(r); r &= r - 1; c4 += __builtin_popcount(ra & g.rows[b]); }
        }
    }
    if (c4 > 0) return c4 * 100 + 50;
    if (has_cycle_len(g, 8)) return 10;
    if (g.n >= 16 && has_cycle_len(g, 16)) return 5;
    return 0;
}

static bool build_random_simple(int n, const std::vector<int>& degs, std::mt19937_64& rng, Gadget& out) {
    std::vector<int> stubs;
    for (int i = 0; i < n; ++i) for (int d = 0; d < degs[i]; ++d) stubs.push_back(i);
    for (int attempt = 0; attempt < 24; ++attempt) {
        std::shuffle(stubs.begin(), stubs.end(), rng);
        out.n = n; out.rows.fill(0);
        bool ok = true;
        for (size_t i = 0; i < stubs.size(); i += 2) {
            int u = stubs[i], v = stubs[i + 1];
            if (u == v || ((out.rows[u] >> v) & 1u)) { ok = false; break; }
            out.rows[u] |= (1u << v); out.rows[v] |= (1u << u);
        }
        if (ok && is_connected(out)) return true;
    }
    return false;
}

static std::string mask_to_str(uint32_t m) {
    std::string s = "["; bool f = true;
    for (int i = 0; i < 20; ++i) if ((m >> i) & 1u) { if (!f) s += ","; s += std::to_string(i); f = false; }
    return s + "]";
}

static void search_degseq(const std::string& name, const std::vector<int>& degs, double secs) {
    int n = (int)degs.size();
    std::mutex mtx;
    std::set<std::tuple<int, int, int>> seen_mins;
    std::vector<std::tuple<std::tuple<int, int, int>, std::array<uint32_t, 3>, Gadget>> found;
    std::atomic<uint64_t> trials{0};
    auto t0 = std::chrono::steady_clock::now();
    std::vector<std::thread> ths;
    for (int tid = 0; tid < 16; ++tid) {
        ths.emplace_back([&, tid]() {
            std::mt19937_64 rng(99112700ULL + (uint64_t)n * 1000 + tid * 313 + name.size() * 17);
            Gadget g;
            std::vector<std::pair<int, int>> edges;
            while (std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() < secs) {
                for (int b = 0; b < 256; ++b) {
                    if (!build_random_simple(n, degs, rng, g)) continue;
                    trials.fetch_add(1, std::memory_order_relaxed);
                    int cp = penalty(g);
                    for (int st = 0; st < 40 && cp > 0; ++st) {
                        edges.clear();
                        for (int u = 0; u < n; ++u) {
                            uint32_t bits = g.rows[u] & ~((1u << (u + 1)) - 1u);
                            while (bits) { int v = __builtin_ctz(bits); bits &= bits - 1; edges.push_back({u, v}); }
                        }
                        if (edges.size() < 2) break;
                        auto [a, c1] = edges[rng() % edges.size()];
                        auto [c, d] = edges[rng() % edges.size()];
                        if (a == c || a == d || c1 == c || c1 == d) continue;
                        int p1u = a, p1v = (rng() & 1) ? c : d;
                        int p2u = c1, p2v = (p1v == c) ? d : c;
                        if (((g.rows[p1u] >> p1v) & 1u) || ((g.rows[p2u] >> p2v) & 1u)) continue;
                        Gadget cand = g;
                        cand.rows[a] ^= (1u << c1); cand.rows[c1] ^= (1u << a);
                        cand.rows[c] ^= (1u << d); cand.rows[d] ^= (1u << c);
                        cand.rows[p1u] |= (1u << p1v); cand.rows[p1v] |= (1u << p1u);
                        cand.rows[p2u] |= (1u << p2v); cand.rows[p2v] |= (1u << p2u);
                        if (!is_connected(cand)) continue;
                        int np = penalty(cand);
                        if (np <= cp) { g = cand; cp = np; }
                    }
                    if (cp == 0 && !has_cycle_len(g, 4) && !has_cycle_len(g, 8) && !has_cycle_len(g, 16)) {
                        uint32_t m01 = path_lengths_mask(g, 0, 1);
                        uint32_t m02 = path_lengths_mask(g, 0, 2);
                        uint32_t m12 = path_lengths_mask(g, 1, 2);
                        if ((m01 & 2u) || (m02 & 2u) || (m12 & 2u)) continue;
                        std::array<std::pair<int, uint32_t>, 3> ps{{
                            {__builtin_ctz(m01), m01}, {__builtin_ctz(m02), m02}, {__builtin_ctz(m12), m12}
                        }};
                        std::sort(ps.begin(), ps.end());
                        auto mk = std::make_tuple(ps[0].first, ps[1].first, ps[2].first);
                        std::lock_guard<std::mutex> lk(mtx);
                        if (seen_mins.insert(mk).second) {
                            found.push_back({mk, {ps[0].second, ps[1].second, ps[2].second}, g});
                        }
                    }
                }
            }
        });
    }
    for (auto& th : ths) th.join();
    std::sort(found.begin(), found.end(), [](const auto& a, const auto& b){ return std::get<0>(a) > std::get<0>(b); });
    std::cout << name << " | trials=" << trials.load() << " | found=" << found.size() << "\n";
    for (const auto& [mk, ms, g] : found) {
        std::cout << "  mins=(" << std::get<0>(mk) << "," << std::get<1>(mk) << "," << std::get<2>(mk) << ")"
                  << " S=" << mask_to_str(ms[0]) << "," << mask_to_str(ms[1]) << "," << mask_to_str(ms[2]) << " edges=";
        bool f = true;
        for (int u = 0; u < g.n; ++u) for (int v = u + 1; v < g.n; ++v)
            if ((g.rows[u] >> v) & 1u) { if (!f) std::cout << ","; std::cout << "(" << u << "," << v << ")"; f = false; }
        std::cout << "\n";
    }
    std::cout << std::flush;
}

int main() {
    // Also check ports with deg 3 (which become deg 4 in the final graph!) + multi-deg4 internals!
    search_degseq("n=7 (ports 2,2,2 + 2xdeg4)", {2,2,2, 3,3, 4,4}, 2.0);
    search_degseq("n=7 (ports 2,2,3 + 1xdeg4)", {2,2,3, 3,3,3, 4}, 2.0);
    search_degseq("n=6 (ports 2,2,3 + 0xdeg4)", {2,2,3, 3,3,3}, 2.0);
    search_degseq("n=8 (ports 2,2,3 + 2xdeg4)", {2,2,3, 3,3,3, 4,4}, 2.0);
    search_degseq("n=9 (ports 2,2,2 + 2xdeg4)", {2,2,2, 3,3,3,3, 4,4}, 2.5);
    search_degseq("n=10 (ports 2,2,2 + 3xdeg4)", {2,2,2, 3,3,3,3, 4,4,4}, 2.5);
    search_degseq("n=11 (ports 2,2,2 + 2xdeg4)", {2,2,2, 3,3,3,3,3,3, 4,4}, 2.5);
    search_degseq("n=13 (ports 2,2,2 + 2xdeg4)", {2,2,2, 3,3,3,3,3,3,3,3, 4,4}, 3.0);
    return 0;
}

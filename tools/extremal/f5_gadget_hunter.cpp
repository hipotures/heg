// Fast 16-core C++17 search for {C4, C8, C16}-free 3-port gadgets of orders:
//   - Cubic: n = 9, 11, 13, 15 (3 ports deg 2, n-3 internals deg 3)
//   - Mixed delta>=3: n = 6, 8, 10, 12, 14 (3 ports deg 2, n-4 internals deg 3, 1 internal deg 4)
// Computes exact internal cycles {4, 8, 16} AND exact port-to-port path-length sets S(0,1), S(0,2), S(1,2)!
#include <algorithm>
#include <array>
#include <atomic>
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
    uint32_t vis = 1u;
    uint32_t q = 1u;
    while (q) {
        int u = __builtin_ctz(q);
        q &= q - 1;
        uint32_t nxt = g.rows[u] & ~vis;
        vis |= nxt;
        q |= nxt;
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
        // Recursive bitset DFS
        auto dfs = [&](auto&& self, int u, int depth, uint32_t vis, int first) -> bool {
            if (depth == target) {
                return ((g.rows[u] >> s) & 1u) && first < u;
            }
            uint32_t avail = g.rows[u] & gt & ~vis;
            while (avail) {
                int w = __builtin_ctz(avail);
                avail &= avail - 1;
                if (self(self, w, depth + 1, vis | (1u << w), first)) return true;
            }
            return false;
        };
        uint32_t b = nbrs;
        while (b) {
            int v = __builtin_ctz(b);
            b &= b - 1;
            if (dfs(dfs, v, 2, (1u << s) | (1u << v), v)) return true;
        }
    }
    return false;
}

static uint32_t path_lengths_mask(const Gadget& g, int src, int dst) {
    uint32_t mask = 0;
    auto dfs = [&](auto&& self, int u, int d, uint32_t vis) -> void {
        if (u == dst) {
            mask |= (1u << d);
            return;
        }
        uint32_t avail = g.rows[u] & ~vis;
        while (avail) {
            int w = __builtin_ctz(avail);
            avail &= avail - 1;
            self(self, w, d + 1, vis | (1u << w));
        }
    };
    dfs(dfs, src, 0, 1u << src);
    return mask;
}

// Check if a random pairing of stubs builds a simple connected {C4,C8,C16}-free gadget
// Also supports 2-edge switch hill-climbing from a random valid degree-sequence graph to eliminate C4/C8/C16!
static bool build_random_simple(int n, const std::vector<int>& degs, std::mt19937_64& rng, Gadget& out) {
    std::vector<int> stubs;
    stubs.reserve(48);
    for (int i = 0; i < n; ++i)
        for (int d = 0; d < degs[i]; ++d) stubs.push_back(i);

    for (int attempt = 0; attempt < 24; ++attempt) {
        std::shuffle(stubs.begin(), stubs.end(), rng);
        out.n = n;
        out.rows.fill(0);
        bool ok = true;
        for (size_t i = 0; i < stubs.size(); i += 2) {
            int u = stubs[i], v = stubs[i + 1];
            if (u == v || ((out.rows[u] >> v) & 1u)) {
                ok = false;
                break;
            }
            out.rows[u] |= (1u << v);
            out.rows[v] |= (1u << u);
        }
        if (ok && is_connected(out)) return true;
    }
    return false;
}

static int count_c4_c8(const Gadget& g) {
    int c4 = 0, c8 = 0;
    const int n = g.n;
    // Exact C4
    for (int s = 0; s <= n - 4; ++s) {
        uint32_t gt = ~((1u << (s + 1)) - 1u);
        uint32_t nb = g.rows[s] & gt;
        while (nb) {
            int a = __builtin_ctz(nb);
            nb &= nb - 1;
            uint32_t r = nb;
            uint32_t ra = g.rows[a] & gt;
            while (r) {
                int b = __builtin_ctz(r);
                r &= r - 1;
                c4 += __builtin_popcount(ra & g.rows[b]);
            }
        }
    }
    if (c4 > 0) return c4 * 100 + 50;
    if (has_cycle_len(g, 8)) return 10;
    if (g.n >= 16 && has_cycle_len(g, 16)) return 5;
    return 0;
}

static std::string mask_to_str(uint32_t m) {
    std::string s = "[";
    bool first = true;
    for (int i = 0; i < 20; ++i) {
        if ((m >> i) & 1u) {
            if (!first) s += ",";
            s += std::to_string(i);
            first = false;
        }
    }
    return s + "]";
}

static void search_order(int n, bool mixed_deg4, int seconds_per_order, int workers) {
    std::vector<int> degs(n, 3);
    degs[0] = degs[1] = degs[2] = 2;
    if (mixed_deg4) degs[n - 1] = 4;

    std::mutex mtx;
    std::set<std::tuple<int, int, int, uint32_t, uint32_t, uint32_t>> seen;
    std::vector<std::tuple<std::tuple<int, int, int>, std::array<uint32_t, 3>, Gadget>> found;
    std::atomic<uint64_t> total_trials{0};

    auto t0 = std::chrono::steady_clock::now();
    std::vector<std::thread> threads;
    for (int tid = 0; tid < workers; ++tid) {
        threads.emplace_back([&, tid]() {
            std::mt19937_64 rng(2026112700ULL + (uint64_t)n * 1000 + (mixed_deg4 ? 500 : 0) + tid * 131);
            Gadget g;
            std::vector<std::pair<int, int>> edges;
            edges.reserve(32);

            while (true) {
                auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
                if (elapsed >= seconds_per_order) break;

                for (int batch = 0; batch < 256; ++batch) {
                    if (!build_random_simple(n, degs, rng, g)) continue;
                    total_trials.fetch_add(1, std::memory_order_relaxed);

                    // Fast hill-climb with up to 40 2-edge switches to eliminate C4/C8/C16!
                    int cur_pen = count_c4_c8(g);
                    for (int st = 0; st < 45 && cur_pen > 0; ++st) {
                        edges.clear();
                        for (int u = 0; u < n; ++u) {
                            uint32_t b = g.rows[u] & ~((1u << (u + 1)) - 1u);
                            while (b) {
                                int v = __builtin_ctz(b);
                                b &= b - 1;
                                edges.push_back({u, v});
                            }
                        }
                        if (edges.size() < 2) break;
                        auto [a, b] = edges[rng() % edges.size()];
                        auto [c, d] = edges[rng() % edges.size()];
                        if (a == c || a == d || b == c || b == d) continue;
                        int p1u = a, p1v = (rng() & 1) ? c : d;
                        int p2u = b, p2v = (p1v == c) ? d : c;
                        if (((g.rows[p1u] >> p1v) & 1u) || ((g.rows[p2u] >> p2v) & 1u)) continue;

                        Gadget cand = g;
                        cand.rows[a] ^= (1u << b); cand.rows[b] ^= (1u << a);
                        cand.rows[c] ^= (1u << d); cand.rows[d] ^= (1u << c);
                        cand.rows[p1u] |= (1u << p1v); cand.rows[p1v] |= (1u << p1u);
                        cand.rows[p2u] |= (1u << p2v); cand.rows[p2v] |= (1u << p2u);
                        if (!is_connected(cand)) continue;
                        int np = count_c4_c8(cand);
                        if (np <= cur_pen) {
                            g = cand;
                            cur_pen = np;
                        }
                    }

                    if (cur_pen == 0 && !has_cycle_len(g, 4) && !has_cycle_len(g, 8) && !has_cycle_len(g, 16)) {
                        uint32_t m01 = path_lengths_mask(g, 0, 1);
                        uint32_t m02 = path_lengths_mask(g, 0, 2);
                        uint32_t m12 = path_lengths_mask(g, 1, 2);
                        if ((m01 & 2u) || (m02 & 2u) || (m12 & 2u)) continue; // skip direct port-port edge (dist=1)
                        std::array<uint32_t, 3> ms{m01, m02, m12};
                        std::array<int, 3> mins{
                            __builtin_ctz(m01),
                            __builtin_ctz(m02),
                            __builtin_ctz(m12)
                        };
                        // Sort by (min, mask)
                        std::array<std::pair<int, uint32_t>, 3> pairs{
                            {{mins[0], ms[0]}, {mins[1], ms[1]}, {mins[2], ms[2]}}
                        };
                        std::sort(pairs.begin(), pairs.end());
                        auto key = std::make_tuple(
                            pairs[0].first, pairs[1].first, pairs[2].first,
                            pairs[0].second, pairs[1].second, pairs[2].second
                        );
                        std::lock_guard<std::mutex> lk(mtx);
                        if (seen.insert(key).second) {
                            found.push_back({
                                {pairs[0].first, pairs[1].first, pairs[2].first},
                                {pairs[0].second, pairs[1].second, pairs[2].second},
                                g
                            });
                        }
                    }
                }
            }
        });
    }
    for (auto& th : threads) th.join();

    // Sort by lexicographically largest (min0, min1, min2)!
    std::sort(found.begin(), found.end(), [](const auto& a, const auto& b) {
        return std::get<0>(a) > std::get<0>(b);
    });

    std::cout << "Order n=" << n << (mixed_deg4 ? " (delta>=3, 1xdeg4)" : " (cubic)")
              << " | trials=" << total_trials.load()
              << " | distinct {C4,C8,C16}-free port-window types=" << found.size() << "\n";
    int shown = 0;
    std::set<std::tuple<int, int, int>> printed_mins;
    for (const auto& [mins, masks, g] : found) {
        if (!printed_mins.insert(mins).second) continue;
        std::cout << "  mins=(" << std::get<0>(mins) << "," << std::get<1>(mins) << "," << std::get<2>(mins) << ")"
                  << " | S=" << mask_to_str(masks[0]) << ", " << mask_to_str(masks[1]) << ", " << mask_to_str(masks[2])
                  << " | edges=";
        bool first = true;
        for (int u = 0; u < g.n; ++u) {
            for (int v = u + 1; v < g.n; ++v) {
                if ((g.rows[u] >> v) & 1u) {
                    if (!first) std::cout << ",";
                    std::cout << "(" << u << "," << v << ")";
                    first = false;
                }
            }
        }
        std::cout << "\n";
        if (++shown >= 8) break;
    }
    std::cout << std::flush;
}

int main() {
    std::cout << "=== 16-CORE {C4, C8, C16}-FREE 3-PORT GADGET HUNTER (n = 6..15) ===\n" << std::flush;
    // Cubic orders: 9, 11, 13, 15
    for (int n : {9, 11, 13, 15}) {
        search_order(n, false, (n >= 13 ? 5 : 3), 16);
    }
    // Non-cubic (1x deg-4) orders: 6, 8, 10, 12, 14
    for (int n : {6, 8, 10, 12, 14}) {
        search_order(n, true, (n >= 12 ? 4 : 2), 16);
    }
    return 0;
}

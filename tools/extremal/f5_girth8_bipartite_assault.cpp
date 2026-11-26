// Phase R2 Breakthrough Engine: Non-Tutte-Coxeter Bipartite Girth-8 Cubic Bases (n_B = 34..46)
// for shattering f_cubic(5) <= 370 AND f_{delta>=3}(5) <= 345!
//
// Mathematical insight:
//   - In ANY bipartite cubic graph B of girth 8 (ZERO cycles of length 3..7 AND ZERO 9-cycles!),
//     every base cycle of length >= 11 automatically lifts to >= 33 > 32 under H7 (lo>=2)!
//   - Only 8-cycles and 10-cycles can ever realize length 32!
//   - Tutte-Coxeter (30) packs 90 eight-cycles into 30 vertices (24 per vertex), forcing >= 20 copies of H15 (n=370).
//   - Larger bipartite girth-8 cubic graphs (n_B = 34, 36, 38, 40, 42, 44, 46) have FAR fewer 8-cycles!
//     E.g. on n_B = 38 with 8 copies of H15 + 30 copies of H7 => n = 120 + 210 = 330 STRICTLY CUBIC!
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <mutex>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

struct BipGraph {
    int n;
    int half;
    std::vector<std::vector<int>> adj;
};

struct Cycle {
    int len;
    std::vector<std::pair<int, int>> items; // (v, off_cycle_nbr_idx)
};

static int count_cycles_len_exact(const BipGraph& g, int target) {
    int n = g.n;
    int cnt = 0;
    std::vector<int> path;
    for (int s = 0; s <= n - target; ++s) {
        auto dfs = [&](auto&& self, int u, int d, uint64_t vis, int first) -> void {
            if (d == target) {
                for (int w : g.adj[u]) if (w == s && first < u) { ++cnt; break; }
                return;
            }
            for (int w : g.adj[u]) {
                if (w > s && !((vis >> w) & 1ULL)) {
                    self(self, w, d + 1, vis | (1ULL << w), first);
                }
            }
        };
        for (int v : g.adj[s]) {
            if (v > s) dfs(dfs, v, 2, (1ULL << s) | (1ULL << v), v);
        }
    }
    return cnt;
}

static bool is_connected_bg(const BipGraph& g) {
    uint64_t vis = 1ULL;
    std::vector<int> q{0};
    for (size_t i = 0; i < q.size(); ++i) {
        for (int w : g.adj[q[i]]) {
            if (!((vis >> w) & 1ULL)) { vis |= (1ULL << w); q.push_back(w); }
        }
    }
    return (int)q.size() == g.n;
}

// Fast count of C4 + C6 (for girth >= 8 hill-climbing)
static std::pair<int, int> count_c4_c6(const BipGraph& g) {
    int c4 = 0, c6 = 0;
    const int n = g.n;
    // C4: canonical min vertex s in A (0..half-1) -> b1 -> a2 -> b2 -> s
    for (int s = 0; s < g.half; ++s) {
        int seen[64] = {0};
        for (int b : g.adj[s]) {
            for (int a : g.adj[b]) {
                if (a > s) { c4 += seen[a]; seen[a]++; }
            }
        }
    }
    if (c4 > 0) return {c4, 999};
    c6 = count_cycles_len_exact(g, 6);
    return {0, c6};
}

// Generate a bipartite cubic graph of order n with girth >= 8 and MINIMIZED C8 count!
static bool build_low_c8_girth8_bipartite(int n, uint64_t seed, BipGraph& out, int& c8_out) {
    std::mt19937_64 rng(seed);
    int half = n / 2;
    for (int restart = 0; restart < 30; ++restart) {
        BipGraph g{n, half, std::vector<std::vector<int>>(n)};
        // 3 random disjoint perfect matchings
        bool ok = true;
        for (int m = 0; m < 3 && ok; ++m) {
            std::vector<int> perm(half);
            for (int i = 0; i < half; ++i) perm[i] = half + i;
            for (int tr = 0; tr < 40; ++tr) {
                std::shuffle(perm.begin(), perm.end(), rng);
                bool clean = true;
                for (int i = 0; i < half; ++i) {
                    if (std::find(g.adj[i].begin(), g.adj[i].end(), perm[i]) != g.adj[i].end()) {
                        clean = false; break;
                    }
                }
                if (clean) {
                    for (int i = 0; i < half; ++i) {
                        g.adj[i].push_back(perm[i]);
                        g.adj[perm[i]].push_back(i);
                    }
                    break;
                }
                if (tr == 39) ok = false;
            }
        }
        if (!ok || !is_connected_bg(g)) continue;

        auto [c4, c6] = count_c4_c6(g);
        int cur_pen = c4 * 1000 + c6 * 20;
        int cur_c8 = (cur_pen == 0) ? count_cycles_len_exact(g, 8) : 9999;

        // Hill-climb to C4=0, C6=0, then minimize C8!
        for (int step = 0; step < 3500; ++step) {
            int a1 = (int)(rng() % half);
            int b1 = g.adj[a1][rng() % 3];
            int a2 = (int)(rng() % half);
            int b2 = g.adj[a2][rng() % 3];
            if (a1 == a2 || b1 == b2) continue;
            if (std::find(g.adj[a1].begin(), g.adj[a1].end(), b2) != g.adj[a1].end()) continue;
            if (std::find(g.adj[a2].begin(), g.adj[a2].end(), b1) != g.adj[a2].end()) continue;

            // Swap (a1,b1),(a2,b2) -> (a1,b2),(a2,b1)
            auto swap_e = [&](int x1, int y1, int x2, int y2) {
                *std::find(g.adj[x1].begin(), g.adj[x1].end(), y1) = y2;
                *std::find(g.adj[y1].begin(), g.adj[y1].end(), x1) = x2;
                *std::find(g.adj[x2].begin(), g.adj[x2].end(), y2) = y1;
                *std::find(g.adj[y2].begin(), g.adj[y2].end(), x2) = x1;
            };
            swap_e(a1, b1, a2, b2);
            if (!is_connected_bg(g)) { swap_e(a1, b2, a2, b1); continue; }
            auto [nc4, nc6] = count_c4_c6(g);
            int npen = nc4 * 1000 + nc6 * 20;
            if (npen < cur_pen) {
                cur_pen = npen;
                if (cur_pen == 0) cur_c8 = count_cycles_len_exact(g, 8);
            } else if (npen == cur_pen) {
                if (cur_pen == 0) {
                    int nc8 = count_cycles_len_exact(g, 8);
                    if (nc8 <= cur_c8) {
                        cur_c8 = nc8;
                    } else {
                        swap_e(a1, b2, a2, b1);
                    }
                } else {
                    // sideways allowed during C4/C6 phase
                }
            } else {
                swap_e(a1, b2, a2, b1);
            }
        }
        if (cur_pen == 0) {
            for (auto& a : g.adj) std::sort(a.begin(), a.end());
            out = g;
            c8_out = cur_c8;
            return true;
        }
    }
    return false;
}

static std::vector<Cycle> find_cycles_up_to(const std::vector<std::vector<int>>& adj, int max_len) {
    int n = (int)adj.size();
    std::vector<Cycle> out;
    std::vector<int> path, dist(n);
    for (int s = 0; s < n; ++s) {
        std::fill(dist.begin(), dist.end(), 999);
        dist[s] = 0;
        std::vector<int> q{s};
        for (size_t qh = 0; qh < q.size(); ++qh) {
            int u = q[qh];
            if (dist[u] >= max_len - 1) continue;
            for (int w : adj[u]) if (w > s && dist[w] > dist[u] + 1) { dist[w] = dist[u] + 1; q.push_back(w); }
        }
        auto dfs = [&](auto&& self, int u, uint64_t vis, int first) -> void {
            int d = (int)path.size();
            if (d >= 3 && std::binary_search(adj[u].begin(), adj[u].end(), s) && first < u) {
                Cycle c; c.len = d;
                for (int idx = 0; idx < d; ++idx) {
                    int v = path[idx], pv = path[(idx + d - 1) % d], nv = path[(idx + 1) % d];
                    int ia = (int)(std::find(adj[v].begin(), adj[v].end(), pv) - adj[v].begin());
                    int ib = (int)(std::find(adj[v].begin(), adj[v].end(), nv) - adj[v].begin());
                    c.items.push_back({v, 3 - ia - ib});
                }
                out.push_back(std::move(c));
            }
            if (d >= max_len) return;
            int rem = max_len - d;
            for (int w : adj[u]) {
                if (w > s && !((vis >> w) & 1ULL) && dist[w] <= rem) {
                    path.push_back(w); self(self, w, vis | (1ULL << w), first); path.pop_back();
                }
            }
        };
        for (int v : adj[s]) if (v > s) { path = {s, v}; dfs(dfs, v, (1ULL << s) | (1ULL << v), v); }
    }
    return out;
}

static inline std::pair<int, int> gadget_contrib(int gt, int p0_v, int off_idx) {
    switch (gt) {
        case 1: return {(p0_v == off_idx) ? 3 : 2, 6};   // H7
        case 2: return {(p0_v == off_idx) ? 5 : 3, 14};  // H15
        case 3: return {(p0_v == off_idx) ? 2 : 3, 7};   // H8*
        default: return {0, 0};
    }
}

static bool solve_base_config(
    const std::vector<std::vector<int>>& adj,
    const std::vector<Cycle>& cycs,
    int a15, int b8, int c7,
    double secs,
    std::vector<int>& best_gt_out,
    std::vector<int>& best_p0_out,
    int& best_viol_out
) {
    const int n = (int)adj.size(), m = (int)cycs.size();
    std::vector<int> init_t;
    for (int i = 0; i < a15; ++i) init_t.push_back(2);
    for (int i = 0; i < b8; ++i) init_t.push_back(3);
    for (int i = 0; i < c7; ++i) init_t.push_back(1);
    std::vector<std::vector<int>> v2c(n);
    for (int ci = 0; ci < m; ++ci) for (auto [v, _] : cycs[ci].items) v2c[v].push_back(ci);

    auto is_bad = [&](int ci, const std::vector<int>& gt, const std::vector<int>& p0) -> bool {
        const auto& c = cycs[ci];
        int lo = c.len, h = c.len;
        for (auto [v, off_idx] : c.items) {
            auto [dl, dh] = gadget_contrib(gt[v], p0[v], off_idx);
            lo += dl; h += dh;
        }
        return (lo <= 32 && 32 <= h) || (lo <= 16 && 16 <= h) || (lo <= 8 && 8 <= h) || (lo <= 4 && 4 <= h);
    };

    std::atomic<bool> solved{false};
    std::mutex mtx;
    best_viol_out = m + 1;
    auto t0 = std::chrono::steady_clock::now();

    std::vector<std::thread> ths;
    for (int tid = 0; tid < 16; ++tid) {
        ths.emplace_back([&, tid]() {
            std::mt19937_64 rng(888202611ULL + tid * 999983ULL + n * 101 + a15 * 17 + b8 * 7);
            std::vector<int> gt(n), p0(n);
            std::vector<uint8_t> bad_flag(m);
            std::vector<int> bad_list; bad_list.reserve(m);
            std::vector<int> bad_pos(m, -1);
            auto add_b = [&](int ci){ bad_pos[ci]=(int)bad_list.size(); bad_list.push_back(ci); bad_flag[ci]=1; };
            auto rem_b = [&](int ci){ int p=bad_pos[ci], l=bad_list.back(); bad_list[p]=l; bad_pos[l]=p; bad_list.pop_back(); bad_pos[ci]=-1; bad_flag[ci]=0; };
            auto str = [](int t){ return t==2?3:(t==3?2:1); };

            while (!solved.load(std::memory_order_relaxed)) {
                if (std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() >= secs) break;
                gt = init_t; std::shuffle(gt.begin(), gt.end(), rng);
                for (int i = 0; i < n; ++i) p0[i] = (int)(rng() % 3);
                bad_list.clear(); std::fill(bad_pos.begin(), bad_pos.end(), -1);
                for (int ci = 0; ci < m; ++ci) { if (is_bad(ci, gt, p0)) add_b(ci); else bad_flag[ci] = 0; }
                int lbest = (int)bad_list.size();
                if (lbest < best_viol_out) {
                    std::lock_guard<std::mutex> lk(mtx);
                    if (lbest < best_viol_out) {
                        best_viol_out = lbest; best_gt_out = gt; best_p0_out = p0;
                        if (lbest == 0) { solved.store(true); return; }
                    }
                }
                for (int step = 0; step < 200000 && !solved.load(std::memory_order_relaxed); ++step) {
                    if ((step & 2047) == 0 && std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() >= secs) break;
                    if (bad_list.empty()) {
                        std::lock_guard<std::mutex> lk(mtx);
                        best_viol_out = 0; best_gt_out = gt; best_p0_out = p0;
                        solved.store(true); return;
                    }
                    int ci = bad_list[rng() % bad_list.size()];
                    const auto& items = cycs[ci].items;
                    if ((rng() % 100) < 35) {
                        int v_l = items[0].first;
                        for (auto [v, _] : items) if (str(gt[v]) < str(gt[v_l])) v_l = v;
                        if ((rng() & 1) == 0) v_l = items[rng() % items.size()].first;
                        int sl = str(gt[v_l]), best_w = -1, best_d = 1e9;
                        for (int tr = 0; tr < 12; ++tr) {
                            int w = (int)(rng() % n);
                            if (str(gt[w]) <= sl) continue;
                            std::swap(gt[v_l], gt[w]);
                            int d = 0;
                            for (int c2 : v2c[v_l]) { bool nb = is_bad(c2, gt, p0); if (nb && !bad_flag[c2]) ++d; else if (!nb && bad_flag[c2]) --d; }
                            for (int c2 : v2c[w]) { if (std::binary_search(v2c[v_l].begin(), v2c[v_l].end(), c2)) continue; bool nb = is_bad(c2, gt, p0); if (nb && !bad_flag[c2]) ++d; else if (!nb && bad_flag[c2]) --d; }
                            std::swap(gt[v_l], gt[w]);
                            if (d < best_d) { best_d = d; best_w = w; }
                        }
                        if (best_w != -1 && (best_d <= 0 || (rng() % 100) < 12)) {
                            std::swap(gt[v_l], gt[best_w]);
                            for (int c2 : v2c[v_l]) { bool nb = is_bad(c2, gt, p0); if (nb && !bad_flag[c2]) add_b(c2); else if (!nb && bad_flag[c2]) rem_b(c2); }
                            for (int c2 : v2c[best_w]) { bool nb = is_bad(c2, gt, p0); if (nb && !bad_flag[c2]) add_b(c2); else if (!nb && bad_flag[c2]) rem_b(c2); }
                            if ((int)bad_list.size() < lbest) {
                                lbest = (int)bad_list.size();
                                std::lock_guard<std::mutex> lk(mtx);
                                if (lbest < best_viol_out) {
                                    best_viol_out = lbest; best_gt_out = gt; best_p0_out = p0;
                                    if (lbest == 0) { solved.store(true); return; }
                                }
                            }
                            continue;
                        }
                    }
                    int best_v = -1, best_c = -1, best_d = 1e9, ties = 0;
                    for (auto [v, _] : items) {
                        int old_c = p0[v];
                        for (int nc = 0; nc < 3; ++nc) {
                            if (nc == old_c) continue;
                            p0[v] = nc; int d = 0;
                            for (int c2 : v2c[v]) { bool nb = is_bad(c2, gt, p0); if (nb && !bad_flag[c2]) ++d; else if (!nb && bad_flag[c2]) --d; }
                            p0[v] = old_c;
                            if (d < best_d) { best_d = d; best_v = v; best_c = nc; ties = 1; }
                            else if (d == best_d && (rng() % (++ties)) == 0) { best_v = v; best_c = nc; }
                        }
                    }
                    if (best_v == -1) continue;
                    if ((rng() % 100) < 15) { best_v = items[rng() % items.size()].first; best_c = (p0[best_v] + 1 + (int)(rng() % 2)) % 3; }
                    p0[best_v] = best_c;
                    for (int c2 : v2c[best_v]) { bool nb = is_bad(c2, gt, p0); if (nb && !bad_flag[c2]) add_b(c2); else if (!nb && bad_flag[c2]) rem_b(c2); }
                    if ((int)bad_list.size() < lbest) {
                        lbest = (int)bad_list.size();
                        std::lock_guard<std::mutex> lk(mtx);
                        if (lbest < best_viol_out) {
                            best_viol_out = lbest; best_gt_out = gt; best_p0_out = p0;
                            if (lbest == 0) { solved.store(true); return; }
                        }
                    }
                }
            }
        });
    }
    for (auto& th : ths) th.join();
    return best_viol_out == 0;
}

int main() {
    std::cout << "=== PHASE R2: BIPARTITE GIRTH-8 CUBIC BASES (n_B = 34..48) FOR f(5) < 370 & < 345 ===\n" << std::flush;
    std::ofstream ofs("/home/user/.gemini/antigravity-cli/brain/560c9e05-87fd-4ced-8168-8df5a850e495/scratch/f5_girth8_new_records.json");
    ofs << "[\n";
    bool first_json = true;

    int best_cubic_n = 370;
    int best_delta3_n = 345;

    for (int nb : {34, 36, 38, 40, 42, 44, 46, 48}) {
        // Generate up to 8 independent low-C8 bipartite girth-8 cubic graphs on nb vertices, keep the lowest C8!
        BipGraph best_bg;
        int best_c8 = 999999;
        bool got = false;
        for (int s = 0; s < 10; ++s) {
            BipGraph bg;
            int c8 = 999999;
            if (build_low_c8_girth8_bipartite(nb, 2026112700ULL + nb * 100 + s, bg, c8)) {
                if (c8 < best_c8) { best_c8 = c8; best_bg = bg; got = true; }
            }
        }
        if (!got) {
            std::cout << "n_B=" << nb << ": failed to construct girth-8 bipartite base quickly.\n" << std::flush;
            continue;
        }
        auto cycs = find_cycles_up_to(best_bg.adj, 10);
        int c10 = (int)cycs.size() - best_c8;
        std::cout << "\n--- Base B_" << nb << " (bipartite girth 8): C8=" << best_c8 << ", C10=" << c10 << " (tot L<=10: " << cycs.size() << ") ---\n" << std::flush;

        // 1. CUBIC: a15 * H15 + (nb - a15) * H7 -> n = 7*nb + 8*a15!
        // Only test a15 where 7*nb + 8*a15 < best_cubic_n!
        int max_a15_cub = (best_cubic_n - 1 - 7 * nb) / 8;
        for (int a15 = max_a15_cub; a15 >= 0; --a15) {
            int n_tot = 7 * nb + 8 * a15;
            if (n_tot >= best_cubic_n) continue;
            std::vector<int> gt, p0;
            int viol = 0;
            bool ok = solve_base_config(best_bg.adj, cycs, a15, 0, nb - a15, 6.0, gt, p0, viol);
            std::cout << "  [CUBIC] B_" << nb << " + " << a15 << "*H15 + " << (nb - a15) << "*H7 -> n=" << n_tot
                      << " | min_viol=" << viol << (ok ? " *** NEW CUBIC RECORD!! ***" : "") << "\n" << std::flush;
            if (ok) {
                best_cubic_n = n_tot;
                if (!first_json) ofs << ",\n";
                first_json = false;
                ofs << "  {\"label\":\"B" << nb << "_" << a15 << "H15_" << (nb - a15) << "H7\",\"nb\":" << nb
                    << ",\"n\":" << n_tot << ",\"cubic\":true,\"c8_base\":" << best_c8 << ",\"c10_base\":" << c10
                    << ",\"edges\":[";
                bool fe = true;
                for (int u = 0; u < nb; ++u) for (int v : best_bg.adj[u]) if (u < v) {
                    if (!fe) ofs << ","; fe = false; ofs << "[" << u << "," << v << "]";
                }
                ofs << "],\"gt\":[";
                for (int i = 0; i < nb; ++i) { if (i) ofs << ","; ofs << gt[i]; }
                ofs << "],\"p0\":[";
                for (int i = 0; i < nb; ++i) { if (i) ofs << ","; ofs << p0[i]; }
                ofs << "]}";
                ofs.flush();
            } else if (viol >= 5) {
                break;
            }
        }

        // 2. GENERAL delta>=3 with H8* + H7 + H15!
        // Try pure a15 * H15 + (nb - a15) * H8* -> n = 8*nb + 7*a15!
        int max_a15_d3 = (best_delta3_n - 1 - 8 * nb) / 7;
        for (int a15 = max_a15_d3; a15 >= 0; --a15) {
            int n_tot = 8 * nb + 7 * a15;
            if (n_tot >= best_delta3_n) continue;
            std::vector<int> gt, p0;
            int viol = 0;
            bool ok = solve_base_config(best_bg.adj, cycs, a15, nb - a15, 0, 6.0, gt, p0, viol);
            std::cout << "  [d>=3 ] B_" << nb << " + " << a15 << "*H15 + " << (nb - a15) << "*H8* -> n=" << n_tot
                      << " | min_viol=" << viol << (ok ? " *** NEW delta>=3 RECORD!! ***" : "") << "\n" << std::flush;
            if (ok) {
                best_delta3_n = n_tot;
                if (!first_json) ofs << ",\n";
                first_json = false;
                ofs << "  {\"label\":\"B" << nb << "_" << a15 << "H15_" << (nb - a15) << "H8s\",\"nb\":" << nb
                    << ",\"n\":" << n_tot << ",\"cubic\":false,\"c8_base\":" << best_c8 << ",\"c10_base\":" << c10
                    << ",\"edges\":[";
                bool fe = true;
                for (int u = 0; u < nb; ++u) for (int v : best_bg.adj[u]) if (u < v) {
                    if (!fe) ofs << ","; fe = false; ofs << "[" << u << "," << v << "]";
                }
                ofs << "],\"gt\":[";
                for (int i = 0; i < nb; ++i) { if (i) ofs << ","; ofs << gt[i]; }
                ofs << "],\"p0\":[";
                for (int i = 0; i < nb; ++i) { if (i) ofs << ","; ofs << p0[i]; }
                ofs << "]}";
                ofs.flush();
            } else if (viol >= 5) {
                break;
            }
        }
    }
    ofs << "\n]\n";
    std::cout << "\n=== PHASE R2 GIRTH-8 SWEEP COMPLETE | BEST CUBIC n=" << best_cubic_n
              << " | BEST delta>=3 n=" << best_delta3_n << " ===\n";
    return 0;
}

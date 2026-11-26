// Exact C++17 solver testing 1-edge and 2-edge contractions of Petersen (and other small bases)
// with our exhaustively discovered 4-port {C4, C8, C16}-free gadgets Q9, Q11*, Q12, Q13*, Q14
// plus 3-port {H7, H8*} to hunt f_{delta>=3}(4) < 73!
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <vector>

struct Gadget {
    std::string name;
    int n;
    int np;
    bool cubic;
    std::vector<std::pair<int, int>> edges;
    std::array<std::array<uint32_t, 4>, 4> masks{};
};

static Gadget make_gadget(std::string name, int n, int np, bool cubic, std::vector<std::pair<int, int>> edges) {
    Gadget g{name, n, np, cubic, edges, {}};
    std::vector<uint32_t> rows(n, 0);
    for (auto [u, v] : edges) { rows[u] |= (1u << v); rows[v] |= (1u << u); }
    for (int i = 0; i < np; ++i) {
        for (int j = i + 1; j < np; ++j) {
            uint32_t m = 0;
            auto dfs = [&](auto&& self, int u, int d, uint32_t vis) -> void {
                if (u == j) { m |= (1u << d); return; }
                uint32_t av = rows[u] & ~vis;
                while (av) { int w = __builtin_ctz(av); av &= av - 1; self(self, w, d + 1, vis | (1u << w)); }
            };
            dfs(dfs, i, 0, 1u << i);
            g.masks[i][j] = g.masks[j][i] = m;
        }
    }
    return g;
}

struct BaseCycle {
    int len;
    std::vector<std::tuple<int, int, int>> steps; // (v, idx_prev, idx_next)
};

static std::vector<BaseCycle> get_cycles(int n, const std::vector<std::vector<int>>& adj, int max_len = 8) {
    std::vector<BaseCycle> out;
    std::vector<int> path;
    for (int s = 0; s < n; ++s) {
        auto dfs = [&](auto&& self, int u, uint32_t vis, int first) -> void {
            int d = (int)path.size();
            if (d >= 3 && std::binary_search(adj[u].begin(), adj[u].end(), s) && first < u) {
                BaseCycle bc;
                bc.len = d;
                for (int i = 0; i < d; ++i) {
                    int v = path[i];
                    int pv = path[(i + d - 1) % d];
                    int nv = path[(i + 1) % d];
                    int ia = (int)(std::find(adj[v].begin(), adj[v].end(), pv) - adj[v].begin());
                    int ib = (int)(std::find(adj[v].begin(), adj[v].end(), nv) - adj[v].begin());
                    bc.steps.push_back({v, ia, ib});
                }
                out.push_back(std::move(bc));
            }
            if (d >= max_len) return;
            for (int w : adj[u]) {
                if (w > s && !((vis >> w) & 1u)) {
                    path.push_back(w);
                    self(self, w, vis | (1u << w), first);
                    path.pop_back();
                }
            }
        };
        for (int v : adj[s]) {
            if (v > s) { path = {s, v}; dfs(dfs, v, (1u << s) | (1u << v), v); }
        }
    }
    return out;
}

static inline bool cycle_ok(
    const BaseCycle& bc,
    const std::vector<const Gadget*>& gptr,
    const std::vector<std::array<int, 4>>& perm
) {
    // Exact bitmask convolution for lengths <= 16!
    uint32_t acc = 1u << bc.len;
    for (auto [v, ia, ib] : bc.steps) {
        int pa = perm[v][ia], pb = perm[v][ib];
        uint32_t pm = gptr[v]->masks[pa][pb];
        uint32_t nacc = 0;
        while (pm) {
            int sh = __builtin_ctz(pm); pm &= pm - 1;
            nacc |= (acc << sh);
        }
        acc = nacc & 0x1FFFFu; // bits 0..16
        if (acc == 0) return true;
    }
    return ((acc & ((1u << 4) | (1u << 8) | (1u << 16))) == 0);
}

static bool solve_base(
    const std::string& label,
    int n_base,
    const std::vector<std::vector<int>>& adj,
    int k4,
    const Gadget& Q,
    const Gadget& H7,
    const Gadget& H8,
    int n_h8,
    int n_unexp = 0
) {
    auto cycs = get_cycles(n_base, adj, n_unexp > 0 ? 7 : 6);
    int n3 = n_base - k4;
    int n_h7 = n3 - n_h8 - n_unexp;
    if (n_h7 < 0) return false;
    int tot_n = k4 * Q.n + n_h8 * 8 + n_h7 * 7 + n_unexp;

    Gadget Unexp{"U1", 1, 3, true, {}, {}};
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) if (i != j) Unexp.masks[i][j] = 1u; // length 0!

    // Precompute all 24 perms of 4, and 6 perms of 3 (actually 3 suffice for H7/H8*, use 3)
    std::vector<std::array<int, 4>> p4s;
    {
        std::array<int, 4> a{0, 1, 2, 3};
        do { p4s.push_back(a); } while (std::next_permutation(a.begin(), a.end()));
    }
    std::vector<std::array<int, 4>> p3s{{0,1,2,0}, {0,2,1,0}, {2,0,1,0}}; // port 2 at index 2, 1, 0

    std::mt19937_64 rng(20261127ULL + tot_n * 131 + n_h8 * 17);
    int best_bad = 999;
    std::vector<int> best_t3(n3);
    std::vector<std::array<int, 4>> best_perm(n_base);

    for (int restart = 0; restart < 400; ++restart) {
        std::vector<int> t3;
        for (int i = 0; i < n_h8; ++i) t3.push_back(2);
        for (int i = 0; i < n_h7; ++i) t3.push_back(1);
        for (int i = 0; i < n_unexp; ++i) t3.push_back(0);
        std::shuffle(t3.begin(), t3.end(), rng);

        std::vector<const Gadget*> gptr(n_base);
        for (int i = 0; i < k4; ++i) gptr[i] = &Q;
        for (int i = 0; i < n3; ++i) gptr[k4 + i] = (t3[i] == 2 ? &H8 : (t3[i] == 1 ? &H7 : &Unexp));

        std::vector<std::array<int, 4>> perm(n_base);
        for (int i = 0; i < k4; ++i) perm[i] = p4s[rng() % 24];
        for (int i = 0; i < n3; ++i) perm[k4 + i] = p3s[rng() % 3];

        auto count_bad = [&]() {
            int b = 0;
            for (const auto& c : cycs) if (!cycle_ok(c, gptr, perm)) ++b;
            return b;
        };
        int cur_bad = count_bad();
        if (cur_bad < best_bad) { best_bad = cur_bad; best_t3 = t3; best_perm = perm; }
        for (int step = 0; step < 800 && cur_bad > 0; ++step) {
            // Pick a random bad cycle
            std::vector<int> bad_ids;
            for (size_t i = 0; i < cycs.size(); ++i) if (!cycle_ok(cycs[i], gptr, perm)) bad_ids.push_back((int)i);
            int ci = bad_ids[rng() % bad_ids.size()];
            int b_nb = 999, b_kind = -1, b_v = -1, b_idx = -1;
            for (auto [v, _1, _2] : cycs[ci].steps) {
                auto oldp = perm[v];
                const auto& cands = (v < k4) ? p4s : p3s;
                for (size_t k = 0; k < cands.size(); ++k) {
                    if (cands[k] == oldp) continue;
                    perm[v] = cands[k];
                    int nb = count_bad();
                    if (nb < b_nb) { b_nb = nb; b_kind = 0; b_v = v; b_idx = (int)k; }
                }
                perm[v] = oldp;
            }
            if (n_h8 > 0 && n_h8 < n3) {
                for (auto [v, _1, _2] : cycs[ci].steps) {
                    if (v < k4) continue;
                    for (int w = k4; w < n_base; ++w) {
                        if (t3[v - k4] == t3[w - k4]) continue;
                        std::swap(t3[v - k4], t3[w - k4]);
                        std::swap(gptr[v], gptr[w]);
                        int nb = count_bad();
                        if (nb < b_nb) { b_nb = nb; b_kind = 1; b_v = v; b_idx = w; }
                        std::swap(t3[v - k4], t3[w - k4]);
                        std::swap(gptr[v], gptr[w]);
                    }
                }
            }
            if (b_kind == 0 && (b_nb <= cur_bad || (rng() % 100) < 15)) {
                perm[b_v] = (b_v < k4) ? p4s[b_idx] : p3s[b_idx];
                cur_bad = b_nb;
            } else if (b_kind == 1 && (b_nb <= cur_bad || (rng() % 100) < 15)) {
                std::swap(t3[b_v - k4], t3[b_idx - k4]);
                std::swap(gptr[b_v], gptr[b_idx]);
                cur_bad = b_nb;
            } else {
                int v = std::get<0>(cycs[ci].steps[rng() % cycs[ci].steps.size()]);
                perm[v] = (v < k4) ? p4s[rng() % 24] : p3s[rng() % 3];
                cur_bad = count_bad();
            }
            if (cur_bad < best_bad) { best_bad = cur_bad; best_t3 = t3; best_perm = perm; }
        }
        if (best_bad == 0) break;
    }

    if (best_bad == 0) {
        std::cout << "*** NEW RECORD FOUND!! " << label << " -> n=" << tot_n
                  << " (k4=" << k4 << "*" << Q.name << ", " << n_h8 << "*H8*, " << n_h7 << "*H7, " << n_unexp << "*U1) ***\n";
        std::cout << "  t3=[";
        for (size_t i = 0; i < best_t3.size(); ++i) { if (i) std::cout << ","; std::cout << best_t3[i]; }
        std::cout << "] perms=[";
        for (int i = 0; i < n_base; ++i) {
            if (i) std::cout << ",";
            std::cout << "(" << best_perm[i][0] << "," << best_perm[i][1] << "," << best_perm[i][2];
            if (i < k4) std::cout << "," << best_perm[i][3];
            std::cout << ")";
        }
        std::cout << "]\n" << std::flush;
        return true;
    } else {
        std::cout << "  " << label << " (n=" << tot_n << "): min_bad=" << best_bad << "\n" << std::flush;
        return false;
    }
}

int main() {
    auto H7 = make_gadget("H7", 7, 3, true, {{0,3},{0,4},{1,3},{1,5},{2,4},{2,6},{3,5},{4,6},{5,6}});
    auto H8 = make_gadget("H8*", 8, 3, false, {{0,3},{0,4},{1,3},{1,5},{2,6},{2,7},{3,6},{4,5},{4,7},{5,7},{6,7}});

    std::vector<Gadget> Qs = {
        make_gadget("Q9",   9,  4, false, {{0,4},{0,5},{1,4},{1,8},{2,6},{2,7},{3,6},{3,8},{4,6},{5,7},{5,8},{7,8}}),
        make_gadget("Q11a", 11, 4, false, {{0,4},{0,5},{1,5},{1,6},{2,7},{2,8},{3,8},{3,9},{4,5},{4,10},{6,7},{6,10},{7,10},{8,9},{9,10}}),
        make_gadget("Q11b", 11, 4, false, {{0,4},{0,10},{1,5},{1,6},{2,4},{2,7},{3,6},{3,10},{4,7},{5,6},{5,8},{7,9},{8,9},{8,10},{9,10}}),
        make_gadget("Q11c", 11, 4, false, {{0,4},{0,5},{1,5},{1,6},{2,7},{2,8},{3,7},{3,10},{4,9},{4,10},{5,6},{6,10},{7,8},{8,9},{9,10}}),
        make_gadget("Q12a", 12, 4, true,  {{0,4},{0,5},{1,6},{1,7},{2,6},{2,8},{3,5},{3,9},{4,10},{4,11},{5,9},{6,10},{7,8},{7,11},{8,11},{9,10}}),
        make_gadget("Q12b", 12, 4, true,  {{0,4},{0,5},{1,4},{1,6},{2,7},{2,8},{3,8},{3,9},{4,9},{5,6},{5,10},{6,10},{7,8},{7,11},{9,11},{10,11}}),
        make_gadget("Q13s", 13, 4, false, {{0,4},{0,5},{1,6},{1,7},{2,8},{2,9},{3,10},{3,11},{4,5},{4,12},{5,8},{6,7},{6,10},{7,12},{8,9},{9,12},{10,11},{11,12}}),
        make_gadget("Q14",  14, 4, true,  {{0,4},{0,5},{1,6},{1,7},{2,8},{2,9},{3,10},{3,11},{4,5},{4,12},{5,10},{6,7},{6,8},{7,13},{8,9},{9,13},{10,11},{11,12},{12,13}}),
    };

    // Build Petersen
    std::vector<std::pair<int, int>> pet_e;
    for (int i = 0; i < 5; ++i) {
        pet_e.push_back({i, (i + 1) % 5});
        pet_e.push_back({i, i + 5});
        pet_e.push_back({i + 5, ((i + 2) % 5) + 5});
    }
    auto build_contracted = [&](std::vector<std::pair<int, int>> ce) {
        std::array<int, 10> mp; mp.fill(-1);
        int nxt = 0;
        for (auto [u, v] : ce) { mp[u] = nxt; mp[v] = nxt; ++nxt; }
        for (int i = 0; i < 10; ++i) if (mp[i] == -1) mp[i] = nxt++;
        std::vector<std::vector<int>> adj(nxt);
        for (auto [u, v] : pet_e) {
            int a = mp[u], b = mp[v];
            if (a != b) { adj[a].push_back(b); adj[b].push_back(a); }
        }
        for (auto& a : adj) std::sort(a.begin(), a.end());
        return std::make_pair(nxt, adj);
    };

    std::cout << "=== 1. PETERSEN 1-EDGE CONTRACTION (n_base=9: 1 deg-4 + 8 deg-3) ===\n";
    auto [n1, adj1] = build_contracted({{0, 1}});
    for (const auto& Q : Qs) {
        for (int nh8 = 8; nh8 >= 0; --nh8) {
            int tot = Q.n + 8 * nh8 + 7 * (8 - nh8);
            if (tot >= 73) continue;
            solve_base("Pet1e_" + Q.name + "_" + std::to_string(nh8) + "H8", n1, adj1, 1, Q, H7, H8, nh8);
        }
    }

    std::cout << "\n=== 2. PETERSEN 2-EDGE CONTRACTION (dist-2 edges (0,1)&(7,9): 2 deg-4 + 6 deg-3) ===\n";
    auto [n2, adj2] = build_contracted({{0, 1}, {7, 9}});
    for (const auto& Q : Qs) {
        for (int nh8 = 6; nh8 >= 0; --nh8) {
            int tot = 2 * Q.n + 8 * nh8 + 7 * (6 - nh8);
            if (tot >= 73) continue;
            solve_base("Pet2e_" + Q.name + "_" + std::to_string(nh8) + "H8", n2, adj2, 2, Q, H7, H8, nh8);
        }
    }

    std::cout << "\n=== 3. PETERSEN UNCONTRACTED WITH 1 UNEXPANDED VERTEX ===\n";
    auto [n0, adj0] = build_contracted({});
    for (int nh8 = 9; nh8 >= 5; --nh8) {
        solve_base("Pet_1U_" + std::to_string(nh8) + "H8", n0, adj0, 0, Qs[0], H7, H8, nh8, 1);
    }
    return 0;
}

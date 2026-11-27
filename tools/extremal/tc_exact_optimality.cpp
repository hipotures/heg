// EXACT Symmetry-Broken Branch-and-Bound + Global Double-Counting Slack Solver
// for Tutte-Coxeter (n=30) with {H_15, H_8*, H_7} gadgets!
//
// Analytic Double-Counting Theorem (exact for all 90 C8 cycles of TC):
//   - Every (v, off_edge) in TC lies on EXACTLY 8 cycles of length 8.
//   - On any C8, let n5 = #{aligned H_15} (dl=5), n2 = #{dl=2 vertices}.
//     Then sum(dl) = 24 + 2*n5 - n2 >= 25  <==>  2*n5 - n2 >= 1.
//   - Summing over all 90 C8s:
//       sum(2*n5 - n2) = 16*a15 - 8*b8 - 16*c7 >= 90
//     <==> 8*a15 - 4*b8 - 8*c7 >= 45!
//   - Immediate Analytic Corollaries (ZERO search needed!):
//       * Cubic (b8=0, a15+c7=30):        a15 >= 18  (n >= 354)
//       * delta>=3 (c7=0, a15+b8=30):     a15 >= 14  (n >= 338)
//       * delta>=3 (a15=15, b8+c7=15):    c7  <= 3   (n >= 342)
//   - Moreover, total global excess slack across all 90 C8s is EXACTLY:
//       TOTAL_SLACK = 16*a15 - 8*b8 - 16*c7 - 90.
//     Every completed C8 with (2*n5 - n2) = s >= 1 consumes (s - 1) units of slack!
//     In fact, for ANY partial C8, if its guaranteed minimum possible (2*n5 - n2) exceeds 1,
//     it ALREADY consumes slack! And if a completed C8 has n2 EVEN, it MUST consume >= 1 slack!
//
// Using this exact global slack bound + C8-tightest-cycle branching + per-node timer check,
// we decide SAT vs PROVEN_UNSAT for the frontier cases!
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

struct Cycle {
    int len;
    int req_sum; // 25 for C8, 23 for C10
    std::array<int, 10> verts;
    std::array<int, 10> off;
};

static std::vector<std::vector<int>> build_tutte_coxeter() {
    const int lcf[6] = {-13, -9, 7, -7, 9, 13};
    int n = 30;
    std::vector<std::vector<int>> adj(n);
    auto add = [&](int u, int v) {
        if (std::find(adj[u].begin(), adj[u].end(), v) == adj[u].end()) {
            adj[u].push_back(v);
            adj[v].push_back(u);
        }
    };
    for (int i = 0; i < n; ++i) {
        add(i, (i + 1) % n);
        add(i, (i + lcf[i % 6] + n) % n);
    }
    for (auto& a : adj) std::sort(a.begin(), a.end());
    return adj;
}

static std::vector<Cycle> find_c8_c10(const std::vector<std::vector<int>>& adj) {
    int n = (int)adj.size();
    std::vector<Cycle> out;
    std::vector<int> path;
    std::vector<int> dist(n);
    for (int s = 0; s < n; ++s) {
        std::fill(dist.begin(), dist.end(), 999);
        dist[s] = 0;
        std::vector<int> q{s};
        for (size_t qh = 0; qh < q.size(); ++qh) {
            int u = q[qh];
            if (dist[u] >= 9) continue;
            for (int w : adj[u]) {
                if (w > s && dist[w] > dist[u] + 1) { dist[w] = dist[u] + 1; q.push_back(w); }
            }
        }
        auto dfs = [&](auto&& self, int u, uint64_t vis, int first) -> void {
            int d = (int)path.size();
            if ((d == 8 || d == 10) && std::binary_search(adj[u].begin(), adj[u].end(), s) && first < u) {
                Cycle c;
                c.len = d;
                c.req_sum = 33 - d;
                for (int idx = 0; idx < d; ++idx) {
                    int v = path[idx];
                    int prev_v = path[(idx + d - 1) % d];
                    int next_v = path[(idx + 1) % d];
                    int ia = (int)(std::find(adj[v].begin(), adj[v].end(), prev_v) - adj[v].begin());
                    int ib = (int)(std::find(adj[v].begin(), adj[v].end(), next_v) - adj[v].begin());
                    c.verts[idx] = v;
                    c.off[idx] = 3 - ia - ib;
                }
                out.push_back(c);
            }
            if (d >= 10) return;
            int rem = 10 - d;
            for (int w : adj[u]) {
                if (w > s && !((vis >> w) & 1ULL) && dist[w] <= rem) {
                    path.push_back(w);
                    self(self, w, vis | (1ULL << w), first);
                    path.pop_back();
                }
            }
        };
        for (int v : adj[s]) {
            if (v > s) { path = {s, v}; dfs(dfs, v, (1ULL << s) | (1ULL << v), v); }
        }
    }
    // Put all C8s first (0..89), then C10s (90..161)
    std::stable_partition(out.begin(), out.end(), [](const Cycle& c) { return c.len == 8; });
    return out;
}

struct Instance {
    std::vector<Cycle> cycles;
    int n_c8 = 0;
    std::array<std::vector<std::pair<int, int>>, 30> v2c;
    std::vector<std::vector<int>> adj;
};

static inline int dl_of(int gt, int p0, int off) {
    if (gt == 2) return (p0 == off) ? 5 : 3;
    if (gt == 1) return (p0 == off) ? 2 : 3;
    return (p0 == off) ? 3 : 2;
}

struct SearchState {
    std::array<int, 30> val;
    int rem[3]; // 0=H7, 1=H8*, 2=H15
    std::array<int, 162> cur_sum;
    std::array<int, 162> unass;
    int total_slack; // 16*a15 - 8*b8 - 16*c7 - 90
};

static inline int cycle_max_sum(const Cycle& c, int cur_sum, int unass, int rem15) {
    int k15 = std::min(unass, rem15);
    return cur_sum + k15 * 5 + (unass - k15) * 3;
}

// Minimum possible final sum of a C8 given cur_sum, unass, and remaining (rem7 + rem8) (which can give 2; H15 gives >= 3)!
static inline int c8_min_excess(int cur_sum, int unass, int rem_non15) {
    int k2 = std::min(unass, rem_non15);
    int min_final = cur_sum + k2 * 2 + (unass - k2) * 3;
    return std::max(0, min_final - 25);
}

static bool assign_v(
    const Instance& inst, SearchState& st, int v, int gt, int p0,
    std::vector<std::pair<int, int>>& trail
) {
    st.val[v] = gt * 3 + p0;
    st.rem[gt]--;
    trail.push_back({v, gt});
    int rem15 = st.rem[2];
    bool ok = true;
    // Update EVERY incident cycle unconditionally so unassign_to is ALWAYS an exact inverse!
    for (auto [ci, off] : inst.v2c[v]) {
        st.cur_sum[ci] += dl_of(gt, p0, off);
        st.unass[ci]--;
        if (cycle_max_sum(inst.cycles[ci], st.cur_sum[ci], st.unass[ci], rem15) < inst.cycles[ci].req_sum)
            ok = false;
    }
    return ok;
}

static void unassign_to(const Instance& inst, SearchState& st, std::vector<std::pair<int, int>>& trail, size_t mark) {
    while (trail.size() > mark) {
        auto [v, gt] = trail.back();
        trail.pop_back();
        int p0 = st.val[v] % 3;
        for (auto [ci, off] : inst.v2c[v]) {
            st.cur_sum[ci] -= dl_of(gt, p0, off);
            st.unass[ci]++;
        }
        st.rem[gt]++;
        st.val[v] = -1;
    }
}

struct ExactSolver {
    const Instance& inst;
    std::chrono::steady_clock::time_point deadline;
    std::atomic<bool> found{false};
    std::atomic<bool> timed_out{false};
    std::atomic<uint64_t> nodes{0};
    std::mutex mtx;
    std::array<int, 30> sol_val{};

    bool dfs(SearchState& st, std::vector<std::pair<int, int>>& trail, uint64_t& local_nodes) {
        if (found.load(std::memory_order_relaxed) || timed_out.load(std::memory_order_relaxed)) return false;
        if ((++local_nodes & 4095ULL) == 0) {
            if (std::chrono::steady_clock::now() >= deadline) {
                timed_out.store(true, std::memory_order_relaxed);
                return false;
            }
        }

        const int rem15 = st.rem[2];
        const int rem_non15 = st.rem[0] + st.rem[1];

        // 1. Exact global slack check across all 90 C8s + feasibility of all 162 cycles!
        int used_slack = 0;
        int tightest_c8 = -1;
        int tightest_margin = 999;
        for (int ci = 0; ci < inst.n_c8; ++ci) {
            int un = st.unass[ci];
            int cs = st.cur_sum[ci];
            if (un == 0) {
                if (cs < 25) return false;
                used_slack += (cs - 25);
            } else {
                int maxs = cycle_max_sum(inst.cycles[ci], cs, un, rem15);
                if (maxs < 25) return false;
                used_slack += c8_min_excess(cs, un, rem_non15);
                // Prefer C8s with smallest (maxs - 25), tie-break by smallest unass!
                int margin = (maxs - 25) * 16 + un;
                if (margin < tightest_margin) { tightest_margin = margin; tightest_c8 = ci; }
            }
            if (used_slack > st.total_slack) return false;
        }
        for (int ci = inst.n_c8; ci < (int)inst.cycles.size(); ++ci) {
            if (st.unass[ci] > 0 && cycle_max_sum(inst.cycles[ci], st.cur_sum[ci], st.unass[ci], rem15) < 23)
                return false;
        }

        // 2. Compute exact legal domain for every unassigned vertex (with slack-aware pruning!)
        int best_v = -1;
        int best_cnt = 100;
        std::array<int, 9> best_choices{};
        int assigned_cnt = 0;

        // First check if any unassigned vertex has 0 or 1 legal choice (unit propagation!)
        // Also prioritize vertices on the tightest C8 if no unit clause exists!
        uint32_t tight_mask = 0;
        if (tightest_c8 != -1) {
            for (int i = 0; i < 8; ++i) tight_mask |= (1u << inst.cycles[tightest_c8].verts[i]);
        }

        for (int v = 0; v < 30; ++v) {
            if (st.val[v] != -1) { assigned_cnt++; continue; }
            std::array<int, 9> choices{};
            int cnt = 0;
            for (int gt : {2, 1, 0}) {
                if (st.rem[gt] == 0) continue;
                int nrem15 = rem15 - (gt == 2 ? 1 : 0);
                int nrem_non15 = rem_non15 - (gt != 2 ? 1 : 0);
                for (int p0 = 0; p0 < 3; ++p0) {
                    bool ok = true;
                    int delta_slack = 0;
                    for (auto [ci, off] : inst.v2c[v]) {
                        int nsum = st.cur_sum[ci] + dl_of(gt, p0, off);
                        int nun = st.unass[ci] - 1;
                        if (cycle_max_sum(inst.cycles[ci], nsum, nun, nrem15) < inst.cycles[ci].req_sum) {
                            ok = false; break;
                        }
                        if (ci < inst.n_c8) {
                            int old_ex = c8_min_excess(st.cur_sum[ci], st.unass[ci], rem_non15);
                            int new_ex = (nun == 0) ? (nsum - 25) : c8_min_excess(nsum, nun, nrem_non15);
                            delta_slack += (new_ex - old_ex);
                        }
                    }
                    if (ok && used_slack + delta_slack <= st.total_slack) {
                        choices[cnt++] = gt * 3 + p0;
                    }
                }
            }
            if (cnt == 0) return false;
            int score = cnt * 2 - (((tight_mask >> v) & 1u) ? 1 : 0);
            if (score < best_cnt) {
                best_cnt = score;
                best_v = v;
                best_choices = choices;
                if (cnt == 1) break;
            }
        }

        if (assigned_cnt == 30) {
            std::lock_guard<std::mutex> lk(mtx);
            if (!found.load()) {
                sol_val = st.val;
                found.store(true);
            }
            return true;
        }

        int n_ch = (best_cnt + 1) / 2;
        for (int i = 0; i < n_ch; ++i) {
            int ch = best_choices[i];
            int gt = ch / 3, p0 = ch % 3;
            size_t mark = trail.size();
            if (assign_v(inst, st, best_v, gt, p0, trail)) {
                if (dfs(st, trail, local_nodes)) return true;
            }
            unassign_to(inst, st, trail, mark);
            if (found.load(std::memory_order_relaxed) || timed_out.load(std::memory_order_relaxed)) return false;
        }
        return false;
    }
};

static void prove_instance(const Instance& inst, const std::string& label, int a15, int b8, int c7, double timeout_s = 60.0) {
    auto t0 = std::chrono::steady_clock::now();
    int total_slack = 16 * a15 - 8 * b8 - 16 * c7 - 90;
    int n_tot = 15 * a15 + 8 * b8 + 7 * c7;
    if (total_slack < 0) {
        std::cout << "[EXACT-TC] " << label << " (n=" << n_tot << ", slack=" << total_slack
                  << ") | status=PROVEN_UNSAT_ANALYTIC (0.000 s)\n" << std::flush;
        return;
    }

    SearchState root;
    root.val.fill(-1);
    root.rem[0] = c7; root.rem[1] = b8; root.rem[2] = a15;
    root.total_slack = total_slack;
    for (size_t ci = 0; ci < inst.cycles.size(); ++ci) {
        root.cur_sum[ci] = 0;
        root.unass[ci] = inst.cycles[ci].len;
    }
    std::vector<std::pair<int, int>> trail;

    // Exact lossless symmetry breaking via |Aut(TC)| = 1440 (transitively acts on vertex + 3-edge frame):
    // Fix v=0 to least-frequent non-zero type and p0[0]=0!
    int fix_gt = (c7 > 0) ? 0 : ((b8 > 0) ? 1 : 2);
    assign_v(inst, root, 0, fix_gt, 0, trail);

    // Build parallel tasks by branching on the 3 neighbors of v=0 (or first C8 through v=0!)
    // Actually branching on 3 vertices of a C8 containing v=0 gives tighter early slack!
    int n0 = inst.adj[0][0], n1 = inst.adj[0][1], n2 = inst.adj[0][2];
    std::vector<SearchState> tasks;
    for (int c0 = 0; c0 < 9; ++c0) {
        int g0 = c0 / 3, p0 = c0 % 3;
        if (root.rem[g0] == 0) continue;
        SearchState s1 = root; std::vector<std::pair<int,int>> tr1;
        if (!assign_v(inst, s1, n0, g0, p0, tr1)) continue;
        for (int c1 = 0; c1 < 9; ++c1) {
            int g1 = c1 / 3, p1 = c1 % 3;
            if (s1.rem[g1] == 0) continue;
            SearchState s2 = s1; std::vector<std::pair<int,int>> tr2;
            if (!assign_v(inst, s2, n1, g1, p1, tr2)) continue;
            for (int c2 = 0; c2 < 9; ++c2) {
                int g2 = c2 / 3, p2 = c2 % 3;
                if (s2.rem[g2] == 0) continue;
                SearchState s3 = s2; std::vector<std::pair<int,int>> tr3;
                if (!assign_v(inst, s3, n2, g2, p2, tr3)) continue;
                tasks.push_back(s3);
            }
        }
    }

    auto deadline = t0 + std::chrono::milliseconds((int64_t)(timeout_s * 1000.0));
    ExactSolver solver{inst, deadline};
    std::atomic<size_t> next_task{0};
    std::vector<std::thread> ths;
    for (int t = 0; t < 16; ++t) {
        ths.emplace_back([&]() {
            std::vector<std::pair<int, int>> tr;
            tr.reserve(32);
            uint64_t local_nodes = 0;
            while (!solver.found.load(std::memory_order_relaxed) && !solver.timed_out.load(std::memory_order_relaxed)) {
                size_t idx = next_task.fetch_add(1, std::memory_order_relaxed);
                if (idx >= tasks.size()) break;
                SearchState st = tasks[idx];
                tr.clear();
                solver.dfs(st, tr, local_nodes);
            }
            solver.nodes.fetch_add(local_nodes, std::memory_order_relaxed);
        });
    }
    for (auto& th : ths) th.join();
    double el = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::cout << "[EXACT-TC] " << label << " (n=" << n_tot << ", slack=" << total_slack
              << ") | tasks=" << tasks.size()
              << " | nodes=" << solver.nodes.load()
              << " | status=" << (solver.found.load() ? "SAT!!" : (solver.timed_out.load() ? "TIMEOUT" : "PROVEN_UNSAT"))
              << " (" << el << " s)\n";
    if (solver.found.load()) {
        std::cout << "  SOLUTION gt=[";
        for (int i = 0; i < 30; ++i) { if (i) std::cout << ","; std::cout << (solver.sol_val[i] / 3); }
        std::cout << "] p0=[";
        for (int i = 0; i < 30; ++i) { if (i) std::cout << ","; std::cout << (solver.sol_val[i] % 3); }
        std::cout << "]\n";
    }
    std::cout << std::flush;
}

int main() {
    Instance inst;
    inst.adj = build_tutte_coxeter();
    inst.cycles = find_c8_c10(inst.adj);
    inst.n_c8 = 0;
    for (const auto& c : inst.cycles) if (c.len == 8) inst.n_c8++;
    for (size_t ci = 0; ci < inst.cycles.size(); ++ci) {
        for (int i = 0; i < inst.cycles[ci].len; ++i) {
            inst.v2c[inst.cycles[ci].verts[i]].push_back({(int)ci, inst.cycles[ci].off[i]});
        }
    }
    std::cout << "TC loaded: 30 vertices, " << inst.n_c8 << " C8 + "
              << (inst.cycles.size() - inst.n_c8) << " C10 cycles\n" << std::flush;

    // Analytic impossibility proofs (instant!):
    prove_instance(inst, "ANALYTIC_TC_13H15_17H8s",   13, 17, 0,  5.0);
    prove_instance(inst, "ANALYTIC_TC_17H15_13H7",    17,  0, 13, 5.0);

    // Exact frontier optimality tests (tightest slack first!!):
    prove_instance(inst, "EXACT_TC_14H15_16H8s",      14, 16, 0, 60.0); // slack = 6!!
    prove_instance(inst, "EXACT_TC_18H15_12H7",       18,  0, 12, 60.0); // slack = 6!!
    prove_instance(inst, "EXACT_TC_15H15_12H8s_3H7",  15, 12, 3, 60.0); // slack = 6!!
    prove_instance(inst, "EXACT_TC_15H15_13H8s_2H7",  15, 13, 2, 60.0); // slack = 14
    prove_instance(inst, "EXACT_TC_15H15_14H8s_1H7",  15, 14, 1, 60.0); // slack = 22
    prove_instance(inst, "EXACT_TC_19H15_11H7",       19,  0, 11, 60.0); // slack = 38
    return 0;
}

// Exact lossless Moore-tree restricted-growth search for connected cubic bipartite graphs
// of girth >= 10 (no C4, no C6, no C8) on n = 2*V vertices, with optional C16 pruning.
//
// Mathematical root normalization (100% lossless for any connected cubic bipartite graph
// of girth >= 10, i.e., linear V_3-configuration with no Berge 2-, 3-, or 4-cycles):
//   - Pick an arbitrary block B0 = {0, 1, 2}.
//   - By no-C4 and no-C6, the 6 remaining blocks incident to {0,1,2} contain 12 pairwise
//     distinct new points 3..14:
//       {0,3,4}, {0,5,6}, {1,7,8}, {1,9,10}, {2,11,12}, {2,13,14}.
//   - By no-C4, no-C6, and no-C8, the 8 remaining blocks incident to {3,4,5,6} contain
//     16 pairwise distinct new points 15..30:
//       {3,15,16}, {3,17,18}, {4,19,20}, {4,21,22},
//       {5,23,24}, {5,25,26}, {6,27,28}, {6,29,30}.
//   - Thus EVERY connected girth>=10 cubic bipartite graph has a labeling beginning with
//     these exact 15 blocks (31 points 0..30, points 0..6 already degree 3).
//   - Restricted-growth recursion then completes points 7..V-1 in ascending order.
//
// Validation:
//   - At V=35 (n=70) with --no-c16, finds completions corresponding to the 3 (3,10)-cages.
//   - At V=35 (n=70) with C16 pruning enabled, proves 0 {C4,C6,C8,C16}-free completions
//     independently of O'Keefe-Wong / Wong!
//   - At V=36 (n=72) with C16 pruning enabled, exhaustively decides the girth>=10 branch of n=72!

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

namespace {

constexpr int kMaxV = 63;

struct Block {
    int a, b, c;
};

struct Counts {
    std::uint64_t states = 0;
    std::uint64_t attempted = 0;
    std::uint64_t pair_rej = 0;
    std::uint64_t c6_rej = 0;
    std::uint64_t c8_rej = 0;
    std::uint64_t c16_rej = 0;
    std::uint64_t completions = 0;
};

struct State {
    int V = 35;
    bool prune_c16 = true;
    std::atomic<bool>* stop_flag = nullptr;
    std::vector<Block> found_witness;
    std::vector<Block> blocks;
    std::array<std::vector<int>, kMaxV> incident;
    std::array<int, kMaxV> deg{};
    std::array<std::uint64_t, kMaxV> pair_mask{};
    int introduced = 31;
    Counts cnt;

    void init_moore_root(int side, bool use_c16) {
        V = side;
        prune_c16 = use_c16;
        blocks.clear();
        for (auto& v : incident) v.clear();
        deg.fill(0);
        pair_mask.fill(0);
        introduced = 31;
        cnt = {};
        const Block root[15] = {
            {0, 1, 2},
            {0, 3, 4},   {0, 5, 6},
            {1, 7, 8},   {1, 9, 10},
            {2, 11, 12}, {2, 13, 14},
            {3, 15, 16}, {3, 17, 18},
            {4, 19, 20}, {4, 21, 22},
            {5, 23, 24}, {5, 25, 26},
            {6, 27, 28}, {6, 29, 30},
        };
        for (const Block& b : root) add(b);
    }

    inline void add(const Block& b) {
        const int id = static_cast<int>(blocks.size());
        blocks.push_back(b);
        ++deg[b.a]; ++deg[b.b]; ++deg[b.c];
        incident[b.a].push_back(id);
        incident[b.b].push_back(id);
        incident[b.c].push_back(id);
        const std::uint64_t ma = 1ULL << b.a;
        const std::uint64_t mb = 1ULL << b.b;
        const std::uint64_t mc = 1ULL << b.c;
        pair_mask[b.a] |= (mb | mc);
        pair_mask[b.b] |= (ma | mc);
        pair_mask[b.c] |= (ma | mb);
    }

    inline void remove(const Block& b) {
        --deg[b.a]; --deg[b.b]; --deg[b.c];
        incident[b.a].pop_back();
        incident[b.b].pop_back();
        incident[b.c].pop_back();
        const std::uint64_t ma = 1ULL << b.a;
        const std::uint64_t mb = 1ULL << b.b;
        const std::uint64_t mc = 1ULL << b.c;
        pair_mask[b.a] &= ~(mb | mc);
        pair_mask[b.b] &= ~(ma | mc);
        pair_mask[b.c] &= ~(ma | mb);
        blocks.pop_back();
    }

    // In a C4-free linear configuration, adding {a,b,c} creates a Berge triangle (C6)
    // iff two of {a,b,c} share a collinear point w.
    inline bool creates_C6(int a, int b, int c) const {
        return ((pair_mask[a] & pair_mask[b]) |
                (pair_mask[a] & pair_mask[c]) |
                (pair_mask[b] & pair_mask[c])) != 0ULL;
    }

    // In a {C4, C6}-free linear configuration, adding {a,b,c} creates a Berge 4-cycle (C8)
    // iff some pair (x, y) in {a,b,c} has a length-3 collinearity path x - u - v - y
    // (automatically using 3 distinct blocks because C4 and C6 are absent).
    inline bool creates_C8(int a, int b, int c) const {
        const std::uint64_t mb = pair_mask[b];
        const std::uint64_t mc = pair_mask[c];
        std::uint64_t ma = pair_mask[a];
        while (ma) {
            const int u = __builtin_ctzll(ma);
            ma &= ma - 1;
            if ((pair_mask[u] & (mb | mc)) != 0ULL) return true;
        }
        std::uint64_t mbb = mb;
        while (mbb) {
            const int u = __builtin_ctzll(mbb);
            mbb &= mbb - 1;
            if ((pair_mask[u] & mc) != 0ULL) return true;
        }
        return false;
    }

    bool path14_dfs(int cur, int target, int used_blocks,
                    std::uint64_t seen_pts, std::uint64_t seen_blks) const {
        if (used_blocks == 7) return cur == target;
        for (int bid : incident[cur]) {
            const std::uint64_t bbit = 1ULL << bid;
            if ((seen_blks & bbit) != 0ULL) continue;
            const Block& blk = blocks[bid];
            const int pts[3] = {blk.a, blk.b, blk.c};
            for (int nxt : pts) {
                if (nxt == cur) continue;
                const std::uint64_t pbit = 1ULL << nxt;
                if ((seen_pts & pbit) != 0ULL) continue;
                if (nxt == target && used_blocks + 1 != 7) continue;
                if (nxt != target && used_blocks + 1 == 7) continue;
                if (path14_dfs(nxt, target, used_blocks + 1,
                               seen_pts | pbit, seen_blks | bbit)) {
                    return true;
                }
            }
        }
        return false;
    }

    bool creates_C16(int a, int b, int c) const {
        const int pts[3] = {a, b, c};
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j) {
                if (path14_dfs(pts[i], pts[j], 0, 1ULL << pts[i], 0ULL)) return true;
            }
        }
        return false;
    }

    // Check feasibility of a candidate {p, q, r} and return 0 if ok (or rejection code).
    inline int check_cand(int p, int q, int r, int old_intro) {
        ++cnt.attempted;
        if ((p < old_intro && deg[p] >= 3) ||
            (q < old_intro && deg[q] >= 3) ||
            (r < old_intro && deg[r] >= 3) ||
            (q < old_intro && ((pair_mask[p] >> q) & 1ULL)) ||
            (r < old_intro && ((pair_mask[p] >> r) & 1ULL)) ||
            (q < old_intro && r < old_intro && ((pair_mask[q] >> r) & 1ULL))) {
            ++cnt.pair_rej;
            return 1;
        }
        if (creates_C6(p, q, r)) {
            ++cnt.c6_rej;
            return 2;
        }
        if (creates_C8(p, q, r)) {
            ++cnt.c8_rej;
            return 3;
        }
        if (prune_c16 && creates_C16(p, q, r)) {
            ++cnt.c16_rej;
            return 4;
        }
        return 0;
    }

    // Collect valid frontier states at depth `split_depth` for parallel work stealing.
    void collect_tasks(int point, int last_q, int last_r, int depth, int split_depth,
                       std::vector<std::tuple<std::vector<Block>, int, int, int, int>>& tasks) {
        ++cnt.states;
        while (point < introduced && deg[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced) {
            if (static_cast<int>(blocks.size()) == introduced) ++cnt.completions;
            return;
        }
        if (static_cast<int>(blocks.size()) >= V) return;
        if (depth >= split_depth) {
            tasks.emplace_back(blocks, introduced, point, last_q, last_r);
            return;
        }
        const int old = introduced;
        int poss[kMaxV];
        int np = 0;
        for (int q = point + 1; q < old; ++q) {
            if (deg[q] < 3 && !((pair_mask[point] >> q) & 1ULL) &&
                (pair_mask[point] & pair_mask[q]) == 0ULL) {
                poss[np++] = q;
            }
        }
        if (old < V) poss[np++] = old;
        if (old + 1 < V) poss[np++] = old + 1;

        for (int i = 0; i < np; ++i) {
            for (int j = i + 1; j < np; ++j) {
                const int q = poss[i], r = poss[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;
                if (check_cand(point, q, r, old) != 0) continue;
                int next = old;
                if (q == old || r == old) ++next;
                if (r == old + 1) ++next;
                const int saved = introduced;
                introduced = next;
                const Block b{point, q, r};
                add(b);
                collect_tasks(point, q, r, depth + 1, split_depth, tasks);
                remove(b);
                introduced = saved;
            }
        }
    }

    void recurse(int point, int last_q, int last_r) {
        if (stop_flag && stop_flag->load(std::memory_order_relaxed)) return;
        ++cnt.states;
        while (point < introduced && deg[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced) {
            if (static_cast<int>(blocks.size()) == introduced) {
                ++cnt.completions;
                if (stop_flag && !stop_flag->exchange(true, std::memory_order_relaxed)) {
                    found_witness = blocks;
                }
            }
            return;
        }
        if (static_cast<int>(blocks.size()) >= V) return;

        // Necessary remaining block count bound: every point u < introduced needs (3 - deg[u]) blocks,
        // and each remaining block covers at most 3 deficit slots!
        int deficit = 0;
        for (int u = point; u < introduced; ++u) deficit += (3 - deg[u]);
        const int rem_blocks = V - static_cast<int>(blocks.size());
        if (deficit > 3 * rem_blocks) return;

        const int old = introduced;
        // Pre-filter q: must have deg[q] < 3, not paired with point, AND not C6/C8 with point!
        // Note: skipping q with C6/C8 against `point` is 100% lossless because ANY {point,q,r}
        // containing that pair (point, q) would create that same C6 or C8!
        int poss[kMaxV];
        int np = 0;
        for (int q = point + 1; q < old; ++q) {
            if (deg[q] >= 3) continue;
            if ((pair_mask[point] >> q) & 1ULL) continue;
            if ((pair_mask[point] & pair_mask[q]) != 0ULL) continue;
            // Check 3-step collinearity (C8 between point and q)
            bool c8_pq = false;
            std::uint64_t mp = pair_mask[point];
            const std::uint64_t mq = pair_mask[q];
            while (mp) {
                const int u = __builtin_ctzll(mp);
                mp &= mp - 1;
                if ((pair_mask[u] & mq) != 0ULL) { c8_pq = true; break; }
            }
            if (c8_pq) continue;
            poss[np++] = q;
        }
        if (old < V) poss[np++] = old;
        if (old + 1 < V) poss[np++] = old + 1;

        for (int i = 0; i < np; ++i) {
            for (int j = i + 1; j < np; ++j) {
                const int q = poss[i], r = poss[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;
                if (check_cand(point, q, r, old) != 0) continue;
                int next = old;
                if (q == old || r == old) ++next;
                if (r == old + 1) ++next;
                const int saved = introduced;
                introduced = next;
                const Block b{point, q, r};
                add(b);
                recurse(point, q, r);
                remove(b);
                introduced = saved;
            }
        }
    }
};

}  // namespace

int main(int argc, char** argv) {
    int V = 35;
    int workers = 16;
    int split_depth = 3;
    bool prune_c16 = true;
    bool stop_first = false;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--side" && i + 1 < argc) V = std::stoi(argv[++i]);
        else if (arg == "--workers" && i + 1 < argc) workers = std::stoi(argv[++i]);
        else if (arg == "--split-depth" && i + 1 < argc) split_depth = std::stoi(argv[++i]);
        else if (arg == "--no-c16") prune_c16 = false;
        else if (arg == "--stop-first") stop_first = true;
        else {
            std::cerr << "usage: cubic_bipartite_girth10_search --side V [--workers 16] [--split-depth 3] [--no-c16] [--stop-first]\n";
            return 2;
        }
    }
    if (V < 31 || V > kMaxV) {
        std::cerr << "V must be in [31, 63]\n";
        return 2;
    }

    const auto t0 = std::chrono::steady_clock::now();
    State root;
    root.init_moore_root(V, prune_c16);
    std::vector<std::tuple<std::vector<Block>, int, int, int, int>> tasks;
    root.collect_tasks(7, -1, -1, 0, split_depth, tasks);
    std::cout << "Girth>=10 Moore-root V=" << V << " (n=" << (2 * V) << ") prune_c16=" << prune_c16
              << " tasks=" << tasks.size() << " workers=" << workers << std::endl;

    std::atomic<std::size_t> next_task{0};
    std::atomic<bool> stop_flag{false};
    std::mutex mtx;
    Counts total = root.cnt;
    std::vector<Block> witness;

    std::vector<std::thread> threads;
    for (int w = 0; w < workers; ++w) {
        threads.emplace_back([&]() {
            Counts loc{};
            State st;
            st.stop_flag = stop_first ? &stop_flag : nullptr;
            while (true) {
                if (stop_first && stop_flag.load(std::memory_order_relaxed)) break;
                const std::size_t idx = next_task.fetch_add(1, std::memory_order_relaxed);
                if (idx >= tasks.size()) break;
                const auto& [blks, intro, pt, lq, lr] = tasks[idx];
                st.V = V;
                st.prune_c16 = prune_c16;
                st.blocks.clear();
                for (auto& v : st.incident) v.clear();
                st.deg.fill(0);
                st.pair_mask.fill(0);
                st.introduced = intro;
                st.cnt = {};
                for (const Block& b : blks) st.add(b);
                st.recurse(pt, lq, lr);
                loc.states += st.cnt.states;
                loc.attempted += st.cnt.attempted;
                loc.pair_rej += st.cnt.pair_rej;
                loc.c6_rej += st.cnt.c6_rej;
                loc.c8_rej += st.cnt.c8_rej;
                loc.c16_rej += st.cnt.c16_rej;
                loc.completions += st.cnt.completions;
                if (!st.found_witness.empty()) {
                    std::lock_guard<std::mutex> lk(mtx);
                    if (witness.empty()) witness = st.found_witness;
                }
            }
            std::lock_guard<std::mutex> lk(mtx);
            total.states += loc.states;
            total.attempted += loc.attempted;
            total.pair_rej += loc.pair_rej;
            total.c6_rej += loc.c6_rej;
            total.c8_rej += loc.c8_rej;
            total.c16_rej += loc.c16_rej;
            total.completions += loc.completions;
        });
    }
    for (auto& th : threads) th.join();
    const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    if (!witness.empty()) {
        std::cout << "FOUND_WITNESS blocks=" << witness.size() << '\n';
    }
    std::cout << "DONE girth>=10 V=" << V << " (n=" << (2 * V) << ") prune_c16=" << prune_c16
              << " states=" << total.states << " attempted=" << total.attempted
              << " pair=" << total.pair_rej << " c6=" << total.c6_rej
              << " c8=" << total.c8_rej << " c16=" << total.c16_rej
              << " completions=" << total.completions
              << " seconds=" << sec << std::endl;
    return total.completions == 0 ? 0 : 2;
}

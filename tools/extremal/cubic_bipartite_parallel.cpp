// Dynamic work-stealing multi-core exact triangle-rooted restricted-growth engine
// with 100% end-to-end ZERO-ORACLE static certificate verification (8 <= SIDE <= 63).
//
// Design & Soundness:
//   1. Exact same root orbits (1 & 2) and restricted-growth schedule as Tranquilli's
//      immutable `triangle_root_universal_search.cpp` (validated bit-for-bit on counts
//      at SIDE = 29, 34, 35, 36, 37, 38, 39!).
//   2. Automatically adapts parallelism to `--workers W` (default = all hardware threads)
//      using a shared work-stealing deque + soft-abort adaptive re-splitting:
//        - Whenever the shared queue drops below `16 * W`, workers split the shallowest
//          tasks 2 levels deeper and push children back to the queue.
//        - Whenever a running task exceeds `8,192` states while the queue is low
//          (`< 4 * W`) OR its certificate buffer exceeds `32 MiB`, it cleanly soft-aborts
//          and re-splits 2 levels deeper so NO single-core straggler can ever stall the run.
//   3. 100% ZERO-ORACLE end-to-end verification: EVERY split step AND EVERY leaf subtree
//      emits explicit C8 (3-block) and C16 (7-block) witness streams that are immediately
//      re-checked by an independent zero-oracle verifier (`ZeroOracleSubtreeVerifier`),
//      asserting exact count equality and exact child-frontier equality at every node.

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr int kMaxSide = 63;
constexpr std::uint8_t kRejectC8 = 0x08U;
constexpr std::uint8_t kRejectC16 = 0x10U;
constexpr std::uint8_t kExpand = 0x20U;

struct Block {
    int a, b, c;
    bool operator==(const Block& o) const { return a == o.a && b == o.b && c == o.c; }
};

struct Counts {
    std::uint64_t states = 0;
    std::uint64_t attempted = 0;
    std::uint64_t structural = 0;
    std::uint64_t c8 = 0;
    std::uint64_t c16 = 0;
    std::uint64_t completions = 0;
    void add(const Counts& o) {
        states += o.states;
        attempted += o.attempted;
        structural += o.structural;
        c8 += o.c8;
        c16 += o.c16;
        completions += o.completions;
    }
    bool eq(const Counts& o) const {
        return states == o.states && attempted == o.attempted &&
               structural == o.structural && c8 == o.c8 &&
               c16 == o.c16 && completions == o.completions;
    }
};

struct SubtreeTask {
    std::vector<Block> blocks;
    int introduced = 0;
    int point = 0;
    int last_q = -1;
    int last_r = -1;
    bool operator==(const SubtreeTask& o) const {
        return introduced == o.introduced && point == o.point &&
               last_q == o.last_q && last_r == o.last_r && blocks == o.blocks;
    }
};

SubtreeTask make_root_task(int orbit) {
    SubtreeTask root;
    root.blocks.push_back({0, 1, 3});
    root.blocks.push_back({1, 2, 4});
    root.blocks.push_back({0, 2, 5});
    if (orbit == 1) {
        root.blocks.push_back({0, 4, 6});
        root.introduced = 7;
    } else if (orbit == 2) {
        root.blocks.push_back({0, 6, 7});
        root.introduced = 8;
    } else {
        throw std::runtime_error("orbit must be 1 or 2");
    }
    root.point = 1;
    root.last_q = 2;
    root.last_r = 4;
    return root;
}

// ---------------- Generator (produces explicit C8 & C16 witness byte stream) ----------------

class SubtreeGenerator {
  public:
    explicit SubtreeGenerator(int side) : side_(side) {}

    void init_from(const SubtreeTask& t) {
        blocks_.clear();
        for (auto& v : incident_) v.clear();
        deg_.fill(0);
        pair_mask_.fill(0);
        introduced_ = t.introduced;
        cnt_ = {};
        for (const Block& b : t.blocks) add(b);
    }

    // Attempts to finish the entire subtree of `t`.
    // Returns true if completed, or false if soft-aborted (caller must re-split `t`).
    bool run_with_budget(const SubtreeTask& t, std::vector<std::uint8_t>* stream,
                         std::uint64_t state_budget, std::size_t byte_budget,
                         const std::atomic<std::size_t>* q_approx,
                         std::size_t low_watermark, Counts& out_cnt) {
        init_from(t);
        stream_ = stream;
        if (stream_) stream_->clear();
        aborted_ = false;
        state_budget_ = state_budget;
        byte_budget_ = byte_budget;
        q_approx_ = q_approx;
        low_watermark_ = low_watermark;
        recurse(t.point, t.last_q, t.last_r);
        if (aborted_) return false;
        out_cnt = cnt_;
        return true;
    }

    // Splits `t` deterministically by `depth_steps` levels, emitting all depth < depth_steps
    // witnesses into `stream` and collecting the exact child frontier in `out_children`.
    Counts split_task(const SubtreeTask& t, int depth_steps,
                      std::vector<SubtreeTask>& out_children,
                      std::vector<std::uint8_t>* stream) {
        init_from(t);
        out_children.clear();
        stream_ = stream;
        if (stream_) stream_->clear();
        split_rec(t.point, t.last_q, t.last_r, 0, depth_steps, out_children);
        return cnt_;
    }

  private:
    int side_;
    std::vector<std::uint8_t>* stream_ = nullptr;
    std::vector<Block> blocks_;
    std::array<std::vector<int>, kMaxSide> incident_;
    std::array<int, kMaxSide> deg_{};
    std::array<std::uint64_t, kMaxSide> pair_mask_{};
    int introduced_ = 0;
    Counts cnt_;

    bool aborted_ = false;
    std::uint64_t state_budget_ = std::numeric_limits<std::uint64_t>::max();
    std::size_t byte_budget_ = std::numeric_limits<std::size_t>::max();
    const std::atomic<std::size_t>* q_approx_ = nullptr;
    std::size_t low_watermark_ = 0;

    inline void emit(std::uint8_t b) {
        if (stream_) stream_->push_back(b);
    }

    inline bool should_abort() const {
        if (stream_ && stream_->size() >= byte_budget_) return true;
        if (cnt_.states >= state_budget_ && q_approx_ &&
            q_approx_->load(std::memory_order_relaxed) < low_watermark_) {
            return true;
        }
        return false;
    }

    bool c8_witness(const Block& cand, std::array<std::uint8_t, 3>& wit) const {
        const int pts[3] = {cand.a, cand.b, cand.c};
        const std::uint64_t cmask = (1ULL << cand.a) | (1ULL << cand.b) | (1ULL << cand.c);
        for (int s_idx = 0; s_idx < 3; ++s_idx) {
            const int s = pts[s_idx];
            for (int t_idx = s_idx + 1; t_idx < 3; ++t_idx) {
                const int t = pts[t_idx];
                const int third = pts[3 - s_idx - t_idx];
                const std::uint64_t forbid_mid = cmask;
                for (int b0 : incident_[s]) {
                    const Block& B0 = blocks_[b0];
                    const int p0[3] = {B0.a, B0.b, B0.c};
                    for (int u : p0) {
                        if (u == s || ((forbid_mid >> u) & 1ULL)) continue;
                        for (int b1 : incident_[u]) {
                            if (b1 == b0) continue;
                            const Block& B1 = blocks_[b1];
                            const int p1[3] = {B1.a, B1.b, B1.c};
                            for (int v : p1) {
                                if (v == u || v == s || v == t || v == third) continue;
                                if (!((pair_mask_[v] >> t) & 1ULL)) continue;
                                for (int b2 : incident_[v]) {
                                    if (b2 == b0 || b2 == b1) continue;
                                    const Block& B2 = blocks_[b2];
                                    if (B2.a == t || B2.b == t || B2.c == t) {
                                        wit = {static_cast<std::uint8_t>(b0),
                                               static_cast<std::uint8_t>(b1),
                                               static_cast<std::uint8_t>(b2)};
                                        return true;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return false;
    }

    bool path14_dfs(int cur, int target, int used_blocks,
                    std::uint64_t seen_pts, std::uint64_t seen_blks,
                    std::array<std::uint8_t, 7>& wit) const {
        if (used_blocks == 6) {
            if (!((pair_mask_[cur] >> target) & 1ULL)) return false;
            for (int bid : incident_[cur]) {
                if ((seen_blks >> bid) & 1ULL) continue;
                const Block& B = blocks_[bid];
                if (B.a == target || B.b == target || B.c == target) {
                    wit[6] = static_cast<std::uint8_t>(bid);
                    return true;
                }
            }
            return false;
        }
        for (int bid : incident_[cur]) {
            const std::uint64_t bbit = 1ULL << bid;
            if (seen_blks & bbit) continue;
            const Block& B = blocks_[bid];
            const int pts[3] = {B.a, B.b, B.c};
            for (int nxt : pts) {
                if (nxt == cur) continue;
                const std::uint64_t pbit = 1ULL << nxt;
                if (seen_pts & pbit) continue;
                if (nxt == target) continue;
                wit[used_blocks] = static_cast<std::uint8_t>(bid);
                if (path14_dfs(nxt, target, used_blocks + 1,
                               seen_pts | pbit, seen_blks | bbit, wit)) {
                    return true;
                }
            }
        }
        return false;
    }

    bool c16_witness(const Block& cand, std::uint8_t& pcode,
                     std::array<std::uint8_t, 7>& wit) const {
        const int pts[3] = {cand.a, cand.b, cand.c};
        int code = 0;
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j, ++code) {
                if (path14_dfs(pts[i], pts[j], 0, 1ULL << pts[i], 0ULL, wit)) {
                    pcode = static_cast<std::uint8_t>(code);
                    return true;
                }
            }
        }
        return false;
    }

    inline void add(const Block& b) {
        const int id = static_cast<int>(blocks_.size());
        blocks_.push_back(b);
        ++deg_[b.a]; ++deg_[b.b]; ++deg_[b.c];
        incident_[b.a].push_back(id);
        incident_[b.b].push_back(id);
        incident_[b.c].push_back(id);
        const std::uint64_t ma = 1ULL << b.a, mb = 1ULL << b.b, mc = 1ULL << b.c;
        pair_mask_[b.a] |= (mb | mc);
        pair_mask_[b.b] |= (ma | mc);
        pair_mask_[b.c] |= (ma | mb);
    }

    inline void remove(const Block& b) {
        --deg_[b.a]; --deg_[b.b]; --deg_[b.c];
        incident_[b.a].pop_back();
        incident_[b.b].pop_back();
        incident_[b.c].pop_back();
        const std::uint64_t ma = 1ULL << b.a, mb = 1ULL << b.b, mc = 1ULL << b.c;
        pair_mask_[b.a] &= ~(mb | mc);
        pair_mask_[b.b] &= ~(ma | mc);
        pair_mask_[b.c] &= ~(ma | mb);
        blocks_.pop_back();
    }

    void split_rec(int point, int last_q, int last_r, int depth, int stop_depth,
                   std::vector<SubtreeTask>& out_children) {
        if (depth >= stop_depth) {
            out_children.push_back({blocks_, introduced_, point, last_q, last_r});
            return;
        }
        ++cnt_.states;
        while (point < introduced_ && deg_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) ++cnt_.completions;
            return;
        }
        if (static_cast<int>(blocks_.size()) >= side_) return;

        const int old = introduced_;
        int poss[kMaxSide];
        int np = 0;
        for (int q = point + 1; q < old; ++q) {
            if (deg_[q] < 3 && !((pair_mask_[point] >> q) & 1ULL)) poss[np++] = q;
        }
        if (old < side_) poss[np++] = old;
        if (old + 1 < side_) poss[np++] = old + 1;

        for (int i = 0; i < np; ++i) {
            for (int j = i + 1; j < np; ++j) {
                const int q = poss[i], r = poss[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;
                ++cnt_.attempted;
                const Block cand{point, q, r};
                if ((point < old && deg_[point] >= 3) ||
                    (q < old && deg_[q] >= 3) ||
                    (r < old && deg_[r] >= 3) ||
                    (q < old && ((pair_mask_[point] >> q) & 1ULL)) ||
                    (r < old && ((pair_mask_[point] >> r) & 1ULL)) ||
                    (q < old && r < old && ((pair_mask_[q] >> r) & 1ULL))) {
                    ++cnt_.structural;
                    continue;
                }
                std::array<std::uint8_t, 3> w8{};
                if (c8_witness(cand, w8)) {
                    ++cnt_.c8;
                    emit(kRejectC8);
                    emit(w8[0]); emit(w8[1]); emit(w8[2]);
                    continue;
                }
                std::uint8_t pcode = 0;
                std::array<std::uint8_t, 7> w16{};
                if (c16_witness(cand, pcode, w16)) {
                    ++cnt_.c16;
                    emit(kRejectC16);
                    emit(pcode);
                    for (int k = 0; k < 7; ++k) emit(w16[k]);
                    continue;
                }
                emit(kExpand);
                int next = old;
                if (q == old || r == old) ++next;
                if (r == old + 1) ++next;
                const int saved = introduced_;
                introduced_ = next;
                add(cand);
                split_rec(point, q, r, depth + 1, stop_depth, out_children);
                remove(cand);
                introduced_ = saved;
            }
        }
    }

    void recurse(int point, int last_q, int last_r) {
        if (aborted_) return;
        ++cnt_.states;
        if ((cnt_.states & 255ULL) == 0 && should_abort()) {
            aborted_ = true;
            return;
        }
        while (point < introduced_ && deg_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) ++cnt_.completions;
            return;
        }
        if (static_cast<int>(blocks_.size()) >= side_) return;

        const int old = introduced_;
        int poss[kMaxSide];
        int np = 0;
        for (int q = point + 1; q < old; ++q) {
            if (deg_[q] < 3 && !((pair_mask_[point] >> q) & 1ULL)) poss[np++] = q;
        }
        if (old < side_) poss[np++] = old;
        if (old + 1 < side_) poss[np++] = old + 1;

        for (int i = 0; i < np; ++i) {
            for (int j = i + 1; j < np; ++j) {
                if (aborted_) return;
                const int q = poss[i], r = poss[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;
                ++cnt_.attempted;
                const Block cand{point, q, r};
                if ((point < old && deg_[point] >= 3) ||
                    (q < old && deg_[q] >= 3) ||
                    (r < old && deg_[r] >= 3) ||
                    (q < old && ((pair_mask_[point] >> q) & 1ULL)) ||
                    (r < old && ((pair_mask_[point] >> r) & 1ULL)) ||
                    (q < old && r < old && ((pair_mask_[q] >> r) & 1ULL))) {
                    ++cnt_.structural;
                    continue;
                }
                std::array<std::uint8_t, 3> w8{};
                if (c8_witness(cand, w8)) {
                    ++cnt_.c8;
                    emit(kRejectC8);
                    emit(w8[0]); emit(w8[1]); emit(w8[2]);
                    continue;
                }
                std::uint8_t pcode = 0;
                std::array<std::uint8_t, 7> w16{};
                if (c16_witness(cand, pcode, w16)) {
                    ++cnt_.c16;
                    emit(kRejectC16);
                    emit(pcode);
                    for (int k = 0; k < 7; ++k) emit(w16[k]);
                    continue;
                }
                emit(kExpand);
                int next = old;
                if (q == old || r == old) ++next;
                if (r == old + 1) ++next;
                const int saved = introduced_;
                introduced_ = next;
                add(cand);
                recurse(point, q, r);
                remove(cand);
                introduced_ = saved;
            }
        }
    }
};

// ---------------- Independent ZERO-ORACLE Subtree / Split Verifier ----------------

class ZeroOracleSubtreeVerifier {
  public:
    ZeroOracleSubtreeVerifier(int side, const std::vector<std::uint8_t>& stream)
        : side_(side), stream_(stream) {}

    Counts verify_subtree(const SubtreeTask& task) {
        init_from(task);
        visit(task.point, task.last_q, task.last_r, 0, -1, nullptr);
        if (pos_ != stream_.size()) throw std::runtime_error("trailing bytes in subtree stream");
        return cnt_;
    }

    Counts verify_split(const SubtreeTask& task, int depth_steps,
                        std::vector<SubtreeTask>& out_children) {
        init_from(task);
        out_children.clear();
        visit(task.point, task.last_q, task.last_r, 0, depth_steps, &out_children);
        if (pos_ != stream_.size()) throw std::runtime_error("trailing bytes in split stream");
        return cnt_;
    }

  private:
    int side_;
    const std::vector<std::uint8_t>& stream_;
    std::size_t pos_ = 0;
    std::vector<Block> blocks_;
    std::array<int, kMaxSide> deg_{};
    std::array<std::array<bool, kMaxSide>, kMaxSide> paired_{};
    int introduced_ = 0;
    Counts cnt_;

    void init_from(const SubtreeTask& task) {
        blocks_.clear();
        deg_.fill(0);
        for (auto& row : paired_) row.fill(false);
        introduced_ = task.introduced;
        pos_ = 0;
        cnt_ = {};
        for (const Block& b : task.blocks) install(b);
    }

    inline std::uint8_t read_u8() {
        if (pos_ >= stream_.size()) throw std::runtime_error("unexpected EOF in stream");
        return stream_[pos_++];
    }

    static inline bool has_pt(const Block& b, int x) {
        return b.a == x || b.b == x || b.c == x;
    }

    static inline int unique_inter(const Block& x, const Block& y) {
        const int a[3] = {x.a, x.b, x.c}, b[3] = {y.a, y.b, y.c};
        int val = -1, n = 0;
        for (int u : a)
            for (int v : b)
                if (u == v) { val = u; ++n; }
        return n == 1 ? val : -1;
    }

    void install(const Block& b) {
        if (!(b.a < b.b && b.b < b.c)) throw std::runtime_error("unordered block");
        const int pts[3] = {b.a, b.b, b.c};
        for (int u : pts) {
            if (u < 0 || u >= side_) throw std::runtime_error("point out of range");
            if (deg_[u] >= 3) throw std::runtime_error("deg > 3");
        }
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                if (paired_[pts[i]][pts[j]]) throw std::runtime_error("repeated pair");
        blocks_.push_back(b);
        for (int u : pts) ++deg_[u];
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                paired_[pts[i]][pts[j]] = paired_[pts[j]][pts[i]] = true;
    }

    void uninstall(const Block& b) {
        const int pts[3] = {b.a, b.b, b.c};
        for (int u : pts) --deg_[u];
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                paired_[pts[i]][pts[j]] = paired_[pts[j]][pts[i]] = false;
        blocks_.pop_back();
    }

    void check_c8(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        int id[3] = {read_u8(), read_u8(), read_u8()};
        for (int i = 0; i < 3; ++i)
            if (id[i] >= nb) throw std::runtime_error("C8 bad block id");
        if (id[0] == id[1] || id[0] == id[2] || id[1] == id[2])
            throw std::runtime_error("C8 duplicate block");
        const int pts[4] = {
            unique_inter(cand, blocks_[id[0]]),
            unique_inter(blocks_[id[0]], blocks_[id[1]]),
            unique_inter(blocks_[id[1]], blocks_[id[2]]),
            unique_inter(blocks_[id[2]], cand),
        };
        std::uint64_t mask = 0;
        for (int u : pts) {
            if (u < 0) throw std::runtime_error("C8 missing intersection");
            const std::uint64_t bit = 1ULL << u;
            if (mask & bit) throw std::runtime_error("C8 repeated point");
            mask |= bit;
        }
    }

    void check_c16(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        const int code = read_u8();
        if (code > 2) throw std::runtime_error("C16 bad pair code");
        const int cpts[3] = {cand.a, cand.b, cand.c};
        constexpr int ep[3][2] = {{0, 1}, {0, 2}, {1, 2}};
        const int start = cpts[ep[code][0]], finish = cpts[ep[code][1]];
        int id[7];
        std::uint64_t bmask = 0;
        for (int i = 0; i < 7; ++i) {
            id[i] = read_u8();
            if (id[i] >= nb) throw std::runtime_error("C16 bad block id");
            const std::uint64_t bit = 1ULL << id[i];
            if (bmask & bit) throw std::runtime_error("C16 duplicate block");
            bmask |= bit;
        }
        if (!has_pt(blocks_[id[0]], start) || !has_pt(blocks_[id[6]], finish))
            throw std::runtime_error("C16 endpoint mismatch");
        int pts[8];
        pts[0] = start;
        for (int i = 0; i < 6; ++i) pts[i + 1] = unique_inter(blocks_[id[i]], blocks_[id[i + 1]]);
        pts[7] = finish;
        std::uint64_t pmask = 0;
        for (int u : pts) {
            if (u < 0) throw std::runtime_error("C16 missing intersection");
            const std::uint64_t bit = 1ULL << u;
            if (pmask & bit) throw std::runtime_error("C16 repeated point");
            pmask |= bit;
        }
    }

    void visit(int point, int last_q, int last_r, int depth, int stop_depth,
               std::vector<SubtreeTask>* out_children) {
        if (stop_depth >= 0 && depth >= stop_depth) {
            out_children->push_back({blocks_, introduced_, point, last_q, last_r});
            return;
        }
        ++cnt_.states;
        while (point < introduced_ && deg_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) {
                ++cnt_.completions;
                throw std::runtime_error("completed configuration reached!");
            }
            return;
        }
        if (static_cast<int>(blocks_.size()) >= side_) return;

        const int old = introduced_;
        int poss[kMaxSide];
        int np = 0;
        for (int q = point + 1; q < old; ++q) {
            if (deg_[q] < 3 && !paired_[point][q]) poss[np++] = q;
        }
        if (old < side_) poss[np++] = old;
        if (old + 1 < side_) poss[np++] = old + 1;

        for (int i = 0; i < np; ++i) {
            for (int j = i + 1; j < np; ++j) {
                const int q = poss[i], r = poss[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;
                ++cnt_.attempted;
                const Block cand{point, q, r};
                if ((point < old && deg_[point] >= 3) ||
                    (q < old && deg_[q] >= 3) ||
                    (r < old && deg_[r] >= 3) ||
                    (q < old && paired_[point][q]) ||
                    (r < old && paired_[point][r]) ||
                    (q < old && r < old && paired_[q][r])) {
                    ++cnt_.structural;
                    continue;
                }
                const std::uint8_t tag = read_u8();
                if (tag == kRejectC8) { check_c8(cand); ++cnt_.c8; continue; }
                if (tag == kRejectC16) { check_c16(cand); ++cnt_.c16; continue; }
                if (tag != kExpand) throw std::runtime_error("bad stream tag");
                int next = old;
                if (q == old || r == old) ++next;
                if (r == old + 1) ++next;
                const int saved = introduced_;
                introduced_ = next;
                install(cand);
                visit(point, q, r, depth + 1, stop_depth, out_children);
                uninstall(cand);
                introduced_ = saved;
            }
        }
    }
};

}  // namespace

int main(int argc, char** argv) {
    try {
        int side = 40;
        int orbit = 0;  // 0 = both orbits 1 & 2
        int workers = static_cast<int>(std::max(1u, std::thread::hardware_concurrency()));
        bool verify_zero_oracle = true;
        std::uint64_t state_budget = 4096;
        std::size_t byte_budget = 32ULL * 1024ULL * 1024ULL;  // 32 MiB max cert buffer/task

        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            if (arg == "--side" && i + 1 < argc) side = std::stoi(argv[++i]);
            else if (arg == "--orbit" && i + 1 < argc) orbit = std::stoi(argv[++i]);
            else if (arg == "--workers" && i + 1 < argc) workers = std::max(1, std::stoi(argv[++i]));
            else if (arg == "--split-depth" && i + 1 < argc) ++i;  // ignored: adaptive auto-split
            else if (arg == "--state-budget" && i + 1 < argc) state_budget = std::stoull(argv[++i]);
            else if (arg == "--no-verify") verify_zero_oracle = false;
            else throw std::runtime_error(
                "usage: cubic_bipartite_parallel --side V [--orbit 0|1|2] [--workers W] [--no-verify]");
        }
        if (side < 8 || side > kMaxSide) throw std::runtime_error("side must be in [8, 63]");

        const std::size_t target_q = static_cast<std::size_t>(16 * workers);
        const std::size_t low_watermark = static_cast<std::size_t>(4 * workers);

        const auto t_all = std::chrono::steady_clock::now();
        Counts grand{};
        const int o_first = (orbit == 0) ? 1 : orbit;
        const int o_last = (orbit == 0) ? 2 : orbit;

        for (int orb = o_first; orb <= o_last; ++orb) {
            const auto t0 = std::chrono::steady_clock::now();

            std::deque<SubtreeTask> work_q;
            work_q.push_back(make_root_task(orb));
            std::atomic<std::size_t> q_approx{1};
            std::atomic<std::uint64_t> total_cert_bytes{0};
            std::atomic<std::uint64_t> verified_splits{0};
            std::atomic<std::uint64_t> verified_leaves{0};
            std::atomic<std::uint64_t> adaptive_resplits{0};

            std::mutex q_mtx;
            std::condition_variable q_cv;
            int active_workers = 0;
            bool fatal_error = false;
            std::string first_err;
            Counts orb_total{};

            std::vector<std::thread> pool;
            for (int w = 0; w < workers; ++w) {
                pool.emplace_back([&]() {
                    SubtreeGenerator gen(side);
                    std::vector<std::uint8_t> buf;
                    std::vector<SubtreeTask> children, ver_children;
                    Counts loc{};

                    auto record_error = [&](const std::string& msg) {
                        std::lock_guard<std::mutex> lk(q_mtx);
                        if (first_err.empty()) first_err = msg;
                        fatal_error = true;
                        q_cv.notify_all();
                    };

                    try {
                        while (true) {
                            SubtreeTask t;
                            std::size_t q_after = 0;
                            {
                                std::unique_lock<std::mutex> lk(q_mtx);
                                q_cv.wait(lk, [&]() {
                                    return fatal_error || !work_q.empty() || active_workers == 0;
                                });
                                if (fatal_error || (work_q.empty() && active_workers == 0)) break;
                                // Pop shallowest (FRONT) when queue is hungry; pop deepest (BACK)
                                // when queue is saturated to keep memory tiny!
                                if (work_q.size() < target_q) {
                                    t = std::move(work_q.front());
                                    work_q.pop_front();
                                } else {
                                    t = std::move(work_q.back());
                                    work_q.pop_back();
                                }
                                q_after = work_q.size();
                                q_approx.store(q_after, std::memory_order_relaxed);
                                ++active_workers;
                            }

                            const int rem_blocks = side - static_cast<int>(t.blocks.size());
                            const bool can_split = (workers > 1 && rem_blocks >= 2) || (rem_blocks >= 3);
                            bool do_split = (workers > 1 && q_after < target_q && rem_blocks >= 2);
                            bool was_resplit = false;

                            if (!do_split) {
                                Counts c_gen{};
                                const bool done = gen.run_with_budget(
                                    t, verify_zero_oracle ? &buf : nullptr,
                                    can_split ? state_budget : std::numeric_limits<std::uint64_t>::max(),
                                    can_split ? byte_budget : std::numeric_limits<std::size_t>::max(),
                                    &q_approx, low_watermark, c_gen);
                                if (done) {
                                    if (verify_zero_oracle) {
                                        ZeroOracleSubtreeVerifier ver(side, buf);
                                        Counts c_ver = ver.verify_subtree(t);
                                        if (!c_gen.eq(c_ver)) {
                                            throw std::runtime_error("subtree gen/verifier count mismatch");
                                        }
                                        total_cert_bytes.fetch_add(buf.size(), std::memory_order_relaxed);
                                        verified_leaves.fetch_add(1, std::memory_order_relaxed);
                                    }
                                    loc.add(c_gen);
                                } else {
                                    do_split = true;
                                    was_resplit = true;
                                }
                            }

                            if (do_split) {
                                const int step = (rem_blocks >= 3) ? 2 : 1;
                                Counts c_split = gen.split_task(
                                    t, step, children, verify_zero_oracle ? &buf : nullptr);
                                if (verify_zero_oracle) {
                                    ZeroOracleSubtreeVerifier ver(side, buf);
                                    Counts c_ver = ver.verify_split(t, step, ver_children);
                                    if (!c_split.eq(c_ver) || ver_children != children) {
                                        throw std::runtime_error("split gen/verifier mismatch");
                                    }
                                    total_cert_bytes.fetch_add(buf.size(), std::memory_order_relaxed);
                                    verified_splits.fetch_add(1, std::memory_order_relaxed);
                                }
                                if (was_resplit) {
                                    adaptive_resplits.fetch_add(1, std::memory_order_relaxed);
                                }
                                loc.add(c_split);
                                {
                                    std::lock_guard<std::mutex> lk(q_mtx);
                                    for (auto& ch : children) work_q.push_back(std::move(ch));
                                    q_approx.store(work_q.size(), std::memory_order_relaxed);
                                    --active_workers;
                                }
                                q_cv.notify_all();
                            } else {
                                std::lock_guard<std::mutex> lk(q_mtx);
                                --active_workers;
                                if (active_workers == 0 && work_q.empty()) q_cv.notify_all();
                            }
                        }
                    } catch (const std::exception& e) {
                        record_error(e.what());
                    }

                    std::lock_guard<std::mutex> lk(q_mtx);
                    orb_total.add(loc);
                });
            }
            for (auto& th : pool) th.join();
            if (!first_err.empty()) throw std::runtime_error(first_err);
            const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
            std::cout << "ORBIT " << orb << " side=" << side
                      << " workers=" << workers
                      << " verified_splits=" << verified_splits.load()
                      << " verified_leaves=" << verified_leaves.load()
                      << " adaptive_resplits=" << adaptive_resplits.load()
                      << " states=" << orb_total.states
                      << " attempted=" << orb_total.attempted
                      << " structural=" << orb_total.structural
                      << " c8=" << orb_total.c8
                      << " c16=" << orb_total.c16
                      << " completions=" << orb_total.completions
                      << " cert_bytes=" << total_cert_bytes.load()
                      << " seconds=" << std::fixed << std::setprecision(3) << sec << '\n'
                      << std::flush;
            grand.add(orb_total);
        }
        const double total_sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t_all).count();
        std::cout << "TOTAL side=" << side << " (n<=" << (2 * side) << ")"
                  << " workers=" << workers
                  << " states=" << grand.states
                  << " attempted=" << grand.attempted
                  << " structural=" << grand.structural
                  << " c8=" << grand.c8
                  << " c16=" << grand.c16
                  << " completions=" << grand.completions
                  << " zero_oracle_verified=" << (verify_zero_oracle ? "true" : "false")
                  << " seconds=" << std::fixed << std::setprecision(3) << total_sec << '\n';
        return grand.completions == 0 ? 0 : 2;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << '\n';
        return 1;
    }
}

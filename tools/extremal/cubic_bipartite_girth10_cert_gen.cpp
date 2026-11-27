// Zero-assumption static rejection-certificate generator for the girth >= 10 Moore-tree
// restricted-growth search over cubic bipartite graphs of order <= 2*V (31 <= V <= 63)
// avoiding {C4, C6, C8, C16}.
//
// Emits magic "EGCBG101" stream where EVERY structurally valid candidate is accompanied by
// either an explicit C6 (2-block), C8 (3-block), or C16 (7-block) witness, or an EXPAND tag.
// No pre-filtering shortcuts: matches the exact restricted-growth schedule of the verifier.

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr int kMaxV = 63;
constexpr std::array<char, 8> kMagic{{'E', 'G', 'C', 'B', 'G', '1', '0', '1'}};
constexpr std::uint8_t kRejectC6 = 0x06U;
constexpr std::uint8_t kRejectC8 = 0x08U;
constexpr std::uint8_t kRejectC16 = 0x10U;
constexpr std::uint8_t kExpand = 0x20U;

struct Block {
    int a, b, c;
};

struct Counts {
    std::uint64_t states = 0;
    std::uint64_t attempted = 0;
    std::uint64_t structural = 0;
    std::uint64_t c6 = 0;
    std::uint64_t c8 = 0;
    std::uint64_t c16 = 0;
    std::uint64_t completions = 0;
};

void write_byte(std::ostream& out, int v) {
    if (v < 0 || v > 255) throw std::runtime_error("byte out of range");
    out.put(static_cast<char>(static_cast<unsigned char>(v)));
    if (!out) throw std::runtime_error("write error");
}

void write_u64(std::ostream& out, std::uint64_t v) {
    for (int sh = 0; sh < 64; sh += 8) write_byte(out, static_cast<int>((v >> sh) & 0xffU));
}

class G10CertGen {
  public:
    G10CertGen(int V, std::ostream& out) : V_(V), out_(out) {
        if (V_ < 31 || V_ > kMaxV) throw std::runtime_error("V must be in [31, 63]");
    }

    Counts run() {
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
        introduced_ = 31;
        recurse(7, -1, -1);
        return cnt_;
    }

  private:
    int V_;
    std::ostream& out_;
    std::vector<Block> blocks_;
    std::array<std::vector<int>, kMaxV> incident_;
    std::array<int, kMaxV> deg_{};
    std::array<std::uint64_t, kMaxV> pair_mask_{};
    // block_of_pair[u][v] = block id containing both u and v, or -1
    std::array<std::array<int, kMaxV>, kMaxV> block_of_pair_{};
    int introduced_ = 31;
    Counts cnt_;

    void add(const Block& b) {
        if (blocks_.empty()) {
            for (auto& row : block_of_pair_) row.fill(-1);
        }
        const int id = static_cast<int>(blocks_.size());
        blocks_.push_back(b);
        ++deg_[b.a]; ++deg_[b.b]; ++deg_[b.c];
        incident_[b.a].push_back(id);
        incident_[b.b].push_back(id);
        incident_[b.c].push_back(id);
        const int pts[3] = {b.a, b.b, b.c};
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j) {
                pair_mask_[pts[i]] |= (1ULL << pts[j]);
                pair_mask_[pts[j]] |= (1ULL << pts[i]);
                block_of_pair_[pts[i]][pts[j]] = id;
                block_of_pair_[pts[j]][pts[i]] = id;
            }
        }
    }

    void remove(const Block& b) {
        --deg_[b.a]; --deg_[b.b]; --deg_[b.c];
        incident_[b.a].pop_back();
        incident_[b.b].pop_back();
        incident_[b.c].pop_back();
        const int pts[3] = {b.a, b.b, b.c};
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j) {
                pair_mask_[pts[i]] &= ~(1ULL << pts[j]);
                pair_mask_[pts[j]] &= ~(1ULL << pts[i]);
                block_of_pair_[pts[i]][pts[j]] = -1;
                block_of_pair_[pts[j]][pts[i]] = -1;
            }
        }
        blocks_.pop_back();
    }

    bool c6_witness(const Block& cand, std::array<std::uint8_t, 2>& wit) const {
        const int pts[3] = {cand.a, cand.b, cand.c};
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j) {
                const int x = pts[i], y = pts[j];
                std::uint64_t common = pair_mask_[x] & pair_mask_[y];
                while (common) {
                    const int w = __builtin_ctzll(common);
                    common &= common - 1;
                    const int b0 = block_of_pair_[x][w];
                    const int b1 = block_of_pair_[w][y];
                    if (b0 >= 0 && b1 >= 0 && b0 != b1) {
                        wit = {static_cast<std::uint8_t>(b0), static_cast<std::uint8_t>(b1)};
                        return true;
                    }
                }
            }
        }
        return false;
    }

    bool c8_witness(const Block& cand, std::array<std::uint8_t, 3>& wit) const {
        const int pts[3] = {cand.a, cand.b, cand.c};
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j) {
                const int x = pts[i], y = pts[j];
                std::uint64_t mx = pair_mask_[x];
                const std::uint64_t my = pair_mask_[y];
                while (mx) {
                    const int u = __builtin_ctzll(mx);
                    mx &= mx - 1;
                    if (u == y) continue;
                    std::uint64_t mv = pair_mask_[u] & my;
                    while (mv) {
                        const int v = __builtin_ctzll(mv);
                        mv &= mv - 1;
                        if (v == x || v == u) continue;
                        const int b0 = block_of_pair_[x][u];
                        const int b1 = block_of_pair_[u][v];
                        const int b2 = block_of_pair_[v][y];
                        if (b0 >= 0 && b1 >= 0 && b2 >= 0 && b0 != b1 && b0 != b2 && b1 != b2) {
                            wit = {static_cast<std::uint8_t>(b0),
                                   static_cast<std::uint8_t>(b1),
                                   static_cast<std::uint8_t>(b2)};
                            return true;
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
        if (used_blocks == 7) return cur == target;
        for (int bid : incident_[cur]) {
            const std::uint64_t bbit = 1ULL << bid;
            if ((seen_blks & bbit) != 0ULL) continue;
            const Block& blk = blocks_[bid];
            const int pts[3] = {blk.a, blk.b, blk.c};
            for (int nxt : pts) {
                if (nxt == cur) continue;
                const std::uint64_t pbit = 1ULL << nxt;
                if ((seen_pts & pbit) != 0ULL) continue;
                if (nxt == target && used_blocks + 1 != 7) continue;
                if (nxt != target && used_blocks + 1 == 7) continue;
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

    void recurse(int point, int last_q, int last_r) {
        ++cnt_.states;
        while (point < introduced_ && deg_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) ++cnt_.completions;
            return;
        }
        if (static_cast<int>(blocks_.size()) >= V_) return;

        // Exact necessary deficit bound (also checked identically in verifier):
        int deficit = 0;
        for (int u = point; u < introduced_; ++u) deficit += (3 - deg_[u]);
        if (deficit > 3 * (V_ - static_cast<int>(blocks_.size()))) return;

        const int old = introduced_;
        std::vector<int> possible;
        possible.reserve(V_);
        for (int q = point + 1; q < old; ++q) {
            if (deg_[q] < 3 && !((pair_mask_[point] >> q) & 1ULL)) possible.push_back(q);
        }
        if (old < V_) possible.push_back(old);
        if (old + 1 < V_) possible.push_back(old + 1);

        for (std::size_t i = 0; i < possible.size(); ++i) {
            for (std::size_t j = i + 1; j < possible.size(); ++j) {
                const int q = possible[i], r = possible[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;

                ++cnt_.attempted;
                const Block cand{point, q, r};
                const int pts[3] = {point, q, r};
                bool invalid = false;
                for (int p : pts)
                    if (p < old && deg_[p] >= 3) invalid = true;
                for (int a = 0; a < 3; ++a)
                    for (int b = a + 1; b < 3; ++b)
                        if (pts[a] < old && pts[b] < old && ((pair_mask_[pts[a]] >> pts[b]) & 1ULL))
                            invalid = true;
                if (invalid) {
                    ++cnt_.structural;
                    continue;
                }

                std::array<std::uint8_t, 2> w6{};
                if (c6_witness(cand, w6)) {
                    ++cnt_.c6;
                    write_byte(out_, kRejectC6);
                    write_byte(out_, w6[0]);
                    write_byte(out_, w6[1]);
                    continue;
                }

                std::array<std::uint8_t, 3> w8{};
                if (c8_witness(cand, w8)) {
                    ++cnt_.c8;
                    write_byte(out_, kRejectC8);
                    for (std::uint8_t id : w8) write_byte(out_, id);
                    continue;
                }

                std::uint8_t pcode = 0;
                std::array<std::uint8_t, 7> w16{};
                if (c16_witness(cand, pcode, w16)) {
                    ++cnt_.c16;
                    write_byte(out_, kRejectC16);
                    write_byte(out_, pcode);
                    for (std::uint8_t id : w16) write_byte(out_, id);
                    continue;
                }

                write_byte(out_, kExpand);
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

}  // namespace

int main(int argc, char** argv) {
    try {
        int V = 35;
        std::string out_path;
        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            if (arg == "--side" && i + 1 < argc) V = std::stoi(argv[++i]);
            else if (arg == "--out" && i + 1 < argc) out_path = argv[++i];
            else throw std::runtime_error("usage: cubic_bipartite_girth10_cert_gen --side V --out FILE");
        }
        if (out_path.empty()) throw std::runtime_error("--out is required");

        std::fstream out(out_path, std::ios::binary | std::ios::out | std::ios::trunc);
        if (!out) throw std::runtime_error("cannot open " + out_path);

        // 68-byte header: 8 magic + 4 meta + 7*8 counts
        for (char ch : kMagic) write_byte(out, static_cast<unsigned char>(ch));
        write_byte(out, V);
        write_byte(out, 0);
        write_byte(out, 7);  // flags: C6 | C8 | C16
        write_byte(out, 0);
        for (int k = 0; k < 7; ++k) write_u64(out, 0);

        const auto t0 = std::chrono::steady_clock::now();
        G10CertGen gen(V, out);
        const Counts c = gen.run();
        const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

        out.seekp(12, std::ios::beg);
        write_u64(out, c.states);
        write_u64(out, c.attempted);
        write_u64(out, c.structural);
        write_u64(out, c.c6);
        write_u64(out, c.c8);
        write_u64(out, c.c16);
        write_u64(out, c.completions);
        out.flush();

        std::cout << "G10_GENERATED side=" << V << " (n<=" << (2 * V) << ")"
                  << " states=" << c.states << " attempted=" << c.attempted
                  << " structural=" << c.structural << " c6=" << c.c6
                  << " c8=" << c.c8 << " c16=" << c.c16
                  << " completions=" << c.completions << " seconds=" << sec << '\n';
        return c.completions == 0 ? 0 : 2;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << '\n';
        return 1;
    }
}

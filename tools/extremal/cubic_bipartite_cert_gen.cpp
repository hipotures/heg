// 64-bit-safe static rejection-certificate generator for Tranquilli's triangle-rooted
// restricted-growth search over linear V_3-configurations (cubic bipartite graphs of order <= 2*V)
// avoiding {C4, C8, C16}. Supports any 7 <= SIDE <= 63 (n <= 126).
//
// Format matches Tranquilli's EG**TRI1 static certificate stream, generalized with magic
// "EGCBTRI1" and 64-bit path masks (eliminating uint32_t shift UB for SIDE >= 32).

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

constexpr int kMaxSide = 63;
constexpr std::array<char, 8> kMagic{{'E', 'G', 'C', 'B', 'T', 'R', 'I', '1'}};
constexpr std::uint8_t kFlagC8 = 1U;
constexpr std::uint8_t kFlagC16 = 2U;
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
    std::uint64_t c8 = 0;
    std::uint64_t c16 = 0;
    std::uint64_t completions = 0;
};

void write_byte(std::ostream& out, int value) {
    if (value < 0 || value > 255) {
        throw std::runtime_error("certificate byte out of range");
    }
    out.put(static_cast<char>(static_cast<unsigned char>(value)));
    if (!out) {
        throw std::runtime_error("failed while writing certificate");
    }
}

void write_u64(std::ostream& out, std::uint64_t value) {
    for (int shift = 0; shift < 64; shift += 8) {
        write_byte(out, static_cast<int>((value >> shift) & 0xffU));
    }
}

class CertGen {
  public:
    CertGen(int side, std::ostream& out) : side_(side), out_(out) {
        if (side_ < 7 || side_ > kMaxSide) {
            throw std::runtime_error("SIDE must be in [7, 63]");
        }
    }

    Counts run(int orbit) {
        add({0, 1, 3});
        add({1, 2, 4});
        add({0, 2, 5});
        Block first{};
        if (orbit == 1) {
            first = {0, 4, 6};
            introduced_ = 7;
        } else if (orbit == 2) {
            if (side_ < 8) {
                throw std::runtime_error("orbit 2 requires SIDE >= 8");
            }
            first = {0, 6, 7};
            introduced_ = 8;
        } else {
            throw std::runtime_error("orbit must be 1 or 2");
        }
        add(first);
        recurse(1, 2, 4);
        return counts_;
    }

  private:
    int side_;
    std::ostream& out_;
    std::vector<Block> blocks_;
    std::array<std::vector<int>, kMaxSide> incident_;
    std::array<int, kMaxSide> degree_{};
    std::array<std::array<bool, kMaxSide>, kMaxSide> paired_{};
    int introduced_ = 6;
    Counts counts_;

    static int intersection(const Block& x, const Block& y) {
        const int a[3] = {x.a, x.b, x.c};
        const int b[3] = {y.a, y.b, y.c};
        int val = -1, cnt = 0;
        for (int u : a) {
            for (int v : b) {
                if (u == v) {
                    val = u;
                    ++cnt;
                }
            }
        }
        if (cnt == 0) return -1;
        return cnt == 1 ? val : -2;
    }

    bool c8_witness(const Block& cand, std::array<std::uint8_t, 3>& wit) const {
        const int k = static_cast<int>(blocks_.size());
        for (int i = 0; i < k; ++i) {
            const int p0 = intersection(cand, blocks_[i]);
            if (p0 < 0) continue;
            for (int j = 0; j < k; ++j) {
                if (j == i) continue;
                const int p1 = intersection(blocks_[i], blocks_[j]);
                if (p1 < 0 || p1 == p0) continue;
                for (int h = 0; h < k; ++h) {
                    if (h == i || h == j) continue;
                    const int p2 = intersection(blocks_[j], blocks_[h]);
                    if (p2 < 0 || p2 == p0 || p2 == p1) continue;
                    const int p3 = intersection(blocks_[h], cand);
                    if (p3 < 0 || p3 == p0 || p3 == p1 || p3 == p2) continue;
                    wit = {static_cast<std::uint8_t>(i),
                           static_cast<std::uint8_t>(j),
                           static_cast<std::uint8_t>(h)};
                    return true;
                }
            }
        }
        return false;
    }

    bool path14_dfs(int cur, int target, int used_blocks,
                    std::uint64_t seen_points, std::uint64_t seen_blocks,
                    std::array<std::uint8_t, 7>& wit) const {
        if (used_blocks == 7) {
            return cur == target;
        }
        for (int bid : incident_[cur]) {
            const std::uint64_t bbit = std::uint64_t{1} << bid;
            if ((seen_blocks & bbit) != 0ULL) continue;
            const Block& blk = blocks_[bid];
            const int pts[3] = {blk.a, blk.b, blk.c};
            for (int nxt : pts) {
                if (nxt == cur) continue;
                const std::uint64_t pbit = std::uint64_t{1} << nxt;
                if ((seen_points & pbit) != 0ULL) continue;
                if (nxt == target && used_blocks + 1 != 7) continue;
                if (nxt != target && used_blocks + 1 == 7) continue;
                wit[used_blocks] = static_cast<std::uint8_t>(bid);
                if (path14_dfs(nxt, target, used_blocks + 1,
                               seen_points | pbit, seen_blocks | bbit, wit)) {
                    return true;
                }
            }
        }
        return false;
    }

    bool c16_witness(const Block& cand, std::uint8_t& pair_code,
                     std::array<std::uint8_t, 7>& wit) const {
        const int pts[3] = {cand.a, cand.b, cand.c};
        int code = 0;
        for (int i = 0; i < 3; ++i) {
            for (int j = i + 1; j < 3; ++j, ++code) {
                const int start = pts[i];
                const int target = pts[j];
                if (path14_dfs(start, target, 0,
                               std::uint64_t{1} << start, 0ULL, wit)) {
                    pair_code = static_cast<std::uint8_t>(code);
                    return true;
                }
            }
        }
        return false;
    }

    void add(const Block& b) {
        const int id = static_cast<int>(blocks_.size());
        blocks_.push_back(b);
        const int pts[3] = {b.a, b.b, b.c};
        for (int p : pts) {
            ++degree_[p];
            incident_[p].push_back(id);
        }
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                paired_[pts[i]][pts[j]] = paired_[pts[j]][pts[i]] = true;
    }

    void remove(const Block& b) {
        const int pts[3] = {b.a, b.b, b.c};
        for (int p : pts) {
            --degree_[p];
            incident_[p].pop_back();
        }
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                paired_[pts[i]][pts[j]] = paired_[pts[j]][pts[i]] = false;
        blocks_.pop_back();
    }

    void recurse(int point, int last_q, int last_r) {
        ++counts_.states;
        while (point < introduced_ && degree_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) {
                ++counts_.completions;
            }
            return;
        }
        if (static_cast<int>(blocks_.size()) >= side_) {
            return;
        }
        const int old = introduced_;
        std::vector<int> possible;
        possible.reserve(side_);
        for (int q = point + 1; q < old; ++q) {
            if (degree_[q] < 3 && !paired_[point][q]) {
                possible.push_back(q);
            }
        }
        if (old < side_) possible.push_back(old);
        if (old + 1 < side_) possible.push_back(old + 1);

        for (std::size_t i = 0; i < possible.size(); ++i) {
            for (std::size_t j = i + 1; j < possible.size(); ++j) {
                const int q = possible[i];
                const int r = possible[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;

                ++counts_.attempted;
                const Block cand{point, q, r};
                const int pts[3] = {point, q, r};
                bool invalid = false;
                for (int p : pts) {
                    if (p < old && degree_[p] >= 3) invalid = true;
                }
                for (int a = 0; a < 3; ++a)
                    for (int b = a + 1; b < 3; ++b)
                        if (pts[a] < old && pts[b] < old && paired_[pts[a]][pts[b]])
                            invalid = true;
                if (invalid) {
                    ++counts_.structural;
                    continue;
                }

                std::array<std::uint8_t, 3> w8{};
                if (c8_witness(cand, w8)) {
                    ++counts_.c8;
                    write_byte(out_, kRejectC8);
                    for (std::uint8_t id : w8) write_byte(out_, id);
                    continue;
                }

                std::uint8_t pcode = 0;
                std::array<std::uint8_t, 7> w16{};
                if (c16_witness(cand, pcode, w16)) {
                    ++counts_.c16;
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
        int side = 35;
        int orbit = 1;
        std::string out_path;
        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            if (arg == "--side" && i + 1 < argc) side = std::stoi(argv[++i]);
            else if (arg == "--orbit" && i + 1 < argc) orbit = std::stoi(argv[++i]);
            else if (arg == "--out" && i + 1 < argc) out_path = argv[++i];
            else throw std::runtime_error("usage: cubic_bipartite_cert_gen --side V --orbit 1|2 --out FILE");
        }
        if (out_path.empty()) throw std::runtime_error("--out is required");

        std::fstream out(out_path, std::ios::binary | std::ios::out | std::ios::trunc);
        if (!out) throw std::runtime_error("cannot open output file: " + out_path);

        // Write placeholder 60-byte header
        for (char ch : kMagic) write_byte(out, static_cast<unsigned char>(ch));
        write_byte(out, side);
        write_byte(out, orbit);
        write_byte(out, kFlagC8 | kFlagC16);
        write_byte(out, 0);
        for (int k = 0; k < 6; ++k) write_u64(out, 0);

        const auto t0 = std::chrono::steady_clock::now();
        CertGen gen(side, out);
        const Counts c = gen.run(orbit);
        const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

        // Patch final header counts
        out.seekp(12, std::ios::beg);
        write_u64(out, c.states);
        write_u64(out, c.attempted);
        write_u64(out, c.structural);
        write_u64(out, c.c8);
        write_u64(out, c.c16);
        write_u64(out, c.completions);
        out.flush();
        if (!out) throw std::runtime_error("failed while patching header");

        std::cout << "GENERATED side=" << side << " orbit=" << orbit
                  << " states=" << c.states << " attempted=" << c.attempted
                  << " structural=" << c.structural << " c8=" << c.c8
                  << " c16=" << c.c16 << " completions=" << c.completions
                  << " seconds=" << sec << '\n';
        return c.completions == 0 ? 0 : 2;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << '\n';
        return 1;
    }
}

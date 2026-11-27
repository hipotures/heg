// Independent zero-oracle static rejection-certificate verifier for EGCBTRI1 streams
// (cubic bipartite C6-branch exhaustion for any 7 <= SIDE <= 63, n <= 126).
//
// Runs NO cycle-search oracle; instead reconstructs the exact restricted-growth proposal
// schedule and checks every explicit C8 (3-block) and C16 (7-block) witness directly.

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
    int p[3];
};

struct Counts {
    std::uint64_t states = 0;
    std::uint64_t attempted = 0;
    std::uint64_t structural = 0;
    std::uint64_t c8 = 0;
    std::uint64_t c16 = 0;
    std::uint64_t completions = 0;
};

struct Header {
    int side = 0;
    int orbit = 0;
    std::uint8_t flags = 0;
    Counts claimed;
};

[[noreturn]] void fail(const std::string& msg) {
    throw std::runtime_error(msg);
}

std::uint8_t read_byte(std::istream& in) {
    const int v = in.get();
    if (v == std::char_traits<char>::eof()) fail("unexpected EOF in certificate");
    return static_cast<std::uint8_t>(static_cast<unsigned char>(v));
}

std::uint64_t read_u64(std::istream& in) {
    std::uint64_t val = 0;
    for (int sh = 0; sh < 64; sh += 8) {
        val |= static_cast<std::uint64_t>(read_byte(in)) << sh;
    }
    return val;
}

Header read_header(std::istream& in) {
    for (char ch : kMagic) {
        if (read_byte(in) != static_cast<std::uint8_t>(static_cast<unsigned char>(ch))) {
            fail("invalid certificate magic");
        }
    }
    Header h;
    h.side = read_byte(in);
    h.orbit = read_byte(in);
    h.flags = read_byte(in);
    if (read_byte(in) != 0U) fail("nonzero reserved header byte");
    h.claimed.states = read_u64(in);
    h.claimed.attempted = read_u64(in);
    h.claimed.structural = read_u64(in);
    h.claimed.c8 = read_u64(in);
    h.claimed.c16 = read_u64(in);
    h.claimed.completions = read_u64(in);
    if (h.side < 7 || h.side > kMaxSide) fail("side out of supported range [7, 63]");
    if (h.orbit != 1 && h.orbit != 2) fail("orbit must be 1 or 2");
    if (h.flags != (kFlagC8 | kFlagC16)) fail("unexpected flags");
    return h;
}

class Verifier {
  public:
    Verifier(std::istream& in, const Header& h) : in_(in), side_(h.side), orbit_(h.orbit) {}

    Counts verify() {
        install({{0, 1, 3}});
        install({{1, 2, 4}});
        install({{0, 2, 5}});
        if (orbit_ == 1) {
            introduced_ = 7;
            install({{0, 4, 6}});
        } else {
            if (side_ < 8) fail("orbit 2 requires side >= 8");
            introduced_ = 8;
            install({{0, 6, 7}});
        }
        visit(1, 2, 4);
        return counts_;
    }

  private:
    std::istream& in_;
    int side_;
    int orbit_;
    std::vector<Block> blocks_;
    std::array<int, kMaxSide> deg_{};
    std::array<std::array<bool, kMaxSide>, kMaxSide> paired_{};
    int introduced_ = 6;
    Counts counts_;

    static bool contains(const Block& b, int x) {
        return b.p[0] == x || b.p[1] == x || b.p[2] == x;
    }

    static int unique_inter(const Block& a, const Block& b) {
        int val = -1, cnt = 0;
        for (int u : a.p)
            for (int v : b.p)
                if (u == v) { val = u; ++cnt; }
        return cnt == 1 ? val : -1;
    }

    void install(const Block& b) {
        if (!(b.p[0] < b.p[1] && b.p[1] < b.p[2])) fail("unordered block");
        for (int u : b.p) {
            if (u < 0 || u >= side_) fail("point out of range");
            if (deg_[u] >= 3) fail("degree > 3 on accepted branch");
        }
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                if (paired_[b.p[i]][b.p[j]]) fail("repeated pair on accepted branch");
        blocks_.push_back(b);
        for (int u : b.p) ++deg_[u];
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                paired_[b.p[i]][b.p[j]] = paired_[b.p[j]][b.p[i]] = true;
    }

    void uninstall(const Block& b) {
        for (int u : b.p) --deg_[u];
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                paired_[b.p[i]][b.p[j]] = paired_[b.p[j]][b.p[i]] = false;
        blocks_.pop_back();
    }

    void check_c8(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        int id[3];
        for (int i = 0; i < 3; ++i) {
            id[i] = read_byte(in_);
            if (id[i] < 0 || id[i] >= nb) fail("C8 witness block index out of range");
        }
        if (id[0] == id[1] || id[0] == id[2] || id[1] == id[2]) fail("C8 witness repeats block");
        const int pts[4] = {
            unique_inter(cand, blocks_[id[0]]),
            unique_inter(blocks_[id[0]], blocks_[id[1]]),
            unique_inter(blocks_[id[1]], blocks_[id[2]]),
            unique_inter(blocks_[id[2]], cand),
        };
        std::uint64_t mask = 0;
        for (int u : pts) {
            if (u < 0) fail("C8 witness missing intersection");
            const std::uint64_t bit = std::uint64_t{1} << u;
            if ((mask & bit) != 0ULL) fail("C8 witness repeats point");
            mask |= bit;
        }
    }

    void check_c16(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        const int code = read_byte(in_);
        if (code < 0 || code > 2) fail("C16 witness bad pair code");
        constexpr int ep[3][2] = {{0, 1}, {0, 2}, {1, 2}};
        const int start = cand.p[ep[code][0]];
        const int finish = cand.p[ep[code][1]];
        int id[7];
        std::uint64_t bmask = 0;
        for (int i = 0; i < 7; ++i) {
            id[i] = read_byte(in_);
            if (id[i] < 0 || id[i] >= nb) fail("C16 witness block index out of range");
            const std::uint64_t bbit = std::uint64_t{1} << id[i];
            if ((bmask & bbit) != 0ULL) fail("C16 witness repeats block");
            bmask |= bbit;
        }
        if (!contains(blocks_[id[0]], start)) fail("C16 witness start not in first block");
        if (!contains(blocks_[id[6]], finish)) fail("C16 witness finish not in last block");
        int pts[8];
        pts[0] = start;
        for (int i = 0; i < 6; ++i) {
            pts[i + 1] = unique_inter(blocks_[id[i]], blocks_[id[i + 1]]);
        }
        pts[7] = finish;
        std::uint64_t pmask = 0;
        for (int u : pts) {
            if (u < 0) fail("C16 witness missing intersection");
            const std::uint64_t bit = std::uint64_t{1} << u;
            if ((pmask & bit) != 0ULL) fail("C16 witness repeats point");
            pmask |= bit;
        }
    }

    void visit(int point, int last_q, int last_r) {
        ++counts_.states;
        while (point < introduced_ && deg_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) {
                ++counts_.completions;
                fail("certificate expanded to a completed configuration!");
            }
            return;
        }
        if (static_cast<int>(blocks_.size()) >= side_) return;

        const int old = introduced_;
        std::vector<int> possible;
        possible.reserve(side_);
        for (int q = point + 1; q < old; ++q) {
            if (deg_[q] < 3 && !paired_[point][q]) possible.push_back(q);
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
                const Block cand{{point, q, r}};
                bool invalid = false;
                for (int u : cand.p)
                    if (u < old && deg_[u] >= 3) invalid = true;
                for (int a = 0; a < 3; ++a)
                    for (int b = a + 1; b < 3; ++b)
                        if (cand.p[a] < old && cand.p[b] < old && paired_[cand.p[a]][cand.p[b]])
                            invalid = true;
                if (invalid) {
                    ++counts_.structural;
                    continue;
                }

                const std::uint8_t tag = read_byte(in_);
                if (tag == kRejectC8) {
                    check_c8(cand);
                    ++counts_.c8;
                    continue;
                }
                if (tag == kRejectC16) {
                    check_c16(cand);
                    ++counts_.c16;
                    continue;
                }
                if (tag != kExpand) fail("unknown tag byte in certificate");

                int next = old;
                if (q == old || r == old) ++next;
                if (r == old + 1) ++next;
                const int saved = introduced_;
                introduced_ = next;
                install(cand);
                visit(point, q, r);
                uninstall(cand);
                introduced_ = saved;
            }
        }
    }
};

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 2) fail("usage: cubic_bipartite_cert_verify CERTFILE|-");
        std::ifstream file;
        std::istream* in = &std::cin;
        if (std::string(argv[1]) != "-") {
            file.open(argv[1], std::ios::binary);
            if (!file) fail(std::string("cannot open ") + argv[1]);
            in = &file;
        }
        const auto t0 = std::chrono::steady_clock::now();
        const Header h = read_header(*in);
        Verifier v(*in, h);
        const Counts got = v.verify();
        if (got.states != h.claimed.states || got.attempted != h.claimed.attempted ||
            got.structural != h.claimed.structural || got.c8 != h.claimed.c8 ||
            got.c16 != h.claimed.c16 || got.completions != h.claimed.completions) {
            fail("header counts mismatch");
        }
        if (in->get() != std::char_traits<char>::eof()) fail("trailing bytes in certificate");
        if (got.completions != 0) fail("nonzero completions");
        const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        std::cout << "VERIFIED_OK side=" << h.side << " orbit=" << h.orbit
                  << " states=" << got.states << " attempted=" << got.attempted
                  << " structural=" << got.structural << " c8=" << got.c8
                  << " c16=" << got.c16 << " completions=0 seconds=" << sec << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "VERIFY_FAILED: " << e.what() << '\n';
        return 1;
    }
}

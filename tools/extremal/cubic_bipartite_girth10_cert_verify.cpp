// Independent zero-oracle static rejection-certificate verifier for EGCBG101 streams
// (cubic bipartite girth >= 10 Moore-tree exhaustion for any 31 <= V <= 63).
//
// Runs NO cycle-search oracle; checks every explicit C6 (2-block), C8 (3-block), and
// C16 (7-block) witness directly against the active linear V_3-configuration.

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
    int p[3];
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

struct Header {
    int side = 0;
    Counts claimed;
};

[[noreturn]] void fail(const std::string& msg) { throw std::runtime_error(msg); }

std::uint8_t read_byte(std::istream& in) {
    const int v = in.get();
    if (v == std::char_traits<char>::eof()) fail("unexpected EOF");
    return static_cast<std::uint8_t>(static_cast<unsigned char>(v));
}

std::uint64_t read_u64(std::istream& in) {
    std::uint64_t val = 0;
    for (int sh = 0; sh < 64; sh += 8) val |= static_cast<std::uint64_t>(read_byte(in)) << sh;
    return val;
}

Header read_header(std::istream& in) {
    for (char ch : kMagic) {
        if (read_byte(in) != static_cast<std::uint8_t>(static_cast<unsigned char>(ch))) {
            fail("bad magic (expected EGCBG101)");
        }
    }
    Header h;
    h.side = read_byte(in);
    if (read_byte(in) != 0U) fail("nonzero orbit byte");
    if (read_byte(in) != 7U) fail("unexpected flags byte");
    if (read_byte(in) != 0U) fail("nonzero reserved byte");
    h.claimed.states = read_u64(in);
    h.claimed.attempted = read_u64(in);
    h.claimed.structural = read_u64(in);
    h.claimed.c6 = read_u64(in);
    h.claimed.c8 = read_u64(in);
    h.claimed.c16 = read_u64(in);
    h.claimed.completions = read_u64(in);
    if (h.side < 31 || h.side > kMaxV) fail("side out of range [31, 63]");
    return h;
}

class G10Verifier {
  public:
    G10Verifier(std::istream& in, int side) : in_(in), V_(side) {}

    Counts verify() {
        const Block root[15] = {
            {{0, 1, 2}},
            {{0, 3, 4}},   {{0, 5, 6}},
            {{1, 7, 8}},   {{1, 9, 10}},
            {{2, 11, 12}}, {{2, 13, 14}},
            {{3, 15, 16}}, {{3, 17, 18}},
            {{4, 19, 20}}, {{4, 21, 22}},
            {{5, 23, 24}}, {{5, 25, 26}},
            {{6, 27, 28}}, {{6, 29, 30}},
        };
        for (const Block& b : root) install(b);
        introduced_ = 31;
        visit(7, -1, -1);
        return cnt_;
    }

  private:
    std::istream& in_;
    int V_;
    std::vector<Block> blocks_;
    std::array<int, kMaxV> deg_{};
    std::array<std::array<bool, kMaxV>, kMaxV> paired_{};
    int introduced_ = 31;
    Counts cnt_;

    static bool contains(const Block& b, int x) {
        return b.p[0] == x || b.p[1] == x || b.p[2] == x;
    }

    static int unique_inter(const Block& a, const Block& b) {
        int val = -1, n = 0;
        for (int u : a.p)
            for (int v : b.p)
                if (u == v) { val = u; ++n; }
        return n == 1 ? val : -1;
    }

    void install(const Block& b) {
        if (!(b.p[0] < b.p[1] && b.p[1] < b.p[2])) fail("unordered block");
        for (int u : b.p) {
            if (u < 0 || u >= V_) fail("point out of range");
            if (deg_[u] >= 3) fail("degree > 3");
        }
        for (int i = 0; i < 3; ++i)
            for (int j = i + 1; j < 3; ++j)
                if (paired_[b.p[i]][b.p[j]]) fail("repeated pair");
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

    void check_c6(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        const int b0 = read_byte(in_);
        const int b1 = read_byte(in_);
        if (b0 < 0 || b0 >= nb || b1 < 0 || b1 >= nb || b0 == b1) fail("bad C6 block ids");
        const int pts[3] = {
            unique_inter(cand, blocks_[b0]),
            unique_inter(blocks_[b0], blocks_[b1]),
            unique_inter(blocks_[b1], cand),
        };
        if (pts[0] < 0 || pts[1] < 0 || pts[2] < 0 ||
            pts[0] == pts[1] || pts[0] == pts[2] || pts[1] == pts[2]) {
            fail("invalid C6 witness");
        }
    }

    void check_c8(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        int id[3];
        for (int i = 0; i < 3; ++i) {
            id[i] = read_byte(in_);
            if (id[i] < 0 || id[i] >= nb) fail("bad C8 block id");
        }
        if (id[0] == id[1] || id[0] == id[2] || id[1] == id[2]) fail("duplicate C8 block id");
        const int pts[4] = {
            unique_inter(cand, blocks_[id[0]]),
            unique_inter(blocks_[id[0]], blocks_[id[1]]),
            unique_inter(blocks_[id[1]], blocks_[id[2]]),
            unique_inter(blocks_[id[2]], cand),
        };
        std::uint64_t mask = 0;
        for (int u : pts) {
            if (u < 0) fail("C8 missing intersection");
            const std::uint64_t bit = 1ULL << u;
            if (mask & bit) fail("C8 repeated point");
            mask |= bit;
        }
    }

    void check_c16(const Block& cand) {
        const int nb = static_cast<int>(blocks_.size());
        const int code = read_byte(in_);
        if (code < 0 || code > 2) fail("bad C16 pair code");
        constexpr int ep[3][2] = {{0, 1}, {0, 2}, {1, 2}};
        const int start = cand.p[ep[code][0]];
        const int finish = cand.p[ep[code][1]];
        int id[7];
        std::uint64_t bmask = 0;
        for (int i = 0; i < 7; ++i) {
            id[i] = read_byte(in_);
            if (id[i] < 0 || id[i] >= nb) fail("bad C16 block id");
            const std::uint64_t bbit = 1ULL << id[i];
            if (bmask & bbit) fail("duplicate C16 block id");
            bmask |= bbit;
        }
        if (!contains(blocks_[id[0]], start) || !contains(blocks_[id[6]], finish)) {
            fail("C16 endpoint mismatch");
        }
        int pts[8];
        pts[0] = start;
        for (int i = 0; i < 6; ++i) pts[i + 1] = unique_inter(blocks_[id[i]], blocks_[id[i + 1]]);
        pts[7] = finish;
        std::uint64_t pmask = 0;
        for (int u : pts) {
            if (u < 0) fail("C16 missing intersection");
            const std::uint64_t bit = 1ULL << u;
            if (pmask & bit) fail("C16 repeated point");
            pmask |= bit;
        }
    }

    void visit(int point, int last_q, int last_r) {
        ++cnt_.states;
        while (point < introduced_ && deg_[point] == 3) {
            ++point;
            last_q = last_r = -1;
        }
        if (point >= introduced_) {
            if (static_cast<int>(blocks_.size()) == introduced_) {
                ++cnt_.completions;
                fail("certificate reached a valid completion!");
            }
            return;
        }
        if (static_cast<int>(blocks_.size()) >= V_) return;

        int deficit = 0;
        for (int u = point; u < introduced_; ++u) deficit += (3 - deg_[u]);
        if (deficit > 3 * (V_ - static_cast<int>(blocks_.size()))) return;

        const int old = introduced_;
        std::vector<int> possible;
        possible.reserve(V_);
        for (int q = point + 1; q < old; ++q) {
            if (deg_[q] < 3 && !paired_[point][q]) possible.push_back(q);
        }
        if (old < V_) possible.push_back(old);
        if (old + 1 < V_) possible.push_back(old + 1);

        for (std::size_t i = 0; i < possible.size(); ++i) {
            for (std::size_t j = i + 1; j < possible.size(); ++j) {
                const int q = possible[i], r = possible[j];
                if (r == old + 1 && q != old) continue;
                if (last_q >= 0 && (q < last_q || (q == last_q && r <= last_r))) continue;

                ++cnt_.attempted;
                const Block cand{{point, q, r}};
                bool invalid = false;
                for (int u : cand.p)
                    if (u < old && deg_[u] >= 3) invalid = true;
                for (int a = 0; a < 3; ++a)
                    for (int b = a + 1; b < 3; ++b)
                        if (cand.p[a] < old && cand.p[b] < old && paired_[cand.p[a]][cand.p[b]])
                            invalid = true;
                if (invalid) {
                    ++cnt_.structural;
                    continue;
                }

                const std::uint8_t tag = read_byte(in_);
                if (tag == kRejectC6) { check_c6(cand); ++cnt_.c6; continue; }
                if (tag == kRejectC8) { check_c8(cand); ++cnt_.c8; continue; }
                if (tag == kRejectC16) { check_c16(cand); ++cnt_.c16; continue; }
                if (tag != kExpand) fail("unknown certificate tag");

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
        if (argc != 2) fail("usage: cubic_bipartite_girth10_cert_verify CERTFILE|-");
        std::ifstream file;
        std::istream* in = &std::cin;
        if (std::string(argv[1]) != "-") {
            file.open(argv[1], std::ios::binary);
            if (!file) fail(std::string("cannot open ") + argv[1]);
            in = &file;
        }
        const auto t0 = std::chrono::steady_clock::now();
        const Header h = read_header(*in);
        G10Verifier v(*in, h.side);
        const Counts got = v.verify();
        if (got.states != h.claimed.states || got.attempted != h.claimed.attempted ||
            got.structural != h.claimed.structural || got.c6 != h.claimed.c6 ||
            got.c8 != h.claimed.c8 || got.c16 != h.claimed.c16 ||
            got.completions != h.claimed.completions) {
            fail("header counts mismatch");
        }
        if (in->get() != std::char_traits<char>::eof()) fail("trailing bytes");
        if (got.completions != 0) fail("nonzero completions");
        const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        std::cout << "G10_VERIFIED_OK side=" << h.side << " (n<=" << (2 * h.side) << ")"
                  << " states=" << got.states << " attempted=" << got.attempted
                  << " structural=" << got.structural << " c6=" << got.c6
                  << " c8=" << got.c8 << " c16=" << got.c16
                  << " completions=0 seconds=" << sec << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "G10_VERIFY_FAILED: " << e.what() << '\n';
        return 1;
    }
}

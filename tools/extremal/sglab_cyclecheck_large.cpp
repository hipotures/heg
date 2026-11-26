// Independent C++17 exact cycle verifier for n <= 512 (std::array<uint64_t, 8>)
// Uses canonical min-vertex DFS with sound BFS distance pruning (completely independent of Rust MitM).
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using Mask512 = std::array<uint64_t, 8>;

static inline void mask_set(Mask512& m, int v) { m[v >> 6] |= (uint64_t{1} << (v & 63)); }
static inline void mask_clr(Mask512& m, int v) { m[v >> 6] &= ~(uint64_t{1} << (v & 63)); }
static inline bool mask_has(const Mask512& m, int v) { return (m[v >> 6] & (uint64_t{1} << (v & 63))) != 0; }

struct Graph {
    int n = 0;
    std::vector<std::vector<int>> adj;
    std::vector<Mask512> rows;
};

static Graph parse_graph6(std::string raw) {
    while (!raw.empty() && (raw.back() == '\n' || raw.back() == '\r' || raw.back() == ' ')) raw.pop_back();
    if (raw.rfind(">>graph6<<", 0) == 0) raw.erase(0, 10);
    auto val = [&](size_t idx) -> int {
        if (idx >= raw.size()) throw std::runtime_error("truncated graph6");
        int b = static_cast<unsigned char>(raw[idx]);
        if (b < 63 || b > 126) throw std::runtime_error("invalid graph6 byte");
        return b - 63;
    };
    int n = 0;
    size_t pos = 0;
    if (raw[0] != '~') {
        n = val(0);
        pos = 1;
    } else {
        n = (val(1) << 12) | (val(2) << 6) | val(3);
        pos = 4;
    }
    if (n > 512) throw std::runtime_error("order > 512");
    Graph g;
    g.n = n;
    g.adj.resize(n);
    g.rows.assign(n, Mask512{0, 0, 0, 0, 0, 0, 0, 0});
    int buf = 0, bits = 0;
    for (int v = 1; v < n; ++v) {
        for (int u = 0; u < v; ++u) {
            if (bits == 0) {
                buf = val(pos++);
                bits = 6;
            }
            --bits;
            if ((buf >> bits) & 1) {
                g.adj[u].push_back(v);
                g.adj[v].push_back(u);
                mask_set(g.rows[u], v);
                mask_set(g.rows[v], u);
            }
        }
    }
    return g;
}

// Completely independent exact canonical-start DFS with sound BFS distance pruning:
// Any vertex `w` reached at step `depth` (with `rem = target - depth` steps remaining to return to `s`)
// MUST have shortest-path distance dist(w, s) <= rem in G[s..n].
static bool find_cycle_dfs(const Graph& g, int target, std::vector<int>& witness_out) {
    const int n = g.n;
    std::vector<int> dist(n);
    std::vector<int> path;
    path.reserve(target);

    for (int s = 0; s <= n - target; ++s) {
        int deg_gt = 0;
        for (int v : g.adj[s]) if (v > s) ++deg_gt;
        if (deg_gt < 2) continue;

        std::fill(dist.begin(), dist.end(), 1000000);
        dist[s] = 0;
        std::queue<int> q;
        q.push(s);
        while (!q.empty()) {
            int u = q.front();
            q.pop();
            if (dist[u] >= target - 1) continue;
            for (int w : g.adj[u]) {
                if (w > s && dist[w] > dist[u] + 1) {
                    dist[w] = dist[u] + 1;
                    q.push(w);
                }
            }
        }

        Mask512 vis{0, 0, 0, 0, 0, 0, 0, 0};
        mask_set(vis, s);
        path.clear();
        path.push_back(s);

        auto dfs = [&](auto&& self, int u, int depth, int first) -> bool {
            int rem = target - depth;
            if (rem == 0) {
                if (mask_has(g.rows[u], s) && first < u) {
                    witness_out = path;
                    return true;
                }
                return false;
            }
            for (int w : g.adj[u]) {
                if (w > s && !mask_has(vis, w) && dist[w] <= rem) {
                    mask_set(vis, w);
                    path.push_back(w);
                    if (self(self, w, depth + 1, first)) return true;
                    path.pop_back();
                    mask_clr(vis, w);
                }
            }
            return false;
        };

        for (int v : g.adj[s]) {
            if (v > s) {
                mask_set(vis, v);
                path.push_back(v);
                if (dfs(dfs, v, 2, v)) return true;
                path.pop_back();
                mask_clr(vis, v);
            }
        }
    }
    return false;
}

int main(int argc, char** argv) {
    std::string g6_file;
    std::vector<int> lengths{4, 8, 16, 32};
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--graph6-file" && i + 1 < argc) {
            g6_file = argv[++i];
        } else if (a == "--lengths" && i + 1 < argc) {
            lengths.clear();
            std::stringstream ss(argv[++i]);
            std::string tok;
            while (std::getline(ss, tok, ',')) {
                if (!tok.empty()) lengths.push_back(std::stoi(tok));
            }
        }
    }
    if (g6_file.empty()) {
        std::cerr << "usage: sglab-cyclecheck-large --graph6-file <path> [--lengths 4,8,16,32]\n";
        return 2;
    }
    std::ifstream ifs(g6_file);
    std::string raw((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
    Graph g = parse_graph6(raw);
    auto t0 = std::chrono::steady_clock::now();
    std::cout << "{\"order\":" << g.n << ",\"results\":{";
    for (size_t i = 0; i < lengths.size(); ++i) {
        int L = lengths[i];
        auto tl = std::chrono::steady_clock::now();
        std::vector<int> wit;
        bool found = find_cycle_dfs(g, L, wit);
        double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - tl).count();
        if (i) std::cout << ",";
        std::cout << "\"" << L << "\":{\"status\":\"" << (found ? "FOUND" : "ABSENT") << "\",\"ms\":" << ms << "}";
    }
    double tot_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::cout << "},\"total_ms\":" << tot_ms << "}\n";
    return 0;
}

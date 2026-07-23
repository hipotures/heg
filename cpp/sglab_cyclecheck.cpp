#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

__extension__ using Bits = unsigned __int128;

struct Graph {
    int n = 0;
    std::vector<Bits> rows;
};

struct Search {
    const Graph& graph;
    int target;
    double timeout_seconds;
    std::chrono::steady_clock::time_point started = std::chrono::steady_clock::now();
    std::uint64_t nodes = 0;
    bool timed_out = false;
    std::vector<int> witness;

    Search(const Graph& input_graph, int input_target, double input_timeout)
        : graph(input_graph), target(input_target), timeout_seconds(input_timeout) {}

    bool expired() {
        if (timeout_seconds <= 0.0) {
            return false;
        }
        if ((++nodes & 1023U) != 0) {
            return false;
        }
        const auto elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - started).count();
        timed_out = elapsed >= timeout_seconds;
        return timed_out;
    }

    bool dfs(int start, int last, Bits visited, std::vector<int>& path) {
        if (expired()) {
            return false;
        }
        if (static_cast<int>(path.size()) == target) {
            if ((graph.rows[last] & (Bits{1} << start)) != 0) {
                witness = path;
                return true;
            }
            return false;
        }
        Bits available = graph.rows[last] & ~visited;
        const Bits minimum_mask =
            start >= 127 ? ~Bits{0} : (Bits{1} << (start + 1)) - 1;
        available &= ~minimum_mask;
        while (available != 0) {
            const Bits bit = available & (~available + 1);
            int vertex = 0;
            Bits shifted = bit;
            while ((shifted >>= 1) != 0) {
                ++vertex;
            }
            path.push_back(vertex);
            if (dfs(start, vertex, visited | bit, path)) {
                return true;
            }
            path.pop_back();
            if (timed_out) {
                return false;
            }
            available ^= bit;
        }
        return false;
    }

    bool run() {
        if (target < 3 || target > graph.n) {
            return false;
        }
        for (int start = 0; start < graph.n; ++start) {
            std::vector<int> path{start};
            if (dfs(start, start, Bits{1} << start, path)) {
                return true;
            }
            if (timed_out) {
                return false;
            }
        }
        return false;
    }
};

Graph parse_graph6(std::string raw) {
    while (!raw.empty() && (raw.back() == '\n' || raw.back() == '\r')) {
        raw.pop_back();
    }
    constexpr const char* header = ">>graph6<<";
    if (raw.rfind(header, 0) == 0) {
        raw.erase(0, 10);
    }
    if (raw.empty()) {
        throw std::runtime_error("empty graph6 input");
    }
    std::size_t offset = 0;
    int n = 0;
    const auto value = [&raw](std::size_t position) -> int {
        if (position >= raw.size() || raw[position] < 63 || raw[position] > 126) {
            throw std::runtime_error("invalid graph6 byte");
        }
        return static_cast<unsigned char>(raw[position]) - 63;
    };
    if (raw[0] != '~') {
        n = value(0);
        offset = 1;
    } else if (raw.size() >= 4 && raw[1] != '~') {
        n = (value(1) << 12) | (value(2) << 6) | value(3);
        offset = 4;
    } else {
        throw std::runtime_error("large graph6 order encoding is unsupported");
    }
    if (n < 0 || n > 128) {
        throw std::runtime_error("cycle checker supports at most 128 vertices");
    }
    const std::size_t required = static_cast<std::size_t>(n) * (n - 1) / 2;
    const std::size_t required_bytes = (required + 5) / 6;
    if (raw.size() - offset < required_bytes) {
        throw std::runtime_error("truncated graph6 input");
    }
    if (raw.size() - offset > required_bytes) {
        throw std::runtime_error("graph6 input contains trailing data");
    }
    if (required % 6 != 0 && required_bytes != 0) {
        const int unused_mask = (1 << (6 - required % 6)) - 1;
        if ((value(raw.size() - 1) & unused_mask) != 0) {
            throw std::runtime_error("graph6 padding bits must be zero");
        }
    }
    Graph graph{n, std::vector<Bits>(n, 0)};
    std::size_t position = 0;
    for (int v = 1; v < n; ++v) {
        for (int u = 0; u < v; ++u, ++position) {
            const int byte = value(offset + position / 6);
            if ((byte & (1 << (5 - position % 6))) != 0) {
                graph.rows[u] |= Bits{1} << v;
                graph.rows[v] |= Bits{1} << u;
            }
        }
    }
    return graph;
}

void print_witness(const std::vector<int>& witness) {
    std::cout << '[';
    for (std::size_t i = 0; i < witness.size(); ++i) {
        if (i != 0) {
            std::cout << ',';
        }
        std::cout << witness[i];
    }
    std::cout << ']';
}

}  // namespace

int main(int argc, char** argv) {
    try {
        std::string graph_path;
        std::vector<int> lengths;
        double timeout_seconds = 0.0;
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            if (argument == "--version") {
                std::cout << "sglab-cyclecheck 1\n";
                return 0;
            }
            if (argument == "--graph6" && i + 1 < argc) {
                graph_path = argv[++i];
            } else if (argument == "--length" && i + 1 < argc) {
                lengths.push_back(std::stoi(argv[++i]));
            } else if (argument == "--timeout-seconds" && i + 1 < argc) {
                timeout_seconds = std::stod(argv[++i]);
            } else {
                throw std::runtime_error("invalid arguments");
            }
        }
        if (graph_path.empty() || lengths.empty()) {
            throw std::runtime_error("--graph6 and at least one --length are required");
        }
        if (!std::isfinite(timeout_seconds) || timeout_seconds < 0.0) {
            throw std::runtime_error("--timeout-seconds must be finite and nonnegative");
        }
        for (const int length : lengths) {
            if (length < 3 || length > 128) {
                throw std::runtime_error("--length must be between 3 and 128");
            }
        }
        std::ifstream input(graph_path);
        std::string encoded;
        std::getline(input, encoded);
        if (!input && encoded.empty()) {
            throw std::runtime_error("could not read graph6 file");
        }
        const Graph graph = parse_graph6(encoded);
        for (const int length : lengths) {
            Search search(graph, length, timeout_seconds);
            if (search.run()) {
                std::cout << "{\"status\":\"FOUND\",\"complete\":true,\"length\":"
                          << length << ",\"witness\":";
                print_witness(search.witness);
                std::cout << "}\n";
                return 0;
            }
            if (search.timed_out) {
                std::cout << "{\"status\":\"TIMEOUT\",\"complete\":false,\"length\":"
                          << length << "}\n";
                return 2;
            }
        }
        std::cout << "{\"status\":\"ABSENT\",\"complete\":true,\"lengths\":[";
        for (std::size_t i = 0; i < lengths.size(); ++i) {
            if (i != 0) {
                std::cout << ',';
            }
            std::cout << lengths[i];
        }
        std::cout << "]}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cout << "{\"status\":\"ERROR\",\"complete\":false,\"message\":\"";
        for (const char character : std::string(error.what())) {
            if (character == '"' || character == '\\') {
                std::cout << '\\';
            }
            std::cout << character;
        }
        std::cout << "\"}\n";
        return 1;
    }
}

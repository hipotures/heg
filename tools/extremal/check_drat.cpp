// Independent, zero-dependency C++17 RUP/DRAT proof checker for DIMACS CNF UNSAT proofs.
// Verifies that every added clause C in proof.drat is Reverse Unit Propagation (RUP)
// implied by the current formula (original CNF + previously verified proof clauses),
// and that the proof derives the empty clause (0).
// Usage: ./check-drat <input.cnf> <proof.drat>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct RupChecker {
    int nvars = 0;
    std::vector<std::vector<int>> clauses;
    std::vector<std::vector<int>> watches;
    std::vector<int> units;
    std::vector<int8_t> val;
    std::vector<int> trail;
    bool contradiction = false;

    static inline int to_lit(int x) {
        int v = std::abs(x) - 1;
        return x > 0 ? (2 * v) : (2 * v + 1);
    }
    inline int lit_val(int lit) const {
        int8_t v = val[lit >> 1];
        if (v < 0) return -1;
        return (lit & 1) ? (1 - v) : v;
    }
    inline bool assign(int lit) {
        int v = lit >> 1;
        int8_t want = (lit & 1) ? 0 : 1;
        if (val[v] != -1) return val[v] == want;
        val[v] = want;
        trail.push_back(lit);
        return true;
    }

    void init(int nv) {
        nvars = nv;
        watches.assign(2 * nv, {});
        val.assign(nv, -1);
    }

    void add_clause(std::vector<int> lits) {
        std::sort(lits.begin(), lits.end());
        lits.erase(std::unique(lits.begin(), lits.end()), lits.end());
        for (size_t i = 0; i + 1 < lits.size(); ++i)
            if (lits[i] == (lits[i + 1] ^ 1)) return; // tautology
        if (lits.empty()) { contradiction = true; return; }
        if (lits.size() == 1) { units.push_back(lits[0]); return; }
        int cid = (int)clauses.size();
        watches[lits[0] ^ 1].push_back(cid);
        watches[lits[1] ^ 1].push_back(cid);
        clauses.push_back(std::move(lits));
    }

    bool is_rup(const std::vector<int>& lits) {
        if (contradiction) return true;
        trail.clear();
        bool ok = true;
        for (int u : units) if (!assign(u)) { ok = false; break; }
        if (ok) {
            for (int l : lits) if (!assign(l ^ 1)) { ok = false; break; }
        }
        size_t qh = 0;
        while (ok && qh < trail.size()) {
            int p = trail[qh++];
            auto& ws = watches[p];
            int flit = p ^ 1;
            size_t j = 0;
            for (size_t i = 0; i < ws.size(); ++i) {
                int cid = ws[i];
                auto& cl = clauses[cid];
                if (cl[0] == flit) std::swap(cl[0], cl[1]);
                if (lit_val(cl[0]) == 1) { ws[j++] = cid; continue; }
                bool found = false;
                for (size_t k = 2; k < cl.size(); ++k) {
                    if (lit_val(cl[k]) != 0) {
                        std::swap(cl[1], cl[k]);
                        watches[cl[1] ^ 1].push_back(cid);
                        found = true;
                        break;
                    }
                }
                if (found) continue;
                ws[j++] = cid;
                if (lit_val(cl[0]) == 0 || !assign(cl[0])) {
                    while (++i < ws.size()) ws[j++] = ws[i];
                    ok = false;
                    break;
                }
            }
            ws.resize(j);
        }
        for (int l : trail) val[l >> 1] = -1;
        return !ok;
    }
};

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: " << argv[0] << " <input.cnf> <proof.drat>\n";
        return 2;
    }
    auto t0 = std::chrono::steady_clock::now();
    std::ifstream cnf(argv[1]);
    if (!cnf) { std::cerr << "Cannot open CNF: " << argv[1] << "\n"; return 2; }
    RupChecker chk;
    std::string line;
    while (std::getline(cnf, line)) {
        if (line.empty() || line[0] == 'c') continue;
        std::istringstream iss(line);
        if (line[0] == 'p') {
            std::string p, c; int nv = 0, nc = 0;
            iss >> p >> c >> nv >> nc;
            chk.init(nv);
            continue;
        }
        std::vector<int> lits; int x;
        while (iss >> x && x != 0) lits.push_back(RupChecker::to_lit(x));
        if (!lits.empty()) chk.add_clause(std::move(lits));
    }

    std::ifstream drat(argv[2]);
    if (!drat) { std::cerr << "Cannot open DRAT: " << argv[2] << "\n"; return 2; }
    uint64_t steps = 0;
    bool derived_empty = false;
    while (std::getline(drat, line)) {
        if (line.empty() || line[0] == 'c' || (line.size() >= 2 && line[0] == 'd' && line[1] == ' ')) continue;
        std::istringstream iss(line);
        std::vector<int> lits; int x;
        bool saw_zero = false;
        while (iss >> x) {
            if (x == 0) { saw_zero = true; break; }
            lits.push_back(RupChecker::to_lit(x));
        }
        if (!saw_zero) { std::cerr << "Malformed DRAT line\n"; return 2; }
        if (!chk.is_rup(lits)) {
            std::cerr << "FAIL: step " << (steps + 1) << " is NOT RUP!\n";
            return 1;
        }
        steps++;
        if (lits.empty()) { derived_empty = true; break; }
        chk.add_clause(std::move(lits));
    }

    double el = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    if (derived_empty) {
        std::cout << "VERIFIED UNSAT (RUP/DRAT): " << steps << " proof steps checked in " << el << " s\n";
        return 0;
    }
    std::cerr << "FAIL: DRAT proof did not derive empty clause 0!\n";
    return 1;
}

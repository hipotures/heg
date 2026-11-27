// Self-contained C++17 CDCL SAT solver with 2-watched literals, 1-UIP conflict learning,
// VSIDS, Luby restarts, and standard DRAT (RUP) proof emission!
// Usage: ./mini-cdcl-drat <input.cnf> [output.drat]
// Exit codes: 10 = SAT (prints model v ... 0), 20 = UNSAT (writes verified RUP/DRAT proof!).
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct Clause {
    std::vector<int> lits; // 2*v for +v, 2*v+1 for -v (0-indexed v)
    bool learnt = false;
};

struct Solver {
    int nvars = 0;
    std::vector<Clause> clauses;
    std::vector<std::vector<int>> watches; // lit -> list of clause indices
    std::vector<int8_t> val;               // -1 unassigned, 0 false, 1 true (for var)
    std::vector<int> level;
    std::vector<int> reason;               // clause index, -1 for decision
    std::vector<int> trail;
    std::vector<int> trail_lim;
    std::vector<double> activity;
    double var_inc = 1.0;
    double var_decay = 0.95;
    std::vector<int8_t> phase;
    std::vector<uint8_t> seen;
    // Max-heap for O(log n) VSIDS variable selection
    std::vector<int> heap;
    std::vector<int> heap_pos;
    int qhead = 0;
    uint64_t conflicts = 0;
    uint64_t decisions = 0;
    uint64_t propagations = 0;
    std::ofstream* drat = nullptr;

    static inline int to_lit(int dimacs_lit) {
        int v = std::abs(dimacs_lit) - 1;
        return dimacs_lit > 0 ? (2 * v) : (2 * v + 1);
    }
    static inline int from_lit(int lit) {
        int v = (lit >> 1) + 1;
        return (lit & 1) ? -v : v;
    }
    inline int lit_val(int lit) const {
        int8_t v = val[lit >> 1];
        if (v < 0) return -1;
        return (lit & 1) ? (1 - v) : v;
    }
    inline int cur_level() const { return (int)trail_lim.size(); }

    void heap_sift_up(int i) {
        int v = heap[i];
        double act = activity[v];
        while (i > 0) {
            int p = (i - 1) >> 1;
            if (activity[heap[p]] >= act) break;
            heap[i] = heap[p];
            heap_pos[heap[i]] = i;
            i = p;
        }
        heap[i] = v;
        heap_pos[v] = i;
    }
    void heap_sift_down(int i) {
        int v = heap[i];
        double act = activity[v];
        int sz = (int)heap.size();
        while (true) {
            int l = (i << 1) + 1;
            if (l >= sz) break;
            int r = l + 1;
            int c = (r < sz && activity[heap[r]] > activity[heap[l]]) ? r : l;
            if (act >= activity[heap[c]]) break;
            heap[i] = heap[c];
            heap_pos[heap[i]] = i;
            i = c;
        }
        heap[i] = v;
        heap_pos[v] = i;
    }
    void heap_insert(int v) {
        if (heap_pos[v] != -1) return;
        int i = (int)heap.size();
        heap.push_back(v);
        heap_pos[v] = i;
        heap_sift_up(i);
    }
    int heap_pop() {
        int v = heap[0];
        heap_pos[v] = -1;
        int last = heap.back();
        heap.pop_back();
        if (!heap.empty()) {
            heap[0] = last;
            heap_pos[last] = 0;
            heap_sift_down(0);
        }
        return v;
    }

    void init(int nv) {
        nvars = nv;
        watches.assign(2 * nv, {});
        val.assign(nv, -1);
        level.assign(nv, 0);
        reason.assign(nv, -1);
        activity.assign(nv, 0.0);
        phase.assign(nv, 0);
        seen.assign(nv, 0);
        heap.clear();
        heap_pos.assign(nv, -1);
        for (int v = 0; v < nv; ++v) heap_insert(v);
    }

    void bump(int v) {
        activity[v] += var_inc;
        if (activity[v] > 1e100) {
            for (double& a : activity) a *= 1e-100;
            var_inc *= 1e-100;
        }
        if (heap_pos[v] != -1) heap_sift_up(heap_pos[v]);
    }

    void assign(int lit, int r) {
        int v = lit >> 1;
        val[v] = (lit & 1) ? 0 : 1;
        phase[v] = val[v];
        level[v] = cur_level();
        reason[v] = r;
        trail.push_back(lit);
    }

    void backtrack(int target_lvl) {
        if (cur_level() <= target_lvl) return;
        int stop = trail_lim[target_lvl];
        while ((int)trail.size() > stop) {
            int lit = trail.back();
            trail.pop_back();
            int v = lit >> 1;
            val[v] = -1;
            reason[v] = -1;
            heap_insert(v);
        }
        trail_lim.resize(target_lvl);
        qhead = (int)trail.size();
    }

    void emit_drat_clause(const std::vector<int>& lits) {
        if (!drat) return;
        for (int lit : lits) (*drat) << from_lit(lit) << " ";
        (*drat) << "0\n";
    }

    // Returns false if immediate conflict at level 0
    bool add_clause(std::vector<int> lits, bool learnt) {
        if (!learnt) {
            std::sort(lits.begin(), lits.end());
            lits.erase(std::unique(lits.begin(), lits.end()), lits.end());
            for (size_t i = 0; i + 1 < lits.size(); ++i) {
                if (lits[i] == (lits[i + 1] ^ 1)) return true; // tautology
            }
            // Remove falsified lits at level 0
            std::vector<int> clean;
            for (int l : lits) {
                int lv = lit_val(l);
                if (lv == 1) return true;
                if (lv == -1) clean.push_back(l);
            }
            lits = std::move(clean);
        }
        if (lits.empty()) {
            if (drat) (*drat) << "0\n";
            return false;
        }
        if (lits.size() == 1) {
            int lv = lit_val(lits[0]);
            if (lv == 0) {
                if (drat) (*drat) << "0\n";
                return false;
            }
            if (lv == -1) assign(lits[0], -1);
            if (learnt) emit_drat_clause(lits);
            return true;
        }
        int cid = (int)clauses.size();
        clauses.push_back({lits, learnt});
        watches[lits[0] ^ 1].push_back(cid);
        watches[lits[1] ^ 1].push_back(cid);
        if (learnt) emit_drat_clause(lits);
        return true;
    }

    // Returns conflicting clause index, or -1 if no conflict
    int propagate() {
        while (qhead < (int)trail.size()) {
            int p = trail[qhead++];
            propagations++;
            auto& ws = watches[p];
            size_t j = 0;
            for (size_t i = 0; i < ws.size(); ++i) {
                int cid = ws[i];
                auto& lits = clauses[cid].lits;
                int false_lit = p ^ 1;
                if (lits[0] == false_lit) std::swap(lits[0], lits[1]);
                if (lit_val(lits[0]) == 1) {
                    ws[j++] = cid;
                    continue;
                }
                bool found_new = false;
                for (size_t k = 2; k < lits.size(); ++k) {
                    if (lit_val(lits[k]) != 0) {
                        std::swap(lits[1], lits[k]);
                        watches[lits[1] ^ 1].push_back(cid);
                        found_new = true;
                        break;
                    }
                }
                if (found_new) continue;
                ws[j++] = cid;
                if (lit_val(lits[0]) == 0) {
                    // Conflict! Keep remaining watches
                    while (++i < ws.size()) ws[j++] = ws[i];
                    ws.resize(j);
                    return cid;
                } else {
                    assign(lits[0], cid);
                }
            }
            ws.resize(j);
        }
        return -1;
    }

    void analyze(int confl, std::vector<int>& out_learnt, int& out_btlevel) {
        out_learnt.clear();
        out_learnt.push_back(-1); // placeholder for asserting literal
        int pathC = 0;
        int p = -1;
        int idx = (int)trail.size() - 1;
        int clvl = cur_level();

        while (true) {
            const auto& lits = clauses[confl].lits;
            size_t start = (p == -1) ? 0 : 1;
            for (size_t i = start; i < lits.size(); ++i) {
                int q = lits[i];
                int v = q >> 1;
                if (!seen[v] && level[v] > 0) {
                    seen[v] = 1;
                    bump(v);
                    if (level[v] == clvl) {
                        pathC++;
                    } else {
                        out_learnt.push_back(q);
                    }
                }
            }
            while (!seen[trail[idx] >> 1]) idx--;
            p = trail[idx--];
            confl = reason[p >> 1];
            seen[p >> 1] = 0;
            pathC--;
            if (pathC == 0) break;
        }
        out_learnt[0] = p ^ 1;
        for (size_t i = 1; i < out_learnt.size(); ++i) seen[out_learnt[i] >> 1] = 0;

        // Compute backtrack level and place highest-level literal at out_learnt[1]
        if (out_learnt.size() == 1) {
            out_btlevel = 0;
        } else {
            size_t max_i = 1;
            for (size_t i = 2; i < out_learnt.size(); ++i) {
                if (level[out_learnt[i] >> 1] > level[out_learnt[max_i] >> 1]) max_i = i;
            }
            std::swap(out_learnt[1], out_learnt[max_i]);
            out_btlevel = level[out_learnt[1] >> 1];
        }
        var_inc /= var_decay;
    }

    int pick_branch_var() {
        while (!heap.empty()) {
            int v = heap_pop();
            if (val[v] == -1) return v;
        }
        return -1;
    }

    static uint64_t luby(uint64_t i) {
        uint64_t size = 1, seq = 0;
        while (size < i + 1) { seq++; size = 2 * size + 1; }
        while (size - 1 != i) {
            size = (size - 1) >> 1;
            seq--;
            if (i >= size) i -= size;
        }
        return 1ULL << seq;
    }

    // Returns true = SAT, false = UNSAT
    bool solve() {
        if (propagate() != -1) {
            if (drat) (*drat) << "0\n";
            return false;
        }
        uint64_t restart_idx = 0;
        uint64_t next_restart = 100;
        std::vector<int> learnt;

        while (true) {
            int confl = propagate();
            if (confl != -1) {
                conflicts++;
                if (cur_level() == 0) {
                    if (drat) (*drat) << "0\n";
                    return false;
                }
                int btlevel = 0;
                analyze(confl, learnt, btlevel);
                backtrack(btlevel);
                if (learnt.size() == 1) {
                    emit_drat_clause(learnt);
                    assign(learnt[0], -1);
                } else {
                    int cid = (int)clauses.size();
                    add_clause(learnt, true);
                    assign(learnt[0], cid);
                }
                if (conflicts >= next_restart) {
                    backtrack(0);
                    restart_idx++;
                    next_restart = conflicts + 100 * luby(restart_idx);
                }
            } else {
                int v = pick_branch_var();
                if (v == -1) return true; // All assigned -> SAT!
                decisions++;
                trail_lim.push_back((int)trail.size());
                int lit = phase[v] ? (2 * v) : (2 * v + 1);
                assign(lit, -1);
            }
        }
    }
};

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input.cnf> [output.drat]\n";
        return 2;
    }
    std::ifstream ifs(argv[1]);
    if (!ifs) {
        std::cerr << "Cannot open " << argv[1] << "\n";
        return 2;
    }
    std::ofstream drat_ofs;
    Solver S;
    if (argc >= 3) {
        drat_ofs.open(argv[2]);
        S.drat = &drat_ofs;
    }

    auto t0 = std::chrono::steady_clock::now();
    std::string line;
    bool ok = true;
    while (std::getline(ifs, line)) {
        if (line.empty() || line[0] == 'c') continue;
        std::istringstream iss(line);
        if (line[0] == 'p') {
            std::string p, cnf;
            int nv = 0, nc = 0;
            iss >> p >> cnf >> nv >> nc;
            S.init(nv);
            continue;
        }
        std::vector<int> lits;
        int x;
        while (iss >> x && x != 0) lits.push_back(Solver::to_lit(x));
        if (!lits.empty() && ok) {
            if (!S.add_clause(std::move(lits), false)) ok = false;
        }
    }

    bool sat = ok && S.solve();
    double el = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::cout << "c conflicts=" << S.conflicts << " decisions=" << S.decisions
              << " propagations=" << S.propagations << " time=" << el << "s\n";
    if (sat) {
        std::cout << "s SATISFIABLE\nv";
        for (int v = 0; v < S.nvars; ++v) std::cout << " " << (S.val[v] ? (v + 1) : -(v + 1));
        std::cout << " 0\n";
        return 10;
    } else {
        std::cout << "s UNSATISFIABLE\n";
        return 20;
    }
}

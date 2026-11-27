# Critical Review: Waves D1–F, 1h/2h LNS Campaigns and Track 2 (2026-11-26)

> Polish original: [`REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26_pl.md`](REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26_pl.md). This English version is a translation with identical content.

- **Scope**: commits `7eda717` … `7bb5a67` (Wave A+B+C campaign, D1, D2, 1h LNS, E, 2h ILS-LNS, F, Track 2).
- **Nature**: an independent review of correctness, methodology and conclusions. It does not modify any earlier report (per the "reports are evidence" rule).
- **Review limitations**: the machine was running another experiment (load ≈ 16/16), so `make test`, `cargo test`, campaigns and builds were **not** run. Only light single-threaded computations were performed (`nice`, < 15 s CPU in total). Full texts of the cited preprints were not read, only abstracts.
- **Verification scripts**: `docs/reports/assets/review-2026-11-26/` (`g6.py`, `cyc.c`, `h8.py`, `pet.c`).

---

## 1. Verdict at a glance

| Claim | Status after review |
|---|---|
| Certificate `f_cubic(5) ≤ 370` (`n=370`) | **Independently confirmed** (3-regular, 2-connected, no C4/C8/C16/C32) |
| Certificate `f_{δ≥3}(5) ≤ 345` (`n=345`) | **Independently confirmed** |
| Certificate `f_{δ≥3}(4) ≤ 73` (`n=73`) | **Independently confirmed** |
| Gadget `H8*`: path windows and internal cycles | **Confirmed** |
| No solution for `Petersen + 2·H8* + 8·H7` (`n=72`) | **Confirmed** (only within this construction family) |
| "Previous record" `f_cubic(5)=450` (García, arXiv:2609.04686) | Consistent with García's abstract |
| `f_cubic(6) ≤ 30 360` | Reasoning correct, but **conditional** and with a wrong attribution of the reference value (§3.5) |
| H8* "unique", no gadgets at `n=9,11,13`, `H15` "unique" | **Unproven**: from random sampling, not exhaustive search (§3.3) |
| "Pigeonhole floor" `C16 ≥ 4` for `Petersen + 10·H7` (Wave E) | **Proof is wrong**: the true minimum is 2 bad 5-cycles (§3.4) |
| Cubic campaigns `n = 60…76` framed as `f(4) < 78` | **Futile from the start**: Ripatti (2017) showed the cubic minimum is 78 (§3.1) |
| `f_{δ≥3}(4) ≤ 77` (Wave E) | **No artifact in the repo**; the referenced `/tmp/n77.g6` does not exist (result is superseded by 73 anyway) |

Main conclusion: **the graph certificates are correct**. The weaknesses lie in three places:

- literature review and strategy (a large share of compute went to a goal that cannot be reached);
- reproducibility (tools and data live outside the repo);
- report language ("world record", "exhaustive", "unique", "exact floor") that describes heuristic results as if they were proofs.

---

## 2. What was checked and how

1. **Own graph6 parser and structural analysis** (`g6.py`): vertex and edge counts, degree distribution, connectivity, articulation points.
   - `n=370`: `m=555`, `{3:370}`, 0 articulation points ✔
   - `n=345`: `m=525`, `{3:330, 4:15}`, 0 articulation points ✔
   - `n=73`: `m=111`, `{3:70, 4:3}`, 0 articulation points ✔
2. **Independent exact cycle-spectrum counter** (`cyc.c`). Algorithm: canonical start at the minimum vertex and DFS pruned by BFS distance in `G[≥s]`. Written from scratch and different from the MitM used in `verify-large`.
   - Calibration: Petersen gives 5:12, 6:10, 8:15, 9:20. Tutte–Coxeter gives 8:90, 10:72, 12:300. Both match the literature ✔
   - `n=370`: cycles of lengths {3,5,6,7,9…15} and **33, 34, …**. No cycle of length 16–32 at all. The shortest "lifted" cycle has length **33**, so the margin is 1 (40 such cycles).
   - `n=345`: same picture (924 cycles of length 33).
   - `n=73`: {3,5,6,7,17,18,…}. No C4/C8/C16 ✔
3. **`verify-large` run single-threaded** (`--workers 1`): ABSENT for {4,8,16,32} on both f5 graphs (0.40 s and 0.69 s). Agrees with `cyc.c`. The reported 9.5–14.6 ms with 16 threads is plausible.
4. **H8* windows** (`h8.py`): S(0,1)={2..7}, S(0,2)=S(1,2)={3..7}, internal cycles {3,5,6,7} ✔
5. **Exhaustive check of the Petersen family** (`pet.c`): all subsets of H8* positions × 3¹⁰ orientations, in the window-minimum model.

   | r (number of H8*) | n | solutions with no bad 5-cycle | minimum number of bad 5-cycles |
   |---:|---:|---:|---:|
   | 0 | 70 | 0 | **2** |
   | 1 | 71 | 0 | 2 |
   | 2 | 72 | 0 | 1 |
   | 3 | 73 | 4680 | 0 |

   The Track 2 report (`n=72`: 0 solutions; `n=73`: a solution exists) is correct.
6. **Tutte–Coxeter calculus**: `E[excess] = 16(2a−30)/90` and `4(a−10)/15` re-derived by hand. The averaging is exact because TC is arc-transitive, so every pair of edges at a vertex lies on 8 eight-cycles. The derived thresholds `a ≥ 18` (cubic) and `a ≥ 14` (with H8*) are correct **within this family**. The order arithmetic (`240 + 7a`, `15a + 7c`) checks out.

---

## 3. Weak points and errors (most important first)

### 3.1 [CRITICAL, strategy] Cubic campaigns at `n < 78` searched for an object that, per the literature, does not exist

A. V. Ripatti, *Faster approach for exhaustive search over graphs with certain properties* (BAIKAL 2017, abstract): *"computationally show that the smallest cubic graphs without 4,8,16 cycles have 78 vertices"*. The paper also says there are 6 such graphs (Exoo's graph and 5 others). The method is isomorph-free generation in the style of McKay/Brinkmann (`minibaum`).

The repository contains **no mention** of this result (`grep Ripatti|Baikal` → 0). Meanwhile:

- Wave D1, the 1h campaign (`n=60,62,64`, 34.78 B leaves), Wave E (cubic part) and the 2h campaign (`n=76,74,70` cubic, 42.63 B leaves) searched for a cubic {4,8,16}-free graph with `n < 78`. In total the reports claim ~83 B LNS leaves, i.e. several hours of the whole 16-core machine.
- Part of the Wave D2 voltage lifts at `n=72` (cubic) target the same impossible range.
- Conclusions built on this wrong framing:
  - *"f(4) lies near the upper half of the open window [54, 78]"* (1h): for cubic graphs this window is closed. The origin of the lower bound 54 is never justified.
  - *"just 3 sixteen-cycles shy of breaking Exoo's f_cubic(4) ≤ 78"* (Wave E): the C16 count is not a measure of distance to a solution, and the solution itself does not exist.
  - "rock-solid empirical floor `C16 = 23`", "deep confirmation of the `C16 = 3` floor": these are local minima of a heuristic with no evidential value.

Caveat: Ripatti is a conference abstract, and the phrase "probabilistic checking of every node" needs checking to see whether the final verification was exact. Still, the result should have been taken into account **before** launching the campaigns. A positive consequence: `f_{δ≥3}(4) ≤ 73 < 78` means that (if Ripatti is right) **the δ≥3 optimum is strictly smaller than the cubic optimum**. This fact is worth highlighting instead of "C16 records".

**Recommendation**:

- add Ripatti to `docs/00_RESEARCH_STATUS.md`;
- stop and do not resume cubic `n < 78` campaigns for {4,8,16};
- move the budget to δ≥3 (`n ≤ 72`) and to f(5).

### 3.2 [HIGH, reproducibility] Tools and data live outside the repository

All of the following exist only in another agent's working directory, `~/.gemini/antigravity-cli/brain/560c9e05-…/scratch/` (not tracked by git):

- gadget hunters `f5_gadget_hunter.cpp` and `f5_multideg4_gadgets.cpp`;
- window/CSP solver `f5_window_solver.cpp`;
- PAWS/WalkSAT `f5_paws_frontier.cpp`;
- the "independent C++ verifier" `sglab_cyclecheck_large.cpp`;
- certificate-building scripts (`track2_*.py`, `test_h8star_petersen_f4.py`);
- Wave E scripts (`exp11_*.py`);
- raw campaign JSON files (`campaign_1h_lns_60_62_64.json` etc.).

Consequences:

- The Track 2 report calls `sglab-cyclecheck-large` an "Independent Verification Authority", but its code cannot be reviewed from the repo.
- The `f_{δ≥3}(4) ≤ 77` witness (Wave E) has no certificate in `docs/reports/certificates/`, and the report points to `/tmp/n77.g6`, which does not exist.
- This violates the project mission in AGENTS.md (*"reproducible"*, *"raw scientific history is preserved"*). All of this work ran outside the campaign runtime, the Director and SQLite, so there are no durable campaign records.

**Recommendation**: import the sources into `cpp/` or `tools/` (with a test), add the `n=77` certificate and `n=74`/`C16=3` (if they have evidential value), and the raw JSON files (or their hashes and archive location).

### 3.3 [HIGH, correctness of conclusions] "Unique" and "0 found" come from random sampling, not exhaustive search

`f5_gadget_hunter.cpp` and `f5_multideg4_gadgets.cpp` randomly pair "stubs" (configuration model, `std::shuffle` + `mt19937_64`) and count "trials". On that basis the report claims:

- at `n=7` there are "exactly two" gadgets;
- at `n=9,11,13` there exist "**0** {C4,C8,C16}-free gadgets";
- `H15` is a "unique window type";
- in the status ledger: H8* is the "**unique** … 8-vertex 3-port gadget", while the Track 2 report says "**TWO** sporadic types" (inconsistent).

Configuration-model sampling is non-uniform over isomorphism classes, and rare graphs may not appear even in 10⁷ trials. None of these statements is a theorem. Moreover, the non-cubic variant covered only selected degree sequences (degree-2 ports, 1–3 internal degree-4 vertices).

**Recommendation**: exhaustive generation (`nauty geng` with degree bounds or a dedicated generator) for `n ≤ 13` is cheap and would turn these statements into facts. Until then, reports should say "not found in N trials".

### 3.4 [MEDIUM, mathematical error] False "pigeonhole floor" in Wave E

Wave E: *"40/12 = 3.333 > 3, at least 4 five-cycles carry ≥ 4 port-0 incidences … proving C16 ≥ 4 is exact"*.

- A total of 40 with a maximum of 5 per cycle only gives `40 ≤ 3(12−B) + 5B`, i.e. **B ≥ 2**, not B ≥ 4.
- An exhaustive check (`pet.c`, r=0) gives a **minimum of 2 bad 5-cycles**, not 4. The "exact floor C16 ≥ 4" claim therefore has no proof. It may still be true if every bad 5-cycle yields ≥ 2 sixteen-cycles, but that was not shown.
- The 2h campaign repeats this argument ("consistent with the exact `Petersen + 10·H7` pigeonhole floor").

### 3.5 [MEDIUM, attribution] `f_cubic(6) ≤ 30 360`

- The reasoning is correct. A base cycle of length L ≥ 17 contains ≤ ⌊L/5⌋ copies of H7, so the cycle length is ≥ 4L − ⌊L/5⌋ ≥ 65. Internal gadget cycles have length ≤ 15 and are not powers of 2. A maximal packing satisfies |P| ≥ ⌈2048/46⌉ = 45.
- But:
  - **"Previous Published Best 30 720" is not a published value.** García's abstract gives `f(6) ≤ 32 640` (= 15 · 2176). 30 720 is García's theorem combined with `n(3,17) ≤ 2048`.
  - The result `n(3,17) ≤ 2048` comes from Exoo, Goedgebeur et al., arXiv:2511.07247 (November 2025, EJC v33i3p48), not from "July 2026" as the report states.
  - The bound is **conditional** (the 2048-vertex graph is not in the repo), has no artifact and is not "certified".
  - The improvement is 1.2% and easy to deepen: only base cycles of length 17…21 are binding (for L ≥ 22 the condition 4L − h ≥ 65 holds for every h ≤ L). A maximal 4-packing is a very coarse construction, and for δ≥3 H8* could also be used.

### 3.6 [MEDIUM, language and interpretation] Overstated wording

- **"World records" and "-23.3%" for `f_{δ≥3}(5)`.** The comparison is against the cubic bound (450). It is not known whether a separate published bound exists for δ≥3. The literature status was not verified beyond García's abstract (e.g. whether García's gadget library contains non-cubic gadgets).
- **"Exact Phase Boundaries", "mathematically impossible (a ≤ 13)".** True only within one family: TC base, gadgets {H15, H8*, H7} and the window-minimum model. No lower bound on f(5) follows.
- **"`a = 19` (n=362): min_viol = 5", "n=344: min_viol=3"** are WalkSAT/PAWS results, i.e. heuristics. The instance is tiny (30 positions × type × 3 orientations, 162 base cycles), so **SAT/ILP would decide it exactly in seconds**. Leaving `n = 354…362` as "heuristically unresolved" is a missed opportunity for either a further improvement or a full optimality proof within the family.
- **"Triple-certified"**: one of the three verifiers (C++ large) is outside the repo, and M4 (`cpp/sglab_cyclecheck.cpp`) only supports `n ≤ 128`. For `n=345/370` M4 was not involved at all. Invariant 3 is not violated, since these are not counterexamples, but the word "certified" without M4 is inconsistent with the rest of the project.
- **Dates**: the file is named `…_2026_11_27.md`, while the commit is from 2026-11-26 21:33Z.

### 3.7 [MEDIUM, code] `rust/sglab-engine/src/large_verify.rs` (`verify-large`)

The algorithm is **correct**. Canonical start s = min, all paths of length h to t through vertices > s, and pairs with disjoint interiors in bucket t form a bijection with 2h-cycles (h ≥ 2). The lack of pruning does not affect exactness. Remarks:

1. **Dead code and a misleading comment.** BFS distances (`dist`) are computed but `dfs_half` does not use them. The comment claims `dist_gt_s[v] <= h` pruning is applied. Exactness is preserved, but the documentation is false, and the number of enumerated paths is the full one (for C32 on the order of 3·2¹⁵ per start).
2. **Witness checked only by `debug_assert`.** In a release build, a FOUND cycle is not verified edge by edge.
3. **`--lengths` silently drops invalid tokens** (`filter_map(...ok())`). A typo such as `4,8,16,3 2` verifies fewer lengths without an error. An odd length ends in `assert!` (panic) instead of a CLI error. `from_graph6` does not reject surplus bytes.
4. **Tests**: one test on Markström-24 (`n=24`) covers only the first word of the `[u64; 8]` mask. There is no test for `n > 64` (words 1–7), none for a graph with C32 present, and no comparison with a reference DFS for `n ∈ (128, 512]`, which is exactly the range the tool was built for. For both certificates the gap is closed by my independent `cyc.c`, but future regressions would go unnoticed.

### 3.8 [LOW] Wave D2

- **Inconsistent table.** The C32 Björklund sieve was supposed to be called only for `C4=C8=C16=0` candidates, yet rows `k33 × A4` etc. have 0 such candidates and a sieve result of "FOUND" at the same time. Apparently the sieve ran on `C4=C8=0` candidates. Either the description or the table needs fixing.
- The sieve is **Monte Carlo** (false negatives ≤ 5.2·10⁻⁷). It is fine for FOUND, but must not be used to declare ABSENT. It is not currently used that way, but this should be written down as a rule.
- The citations "Burkhart Nov 2026" and "Zhuge n ≤ 68" were not verified. arXiv identifiers should be given.

### 3.9 [LOW, process] Documentation obligations from AGENTS.md

- The new CLI subcommands (`verify-large`, `lns-polish --rrt-slack/--bipartite`, `voltage-search`, `bjorklund-c32`) are described only in `IMPLEMENTATION_STATUS.md`. Reference and architecture documentation is missing, as is an ADR for the new, durable `n ≤ 512` verification path.
- ~5,000 new lines of Rust (D1–F) come with 9 unit tests (`large_verify` 1, `lns` 1, `voltage_bipartite` 2, `cycles` 5).

---

## 4. Decision concerns

1. **"Compute first, literature later" ordering.** Several hours of 16-core campaigns went into a problem settled in 2017. The cheap step, a literature review, should precede every "record hunt" campaign.
2. **Minimizing the C16 count as the objective.** This signal does not translate into feasibility. Exact methods on small structural spaces (gadgets × orientations × base) are more promising, as Track 2 demonstrated in practice: the records fell in milliseconds thanks to CSP, not thanks to tens of billions of LNS leaves.
3. **Heuristics (WalkSAT/PAWS) where an exact solver suffices.** This applies to `n=362`, `n=354`, `n=344`, `n=338` in the TC family. One SAT/ILP run per case would either improve the record or yield an "optimal within the family" theorem.
4. **Choice of base.** Only TC (f5) and Petersen (f4) were considered. Other girth-8/10 bases (Heawood × lift, cage graphs, voltage lifts) and gadget mixes (including a cubic version of H8*, if one exists) were not searched exactly.
5. **Work outside the project runtime.** The results did not pass through campaigns, the Director or SQLite, so they lack the auditable history the project's invariants require.

---

## 5. Recommended next steps (in order)

1. Import the Track 2 and Wave E sources into the repo, plus the missing certificates (`n=77`, optionally `n=74`/`n=76` as "near-miss") and the raw JSON files.
2. Add to `docs/00_RESEARCH_STATUS.md`: Ripatti 2017, García 2609.04686 (f(6) ≤ 32 640) and Exoo et al. 2511.07247 (n(3,17) ≤ 2048). Describe the status of `f_cubic(4) = 78` (computationally).
3. Erratum (as a new file, without rewriting old reports): the Wave E pigeonhole, "unique/0 found" as sampling results, the 30 720 attribution, the H8* "unique" vs "two types" inconsistency, the D2 table inconsistency.
4. `large_verify.rs`:
   - use `dist` for pruning or remove the BFS and fix the comment;
   - verify the witness in release builds;
   - hard error for invalid `--lengths`;
   - tests for `n ∈ {100, 300, 512}` against a reference DFS (e.g. `cyc.c`) and with a graph in which C32 occurs.
5. When the machine is free: exact SAT/ILP for the TC family (`a = 18, 19` cubic; `n = 338…344` for δ≥3) and exhaustive gadget generation for `n ≤ 13` (`geng`).

---

## 6. Reproducing the verification from this review

```bash
D=docs/reports/assets/review-2026-11-26; W=$(mktemp -d); cp $D/* $W; cd $W
python3 g6.py ~/DEV/heg/docs/reports/certificates/*.g6     # degrees, connectivity, articulation points; writes *.el
gcc -O2 -o cyc cyc.c && ./cyc f5_cubic_n370_TC_20H15_10H7.g6.el 34   # ~5 s, 1 thread
python3 h8.py && gcc -O2 -o pet pet.c && ./pet                       # H8* windows, Petersen family r=0..3
```

## External sources (checked at abstract level only)

- A. V. Ripatti, *Faster approach for exhaustive search over graphs with certain properties*, BAIKAL 2017: https://isem.irk.ru/conferences/mopt2017/Abstracts/BAIKAL_2017_paper_138.pdf
- D. Garcia, *Small graphs without power-of-two cycles…*, arXiv:2609.04686: https://arxiv.org/abs/2609.04686
- G. Exoo, *Three graphs and the Erdős–Gyárfás conjecture*, arXiv:1403.5636: https://arxiv.org/abs/1403.5636
- Exoo, Goedgebeur et al., *New small regular graphs of given girth…*, arXiv:2511.07247: https://arxiv.org/abs/2511.07247

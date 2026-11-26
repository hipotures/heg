# Erratum & Methodological Clarifications for Waves D1–F and Track 2 Reports

- **Date**: 2026-11-26
- **In response to**: [REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md](file:///home/user/DEV/heg/docs/reports/REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md)
- **Scope**: Appends factual corrections and methodological clarifications to earlier immutable reports (`M6_WAVE_D2_VOLTAGE_BJORKLUND_2026_11_26.md`, `M6_CAMPAIGN_1H_LNS_F4_60_62_64_2026_11_26.md`, `M6_WAVE_E_U128_LNS_F4_HUNT_2026_11_26.md`, `M6_CAMPAIGN_2H_ILS_LNS_CUBIC_F4_2026_11_26.md`, `M6_GOAL_TRACK2_F5_H8STAR_WORLD_RECORDS_2026_11_27.md`) without modifying historical reports (preserving `AGENTS.md` Invariant 12).

---

## 1. Confirmed Core Certificates (Unchanged)

Independent from-scratch review (`g6.py`, `cyc.c`, `h8.py`, `pet.c`) confirmed all three extremal graph certificates:
- `docs/reports/certificates/f5_cubic_n370_TC_20H15_10H7.g6` (`n = 370, m = 555`, 3-regular, 2-connected, no cycles of length 16..32, shortest lifted cycle = 33);
- `docs/reports/certificates/f5_delta3_n345_TC_15H15_15H8star.g6` (`n = 345, m = 525`, `{3: 330, 4: 15}`, 2-connected, no cycles of length 16..32);
- `docs/reports/certificates/f4_delta3_n73_Petersen_3H8star_7H7.g6` (`n = 73, m = 111`, `{3: 70, 4: 3}`, 2-connected, no `C4, C8, C16`);
- Plus the newly imported Wave E witness `docs/reports/certificates/f4_delta3_n77_G78_contract.g6` (`n = 77, m = 116`, `{3: 76, 4: 1}`, 2-connected, no `C4, C8, C16`).

---

## 2. Specific Corrections

### 2.1 Literature & Cubic `f_cubic(4) < 78` Strategy (Review §3.1)
- A. V. Ripatti (*Faster approach for exhaustive search over graphs with certain properties*, BAIKAL 2017) computationally reported that the smallest **cubic** graphs avoiding `{C4, C8, C16}` have **78 vertices** (Exoo's $G_{78}$ plus 5 others).
- **Correction**: Earlier reports framed our 1h/2h cubic LNS campaigns at `n = 60..76` as hunting `f_cubic(4) < 78` and described heuristic minima (`C16 = 3`, `C16 = 23`) as empirical floors or distance to a solution. Those cubic `n < 78` hunts have been terminated and documented in `docs/00_RESEARCH_STATUS.md`. Conversely, conditional on Ripatti (2017), our independently verified `n = 73` witness (`delta(G) = 3`) demonstrates strict separation: **$f_{\delta \ge 3}(4) \le 73 < 78 = f_{\mathrm{cubic}}(4)$**.

### 2.2 Wave E Pigeonhole Proof for `Petersen + 10·H_7` (Review §3.4)
- **Erroneous claim in Wave E & 2h reports**: Claimed `40/12 = 3.333 > 3` implies at least `4` bad 5-cycles and thus an exact pigeonhole floor `C16 >= 4`.
- **Correction**: Because a single 5-cycle can hold up to `5` port-0 incidences (not at most `4`), `40 <= 3(12 - B) + 5B` yields only **`B >= 2`**, and exhaustive enumeration (`pet.c`, `r = 0`) confirms the true minimum is **2 bad 5-cycles** (not 4). The "exact pigeonhole floor `C16 >= 4`" claim is retracted.

### 2.3 Gadget Sampling vs. Exhaustiveness & `H_8*` Wording (Review §3.3)
- **Erroneous wording in Track 2 & status ledger**: Described `f5_gadget_hunter.cpp` / `f5_multideg4_gadgets.cpp` results as proving "0 gadgets exist" at `n = 9, 11, 13` or that `H_15` / `H_8*` are "unique".
- **Correction**: Both C++ tools performed **randomized configuration-model sampling** (`180.7M` trials), NOT exhaustive isomorph-free enumeration. All such statements should be read strictly as "none found in `N` randomized configuration-model trials". At `n = 8` (1 internal deg-4), **two** distinct port-window types were found (`mins = (2,3,3)` for $H_8^*$ and `mins = (2,2,2)` for its symmetric variant). (Truly exhaustive enumeration for small orders is performed separately in the follow-up Phase R2 report.)

### 2.4 Attribution & Scope of `f_cubic(6) <= 30,360` (Review §3.5)
- **Correction**: García (`arXiv:2609.04686`, Sept 2026) reports `f(6) <= 32,640` (`15 * 2176`). The intermediate value `30,720` (`15 * 2048`) arises from combining García's theorem with Exoo, Goedgebeur et al. (`arXiv:2511.07247`, **Nov 2025**, *EJC* v33i3p48, not "July 2026"). Our analytic bound `f_cubic(6) <= 30,360` is **conditional** on the existence of that 2048-vertex girth-17 cubic graph (no graph6 artifact is included in this repository).

### 2.5 Scope of Bounds, Heuristics vs. Exact Solvers, and M4 Terminology (Review §3.6)
- Comparisons of `f_{delta>=3}(5) <= 345` against `450` compare against the known **cubic** upper bound `450` (a separate published general-$\delta \ge 3$ bound for `f(5)` has not been established in the literature survey).
- Statements like "mathematically impossible (`a <= 13`)" apply **strictly inside the specific family** (`Tutte–Coxeter` base + `{H_15, H_8*, H_7}` + minimum-window model), not to arbitrary graphs.
- Heuristic `min_viol` values (`n = 362: 5`, `n = 344: 3`) are WalkSAT/PAWS upper bounds, not infeasibility proofs.
- Production M4 (`cpp/sglab_cyclecheck.cpp`) supports `n <= 128` (`unsigned __int128`). Graphs of order `n = 345, 370` were independently verified by Rust `verify-large`, `tools/extremal/sglab_cyclecheck_large.cpp`, and the review's `docs/reports/assets/review-2026-11-26/cyc.c` — not by production M4.
- Report file `M6_GOAL_TRACK2_F5_H8STAR_WORLD_RECORDS_2026_11_27.md` was committed on `2026-11-26T21:33Z` despite the `2026_11_27` suffix.

### 2.6 Wave D2 Table Clarification (Review §3.8)
- In `M6_WAVE_D2_VOLTAGE_BJORKLUND_2026_11_26.md`, the Björklund `C32` narrow sieve (`FOUND` column) was invoked on best **`C4 = C8 = 0`** voltage-lift candidates (not strictly `C4 = C8 = C16 = 0` candidates). As a one-sided Monte Carlo sieve (zero false positives, false-negative error $\le 5.2 \times 10^{-7}$), it is valid for `FOUND` witnesses only and must never be used alone to certify `ABSENT`.

### 2.7 Code & Reproducibility Hardening Completed (Review §3.2, §3.7)
- `rust/sglab-engine/src/large_verify.rs` and `main.rs` hardened: removed unused `dist`/`queue` dead code and fixed doc comment; enforced runtime witness verification in release builds; rejected malformed/odd `--lengths` tokens and trailing `graph6` bytes with exit code `2`; added multi-word `[u64; 8]` unit tests covering `n = 24, 300, 512` (exercising word 7 / bit 511) with independent DFS cross-checks.
- Imported Track 2 reproducible C++/Python sources into `tools/extremal/` and added missing `docs/reports/certificates/f4_delta3_n77_G78_contract.g6`.

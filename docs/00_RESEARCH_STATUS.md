# Research Status and Target Selection

**Status check date:** 2026-11-26 (updated from 2026-07-23)

## 1. Clarification

"Structural graph problems" is a broad class, not one conjecture. It cannot itself be "solved." A research implementation needs a specific mathematical statement, object class, and exact verifier.

This bundle chooses the **Erdős–Gyárfás conjecture** as the first target and retains a generic plugin interface for later targets.

## 2. Why recently discussed alternatives are excluded

### Cycle Double Cover Conjecture

Do not use this as the initial open target. OpenAI released a claimed proof in July 2026, together with the full prompt. Independent expert expositions appeared on arXiv days later. Even if community review continues, this is no longer a sensible fresh counterexample-search target.

### Brandt regular-supergraph problem

A public claim posted on 2026-07-23 reports a 9-vertex counterexample with an exact Farkas infeasibility certificate. At the time of this status check, the claim is primarily circulating through social media and a LinkedIn summary rather than a peer-reviewed paper. Treat it as an active claimed refutation and exclude it from the target queue unless the exact original statement and witness are independently audited.

### Graffiti conjectures 39, 40, and 154

Recent social-media claims report proofs or refutations. They should be placed in a reproduction benchmark queue, not in the fresh-target queue.

## 3. Selected pilot: Erdős–Gyárfás conjecture

Statement:

> Every finite simple graph with minimum degree at least 3 contains a simple cycle whose length is a power of two.

A counterexample is a finite simple graph `G` such that:

- `delta(G) >= 3`, and
- `G` contains no cycle of length `4, 8, 16, 32, ...` up to `|V(G)|`.

### Current status (updated 2026-11-26)

As of late November 2026, the Erdős–Gyárfás conjecture remains **open**, with substantially sharper computational lower bounds and extremal upper bounds:

- **General $\delta(G) \ge 3$ exhaustive lower bound**: `n <= 40` (Ducoffe & Dumitru, Sept 2026, `arXiv:2609.28594`, SAT Modulo Symmetries; previously `n <= 31` by Balaji 2026). Even minimal counterexamples must be strictly 2-connected; odd minimal counterexamples are either 2-connected or symmetric equal-order, equal-edge 1-clique-sums of two 2-degenerate blocks sharing a degree-4 cut-vertex (Theorem 2.3 / Corollary 2.4 / Conjecture 4.1).
- **Cubic (3-regular) exhaustive lower bound**: `n <= 48` (Ducoffe & Dumitru, `arXiv:2609.28594`).
- **Bipartite exhaustive lower bounds**: `n <= 66` for general bipartite $\delta \ge 3$ (`arXiv:2609.28594`); `n <= 58` for cubic bipartite (Tranquilli, Aug 2026, `arXiv:2608.02675`); Zenodo artifact extending cubic bipartite to `n <= 68` (Zhuge, `zenodo.21981786`, unrefereed). Girth-10 cubic bipartite cages first appear at `n = 70`.
- **Structural / algebraic subclasses closed (2023–2026)**: large average degree (Liu–Montgomery, *JAMS* 2023), $P_{13}$-free graphs (Hegde–Sandeep–Shashank 2024/2025), diameter 2 (Carr, `arXiv:2508.19302`), 3-connected cubic planar/projective with large edge-width (Culus 2026), Cayley graphs of odd-order and finite nilpotent groups (Burkhart, Nov 2026, `arXiv:2611.05060`).
- **Extremal avoidance function $f(k)$ (smallest graph avoiding $\{C_4, C_8, \dots, C_{2^k}\}$)**:
  - $f(2) = 10$ (Petersen), $f(3) = 24$ (Markström 2004 / García `arXiv:2609.04686`).
  - **$f_{\mathrm{cubic}}(4) = 78$ (computationally)**: A. V. Ripatti (*Faster approach for exhaustive search over graphs with certain properties*, BAIKAL 2017) computationally reported that the smallest **cubic** graphs avoiding $\{C_4, C_8, C_{16}\}$ have **78 vertices** (Exoo's $G_{78}$ plus 5 others; note the conference abstract mentions probabilistic node checking, so independent verification of full exhaustiveness remains useful, **but heuristic cubic searches for $\{4, 8, 16\}$-free graphs at `n < 78` must NOT be run as `f_cubic(4)` record hunts**).
  - **$f_{\delta \ge 3}(4) \le 73$** (this project, `docs/reports/certificates/f4_delta3_n73_Petersen_3H8star_7H7.g6`, independently verified): strictly smaller than the cubic minimum `78`, proving separation between $f_{\delta \ge 3}(4)$ and $f_{\mathrm{cubic}}(4)$ (conditional on Ripatti 2017).
  - **$f_{\mathrm{cubic}}(5)$**: Exoo (2014, `arXiv:1403.5636`) / repaired by García (Sept 2026, `arXiv:2609.04686`) gave `<= 450`. This project established and independently verified **`f_cubic(5) <= 370`** (`Tutte–Coxeter + 20·H_15 + 10·H_7`) and **`f_{delta>=3}(5) <= 345`** (`Tutte–Coxeter + 15·H_15 + 15·H_8*`).
  - **$f_{\mathrm{cubic}}(6)$**: García (`arXiv:2609.04686`) states `<= 32,640` (`15 * 2176`); combining García's theorem with Exoo–Goedgebeur et al. (`arXiv:2511.07247`, Nov 2025, `n(3, 17) <= 2048`) gives `<= 30,720`, and our maximal 4-packing $H_7$ refinement yields the conditional analytic bound `<= 30,360`.

### Consequence for this project

- **Do NOT spend compute searching for cubic $\{C_4, C_8, C_{16}\}$-free graphs at `n < 78`** (closed computationally by Ripatti 2017).
- **High-value open targets**:
  1. General $\delta(G) \ge 3$ $\{C_4, C_8, C_{16}\}$-free graphs at **`n <= 72`** (strictly below our `n = 73` witness);
  2. Exact optimality / further reductions for **$f_{\mathrm{cubic}}(5)$ (`< 370`)** and **$f_{\delta \ge 3}(5)$ (`< 345`)** using exact CSP/SAT and non-Tutte–Coxeter girth-7/8 bases;
  3. **Bipartite cubic `n >= 70`** EGC frontier (including cubic bipartite $\{4,8,16\}$-free at `n >= 78`, non-nilpotent voltage lifts, and girth-10 cages);
  4. **Ducoffe–Dumitru Conjecture 4.1 (`single_block_41`, `k in [21, 31]`, odd `n in [41, 61]`)** where `C32 = C64 = 0` holds automatically by Theorem 4.2.
- Any exhaustive claim requires a deterministic proof artifact and independent verification; any heuristic failure is only `NO_RESULT_WITHIN_BUDGET`.

## 4. Why this is a suitable engineering target

Advantages:

- the counterexample is a finite graph;
- graph mutations are simple;
- minimum degree can be preserved structurally;
- a candidate is independently checkable;
- recent theory gives constraints for the generator;
- cubic graphs admit degree-preserving edge swaps;
- SAT and isomorph-free graph generation are natural secondary methods.

Difficulties:

- exact detection of long cycles is expensive;
- the score landscape becomes sparse near zero forbidden cycles;
- avoiding `C4`, `C8`, and `C16` does not suffice at `n >= 32` because `C32` becomes relevant;
- exhaustive nonexistence is much harder than validating a found graph;
- the current public frontier makes naive small-order search scientifically redundant.

## 5. Secondary target queue

These are not implemented in v1, but the plugin interface should accommodate them:

1. Goddyn's conjecture on removable cycles in cycle permutation graphs, reported open in a 2026 revision.
2. Barnette's conjecture, still a major open Hamiltonicity problem but likely too hard for a first discovery target.
3. Lovász-type Hamiltonicity questions for vertex-transitive graphs, still open in general and requiring specialized generators.
4. Directed-graph structural conjectures such as Seymour's second-neighborhood conjecture, after a separate directed-graph model is added.
5. Newly published "every graph in class C has structure X" conjectures from current preprints, after status verification and statement audit.

## 6. Status-check protocol before every public claim

Before announcing a result:

1. Search the exact conjecture name and equivalent formulations.
2. Check arXiv recent submissions and revisions.
3. Check the original problem list or survey.
4. Search public code repositories for the exact witness size and class.
5. Search current social-media claims, but do not treat them as authoritative without artifacts.
6. Contact or notify the conjecture author when feasible.
7. Record the check timestamp and sources in the result artifact.

## 7. Sources

- A. V. Ripatti, *Faster approach for exhaustive search over graphs with certain properties*, BAIKAL 2017. https://isem.irk.ru/conferences/mopt2017/Abstracts/BAIKAL_2017_paper_138.pdf
- G. Exoo, *Three graphs and the Erdős–Gyárfás conjecture*, arXiv:1403.5636, 2014. https://arxiv.org/abs/1403.5636
- G. Exoo, J. Goedgebeur, J. Jooken, T. Stubbe, T. Van den Eede, *New small regular graphs of given girth*, arXiv:2511.07247, Nov 2025. https://arxiv.org/abs/2511.07247
- D. García, *Small graphs without power-of-two cycles: a lower bound of 24, a correction to a construction of Exoo, and explicit bounds for $f(k)$*, arXiv:2609.04686, Sept 2026. https://arxiv.org/abs/2609.04686
- G. Ducoffe, A. Dumitru, *Towards a more structured search for Erdős–Gyárfás counterexamples*, arXiv:2609.28594, Sept 2026. https://arxiv.org/abs/2609.28594
- L. Tranquilli, *A 60-Vertex Lower Bound for Cubic Bipartite Counterexamples to the Erdős–Gyárfás Conjecture*, arXiv:2608.02675, Aug 2026. https://arxiv.org/abs/2608.02675
- Z. Zhuge, *Reproducibility Artifact for a 70-Vertex Lower Bound for Cubic Bipartite Counterexamples*, Zenodo, Aug 2026. https://zenodo.org/records/21981786
- C. Burkhart, *Odd-ordered Cayley graphs satisfy Erdős–Gyárfás*, arXiv:2611.05060, Nov 2026. https://arxiv.org/abs/2611.05060
- Avery Carr, *Every Minimal Counterexample to the Erdős–Gyárfás Conjecture is Predominantly Cubic*, arXiv:2605.22844, 2026. https://arxiv.org/abs/2605.22844
- Hegde, Sandeep, Shashank, *Erdős–Gyárfás conjecture on graphs without long induced paths*, arXiv:2410.22842. https://arxiv.org/abs/2410.22842
- Public SAT repository claiming verification through 31 vertices: https://github.com/ArjunBalaji79/erdos-gyarfas-min-degree-3
- OpenAI, *A Proof of the Cycle Double Cover Conjecture*. https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_proof.pdf
- OpenAI, full prompt for the Cycle Double Cover proof. https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf
- Sang-il Oum, exposition, arXiv:2607.16356. https://arxiv.org/abs/2607.16356
- Recent public Brandt claim summary: https://www.linkedin.com/posts/imjaredz_you-might-have-seen-that-chatgpt-just-cracked-activity-7485855388882391040-9pB1

# Research Status and Target Selection

**Status check date:** 2026-07-23

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

### Current status

A May 2026 preprint explicitly treats the conjecture as open and proves structural restrictions on a minimal counterexample:

- vertices of degree at least 4 form an independent set;
- a minimal counterexample has degree-3 vertices;
- every vertex is adjacent to a degree-3 vertex;
- at least `4/7` of the vertices have degree exactly 3;
- every regular minimal counterexample is cubic.

A recent public GitHub repository claims a SAT-based exhaustive verification through 31 vertices. It reports SAT Modulo Symmetries as the main path and an independent CEGAR-SAT cross-check through 19 vertices. This result should be treated as a strong active computational claim, but it is not a substitute for independent reproduction.

### Consequence for this project

- `n <= 19`: independent local reproduction gate;
- `20 <= n <= 31`: optional reproduction frontier, not novelty;
- `n >= 32`: heuristic research frontier;
- any exhaustive claim requires a proof artifact and independent verification;
- any heuristic failure is only `NO_RESULT_WITHIN_BUDGET`.

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

- Avery Carr, *Every Minimal Counterexample to the Erdős–Gyárfás Conjecture is Predominantly Cubic*, arXiv:2605.22844, 2026. https://arxiv.org/abs/2605.22844
- Hegde, Sandeep, Shashank, *Erdős–Gyárfás conjecture on graphs without long induced paths*, arXiv:2410.22842. https://arxiv.org/abs/2410.22842
- Public SAT repository claiming verification through 31 vertices: https://github.com/ArjunBalaji79/erdos-gyarfas-min-degree-3
- OpenAI, *A Proof of the Cycle Double Cover Conjecture*. https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_proof.pdf
- OpenAI, full prompt for the Cycle Double Cover proof. https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf
- Sang-il Oum, exposition, arXiv:2607.16356. https://arxiv.org/abs/2607.16356
- Recent public Brandt claim summary: https://www.linkedin.com/posts/imjaredz_you-might-have-seen-that-chatgpt-just-cracked-activity-7485855388882391040-9pB1

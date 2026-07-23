# Risks and Limitations

## Mathematical risks

### No useful gradient

Near-counterexamples may still contain many long forbidden cycles, and capped counts may poorly predict exact validity.

Mitigation:

- compare multiple score definitions;
- retain novelty search;
- analyze motifs rather than only scalar score;
- use exact verification on a controlled sample, not only top score.

### Search restricted to the wrong class

Cubic search may miss a mixed-degree counterexample.

Mitigation:

- label cubic mode as a phase, not a theorem;
- add mixed-degree mode using current structural constraints;
- periodically run unrestricted small experiments.

### Hidden statement mismatch

Open problems often have variants involving connectedness, induced subgraphs, multigraphs, or exact definitions of cycles.

Mitigation:

- preserve the original statement and citation;
- create a target audit checklist;
- include examples and non-examples;
- have a mathematician review the encoded statement.

## Verification risks

### Same bug in two verifiers

If both implementations share logic, they are not independent.

Mitigation:

- use different algorithms and languages;
- compare Python DFS with Glasgow subgraph or SAT;
- export a standalone artifact.

### False UNSAT

Can result from an encoding bug or unsafe symmetry breaking.

Mitigation:

- small-order ground truth;
- proof logging;
- independent solver overlap;
- witness-backed lazy clauses;
- no novel static symmetry rule without validation.

## Engineering risks

### Memory explosion

Likely in SAT, canonical generation, long-cycle enumeration, or unbounded archives.

Mitigation: see resource-safety document.

### Python bottleneck

Likely in exact long-cycle detection.

Mitigation:

- profile;
- use integer bitsets;
- add one C++ helper;
- avoid per-edge Python object allocation.

### Dashboard affects search

Mitigation:

- dashboard reads snapshots;
- bounded polling;
- no direct worker queries;
- low-frequency database reads.

## Research-process risks

### Target already resolved

The current AI-driven pace makes this realistic.

Mitigation:

- status check before each major run and before publication;
- target registry with timestamp;
- keep framework reusable.

### Reproducing a known result

Mitigation:

- search exact graph6 hashes and invariants;
- compare with public repositories;
- contact authors;
- describe reproduction honestly.

### Overclaiming from computation

Mitigation:

- strict status vocabulary;
- preserved artifacts;
- external verification;
- separate engineering completion from mathematical result.

# Target Specification: Erdős–Gyárfás Conjecture

## Mathematical statement

For every finite simple graph `G`, if the minimum degree satisfies

```text
delta(G) >= 3,
```

then `G` contains a simple cycle whose length is a power of two.

For a graph of order `n`, the forbidden cycle lengths for a counterexample are:

```text
L(n) = { 2^j : 4 <= 2^j <= n }.
```

Examples:

- `n=15`: `4, 8`
- `n=31`: `4, 8, 16`
- `n=32`: `4, 8, 16, 32`
- `n=63`: `4, 8, 16, 32`
- `n=64`: `4, 8, 16, 32, 64`

## Candidate validity

A final counterexample candidate must be:

- finite;
- simple;
- undirected;
- loopless;
- connected when searching for a minimal witness;
- minimum degree at least 3;
- free of every cycle length in `L(n)`.

Disconnected graphs are unnecessary for minimal search because any connected component with minimum degree at least 3 would itself be a smaller counterexample.

## Structural knowledge to encode as optional search priors

From current literature on minimal counterexamples:

- every regular minimal counterexample is cubic;
- vertices of degree at least 4 form an independent set;
- every vertex is adjacent to a degree-3 vertex;
- at least `4/7` of vertices have degree 3;
- a counterexample must contain an induced `P13`, because the conjecture is known for `P13`-free graphs.

These constraints are valid for a minimal counterexample or known subclasses. Keep them as named modes, not silent assumptions:

- `cubic_first`
- `minimal_structure_mixed_degree`
- `unrestricted_min_degree_3`

## Search phases

### Phase A — cubic graphs

Advantages:

- degree constraint is automatic;
- double-edge swaps preserve degrees;
- compact state;
- current theory justifies cubic minimal candidates as an important class.

Limitation:

- a minimal counterexample need not be regular.

### Phase B — predominantly cubic mixed-degree graphs

Generate degree sequences satisfying:

- minimum degree 3;
- at least `ceil(4n/7)` degree-3 vertices;
- vertices with degree at least 4 form an independent set;
- every vertex has a degree-3 neighbor.

Mutations must preserve or repair these constraints.

### Phase C — unrestricted minimum-degree-3 graphs

Use only after phases A and B are stable. The search space is much larger and mutation repair becomes more expensive.

## Score design

Use a lexicographic score, not one fragile scalar.

```text
1. structural validity
2. number of detected forbidden cycles, lower is better
3. weighted detected-cycle count, lower is better
4. exact-verifier progress / witness hardness
5. novelty against archive
6. simplicity / canonical uniqueness
```

For heuristic ranking, witness enumeration may be capped. For exact final verification, it may not be capped.

Suggested length weights emphasize short cycles because they are cheap and highly constraining:

```text
C4:  16
C8:   8
C16:  4
C32:  2
C64:  1
```

Do not infer absence from a capped search.

## Mutations

### Cubic mode

Use a legal double-edge swap:

```text
remove (a,b), (c,d)
add    (a,c), (b,d)
```

or the alternative pairing, provided:

- all vertices are distinct where required;
- new edges do not already exist;
- no loop is created;
- connectedness is preserved or cheaply repaired.

Add larger moves only after baseline profiling:

- two consecutive swaps;
- cycle switching;
- edge rotation;
- restart from archive elite plus perturbation.

### Mixed-degree mode

Operators:

- degree-preserving edge swap;
- add one edge and remove another;
- move one endpoint;
- constrained degree-sequence rewiring;
- repair pass for minimum degree and high-degree independence.

Reject invalid moves cheaply before cycle scoring.

## Exact witness format

For every found forbidden cycle, store the ordered vertex list:

```json
{
  "length": 16,
  "vertices": [0, 7, 3, 11, 5, 9, 2, 14, 6, 1, 10, 4, 13, 8, 12, 15]
}
```

For a verified counterexample, store an empty forbidden-witness list plus independent verifier reports.

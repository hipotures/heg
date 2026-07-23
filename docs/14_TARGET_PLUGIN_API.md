# Target Plugin API

## Required concepts

```python
class TargetPlugin(Protocol):
    id: str

    def validate_graph(self, graph: BitGraph) -> ValidationResult: ...
    def generate_seed(self, rng: Random, config: TargetConfig) -> BitGraph: ...
    def mutate(self, graph: BitGraph, rng: Random, config: TargetConfig) -> MutationResult: ...
    def cheap_score(self, graph: BitGraph, budget: ScoreBudget) -> ScoreResult: ...
    def exact_verify(self, graph: BitGraph, budget: VerifyBudget | None) -> VerifyResult: ...
    def canonical_key(self, graph: BitGraph) -> bytes: ...
    def explain(self, graph: BitGraph, result: VerifyResult) -> dict: ...
```

## Result requirements

Every result includes:

- status enum;
- elapsed time;
- implementation name and version;
- witnesses;
- whether the computation was complete;
- error or timeout metadata.

## Separation of concerns

- `cheap_score` may be incomplete but must say so.
- `exact_verify` must be complete to return `VERIFIED` or `REJECTED`.
- search algorithms do not inspect target-specific internal fields beyond the documented score tuple.
- SAT encoding is an optional separate protocol.

## Adding a target

A new target requires:

1. original statement and citation;
2. status check;
3. exact object class;
4. positive and negative examples;
5. verifier specification;
6. mutation operators;
7. score rationale;
8. known lower bounds and searched ranges;
9. artifact format;
10. target-specific risk note.

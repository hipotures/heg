# Target Plugin API

## Required concepts

```python
class TargetPlugin(Protocol):
    id: str

    def validate_graph(self, graph: BitGraph) -> ValidationResult: ...
    def generate_seed(self, rng: Random, config: dict[str, Any]) -> BitGraph: ...
    def mutate(self, graph: BitGraph, rng: Random, config: dict[str, Any]) -> BitGraph: ...
    def cheap_score(self, graph: BitGraph, cap: int) -> ScoreResult: ...
    def exact_verify(self, graph: BitGraph) -> VerifyResult: ...
    def canonical_key(self, graph: BitGraph) -> bytes: ...
    def explain(self, graph: BitGraph, result: VerifyResult) -> dict[str, Any]: ...
```

## Result requirements

Every exact verification result includes:

- status enum;
- elapsed time;
- implementation identifier;
- witnesses;
- whether the computation was complete;
- optional error metadata.

External implementation versions and paths belong to immutable run
environment metadata and `tool_versions`, rather than being duplicated into
every hot-loop score.

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

## M6 hidden-witness control

`m6_hidden_witness_control_v1` is a deliberately false, control-only installed
target for acceptance testing. It is never the default research target and
must never be reported as an open mathematical result. Its verifier contract
uses the same two independent M4 implementations with target-specific cycle
lengths. The finite witness is retained in test/certification artifacts but is
not supplied to the Director snapshot.

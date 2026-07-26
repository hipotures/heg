# Search Lanes

## Role

Search lanes are concurrent, stateful graph-search workers controlled through
reviewed Director actions.

## Lane identity

A lane persists across process generations and records:

- lane ID and version;
- graph family;
- algorithm and parameters;
- deterministic seed lineage;
- parent/fork provenance;
- resource share;
- checkpoints;
- telemetry;
- state and terminal reason.

## Algorithms

The reviewed catalog includes:

- random restart;
- simulated annealing;
- iterated local search;
- iterated local search with tabu.

Implemented controls are algorithm-specific. Unsupported parameters are
rejected rather than ignored.

## Mutation operators

Reviewed operators include:

- uniform two-edge switch;
- forbidden-cycle-break switch.

Weights are known-name-only, non-negative, positive-sum, and normalized before
execution.

## Micro-batch boundary

Actions apply between bounded micro-batches. Each micro-batch produces:

- evaluations;
- score/best updates;
- operator statistics;
- resource/throughput metrics;
- checkpoint before matching high-water telemetry;
- candidate improvements.

Erdős–Gyárfás score profiling is optional and independent of ancestry
instrumentation. When enabled, each worker keeps per-length elapsed
nanoseconds and DFS-node counts in one batch-local accumulator. No
per-candidate profile dictionary, JSON, event, SQLite row or log line is
created. The aggregated `timing.score_profile` is emitted and persisted once
with the completed batch.

Long-running batches may also publish a transient live-frontier sample at most
once per second. The worker copies the already accepted graph, its existing
score, candidate ID, lane version, and high-water counter into a size-bounded
payload. This path never calls the scorer or constructs a resumable checkpoint.
The non-important queue event may be dropped under pressure.

## Checkpoints

Checkpoint content includes enough state to reproduce continuation:

- graph;
- RNG;
- tabu/recent state;
- counters;
- parameter/version metadata;
- hash/manifest.

Resume verifies hashes and starts a new process generation.

Live-frontier samples are not checkpoints. The coordinator atomically
overwrites one SHA-256-protected `live-frontier-*.json` file per lane, keeps no
history, and creates no SQLite row. Durable post-batch checkpoints and their
checkpoint-before-telemetry ordering remain unchanged.

## Concurrency

The coordinator remains the single SQLite writer. Workers communicate through
bounded queues. The Director may reason while lanes continue searching.

## Resource changes

Resume can change application worker slots and lane limits. It does not claim
OS CPU isolation.

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
nanoseconds, DFS-node counts, evaluation counts, complete recounts and
cutoffs in one batch-local accumulator. No
per-candidate profile dictionary, JSON, event, SQLite row or log line is
created. The aggregated `timing.score_profile` is emitted and persisted once
with the completed batch.

The Erdős–Gyárfás lane may use one persistent `sglab-score-worker` C++17
process. Requests contain bounded adjacency bitsets; responses contain only
counts, completeness flags, DFS nodes and elapsed nanoseconds. The process
starts once per lane, has a separate memory limit and a bounded protocol,
and is included in lane process-tree RSS. A protocol error, timeout or crash
is never interpreted as a zero count: the lane retries once and then switches
to the Python scorer.

`python`, `shadow` and `cpp` scorer modes are rollout controls. Shadow mode
compares every graph with Python. C++ mode audits every 4096th evaluation and
every proposed global record with a full Python recount. A mismatch disables
the worker and makes Python authoritative.

For non-perturbation ILS/tabu moves, an optional monotone cutoff may stop after
the partial lexicographic penalty already proves that the move cannot be
accepted or become a global record. Random restart, simulated annealing and
perturbation moves always receive a full score. The cutoff changes neither RNG
consumption nor accepted/search-record trajectories.

Checkpoint field `duplicate_key_scheme` explicitly selects
`legacy_sha_graph6_v1` or `delta_local_v2`. Historical
`tabu_key_scheme=sha256_graph6_v1|zobrist256_v1` values remain readable.
Resume and trajectory-preserving forks inherit the checkpoint scheme without
rewriting the visited/tabu membership. Only a new lane or explicit
algorithmic restart may select `delta_local_v2`.

The legacy scheme still produces exactly SHA-256(canonical graph6), but its
encoder writes directly into a reusable byte buffer and reuses the digest
when candidate ancestry needs the same graph identity. The deterministic
256-bit edge-XOR delta key avoids graph6/SHA-256 in local duplicate/tabu
bookkeeping. It is not a canonical graph identity and is never certification
evidence.

Random-restart outputs use `provenance_kind=independent_sample`: each graph is
a sibling generated from RNG state, not a mutation child of the previous
sample. The hot loop therefore keeps only scalar evaluation state. Full
provenance is materialized for global records, retained candidates, M4
snapshots and periodic checkpoints. Mutation-based lanes retain bounded
`mutation_chain` ancestry.

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
- local tabu-key scheme;
- current/best provenance kind and reproduction metadata;
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

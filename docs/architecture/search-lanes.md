# Search Lanes

## Role

Search lanes are concurrent, stateful graph-search workers controlled through
reviewed Director actions.

They may be coordinated by either the AI Director or the `balanced_v1`
no-LLM scheduler. Only the source of reviewed actions changes; worker
algorithms, micro-batch boundaries, checkpoint integrity, and M4 authority are
identical.

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

Every campaign seed construction is observed at the call boundary without an
additional generator call or RNG draw. Fixed-size accumulators record graph
family/order, effective generator mode, source, success/failure, internal
attempt count, retry budget, elapsed nanoseconds, and categorized failure.
Sources distinguish initial lane creation, automatic algorithm restart,
explicit reviewed restart, and each random-restart candidate. Restoring a
checkpoint graph is not seed construction and increments nothing.

Batch and cumulative lane telemetry contain call/success/failure totals,
attempt and elapsed totals/maxima, retry exhaustion, fixed-bucket p50/p95/p99
estimates, and the share of measured search-loop time spent in seed
construction. Histograms and source/category maps have compile-time bounds;
there is no per-seed event, row, artifact, or prompt history.

Erdős–Gyárfás score profiling is optional and independent of ancestry
instrumentation. When enabled, each worker keeps per-length elapsed
nanoseconds, DFS-node counts, evaluation counts, complete recounts and
cutoffs in one batch-local accumulator. No
per-candidate profile dictionary, JSON, event, SQLite row or log line is
created. The aggregated `timing.score_profile` is emitted and persisted once
with the completed batch.

Mutation profiling follows the same batch-only contract. Fixed in-memory
integer accumulators separate uniform, forbidden-cycle-targeted and
random-restart mutation time, plus targeted witness-search nanoseconds and
cache hit/miss counts. The aggregated `timing.mutation_profile` is materialized
only at batch completion and is absent when score profiling is disabled.

The forbidden-cycle-break operator retains one ephemeral witness-choice cache
for the lane's current immutable graph. A rejected candidate keeps the cache;
an accepted move, seed restart or checkpoint restart invalidates it
immediately. Cache population uses the same bounded Python witness traversal
and produces the same ordered choices as the uncached operator, so RNG
consumption and deterministic continuation are unchanged. The cache is never
serialized, checkpointed or shared between lane processes.

Every heuristic lane owns one persistent optimized `sglab-score-worker`
C++17 process. Requests contain the target's reviewed cycle lengths and
bounded adjacency bitsets; responses contain only counts, completeness flags,
DFS nodes and elapsed nanoseconds. The
process starts once per lane, has a separate memory limit and a bounded
protocol, and is included in lane process-tree RSS. A protocol error, timeout,
malformed response or crash is never interpreted as a zero count: the lane
restarts the worker once and then fails closed. There is no alternate
heuristic scorer, shadow mode or runtime backend selection.

For non-perturbation ILS/tabu moves, an optional monotone cutoff may stop after
the partial lexicographic penalty already proves that the move cannot be
accepted or become a global record. Random restart, simulated annealing and
perturbation moves always receive a full score. The cutoff changes neither RNG
consumption nor accepted/search-record trajectories.

New lanes and explicit algorithmic restarts always use
`duplicate_key_scheme=delta_local_v2`. Historical
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

When an older random-restart checkpoint still contains mutation-era
`accepted_ancestry` or `best_ancestry`, those fields remain immutable
historical evidence but are not restored into the live independent-sample
tracker. Graph, RNG, score, evaluation counters and duplicate state resume
unchanged; subsequent checkpoints write empty mutation-ancestry lists.

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

Seed telemetry is carried in the checkpoint so cumulative aggregates survive
Resume. Because elapsed time is observational and nondeterministic, it has a
separate SHA-256 envelope and is excluded from the scientific checkpoint
identity. Recovery verifies both hashes. Instrumentation therefore leaves the
graph/RNG/search checkpoint ID identical to an uninstrumented run.

Resume verifies hashes and starts a new process generation.

Live-frontier samples are not checkpoints. The coordinator atomically
overwrites one SHA-256-protected `live-frontier-*.json` file per lane, keeps no
history, and creates no SQLite row. Durable post-batch checkpoints and their
checkpoint-before-telemetry ordering remain unchanged.

## Concurrency

The coordinator remains the single SQLite writer. Workers communicate through
bounded queues. The Director may reason while lanes continue searching.

For a passive review, queued lane events are drained before the scientific
snapshot is published. The deterministic host review and commit then form one
coordinator scheduling step with no intervening event pump. Lanes may continue
computing, but their queued outcomes are applied only after that commit. An LLM
review retains event pumping while inference is in flight.

Passive reviews are due at persisted aggregate evaluation boundaries. Routine
telemetry arrival time and wall-clock timing do not select scientific actions;
critical worker, resource, lease, and verifier-integrity events may force a
fail-closed review.

## Resource changes

Resume can change application worker slots and lane limits. It does not claim
OS CPU isolation.

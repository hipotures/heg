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

## Checkpoints

Checkpoint content includes enough state to reproduce continuation:

- graph;
- RNG;
- tabu/recent state;
- counters;
- parameter/version metadata;
- hash/manifest.

Resume verifies hashes and starts a new process generation.

## Concurrency

The coordinator remains the single SQLite writer. Workers communicate through
bounded queues. The Director may reason while lanes continue searching.

## Resource changes

Resume can change application worker slots and lane limits. It does not claim
OS CPU isolation.

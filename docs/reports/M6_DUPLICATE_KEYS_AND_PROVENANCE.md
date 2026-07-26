# M6 versioned duplicate keys and independent provenance

Date: **2026-07-26**

## Outcome

The allocation-light legacy SHA/graph6 key and independent-sample provenance
passed every acceptance gate on clean commit
`2e15a7ad3908920e58d92a5a2d41370465bc5efc`.

Seven old/new pairs alternated execution order. The benchmark used the same
order-96, 1000-candidate workload on both sides and compared graph, score,
best graph, best score, RNG state, accepted count and record count.

| Change | Old median | New median | Throughput | Targeted time |
|---|---:|---:|---:|---:|
| reference legacy graph6/SHA → reusable encoder | 255.21/s | 292.57/s | **+14.6%** | duplicate **−48.1%** |
| random mutation ancestry → independent provenance | 389.69/s | 519.92/s | **+33.4%** | ancestry **−99.68%** |

Required gates were +10%/−20% for legacy keys and +25%/−80% for independent
provenance. All four passed. Every paired logical trajectory was identical.

## Continuity and identity

- Historical `sha256_graph6_v1` and `zobrist256_v1` aliases remain readable.
- Resume and trajectory-preserving fork inherit the recorded scheme.
- An explicit algorithmic restart is required to create fresh
  `delta_local_v2` duplicate state.
- The optimized legacy digest is byte-identical to SHA-256 over canonical
  graph6.
- Random-restart on/off tests preserve generated graph sequence, score,
  best progression, RNG state and checkpoint continuation.
- Candidate graph hash, candidate ID, score and M4 input are unchanged.
- SQLite v15→v16 was tested through Online Backup; integrity and foreign-key
  checks passed, and candidate provenance was copied into the immutable pin
  snapshot.

## Profiling gate

With otherwise identical C++/early-exit/fast-key settings:

| Mode | Median throughput |
|---|---:|
| profiling off | 333.98/s |
| profiling on | 335.11/s |

The calculated overhead was **−0.34%**, i.e. no measurable regression and
comfortably below the 2% production limit. Profiling still aggregates only
in-memory integer counters once per completed batch.

## Pipeline stages outside candidate evaluation

A separate seven-sample microbenchmark reported:

| Stage | Median |
|---|---:|
| candidate evaluation, batch of 10 at order 20 | 5.374 ms |
| checkpoint serialization | 0.116 ms |
| SQLite commit of 100 rows | 0.118 ms |
| telemetry event round trip | 0.0012 ms |
| live-frontier publication | 0.169 ms |

Live publication copies an existing graph and score. Its test fails if the
path invokes `_score()` or constructs a resumable checkpoint.

## Other score-pipeline checks

The same run retained all earlier gates:

- Python→C++: 9.85× at order 64 and 19.58× at order 96;
- conservative early exit: +10.4%;
- optimized legacy key→delta-local key: +14.0%;
- no worker parity mismatch affected a compared trajectory;
- incremental witness maintenance remains deferred because 0 of 2125
  dominant C16/C32/C64 stages completed.

## Reproduction

```bash
make score-worker
PYTHONPATH=src python -m sglab benchmark score-kernel \
  --iterations 7 \
  --backend-evaluations 100 \
  --search-evaluations 1000 \
  --output <artifact-directory>

PYTHONPATH=src python -m sglab benchmark micro \
  --iterations 7 \
  --output <artifact-directory>
```

The full score-kernel JSON produced during acceptance had SHA-256
`60a0121d6590e6de3b74284d31bdb02957a1f7472355963ef180d6b56c32ea4c`.

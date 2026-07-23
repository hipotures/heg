# Data Formats

## Graph persistence

Primary compact format: graph6.

Secondary readable format:

```json
{
  "n": 6,
  "edges": [[0,1], [1,2], [2,0]]
}
```

The graph6 and JSON forms must be cross-hashed in the manifest.

## Run record

```json
{
  "run_id": "20260723T140000Z-eg-n32-sa-s1",
  "created_at": "2026-07-23T14:00:00Z",
  "target": "erdos_gyarfas",
  "status_checked_at": "2026-07-23",
  "parameters": {},
  "environment": {},
  "git_commit": "...",
  "tool_versions": {},
  "status": "RUNNING"
}
```

## Live state

```json
{
  "updated_at": "...",
  "run_id": "...",
  "status": "RUNNING",
  "elapsed_seconds": 1234,
  "workers": {"alive": 12, "failed": 0},
  "throughput": {"candidates_per_second": 21000},
  "best": {"candidate_id": "...", "score": [1, 3, 18, 0]},
  "resources": {"rss_bytes": 123, "disk_free_bytes": 456},
  "queues": {"improvements": 2, "exact": 1}
}
```

## Control file

```json
{
  "version": 17,
  "requested_at": "...",
  "action": "PAUSE"
}
```

The master processes each monotonically increasing version once.

## Candidate record

```json
{
  "candidate_id": "sha256-prefix",
  "run_id": "...",
  "graph6": "...",
  "order": 32,
  "size": 48,
  "degree_histogram": {"3": 32},
  "score": {
    "valid": true,
    "witness_counts": {"4": 0, "8": 0, "16": 1, "32": 4},
    "weighted_penalty": 12,
    "novelty": 0.73
  },
  "verification_status": "PENDING"
}
```

## Benchmark record

Include raw samples or histograms, not only averages. Store units explicitly.

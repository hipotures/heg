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
  "target": "erdos_gyarfas",
  "status": "RUNNING",
  "elapsed_seconds": 1234,
  "remaining_seconds": 85166,
  "configuration": {"order": 32, "mode": "cubic_first"},
  "workers": {"configured": 12, "alive": 12, "failed": 0, "items": []},
  "throughput": {"candidates": 123456, "candidates_per_second": 21000},
  "best": {
    "candidate_id": "...",
    "score": {"ordering_key": [0, 3, 18, -730000, 48]}
  },
  "exact_verification": {"queued": 0, "verified_candidates": 1},
  "resources": {
    "master_rss_bytes": 123,
    "worker_rss_bytes": 456,
    "aggregate_rss_bytes": 579,
    "disk_free_bytes": 789,
    "database_bytes": 12345
  },
  "queues": {
    "telemetry_current": 2,
    "telemetry_max": 256,
    "exact_current": 0
  }
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

Active campaigns use a separate
`research-campaign-control.json` file with the same monotonic shape so legacy
run controls cannot be mistaken for campaign controls. The workspace also
contains `active-research-campaign.json`, a small operational pointer with the
campaign ID, campaign directory, coordinator PID, and start time. SQLite
remains authoritative for campaign state.

Active campaign files live under:

```text
workspace/research-campaigns/<campaign-id>/
  candidates/
  diagnostics/
  director/requests/
  director/evidence-registries/
  director/responses/
  director/wire/
  lane-checkpoints/
  snapshots/
  verification/
  exports/
```

The shared `results.sqlite3` schema v9 records campaigns, persistent sessions
and turns, snapshots and triggers, lanes/revisions/windows, action
batches/outcomes, hypotheses, retained candidates, verification jobs, and
terminal events. App-server turns retain cache-read, cache-write, output,
reasoning, server-authoritative total-token counts, raw usage, and the final
agent item ID. Incomplete turns additionally retain lifecycle status, request,
thread, turn and item correlation, reasoning-item IDs, latest event sequence,
terminal reason, and the canonical evidence-registry reference/hash. Final
answer and usage remain nullable. Only the campaign supervisor writes these
records.

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
    "complete": false,
    "novelty": 0.73,
    "simplicity": 48,
    "ordering_key": [0, 5, 12, -730000, 48]
  },
  "verification_status": "PENDING",
  "artifacts": {
    "graph6": "<candidate-id>.graph6",
    "json": "<candidate-id>.json",
    "svg": "<candidate-id>.svg"
  }
}
```

## Benchmark record

Include raw samples or histograms, not only averages. Store units explicitly.
Reports also preserve the exact reproduction argv, hardware/cgroup metadata,
Git commit and dirty-state status when known, and all pass/fail gate fields.

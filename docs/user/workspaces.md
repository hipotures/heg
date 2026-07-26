# Workspaces

## What a workspace contains

A workspace is the portable boundary for:

- SQLite state;
- campaign plans and attempts;
- Director request/response artifacts;
- scientific-memory snapshots;
- lane checkpoints;
- retained candidates;
- M4 verification artifacts;
- comparison suites;
- logs, reports, and exports.

The exact filesystem layout is described in
[Artifact Layout](../reference/artifact-layout.md).

## Isolation rule

Distinct workspaces are independent. A campaign in one workspace cannot see
another workspace unless an explicit import, clone, comparison fixture, or
future fork operation is used.

This prevents accidental leakage between experiments and keeps exports
reproducible.

## When to create a new workspace

Create one when:

- changing to a different research target;
- running an independent clean-room experiment;
- preparing a controlled model comparison;
- preserving a production workspace before destructive diagnostics;
- generating the synthetic UI review fixture.

Do not create one merely because:

- time expired;
- the operator stopped the campaign;
- worker resources changed;
- a non-scientific bug was fixed.

Those are Resume cases.

## Naming

Use descriptive names:

```text
workspace/erdos-gyarfas-luna-high-01
workspace/erdos-gyarfas-control-static-01
workspace/model-comparisons-live
workspace/ui-review-demo
```

Synthetic workspaces must be visibly marked and must never be used for real
scientific claims.

## Database consistency

The workspace database uses SQLite WAL mode. Do not copy only the main
database file while it is live. Use:

- the project's export command;
- SQLite Online Backup;
- a supported workspace clone/import command.

## Opening a dashboard

```bash
sglab serve   --workspace workspace/erdos-gyarfas-luna-high-01   --host 127.0.0.1   --port 8788
```

[screenshot: ID=USR-WORKSPACE-01; save as docs/assets/screenshots/user/workspaces/workspace-identity.png; crop the dashboard header and first identity/summary section showing the current workspace kind or path, campaign ID, target, and synthetic/non-synthetic state if displayed; exclude browser address bar and all lower research panels.]

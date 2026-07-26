# Operator Guide

This guide covers deployment, authentication, resource limits, process
lifecycle, recovery, backup, and security.

## Normal deployment shape

```mermaid
flowchart LR
    Browser -->|localhost/LAN| Web[Standard-library HTTP server]
    Web --> Coordinator[Campaign coordinator]
    Coordinator --> Director[Private Codex App Server runtime]
    Coordinator --> Lanes[Local search processes]
    Coordinator --> M4[Verification broker]
    Coordinator --> DB[(Workspace SQLite)]
    Lanes --> Files[Checkpoints and candidate artifacts]
    M4 --> Files
```

## Operator responsibilities

- protect dashboard state-changing endpoints;
- authorize exact campaign/comparison fingerprints;
- keep auth material outside workspaces and Git;
- choose host-level memory/CPU controls when application limits are
  insufficient;
- use consistent SQLite backup/export procedures;
- inspect faults before Resume;
- preserve evidence reports and historical attempts.

## Start here

- [Deployment](deployment.md)
- [Authentication](authentication.md)
- [Resource limits](resource-limits.md)
- [Process lifecycle](process-lifecycle.md)
- [Recovery](recovery.md)
- [Backup and export](backup-and-export.md)
- [Security](security.md)

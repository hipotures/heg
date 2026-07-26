# Architecture Decision Records

ADRs explain durable architectural decisions and their consequences.

| ADR | Decision |
|---|---|
| [0001](0001-workspace-isolation.md) | Workspaces are isolated research environments |
| [0002](0002-campaign-vs-execution-attempt.md) | Campaign identity is separate from process attempts |
| [0003](0003-stateless-director.md) | Production Director uses bounded stateless turns |
| [0004](0004-m4-certification-authority.md) | M4 is the only certification authority |
| [0005](0005-scientific-memory-compaction.md) | Scientific memory is deterministic and bounded |
| [0006](0006-candidate-pinning.md) | Candidate-target actions use pins and immutable snapshots |
| [0007](0007-sqlite-single-writer.md) | Workspace SQLite uses a single authoritative writer |
| [0008](0008-fail-closed-runtime.md) | Runtime failures preserve evidence and stop safely |
| [0009](0009-persistent-heuristic-score-worker.md) | Heuristic cycle counting may use a persistent audited C++ worker |

ADRs are not implementation reports. They describe why the current design was
chosen.

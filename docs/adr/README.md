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
| [0010](0010-versioned-duplicate-keys-and-independent-provenance.md) | Duplicate keys are checkpoint-versioned and random restart uses independent provenance |
| [0011](0011-director-request-headroom-and-floor-recovery.md) | Director requests use token headroom and tightest-safe-state recovery; its 16,000 hard gate is superseded |
| [0012](0012-director-client-context-hard-limit-32k.md) | Director client-owned requests use a 32,000-token hard gate |
| [0013](0013-mandatory-optimized-cpp-heuristic-scorer.md) | Heuristic scoring has one mandatory optimized C++ implementation and fails closed |
| [0014](0014-no-llm-passive-scheduler.md) | Campaigns may use a deterministic no-LLM scheduler through the shared reviewed action pipeline |
| [0015](0015-seed-generation-telemetry.md) | Seed telemetry is bounded and separately hashed from scientific checkpoint identity |

ADRs are not implementation reports. They describe why the current design was
chosen.

# Resource and Memory Safety

Target machine profile:

- 16 CPU cores / 32 threads or similar;
- 192 GB RAM;
- Linux with cgroup v2;
- GPU present but not required.

## CPU allocation

Default:

- 12 search workers;
- 1 master;
- 1 exact-verifier worker;
- reserve at least 2 hardware threads for the OS and dashboard.

Do not automatically use every logical CPU. Solver and memory behavior must determine concurrency.

## Memory allocation

For 192 GB RAM, suggested initial limits:

- `MemoryHigh`: 150 GB;
- `MemoryMax`: 168 GiB (180,388,626,432 bytes);
- hard reserve: at least 20 GB for OS, filesystem cache, and recovery.

Tune after measuring. Do not assume a solver's memory scales linearly.

## cgroup v2

Preferred launch pattern with systemd:

```bash
systemd-run --user --scope \
  -p MemoryHigh=150G \
  -p MemoryMax=168G \
  -p TasksMax=512 \
  -p CPUQuota=1400% \
  ./scripts/run_experiment.sh ...
```

If user scopes are unavailable, use a dedicated system service or direct cgroup v2 files.

## Fallback limits

- `resource.setrlimit(RLIMIT_AS, ...)` for subprocesses;
- process-group creation with `start_new_session=True`;
- kill the complete process group after timeout;
- read `/proc/<pid>/status` and `/proc/<pid>/statm`;
- terminate workers crossing the configured RSS limit;
- recycle workers periodically to bound allocator fragmentation.

`RLIMIT_AS` can interact poorly with memory-mapped libraries. Prefer cgroups where available.

## Bounded data structures

Mandatory:

- bounded multiprocessing queues;
- fixed top-K archive;
- fixed tabu size;
- capped witness lists in heuristic scoring;
- batched metrics;
- bounded log tail in memory;
- database retention rules.

Never accumulate all candidates or all cycle witnesses.

## SQLite protection

- WAL mode;
- one writer;
- batch inserts;
- periodic WAL checkpoint;
- retain at most 100,000 periodic metric rows per run database;
- delete evicted candidate rows and files with the bounded top-K archive;
- database size shown in dashboard;
- no per-candidate write;
- index only columns used by UI and reports.

## Disk protection

Before and during a run:

- check free bytes;
- stop starting new exact jobs below threshold;
- rotate or cap logs;
- compress old JSONL logs;
- keep only explicit checkpoints;
- hash and deduplicate artifacts.

## Subprocess protection

Every external call must define:

- wall timeout;
- maximum captured stdout/stderr bytes;
- process group;
- expected exit codes;
- output parser with schema validation;
- temporary directory cleanup.

## Failure handling

A worker failure must not terminate the master. Record:

- signal or exit code;
- last candidate ID;
- RSS estimate;
- tool command;
- stderr tail;
- retry decision.

Retry only deterministic infrastructure failures. Do not repeatedly retry the same memory-exploding exact instance without changing the budget or method.

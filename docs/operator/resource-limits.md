# Resource Limits

## Application versus OS limits

HEG application limits bound worker slots, lanes, queues, files, and memory
contracts. CPU worker slots are not cgroup or affinity isolation.

Use host-level cgroups, systemd limits, or containers when hard CPU/RAM
enforcement is required.

## Search resources

Campaign plans may fingerprint:

- CPU worker slots;
- maximum active lanes;
- maximum resource share per lane;
- maximum aggregate share;
- memory per lane;
- queue capacities;
- telemetry/checkpoint retention;
- verifier concurrency and memory.

Resume may change allowed execution resources while preserving campaign
scientific identity.

When the persistent score backend is requested, each eligible lane reserves
64 MiB for its `sglab-score-worker` child and gives the remainder of the lane
limit to the Python parent. Lane limits below 128 MiB disable the child and
use Python. Coordinator snapshots sum parent and descendant RSS so the helper
does not disappear from memory accounting.

## App Server resource categories

Resource accounting separates:

| Category | Examples |
|---|---|
| Preserved artifacts | request, response, state, registries, schema, bounded wire log, safe report |
| Runtime scratch | private homes, SQLite/WAL/SHM, rollouts, temporary files |
| Credential material | private `auth.json`; never opened by accounting |
| Logs | stdout, stderr, wire, worker logs with individual caps |

Default comparison-era limits documented by the current runtime include:

- preserved artifacts: 64 MiB;
- runtime scratch: 512 MiB;
- single preserved file: 32 MiB;
- single runtime file: 256 MiB;
- bounded wire/stderr/stdout.

Campaign plans may use a different fingerprinted stdout limit.

## Filesystem accounting

The accounting path:

- uses `lstat`;
- never follows symlinks;
- deduplicates hard links by device/inode;
- records apparent and allocated bytes;
- identifies sparse files;
- rejects or reports escape/race conditions;
- persists peak and threshold attribution before cleanup.

Expected App Server wrapper symlinks are classified separately from byte
quotas. A quota message is valid only when the numeric inequality is true.

## Failure behavior

- active turn: interrupt when supported;
- drain late events;
- preserve known IDs/items/nullable usage;
- graceful shutdown;
- block later dependent work;
- retain exact category, limit, peak, contributor, stage, and cleanup result.

A completed valid turn remains valid when a later suite-level preservation or
shutdown failure occurs.

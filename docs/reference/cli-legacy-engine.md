# Legacy Engine and Diagnostic CLI

These commands expose fixed scientific parameters and are not the normal
Active Director campaign interface.

## Fixed-configuration search

```bash
sglab run   --target erdos_gyarfas   --order 32   --mode cubic_first   --algorithm simulated_annealing   --workers 12   --seed 1   --time-limit 24h   --memory-high 161061273600   --memory-limit 180388626432   --exact-timeout 30   --workspace ./workspace
```

Modes include:

- `cubic_first`;
- `minimal_structure_mixed_degree`;
- `unrestricted_min_degree_3`.

Algorithms include:

- `simulated_annealing`;
- `iterated_local_search`.

## Legacy controls

```bash
sglab control --workspace ./workspace --action PAUSE
sglab control --workspace ./workspace --action RESUME
sglab control --workspace ./workspace --action STOP

sglab resume --run ./workspace/runs/<run-id> --time-limit 2h
```

These commands resume a legacy run/RNG checkpoint, not an Active Director
campaign execution attempt.

## Standalone verification

```bash
sglab verify --graph6 candidate.graph6
sglab verify --graph-json candidate.json

sglab verify   --graph6 candidate.graph6   --artifact-dir ./certificate   --timeout 0   --memory-limit 0
```

`--reference-only` is diagnostic and cannot produce a two-verifier
certificate.

## SAT

```bash
sglab sat   --order 8   --solver cadical195   --seed 1   --time-limit 10m   --memory-limit 8589934592   --output ./workspace/sat-n8
```

Timeout or unchecked UNSAT is not certification.

## Benchmarks

```bash
sglab benchmark micro --iterations 10 --output ./workspace/benchmarks

sglab benchmark calibrate   --minutes 15   --seeds 2   --target erdos_gyarfas   --output ./workspace/benchmarks

sglab benchmark soak   --hours 2   --order 32   --workers 12   --workspace ./workspace-soak   --output ./workspace-soak/benchmarks
```

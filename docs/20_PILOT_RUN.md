# Documented Integration Pilot

This pilot is engineering evidence, not a result about the Erdős–Gyárfás
conjecture. It deliberately uses `n=8`, which is below the research frontier,
to exercise the complete operational path quickly and deterministically.

## Reproduction

Use two terminals:

```bash
sglab init --workspace ./workspace-pilot
sglab serve --workspace ./workspace-pilot --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/` in a browser. Start this bounded run from the
form:

- target: `erdos_gyarfas`
- order: `8`
- mode: `cubic_first`
- algorithm: `simulated_annealing`
- workers: `2`
- seed: `20260724`
- time limit: `120` seconds
- memory limit: `1073741824` bytes
- notes: `documented local integration pilot`

Observe the live counters, then use the dashboard buttons in this order:
`Pause`, `Resume`, `Stop`. Download the best `.graph6` file and run:

```bash
sglab verify \
  --graph6 ./workspace-pilot/runs/<run-id>/best/<candidate-id>.graph6 \
  --artifact-dir ./workspace-pilot/independent-verification \
  --timeout 0 \
  --memory-limit 0
```

An `n=8` candidate is expected to be rejected because it contains a forbidden
cycle. That rejection is a successful pilot outcome; it is not a
counterexample.

## Recorded run

The full path was exercised on 2026-07-24 with Python 3.12.10:

- run ID: `20260724T020412Z-eg-n8-sa-s20260724`;
- dashboard start request accepted with a dedicated coordinator process;
- live browser view rendered status, metrics, bounded logs, candidates,
  experiments, and controls;
- the running state reached 220,091 candidates at 21,883.9 candidates/s;
- `PAUSE` was accepted and the candidate counter remained exactly 445,576
  across consecutive state polls;
- `RESUME` was accepted and the counter advanced to 730,379;
- `STOP` was accepted and the run ended cleanly as
  `NO_RESULT_WITHIN_BUDGET`, with 968,205 candidates and zero worker failures;
- the final candidate ID was `defa42200f149bae4cd4`;
- its graph6 SHA-256 was
  `69f078b1ffb7f822c743b98aedb36f430499593892369fd51472e5d1857a7ee5`;
- standalone verification returned `INVALID_CANDIDATE`;
- the Python reference DFS and independent C++17 bitset DFS both completed
  and found the same 4-cycle witness `(0, 1, 2, 3)`.

The dashboard itself was rendered with headless Chromium at 1440×1200 after
the run. This confirms that the browser page, not only its JSON endpoints,
loaded the recorded state and candidate table.

## Runtime connectivity

The pilot made no AI or model calls. Search, verification, SQLite persistence,
and dashboard rendering were local. The dashboard bound only to
`127.0.0.1`; no outbound network connection is required during normal use.

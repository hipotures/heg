# Files to Remove After Documentation Migration

This is a **reviewed removal list**, not an automatic deletion script.

Remove a file only after confirming that the replacement documents listed
beside it are present and that no code or external link still depends on the
old path.

## Superseded current manuals

| Remove after migration | Replaced by |
|---|---|
| `docs/15_OPERATIONS_RUNBOOK.md` | `docs/operator/README.md`, `deployment.md`, `recovery.md`, `security.md` |
| `docs/18_COMMAND_REFERENCE.md` | `docs/reference/cli-campaigns.md`, `cli-comparisons.md`, `cli-legacy-engine.md`, `http-api.md` |
| `docs/CAMPAIGN_RESUME.md` | `docs/user/resume.md`, `docs/architecture/campaign-runtime.md`, `docs/reference/state-machines.md` |
| `docs/CAMPAIGN_SCIENTIFIC_MEMORY.md` | `docs/architecture/scientific-memory.md`, `docs/adr/0005-scientific-memory-compaction.md` |
| `docs/COMPARISON_UI.md` | `docs/user/comparisons.md`, `docs/architecture/comparison-system.md` |
| `docs/COMPARISON_WORKER.md` | `docs/operator/process-lifecycle.md`, `docs/architecture/comparison-system.md`, `docs/reference/cli-comparisons.md` |

## Planning-only material

Remove these only if they still exist and all implemented behavior has been
captured in current docs and reports:

```text
planning/m6-active-director/
```

Planning documents describe intended work and should not remain in the normal
documentation navigation after implementation.

## Relocate rather than delete

| Existing file | Recommended destination |
|---|---|
| `docs/20_PILOT_RUN.md` | `docs/reports/legacy/20_PILOT_RUN.md` |
| `docs/19_BENCHMARK_RESULTS.md` | Keep in place or move to `docs/reports/benchmarks/`; retain evidence |
| Any `M6_*` or `M7_*` acceptance document outside `docs/reports/` | Move into `docs/reports/` without rewriting content |

## Keep

Do **not** delete:

- `docs/reports/**`;
- `docs/IMPLEMENTATION_STATUS.md`;
- benchmark raw evidence;
- runtime reports;
- migration reports;
- certificate artifacts;
- old reports whose claims have been superseded, provided they remain clearly
  dated and linked as historical evidence.

## Link cleanup

Before deletion:

```bash
rg -n '15_OPERATIONS_RUNBOOK|18_COMMAND_REFERENCE|CAMPAIGN_RESUME|CAMPAIGN_SCIENTIFIC_MEMORY|COMPARISON_UI|COMPARISON_WORKER' .
```

Update inbound links to the replacement pages.

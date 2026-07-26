# Documentation Migration Guide

This package replaces a milestone-driven documentation layout with an
audience-driven layout.

## Merge order

1. Merge `docs/` into the existing directory.
2. Add root `AGENTS.md`.
3. Review and optionally replace root `README.md`.
4. Capture screenshots listed in `docs/user/screenshot-plan.md`.
5. Verify relative links.
6. Apply `docs/FILES_TO_REMOVE.md`.
7. Update `docs/IMPLEMENTATION_STATUS.md` only as a chronological ledger.

## Source-of-truth hierarchy

When documents disagree, use this order:

1. current code and SQLite migrations;
2. architecture and reference documents in this package;
3. current user/operator documents;
4. current implementation status;
5. historical evidence reports;
6. superseded planning documents.

Historical reports are never silently edited to match current behavior.

## Existing documents

Do not delete `docs/reports/`. Add `docs/reports/README.md` and keep evidence
files in place.

The package intentionally splits large mixed-purpose files:

- command reference → focused CLI and API references;
- operations runbook → operator deployment/recovery/security pages;
- campaign resume → user, architecture, reference, and Codex pages;
- scientific memory → architecture, reference, and ADR pages;
- comparison UI/worker → user, architecture, operator, and reference pages.

## Post-merge checks

```bash
git status --short
find docs -type f -name '*.md' -print | sort
rg -n '\[screenshot:' docs/user
rg -n 'docs/(15_OPERATIONS_RUNBOOK|18_COMMAND_REFERENCE|CAMPAIGN_RESUME|CAMPAIGN_SCIENTIFIC_MEMORY)' .
```

Run the repository gates only if documentation tooling or code was changed.
Markdown-only replacement does not require model or runtime access.

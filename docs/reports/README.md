# Evidence Reports

This directory contains implementation and runtime evidence.

Reports answer:

> What was executed, under which commit and limits, and what did that gate
> prove?

They do not replace the current user guide, operator runbook, architecture, or
reference.

## Rules

- Keep reports immutable once they are cited as evidence.
- Create a new report for a new gate or correction.
- Preserve tested commit, plan fingerprint, limits, hashes, and uncertainty.
- Never retrofit a historical report to describe later behavior.
- Do not include credentials, auth hashes, bearer tokens, or private runtime
  paths.
- A report may prove an engineering property; it must not turn a heuristic
  search result into a mathematical claim.

Use [Implementation Status](../IMPLEMENTATION_STATUS.md) as the chronological
ledger that points to these reports.

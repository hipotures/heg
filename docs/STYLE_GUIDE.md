# Documentation Style Guide

## Format

Use GitHub-flavored Markdown. Do not require a site generator for normal
reading.

## Voice

- Write direct, technical English.
- Separate mathematical claims from engineering status.
- Prefer explicit states and contracts over promotional language.
- State uncertainty rather than filling gaps.
- Use `M4`, `Director`, `Resume`, `Workspace`, and `Campaign` consistently.

## Structure

Every substantial page should contain:

1. a one-paragraph purpose statement;
2. the intended reader;
3. the normal workflow;
4. safety or failure semantics;
5. links to deeper architecture/reference material.

## GitHub callouts

Use:

```markdown
> [!NOTE]
> Additional context.

> [!IMPORTANT]
> A contract that affects correctness.

> [!WARNING]
> An operation that can consume credentials, model turns, or scientific budget.

> [!CAUTION]
> A condition that may invalidate scientific interpretation.
```

## Commands

- Show complete commands.
- Use placeholders in angle brackets.
- Explain which commands are deterministic and which may access auth or a
  model.
- Do not put credential values in examples.
- Bind dashboards to `127.0.0.1` unless the section explicitly discusses LAN
  exposure.

## Status language

Use:

- **implemented** for code present in the documented baseline;
- **proven** only when an acceptance gate exists;
- **supported** for a documented runtime path;
- **experimental** for available but not default paths;
- **unknown** for timeout or incomplete verification;
- **not a mathematical result** whenever an engineering result could be
  mistaken for a theorem result.

## Screenshot markers

User documents use:

```text
[screenshot: ID=USR-...; save as docs/assets/screenshots/...png; crop ...]
```

The marker must name:

- page or route;
- visible anchor headings;
- exact crop boundaries;
- required state/data;
- excluded browser chrome or unrelated sections;
- desktop or mobile requirement.

Replace a marker only after the image exists at the specified path.

## Diagrams

Use Mermaid for architecture and state machines. Keep diagrams small enough to
render legibly on GitHub.

## Links

Prefer relative links. Link user pages to architecture and reference pages
instead of duplicating protocol detail.

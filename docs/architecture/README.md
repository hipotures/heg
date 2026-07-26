# Architecture

This section describes the current production design, not the historical
sequence of milestones.

## Reading order

1. [System overview](overview.md)
2. [Domain model](domain-model.md)
3. [Campaign runtime](campaign-runtime.md)
4. [Director loop](director-loop.md)
5. [Scientific memory](scientific-memory.md)
6. [Search lanes](search-lanes.md)
7. [Candidate lifecycle](candidate-lifecycle.md)
8. [M4 verification](m4-verification.md)
9. [Persistence](persistence.md)
10. [System invariants](invariants.md)

Subsystem-specific pages:

- [Codex App Server integration](app-server-integration.md)
- [Comparison system](comparison-system.md)
- [Web control plane and visualization](web-control-plane.md)
- [Repository map](repository-map.md)

## Architectural stance

HEG separates:

- scientific identity from process execution;
- heuristic search from exact certification;
- full durable history from bounded model context;
- visible evidence from executable targets;
- user/operator controls from AI-selected scientific parameters;
- current documentation from historical reports.

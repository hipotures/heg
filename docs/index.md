# Documentation Index

This file provides a complete flat index for readers and automated agents.

## User

- [User guide](user/README.md)
- [Core concepts](user/concepts.md)
- [Quickstart](user/quickstart.md)
- [Workspaces](user/workspaces.md)
- [Campaigns](user/campaigns.md)
- [Pause, continue, stop, and Resume](user/resume.md)
- [Dashboard](user/dashboard.md)
- [Model comparisons](user/comparisons.md)
- [Candidates and exact verification](user/candidates-and-verification.md)
- [Troubleshooting](user/troubleshooting.md)
- [Screenshot plan](user/screenshot-plan.md)

## Operator

- [Operator guide](operator/README.md)
- [Deployment](operator/deployment.md)
- [Authentication](operator/authentication.md)
- [Resource limits](operator/resource-limits.md)
- [Process lifecycle](operator/process-lifecycle.md)
- [Recovery](operator/recovery.md)
- [Backup and export](operator/backup-and-export.md)
- [Security](operator/security.md)

## Architecture

- [Architecture overview](architecture/README.md)
- [System overview](architecture/overview.md)
- [Repository map](architecture/repository-map.md)
- [Domain model](architecture/domain-model.md)
- [Campaign runtime](architecture/campaign-runtime.md)
- [Director loop](architecture/director-loop.md)
- [Scientific memory](architecture/scientific-memory.md)
- [Search lanes](architecture/search-lanes.md)
- [Candidate lifecycle](architecture/candidate-lifecycle.md)
- [M4 verification](architecture/m4-verification.md)
- [Persistence](architecture/persistence.md)
- [Codex App Server integration](architecture/app-server-integration.md)
- [Comparison system](architecture/comparison-system.md)
- [Web control plane and visualizations](architecture/web-control-plane.md)
- [System invariants](architecture/invariants.md)

## Reference

- [Reference home](reference/README.md)
- [Campaign CLI](reference/cli-campaigns.md)
- [Comparison CLI](reference/cli-comparisons.md)
- [Legacy engine and diagnostics CLI](reference/cli-legacy-engine.md)
- [Configuration](reference/configuration.md)
- [HTTP API](reference/http-api.md)
- [SQLite schema](reference/sqlite-schema.md)
- [State machines](reference/state-machines.md)
- [Director action catalog](reference/action-catalog.md)
- [Director output contract](reference/director-schema.md)
- [Artifact layout](reference/artifact-layout.md)
- [Statuses and error codes](reference/statuses-and-errors.md)

## Codex development guide

- [Codex guide](codex/README.md)
- [Change map](codex/change-map.md)
- [Testing matrix](codex/testing-matrix.md)
- [Database migrations](codex/database-migrations.md)
- [Adding an action](codex/adding-an-action.md)
- [Adding a Director field](codex/adding-a-director-field.md)
- [Adding a dashboard view](codex/adding-a-dashboard-view.md)
- [Modifying Resume](codex/modifying-resume.md)
- [Debugging production campaigns](codex/debugging-production-campaigns.md)
- [Capturing documentation screenshots](codex/capturing-screenshots.md)

## Architecture decisions

- [ADR index](adr/README.md)
- [Workspace isolation](adr/0001-workspace-isolation.md)
- [Campaign versus execution attempt](adr/0002-campaign-vs-execution-attempt.md)
- [Stateless Director](adr/0003-stateless-director.md)
- [M4 certification authority](adr/0004-m4-certification-authority.md)
- [Scientific-memory compaction](adr/0005-scientific-memory-compaction.md)
- [Candidate pinning](adr/0006-candidate-pinning.md)
- [SQLite single writer](adr/0007-sqlite-single-writer.md)
- [Fail-closed runtime](adr/0008-fail-closed-runtime.md)

## Current status

- [Current Production Status](CURRENT_STATUS.md)
- [Implementation Status](IMPLEMENTATION_STATUS.md)

## Maintenance

- [Documentation migration guide](MIGRATION_GUIDE.md)
- [Files to remove after migration](FILES_TO_REMOVE.md)
- [Documentation style guide](STYLE_GUIDE.md)
- [Glossary](GLOSSARY.md)

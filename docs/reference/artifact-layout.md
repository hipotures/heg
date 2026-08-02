# Artifact Layout

Exact paths are workspace-versioned, but the logical layout is:

```text
repository/artifacts/proposal-ranking/mutation_forge_stage4r_v1/
├── README.md
├── import-manifest.json
├── champion.json
└── generation-summary.json

workspace/
├── results.sqlite3
├── artifacts/
│   ├── README.md
│   ├── workspace-artifact-manifest.json
│   ├── source-index.json
│   └── director-turns/turn-<sequence>/
│       ├── README.md
│       ├── request.json / request.md
│       ├── response.json / response.md
│       ├── validation.json
│       ├── usage.json
│       ├── provenance.json
│       ├── events.json
│       └── raw/
├── director/
│   ├── requests/
│   ├── responses/
│   ├── registries/
│   ├── context-budgets/
│   └── wire/
├── checkpoints/
├── candidates/
├── verification/
├── scientific-memory/
├── comparisons/
├── exports/
├── logs/
└── reports/
```

An active research campaign additionally uses:

```text
research-campaigns/<campaign-id>/lane-checkpoints/
├── checkpoint-<content-hash>.json
└── live-frontier-<lane-hash>.json
```

Checkpoint files are durable, retained artifacts. Each live-frontier file is
an atomically overwritten, transient 64 KiB-bounded sample; it is not entered
in SQLite and is never a Resume source.

## Safe relative references

SQLite and public reports should store safe relative artifact references and
SHA-256 values, not private absolute paths.

## Candidate artifacts

May include:

- graph6;
- edge JSON;
- SVG;
- score/provenance metadata;
- immutable snapshot;
- verifier artifacts.

## Director artifacts

- request;
- raw response;
- normalized response;
- state and registries;
- schema;
- validation report;
- bounded wire/stderr logs.

The operator-facing projection for every retained App Server turn is a
`artifacts/director-turns/turn-<sequence>/` capsule.  SQLite rows and the
original campaign request/response/wire files remain authoritative; the
capsule references one raw object under `raw/` (content-addressed/hard-linked
when possible) and adds readable Markdown plus exact validation
paths/messages.  Capsule-level JSON files are compact reference envelopes,
not duplicate transport payloads.  `artifacts/README.md` indexes capsules
chronologically and links the latest turn and the imported proposal-ranking
archive.

`workspace-artifact-manifest.json` is a non-destructive migration inventory.
It records every durable non-credential artifact path, byte size, allocated
size, SHA-256, and class (`source`, `scientific`, `transport`, `projection`,
`logs`, or `other`), plus apparent, allocated, deduplicated allocated, and
duplicate allocated totals.  Existing files are never removed by the first
pass.
Source/program files, candidate graphs, verifier certificates, decisions,
usage, failures, and scientific memory are append-only evidence; only model
projection lists may be bounded.

`source-index.json` directly maps each discovered program/source ID to its
source path, byte identity, and adjacent metadata path.  It is a projection
index only; source bytes remain first-class files and are never represented
solely by SQLite or JSON metadata.

The repository-level
`artifacts/proposal-ranking/mutation_forge_stage4r_v1/` directory is a
byte-preserving import of the reviewed Mutation Forge AI-program candidate
archive.  It contains the original valid, invalid, repaired, duplicate, and
failed slot records and a manifest of every imported path.  It is distinct
from graph candidate artifacts and does not enable ranking by itself.

## Verification artifacts

- candidate graph;
- target metadata;
- independent verifier reports;
- witness;
- manifest;
- environment/tool metadata;
- reproduction command.

## Scientific memory

Immutable canonical JSON snapshots with metadata and hash.

## Exclusions

Never include in public artifacts/manifests:

- auth files;
- bearer tokens;
- credential hashes;
- private Codex homes;
- unrestricted rollouts;
- private symlink targets.

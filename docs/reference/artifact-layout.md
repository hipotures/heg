# Artifact Layout

Exact paths are workspace-versioned, but the logical layout is:

```text
workspace/
├── results.sqlite3
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

# Documentation Screenshots

Screenshots referenced by user documentation belong under this directory.

Suggested structure:

```text
docs/assets/screenshots/
└── user/
    ├── quickstart/
    ├── workspaces/
    ├── campaigns/
    ├── resume/
    ├── dashboard/
    ├── comparisons/
    ├── verification/
    └── troubleshooting/
```

Capture instructions are embedded as markers in user documents and collected
in `docs/user/screenshot-plan.md`.

Do not include:

- bearer tokens;
- credential paths or hashes;
- private runtime paths;
- browser developer tools containing secrets;
- synthetic data presented as a real scientific result.

Use the UI demo fixture for generic documentation screenshots. Use real
workspace screenshots only when the page explicitly documents a real runtime
state and sensitive fields have been reviewed.

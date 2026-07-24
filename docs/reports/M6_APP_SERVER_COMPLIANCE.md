# M6 App Server No-Model Compliance

Date: **2026-07-24**

Target: **codex-cli 0.145.0**

Result: **PASS**

The deterministic command:

```text
sglab ai-director compliance-audit \
  --workspace workspace/app-server-compliance-accepted \
  --output docs/reports/M6_APP_SERVER_COMPLIANCE.json
```

reported:

| Condition | Result |
| --- | --- |
| strict config startup | pass |
| experimental schema discovery | pass |
| invalid config rejected | pass |
| skill-list errors empty | pass |
| all skill paths absolute | pass |
| all discovered skills disabled | pass |
| active skills after reload | 0 |
| private `CODEX_HOME` | pass |
| separate `CODEX_SQLITE_HOME` | pass |
| opaque `thread.path` handling | pass |
| complete usage schema | pass |
| graceful shutdown exercised | pass |
| failures | empty |
| `ok` | `true` |

The pre-disable and post-disable `skills/list` payloads are retained in the
private audit directory reported by the JSON artifact. The command did not
start a model turn and did not import authentication.

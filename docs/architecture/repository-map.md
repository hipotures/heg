# Repository Map

The exact tree evolves, but the following areas are the current architectural
anchors.

```text
README.md
AGENTS.md
pyproject.toml
Makefile

src/sglab/
├── cli.py
├── model.py
├── web.py
├── research/
│   ├── campaign.py
│   ├── director.py
│   ├── protocol.py
│   ├── store.py
│   ├── app_server_client.py
│   ├── app_server_protocol.py
│   ├── auth.py
│   ├── compliance.py
│   ├── inspection.py
│   └── ...
└── search/
    └── runner.py

sql/
└── versioned migrations

web/
└── index.html

tests/
└── unit, integration, fake-App-Server, HTTP, UI, recovery, and runtime gates

docs/
├── user/
├── operator/
├── architecture/
├── reference/
├── codex/
├── adr/
├── reports/
└── IMPLEMENTATION_STATUS.md
```

## Key responsibilities

| Area | Responsibility |
|---|---|
| `src/sglab/cli.py` | CLI parsing and command dispatch |
| `src/sglab/research/campaign.py` | Campaign coordination, state projection, runtime integration |
| `src/sglab/research/director.py` | Director turn lifecycle, repair/replan, prompt construction |
| `src/sglab/research/protocol.py` | Structured output schema and semantic contracts |
| `src/sglab/research/store.py` | Durable single-writer persistence and queries |
| `src/sglab/research/app_server_client.py` | Strict stdio App Server runtime |
| `src/sglab/research/auth.py` | Private runtime homes and authorized auth import |
| `src/sglab/research/compliance.py` | Deterministic protocol/isolation audit |
| `src/sglab/research/inspection.py` | Opaque rollout-path inspection |
| `src/sglab/search/runner.py` | Bounded legacy/search-kernel execution |
| `src/sglab/model.py` | Graph representation and graph6 support |
| `src/sglab/web.py` and `web/index.html` | Local API and semantic dashboard |
| `sql/` | Authoritative schema migrations |
| `tests/` | Enforced contracts and acceptance boundaries |

## Change rule

Do not infer the complete change surface from one module. Use
[Codex Change Map](../codex/change-map.md) before editing a cross-cutting
contract.

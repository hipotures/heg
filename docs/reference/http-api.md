# HTTP API Reference

The dashboard uses a standard-library HTTP server.

## Document routes

```text
GET /
GET /comparisons
GET /comparisons/new
GET /comparisons/<suite-id>
GET /comparisons/<suite-id>/blind
GET /model-cost-profiles
```

## Core read APIs

Current and legacy routes include:

```text
GET /api/status
GET /api/runs
GET /api/candidates?limit=<n>
GET /api/logs?limit=<n>
GET /api/artifact/<candidate-id>.<graph6|json|svg>
GET /api/research-campaign
GET /api/research-campaign/visualization/graph
GET /api/research-campaign/visualization/series
GET /api/comparisons/<id>
GET /api/comparisons/<id>/progress
GET /api/comparisons/<id>/turns
```

The bounded visualization series contains lane lifecycle summaries and
completed metric windows. The dashboard sums the latest completed throughput
window for every lane whose current state is `running`; lane-specific values
remain separate evidence.

## Core write APIs

```text
POST /api/control
POST /api/runs
POST /api/research-campaign
POST /api/research-campaign/control
POST /api/comparisons
POST /api/comparisons/<id>/prepare
POST /api/comparisons/<id>/authorize
POST /api/comparisons/<id>/start
POST /api/comparisons/<id>/stop
POST /api/comparisons/<id>/ratings
POST /api/comparisons/<id>/pairwise-ratings
POST /api/model-cost-profiles
```

The current campaign UI also exposes protected Resume preview/start operations.
Use route discovery/tests or current server source for exact endpoint spelling
on the installed commit.

## Security

- state-changing requests require bearer protection when configured;
- model, effort, context, fixture, numeric limits, and IDs are allowlisted;
- arbitrary command, auth path, or filesystem path is rejected;
- request/response sizes are bounded;
- artifact paths are confined to configured workspaces;
- default bind is `127.0.0.1`.

## Compatibility

The HTTP API is an internal local control-plane API, not a promised public
internet API. Changes must preserve the semantic dashboard and update this
reference plus HTTP tests.

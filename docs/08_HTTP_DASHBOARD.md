# Minimal HTTP Dashboard

## Technology

- Python `http.server.ThreadingHTTPServer`;
- static HTML, CSS, and plain JavaScript;
- JSON polling every 2 seconds;
- no frontend build step;
- no WebSockets required.

## Default binding

```text
127.0.0.1:8080
```

To expose on a LAN, require an explicit `--host 0.0.0.0` and recommend firewall restrictions or SSH tunneling.

## Main screen

Show:

- run ID and target;
- status;
- graph order and mode;
- algorithm and seed;
- elapsed and remaining budget;
- worker health;
- candidates per second;
- best score tuple;
- exact-verification queue;
- verified candidate count;
- RSS, CPU load, disk free, database size;
- last 50 events.

## Best-candidate screen

For each archived candidate:

- candidate ID;
- score components;
- order and size;
- degree histogram;
- forbidden cycle witnesses found by heuristic scorer;
- exact-verifier status;
- graph SVG;
- graph6 download;
- JSON artifact download.

Use a simple deterministic circle or force-free layout. The drawing is for inspection, not proof.

## Controls

Simple form fields only:

- target;
- order `n`;
- mode;
- algorithm;
- worker count;
- seed;
- time limit;
- memory limit;
- notes.

Buttons:

- Start
- Pause
- Resume
- Stop

No arbitrary command input.

## API

Suggested endpoints:

```text
GET  /api/status
GET  /api/runs
GET  /api/candidates?limit=50
GET  /api/logs?limit=100
GET  /api/artifact/<safe-id>
POST /api/control
POST /api/runs
```

All responses are JSON except static files and explicit artifact downloads.

## Authentication

Optional token:

```text
SGLAB_WEB_TOKEN=<random-value>
```

Accept `Authorization: Bearer ...`. If a token is configured, require it for POST endpoints and artifact downloads.

## Safety

- validate integer ranges;
- whitelist target and algorithm names;
- reject path traversal;
- cap response sizes;
- read only from configured workspace;
- use CSRF-resistant bearer token for exposed deployments;
- never invoke a shell from request parameters.

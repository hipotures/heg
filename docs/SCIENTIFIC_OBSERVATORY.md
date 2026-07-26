# Scientific observatory

The research dashboard contains a bounded, read-only observatory for the
currently selected graph-search campaign. It turns retained scientific records
into inspectable views without changing campaign, lane, verifier, or Director
state.

## Graph view

The primary canvas can display:

- the best retained candidate across the campaign;
- the best retained candidate from a selected lane;
- the immutable candidate snapshot currently consumed by M4;
- a specific retained candidate selected from history.

The server decodes `graph6` and returns only numbered vertices, edges, hashes,
scores, provenance, and bounded cycle overlays. Neither `graph6` nor artifact
paths are exposed to the browser. Pan, zoom, layer visibility, source
selection, and the selected vertex survive the dashboard's periodic refresh.
The display uses a deterministic layout so an unchanged candidate does not
jump between polls.

Cycle layers use separate styles for lengths 4, 8, 16, 32, and other relevant
lengths. Display-cycle examples come from a bounded local scan and are always
labelled non-certifying. An exact M4 witness is shown only after the persisted
manifest passes path containment, size, graph-hash, and witness-edge checks.
The exact witness is visually distinct from every heuristic overlay.

Selecting a vertex opens a small inspector with its degree, adjacent vertex
IDs, membership in displayed cycle examples, and membership in the persisted
M4 witness. The canvas exposes its current zoom percentage. Ordinary wheel
scrolling remains page scrolling; only Ctrl/pinch gestures zoom the graph, so
scrolling past the observatory cannot accidentally leave it magnified.

## Supporting views

The same observatory provides bounded tabs for:

- weighted-penalty progress from retained candidate history;
- cycle-profile counts and completeness semantics;
- lane state, throughput, diversity, and latest progress;
- M4 verification queue and completed outcomes;
- retained candidate history with direct graph selection.

Candidate history is limited to 256 records, verifier history to 64 records,
and metric history to 120 windows per lane with a 2,048-window aggregate read
bound. Lists are bounded in SQLite before browser rendering.

## API

Both endpoints are bearer-protected whenever the dashboard is protected:

```text
GET /api/research-campaign/visualization/graph?source=global_best
GET /api/research-campaign/visualization/series
```

`source` may be `global_best`, `lane_best`, `m4_active`, or `candidate`.
`lane_best` requires `lane_id`; `candidate` requires `candidate_id`.
Unknown selections return `404`, while a valid source that currently has no
displayable record returns `409`.

The service opens SQLite in read-only mode. Verification manifests are read
only through a campaign-root-contained, non-symlink path and have a 1 MiB
display limit. No endpoint writes campaign data, follows a symlink, starts
search, calls a model, or schedules verification.

## Responsive and refresh behavior

Desktop uses a graph-first stage with an adjacent scientific summary. Narrow
screens stack those regions and keep tab overflow local to the observatory.
The SVG receives a mobile-specific minimum height without widening the page.
An in-place refresh updates data without replacing the component root, so open
tabs, graph controls, scroll position, and disclosure state remain stable.
When the graph order changes, the canvas crossfades; for the same order, node
positions interpolate. Both transitions respect `prefers-reduced-motion`.

Rendered verification uses Playwright CDP at desktop and phone widths in
addition to HTTP and service-level tests.

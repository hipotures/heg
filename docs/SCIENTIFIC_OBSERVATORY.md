# Scientific observatory

The research dashboard contains a bounded, read-only observatory for the
currently selected graph-search campaign. It turns retained scientific records
into inspectable views without changing campaign, lane, verifier, or Director
state.

## Graph view

The primary canvas can display:

- the best retained candidate across the campaign;
- the latest live search-frontier graph from an active lane;
- the best retained candidate from a selected lane;
- the immutable candidate snapshot currently consumed by M4;
- a specific retained candidate selected from history.

The server decodes `graph6` and returns only numbered vertices, edges, hashes,
scores, provenance, and bounded cycle overlays. Neither `graph6` nor artifact
paths are exposed to the browser. Pan, zoom, layer visibility, source
selection, and the selected vertex survive the dashboard's periodic refresh.
The display uses a deterministic layout so an unchanged candidate does not
jump between polls.

`Live search frontier` first reads the newest integrity-checked transient lane
preview and falls back to an integrity-checked checkpoint when no valid
preview exists. Each active worker may publish at most one preview per second
by copying its already accepted graph and score; it does not rescore the graph
or serialize a full checkpoint. The coordinator atomically overwrites one
64 KiB-bounded file per lane and does not create a SQLite row. A dropdown
directly after the graph-source selector sets the browser sampling interval to
1, 2, 3, 4, or 5 seconds and appears only in live-frontier mode. The default is
5 seconds and the selection persists for the browser session. Live graphs are
labelled transient heuristic telemetry: they are neither retained scientific
records nor exact certification. Preview files are bounded to 64 KiB and
checkpoint files to 1 MiB; both are read without following symlinks and
verified against their stored SHA-256 before decoding. When the campaign is not
running, the toolbar says `Frontier paused` and shows the campaign state/fault
without presenting a stale sample timestamp.

Every displayed cycle length has a stable color derived only from its length;
the graph, vertex sectors, layer controls, and graph legend reuse that exact
color. On an edge shared by several visible bounded examples, equal-length
colored segments repeat in ascending cycle-length order. The edge direction is
canonicalized from the lower vertex ID to the higher ID, so the segment order
does not depend on cycle traversal or refresh order. Hiding a layer immediately
recomputes the remaining segments.

Vertices render above all edge overlays. A vertex outside every visible
bounded example remains hollow, one membership produces a solid fill, and
multiple memberships produce equal clockwise sectors ordered by cycle length.
The accessible vertex label names the same memberships. Display-cycle examples
come from a bounded local scan and are always labelled non-certifying. An exact
M4 witness is shown only after the persisted manifest passes path containment,
size, graph-hash, and witness-edge checks. Its double outline remains the
authority cue while its inner stroke and vertex ring use the stable color of
the witness length.

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

`source` may be `global_best`, `live_frontier`, `lane_best`, `m4_active`, or
`candidate`.
`lane_best` requires `lane_id`; `candidate` requires `candidate_id`.
Unknown selections return `404`, while a valid source that currently has no
displayable record returns `409`.

The service opens SQLite in read-only mode. Verification manifests are read
only through a campaign-root-contained, non-symlink path and have a 1 MiB
display limit. Live previews and checkpoints use the same no-follow and
bounded-read principles, and their internal hash is recomputed. No endpoint
writes campaign data, follows a symlink, starts search, calls a model, or
schedules verification.

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

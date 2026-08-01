# Web Control Plane and Visualizations

## Technology

- Python standard-library threaded HTTP server;
- static HTML/CSS;
- plain JavaScript;
- no frontend build step;
- bearer-protected state-changing APIs;
- default `127.0.0.1` binding.

## Document routes

- `/`
- `/comparisons`
- `/comparisons/new`
- `/comparisons/<suite-id>`
- `/comparisons/<suite-id>/blind`
- `/model-cost-profiles`

Research domains are presented as bounded dashboard sections.
The section navigation maps every rendered main section to a one-word anchor.
Conditional comparison, visualization, and legacy anchors follow the same
visibility state as their target section, so the menu does not retain dead
links.

## Semantic view models

The browser receives bounded summaries rather than raw SQLite dumps.
Technical JSON remains secondary disclosure.

Campaign creation and Resume expose an explicit Director-mode selector. The
default `llm` mode retains the credential gate. `passive` is labelled
**No-LLM passive search**, accepts a bounded deterministic seed, and does not
require or report Director authentication. Status and attempt cards project
the persisted mode, mode transition, contract fingerprint, passive policy
version, latest reason codes, and scheduler-decision count. Model-token fields
are rendered as not applicable in passive mode rather than as an
authentication or connection fault.

LLM campaign creation also exposes the reviewed `mutation_forge_stage4r_v1`
proposal-ranking choice. The dashboard sends only that catalog ID (or an
explicit disabled value); status and export project the plan-bound value and
enabled state. Passive mode remains unchanged. Resume has no ranking control
and therefore cannot silently change the scientific contract.

The dashboard launches a campaign runner as a detached child so a dashboard
restart does not silently terminate a healthy scientific attempt. The runner
therefore owns and closes all lane multiprocessing resources when its attempt
becomes terminal. A dead PID in the active-campaign pointer is not considered
live; a terminal runner must not survive merely because queue feeder resources
remain open.

## Live updates

The dashboard polls bounded APIs and avoids rebuilding unchanged large DOM
collections. Current visualizations include campaign scientific observatory
and live search-frontier views. The live-frontier graph has an independent
browser-session sampling control with allowlisted intervals from 1 to 5
seconds; other dashboard data retains the dashboard-wide polling cadence.
The server prefers the lane's 64 KiB transient live-frontier file and falls
back to the latest integrity-checked durable checkpoint. Reading the preview
does not trigger scoring, checkpoint creation, or a database write.
The browser continues polling while the user has an active text selection but
defers DOM replacement only for a container intersecting that selection. This
prevents invalidating copy selection without freezing unrelated telemetry or
the live graph drawing; the selected container catches up on the next polling
interval after the selection is cleared.
Dashboard metric and semantic value tiles share one delegated, browser-local
single-click copy interaction that issues no API request. Clipboard text
contains the tile label and full value. Abbreviated IDs, hashes, and SHA-256
values therefore copy their complete underlying value without changing the
card layout. Standalone abbreviated identifiers use the same mechanism, so
separate `Copy ID` controls are unnecessary. Enter and Space activate focused
copyable values.
All primary dashboard and comparison timestamps are rendered through the
browser's local timezone using European day-month-year order and a 24-hour
clock. This includes attempts, Director actions and turns, events, hypotheses,
lane revisions, runs, live-frontier publication, retained-candidate history,
and comparison creation. Original values remain in semantic `time` elements
and tooltips; technical raw JSON, persistence, ordering, and API responses stay
in UTC. Persistent App Server turns retain their descending `started_at`
order. Each turn also joins its immutable App Server session record and shows
the requested model and reasoning effort as a compact `model:effort` badge;
the dashboard does not infer this provenance from current campaign state.
The live-frontier inspector derives aggregate campaign throughput by summing
the latest completed metric window for each running lane. Missing first-batch
measurements do not erase the available aggregate; the UI exposes measured
versus running-lane coverage in the value tooltip. Per-lane throughput remains
available in the lane view and uses the same latest-completed-window semantic,
while rolling telemetry remains available for trend fields. The main campaign
lane panel shows up to eight lane cards without requiring expansion.
When the campaign is not running, both the aggregate and per-lane current
throughput render as `0/s`; completed metric windows remain intact as
historical telemetry.
Resume also establishes a new measurement boundary. Metric windows completed
before the current execution attempt's `started_at` remain historical and do
not contribute to current per-lane or aggregate throughput. The UI shows
`0/s` until the first new window completes.
Visible bounded cycle examples use deterministic length-based presentation
tokens. The same token colors the cycle's highlighted edge segments, vertex
membership sectors, and SVG legend sample. When visible cycles share an edge,
the browser canonicalizes its direction by vertex ID and repeats equal colored
segments in ascending cycle-length order. Vertices are rendered after edge
overlays and use a hollow marker for zero memberships, a solid fill for one,
and equal ordered sectors for multiple memberships. Layer visibility changes
recompute both representations locally. Exact M4 authority retains a double
outline with a length-colored core. These are read-only projections over the
existing bounded cycle and witness payloads.

## Graph visualization

A graph drawing is an embedding of the abstract adjacency structure.

- 2D and 3D views represent the same graph;
- moving vertices does not change graph properties;
- forbidden cycles may be highlighted;
- candidate/frontier/lane provenance may drive color or shape.

## Safety

- no browser-supplied command or auth path;
- fixed worker argv;
- bounded response sizes;
- path traversal protection;
- state-based control enablement;
- raw credentials and private paths never rendered.

## Accessibility baseline

- semantic headings/tables;
- visible focus;
- labelled forms;
- status text in addition to color;
- keyboard-accessible details;
- responsive cards/local table scrolling;
- light and dark themes.

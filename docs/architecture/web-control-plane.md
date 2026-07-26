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

## Semantic view models

The browser receives bounded summaries rather than raw SQLite dumps.
Technical JSON remains secondary disclosure.

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
The six live-frontier summary cards copy their own label and current value on
a single click. This clipboard interaction is browser-local and issues no API
request. Clipboard text matches the card's displayed text, including an
abbreviated graph hash.
The live-frontier inspector derives aggregate campaign throughput by summing
the latest completed metric window for each running lane. Missing first-batch
measurements do not erase the available aggregate; the UI exposes measured
versus running-lane coverage in the value tooltip. Per-lane throughput remains
available in the lane view.

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

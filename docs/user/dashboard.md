# Dashboard

The dashboard is a local research control room. It is not a mathematical proof
interface.

## Start

```bash
sglab serve   --workspace <workspace>   --host 127.0.0.1   --port 8788
```

## Main areas

The section navigation includes one-word links for every main dashboard
section. Links for comparisons, live visuals, and legacy-only sections appear
only while their corresponding section is available.

### Campaign status

Shows:

- campaign and execution-attempt identity;
- active orchestration mode;
- state and stop condition;
- cumulative and attempt-local counters;
- Director connection/auth status;
- resource usage;
- fault detail;
- M4 queue and certification state.

For **No-LLM passive search**, the status also shows policy/version and the
last deterministic reason codes. Director auth, connection, context, and token
usage render as not applicable rather than as faults.

### Director assessment and hypotheses

Shows the latest bounded scientific interpretation, hypothesis ledger, evidence
references, and confidence.

### Decisions and measured effects

Each decision is rendered semantically:

- action types;
- targets;
- parameters;
- rationale;
- expected signal;
- validation status;
- executed/not executed;
- measured downstream outcome.

Raw JSON is secondary technical evidence only.
The same view renders passive scheduler actions and their measured outcomes;
the durable source is labeled as scheduler provenance rather than a model
turn.

### Search lanes

Lane cards and trajectories show:

- algorithm and graph family;
- order and mutation mix;
- current state;
- checkpoint lineage;
- best score;
- throughput and diversity;
- revisions, forks, restarts, and stops.

### Scientific observatory

The observatory may include:

- current or best graph;
- live search frontier;
- candidate lineage;
- highlighted forbidden-cycle witnesses;
- lane trajectories;
- M4 status.

The 2D/3D drawing is a visualization of the same abstract graph. Moving or
rotating vertices does not change graph adjacency or mathematical properties.
Each visible cycle length keeps one color across highlighted edges, vertex
fills, and the legend. Shared highlighted edges alternate equal colored
segments in cycle-length order. A hollow vertex is outside every visible
bounded cycle; a solid vertex belongs to one, and a vertex split into equal
sectors belongs to several. Use the layer checkboxes to remove a cycle length;
shared-edge segments and vertex sectors update to reflect only the remaining
visible layers. The double-outlined M4 witness remains separately identified
as exact evidence.
When viewing the live search frontier, use the seconds dropdown immediately
after the graph-source selector to choose a 1–5 second refresh interval. The
choice lasts for the current browser session. During a long search batch the
graph may advance from a lightweight one-second lane preview; this preview
reuses the existing score, is not a checkpoint, and is not certification.
The live-frontier inspector reports aggregate campaign throughput: the sum of
the latest completed throughput measurement for every running lane. Until a
new lane completes its first batch, the value sums the available running-lane
measurements and its tooltip reports measurement coverage.
Click any dashboard metric or semantic value tile to copy its label and full
value. The same interaction applies to the six live-frontier metrics and the
execution-attempt resource tiles. Abbreviated IDs, hashes, and SHA-256 values
copy their complete underlying value. Standalone abbreviated identifiers are
also directly clickable; separate `Copy ID` buttons are not shown.

All primary dates and times are converted by the browser to the operator's
local timezone, using European day-month-year order and a 24-hour clock. This
applies across campaign attempts, Director records, events, lane history,
search runs, graph provenance, candidate history, and comparison suites.
Persistent App Server turns remain newest first. Hover a local timestamp to
inspect its original persisted UTC value; raw technical JSON remains unchanged.
Each turn's status row also shows the model and reasoning effort recorded for
its App Server session in `model:effort` form.

[screenshot: ID=USR-DASHBOARD-01; save as docs/assets/screenshots/user/dashboard/scientific-observatory.png; crop the complete “Scientific observatory” or “Search frontier” panel with the graph visualization, legend, current/best candidate selector, lane/frontier points, and any 2D/3D or camera controls; include the panel title and exclude unrelated campaign forms.]

### Candidates and verification

Shows retained candidates, score semantics, exact-verifier result, artifact
links, and cycle witnesses.

### Execution attempts and scientific memory

Shows:

- attempt history;
- current attempt resources;
- cumulative versus local metrics;
- scientific-memory version, bytes, token estimate, and trigger;
- reused checkpoints.

## Automatic refresh

The UI polls bounded summary endpoints. It should update scientific state
without rendering thousands of rows. Lists use bounded pages or “Show more”.
While text is selected, automatic updates preserve only the selected panel so
that the selection remains stable for copying. Polling and unrelated panels,
including the live graph drawing, continue to update. The selected panel
catches up automatically after the selection is cleared.

## Controls

Controls are state-dependent:

- pause only while running;
- continue only while live-paused;
- stop only while controllable;
- Resume only for supported terminal/recovery states;
- no dead Resume control for a fault that has not been acknowledged.

Campaign creation and the new-attempt Resume panel both offer `AI Director`
and `No-LLM passive search`. Changing the selection affects only the new
attempt and never triggers an automatic fallback.

## Theme and responsive behavior

The dashboard supports light and dark themes. Wide technical tables stay in
local scroll containers or switch to cards on narrow screens.

[screenshot: ID=USR-DASHBOARD-02; save as docs/assets/screenshots/user/dashboard/mobile-dashboard.png; use a 390×844 viewport, capture the header, primary navigation, campaign summary, and first scientific card; demonstrate no page-wide horizontal overflow and visible touch-sized controls.]

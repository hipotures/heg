# Web UI architecture

The Structural Graph Lab interface is intentionally small: the Python
standard-library HTTP server serves one static research dashboard and a set of
server-rendered comparison shells. Plain JavaScript fetches bounded JSON view
models and renders semantic summaries. There is no frontend build step or
framework.

## Information architecture

The research dashboard keeps the operational domains in one control-room page
with anchored sections:

- campaign controls and coordinator state;
- a read-only scientific observatory for graph structure, score progression,
  lanes, exact verification, and retained-candidate history;
- Director assessment, hypotheses, and decisions;
- measured decision effects and parameter revisions;
- search lanes and retained candidates;
- App Server turn accounting, events, and experiment history;
- a compact entry point to controlled comparisons.

Comparison pages remain separate routes because they have a different
lifecycle and authorization boundary:

- `/comparisons` — suite discovery and filtering;
- `/comparisons/new` — draft and arm-matrix creation;
- `/comparisons/<id>` — immutable plan, turns, validity, cost, and ratings;
- `/comparisons/<id>/blind` — quality review before contract disclosure;
- `/model-cost-profiles` — append-only relative and optional API-equivalent
  cost assumptions.

## Semantic presentation

Primary views render domain concepts rather than serialized database rows.
Director actions have action-specific labels and grouped controls. Measured
effects expose score movement, evaluation budget, throughput, diversity, and
verifier state. IDs are abbreviated in normal reading flow and retain their
complete value in a `title` attribute.

Raw and normalized JSON remains available in keyboard-accessible
`<details>` elements. Moving it behind disclosure preserves auditability
without making protocol encoding the primary interface.

Lists are bounded before rendering. Tables use semantic headers, top-aligned
compact rows, and local overflow containment. At narrow viewports, operational
tables become labelled row cards; decision, lane, candidate, and suite content
already uses responsive cards.

The scientific observatory is a separate static JavaScript component mounted
inside the same page. Its graph and series view models are server-bounded and
read-only. The component updates in place during the five-second dashboard
poll, preserving the selected source, tab, layers, pan/zoom, selected vertex,
and page scroll position. Exact M4 witness paths and bounded display-only cycle
examples have deliberately different labels and styles. See
`docs/SCIENTIFIC_OBSERVATORY.md`.

## Theme contract

Every page supports light and dark themes through the same CSS-variable
contract. The header toggle stores `light` or `dark` under
`localStorage["sglab-theme"]`. When no preference has been stored, the page
uses `prefers-color-scheme`. A small script in `<head>` applies the theme
before page rendering to avoid a light/dark flash.

Color is never the only status signal: every semantic color is paired with a
text badge. The normal UI uses a proportional system font; the monospace stack
is reserved for identifiers, hashes, logs, and technical evidence.

## Safety boundary

The redesign does not alter comparison authorization, search, or Director
semantics. All state changes remain POST-only and bearer-protected. Returned
measurement-only decisions remain read-only. Browser input cannot provide an
auth path, command, executable, or arbitrary filesystem location.

The deterministic `ui_demo` fixture is the browser-review target. It is
isolated from production workspaces and contains synthetic states explicitly
marked as demo data.

## Browser verification

Rendered behavior is checked with Playwright CDP at desktop, tablet, and mobile
sizes. The audit records screenshots, accessibility snapshots, console and
network messages, viewport overflow, table/pre dimensions, and form-label
associations. Unit tests cover stable rendering contracts but do not replace
the browser audit.

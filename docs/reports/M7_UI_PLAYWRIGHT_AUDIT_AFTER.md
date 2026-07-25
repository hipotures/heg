# M7 UI Playwright audit — after redesign

Date: 2026-07-25

## Result

The complete deterministic UI workspace was re-inspected through
`playwright-cdp` after the redesign. All application route shapes, lifecycle
states, empty/error states, comparison pages, both themes, and the required
viewport set were exercised against the rendered application.

The blocker-level failures from the before audit are resolved:

- the dashboard no longer expands to a 4,400-pixel document;
- raw JSON is no longer the primary scientific interface;
- light and dark themes are first-class and the browser remembers the choice;
- comparison lifecycle controls agree with persisted suite state;
- failed/invalid blind comparisons use a reliability empty state rather than
  presenting blank answers;
- the 404 response retains application navigation and visual context.

The phone layout is the primary compact interaction target. At `390×844`, the
application document is 375 pixels wide with no page-level horizontal
overflow. Primary navigation, forms, buttons, copy controls, section actions,
and list expansion controls provide 44-pixel touch targets.

## Safety boundary

This was a deterministic browser and engineering audit only. It performed:

- zero model inferences;
- zero auth reads or copies;
- zero authenticated App Server turns;
- zero paid comparisons;
- zero production graph-search batches.

All reviewed records came from `workspace/ui-review-demo` and are explicitly
marked synthetic/demo. The imported M6 reports retain their original hashes.

## Page inventory and evidence

The application has six document-route shapes. Research campaigns,
hypotheses, Director decisions/effects, lanes, candidates, App Server turns,
events, and legacy runs are bounded sections of the main dashboard.

| Page/state | Before | After | Result |
| --- | --- | --- | --- |
| Dashboard | [desktop](ui-playwright/before/dashboard-1920x1080.png), [phone](ui-playwright/before/dashboard-390x844.png) | [1920](ui-playwright/after/dashboard-desktop-1920-final.png), [1440](ui-playwright/after/dashboard-desktop-1440-final.png), [1280](ui-playwright/after/dashboard-desktop-1280-final.png), [1024](ui-playwright/after/dashboard-tablet-1024-final.png), [phone](ui-playwright/after/dashboard-mobile-touch-final.png) | Semantic cards, bounded lists, local responsive tables, no page overflow |
| Comparisons list | [desktop](ui-playwright/before/comparisons-1440x900.png), [phone](ui-playwright/before/comparisons-390x844.png) | [phone](ui-playwright/after/comparisons-mobile-final.png) | Compact suite cards and stable filters replace the eleven-column scan path |
| Empty filtered list | [before](ui-playwright/before/comparisons-empty-filter-1024x768.png) | [after](ui-playwright/after/comparisons-empty-mobile-390.png) | Explicit recovery-oriented empty state |
| New suite | [desktop](ui-playwright/before/comparisons-new-1440x900.png), [phone](ui-playwright/before/comparisons-new-390x844.png) | [phone](ui-playwright/after/new-suite-mobile-final.png) | Grouped labelled controls and prominent inference budget |
| Completed detail | [desktop](ui-playwright/before/comparison-completed-1440x900.png), [phone](ui-playwright/before/comparison-completed-390x844.png) | [phone](ui-playwright/after/comparison-detail-mobile-final.png) | Semantic plan, usage, validity, decisions, effects, and secondary technical evidence |
| Running detail | [before](ui-playwright/before/comparison-running-1280x720.png) | [after](ui-playwright/after/comparison-running-final.png) | Runtime state and permitted Stop action remain visible |
| Timed-out detail | [before](ui-playwright/before/comparison-timeout-1280x720.png) | [after](ui-playwright/after/comparison-timeout-mobile-final.png) | Nullable usage/final answer remain unavailable; terminal controls are disabled |
| Historical read-only detail | [before](ui-playwright/before/comparison-historical-1280x720.png) | [after](ui-playwright/after/comparison-historical-final.png) | Preserved M6 result is semantic and non-mutable |
| Blind comparison | [desktop](ui-playwright/before/comparison-blind-1280x720.png), [phone](ui-playwright/before/comparison-blind-390x844.png) | [phone](ui-playwright/after/comparison-blind-mobile-final.png) | Semantic answers; model, effort, context, usage, latency, and cost remain hidden before rating |
| Blind reliability empty state | — | [after](ui-playwright/after/comparison-blind-empty-mobile-final.png) | Failed/invalid turns are not presented as ordinary quality answers |
| Cost profiles | [desktop](ui-playwright/before/model-cost-profiles-1024x768.png), [phone](ui-playwright/before/model-cost-profiles-390x844.png) | [phone](ui-playwright/after/model-cost-profiles-mobile-final.png) | Editable semantic profile cards; no primary raw JSON |
| 404 | [before](ui-playwright/before/error-404-1024x768.png) | [after](ui-playwright/after/error-404-mobile-390.png) | Styled recovery page with global navigation and theme |

## Responsive findings

The after audit used:

- `1920×1080`
- `1440×900`
- `1280×720`
- `1024×768`
- `390×844`

At every viewport, `document.documentElement.scrollWidth` equalled
`clientWidth`. At `1024×768`, the dashboard measured `1009/1009`; at
`390×844`, it measured `375/375`. Wide scientific tables are locally
contained and switch to labelled record cards at the phone breakpoint.

The mobile header is consistent on every route: brand and theme control occupy
the first row, and the same four global destinations occupy a two-by-two
navigation grid. The dashboard's separate five-item section navigator is
explicitly labelled and remains local to the dashboard.

Long IDs are abbreviated visually and retain the full value in `title` and
Copy ID controls. Unavoidable technical values use `overflow-wrap:anywhere`.
No fixed oversized row height remains.

## Semantic presentation

Reviewed Director actions have specific meaning-first renderers:

- start lane;
- request diagnostic;
- set review trigger;
- promote candidate;
- schedule verification;
- stop lane;
- strategy/resource changes.

Nested controls are grouped, nulls are omitted, booleans and percentages are
formatted, and measured effects show score movement, evaluations, elapsed
time, throughput, accepted mutations, global records, diversity, verifier
status, and expected-signal status. Raw and normalized records remain
available in collapsed `<details>` panels.

## Theme and typography

The interface uses proportional system UI typography for normal reading and
monospace only for identifiers and technical evidence. Both light and dark
themes use the same semantic layout and status language.

The visible theme control updates `aria-pressed`, never wraps on the phone
layout, and stores the selected value under `localStorage["sglab-theme"]`.
Navigation to another page retained the selected dark theme during the audit.
When no stored choice exists, the operating-system preference is used.

## Accessibility baseline

- one `h1` per page and ordered `h2`/`h3` content hierarchy;
- labelled primary and dashboard-section navigation;
- visible keyboard focus treatment;
- form controls have associated or wrapping labels;
- buttons have visible text or accessible names;
- tables retain semantic headers;
- status includes text and is not conveyed by color alone;
- technical disclosures use keyboard-operable `<details>`;
- blind response controls remain hidden until a valid pair exists;
- phone interaction targets are at least 44 pixels in the audited primary
  paths.

This is a practical baseline, not a formal WCAG conformance claim.

## Console, network, and performance

Normal application routes produced no console exceptions and no failed
network requests. The deliberate unknown route produced the expected HTTP 404
only. Dashboard API requests completed successfully.

The UI continues to render bounded collections: initial decision, lane,
candidate, event, hypothesis, and revision views show a small first page with
an explicit Show more control. No page renders thousands of DOM rows. The
fixture remains approximately 0.72 MiB and local view-model construction
remains below the Phase-A recorded 20 ms maximum sample.

## Remaining issues

No blocker-level UI issue remains.

Known non-blocking limitations:

- the research dashboard is intentionally a long operational document, even
  though each individual collection is bounded;
- the phone layout prioritizes readability over simultaneous cross-column
  comparison;
- the comparison execution worker remains outside this UI-review milestone;
- the measured stateless recommendation still rests on one controlled pair;
- browser chrome may display its own `--no-sandbox` warning; that warning is
  outside the rendered application.

## Verification

- focused UI/fixture/comparison/HTTP tests: 45/45;
- complete safe suite: 175/175, twice, plus the required `make test`;
- `make doctor`: pass;
- `make check`: pass;
- `make benchmark-smoke`: pass;
- `make dashboard-smoke`: pass;
- loopback HTTP tests: pass;
- SQLite schema: 10;
- SQLite `integrity_check`: `ok`.

```text
ui_demo_workspace_created: true
all_pages_inventoried: true
before_playwright_audit_completed: true
raw_json_removed_from_primary_views: true
semantic_action_renderers_created: true
decision_effect_view_created: true
table_overflow_fixed: true
excessive_row_height_fixed: true
responsive_audit_completed: true
accessibility_baseline_completed: true
comparison_pages_audited: true
console_errors_remaining: 0
network_errors_remaining: 0
after_playwright_audit_completed: true
http_tests_passed: true
sqlite_integrity_check: ok
remaining_ui_blockers: []
ready_for_real_user_ui_testing: true
```

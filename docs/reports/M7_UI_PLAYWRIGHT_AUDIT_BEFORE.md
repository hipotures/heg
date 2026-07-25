# M7 UI Playwright audit — before redesign

This report is the frozen visual baseline for the deterministic UI review workspace at commit `dbedf657e0932c2c69e33d01625b95377206437d`. The rendered application was inspected through `playwright-cdp` at `1920×1080`, `1440×900`, `1280×720`, `1024×768`, and `390×844`.

No model, authentication material, paid comparison, App Server turn, or graph-search campaign was used. Normal routes produced no console or network failures; the explicit unknown route correctly returned HTTP 404.

## Exact page inventory

The application currently has six document-route shapes:

- `/`
- `/comparisons`
- `/comparisons/new`
- `/comparisons/<suite-id>`
- `/comparisons/<suite-id>/blind`
- `/model-cost-profiles`

Campaign lists/details, hypotheses, AI decisions, lanes, candidates, logs and events are not separate pages. They are embedded as twelve sections of `/`. The audit covered the dashboard, all comparison lifecycle states represented by the fixture, an empty filtered list, prepared/running/completed/invalid/timed-out/read-only details, blind comparison, cost profiles and the 404 state.

## Blockers

### 1. The dashboard is not a bounded layout

At desktop width `1905 px`, the document is `4408 px` wide. The decisions table alone is `4359 px`, with 260 visible elements crossing the viewport. At mobile width `375 px`, the document remains `4392 px` wide, 1084 elements cross the viewport, and one table row reaches `1090 px` high.

The mobile screenshot is the clearest evidence: nearly all content is rendered into a tiny strip at the left of a 4392-pixel canvas.

- [Desktop dashboard](ui-playwright/before/dashboard-1920x1080.png)
- [Mobile dashboard](ui-playwright/before/dashboard-390x844.png)

### 2. Raw JSON is the primary interface

The dashboard contains 165 cells beginning with JSON. The completed comparison has 13 primary raw blocks totalling 6728 characters. Cost profiles are a 3790-character JSON block. Both blind answers are JSON strings.

This prevents fast scientific review and directly violates the required meaning-first presentation. JSON should remain available as secondary technical evidence, not be the main reading path.

- [Completed comparison](ui-playwright/before/comparison-completed-1440x900.png)
- [Blind comparison](ui-playwright/before/comparison-blind-1280x720.png)
- [Cost profiles](ui-playwright/before/model-cost-profiles-1024x768.png)

### 3. Research information architecture is a single 10k–22k pixel page

The dashboard renders 121 table rows, 40 candidates and all research domains at once. There is no route-level place for a researcher to focus on campaigns, decisions, lanes, candidates or events. Long identifiers and raw nested parameters make comparison across records difficult.

## High-severity findings

- The UI is dark-only, all-monospace, and has no theme switch. The redesign must provide first-class light and dark themes, a visible accessible control, `localStorage` persistence, and no flash of the wrong theme on navigation.
- Completed and historical read-only suites still show Prepare, Authorize, Start and Stop buttons.
- Prepared, invalid and timed-out suites show blind/rating affordances even when no valid pair or valid rateable turn exists.
- The comparison list uses an eleven-column table. It avoids desktop overflow but requires an unlabelled 995-pixel local scroll region on mobile.
- The new-suite desktop grid crowds the maximum-token field beyond the visual card boundary. The hard inference maximum is not visually prominent.
- Unknown routes fall through to the unstyled standard-library 404 page and lose all application navigation.

## Medium-severity findings

- Form controls have associated accessible names, and heading order is mostly coherent.
- Table header rows are exposed as ordinary cells rather than proper column headers.
- The dashboard has 130 visible controls smaller than 44 pixels; the comparison list has 18 and the new-suite page has 17.
- Status is dense text without a consistent semantic badge or icon/text pairing.
- The dashboard repeatedly polls six APIs. All returned `200`, but the idle network log grows rapidly.
- Desktop cost-profile labels collide, floating-point artifacts such as `0.6000000000000001` are visible, and nullable rates have no semantic explanation.

## Page-by-page evidence

| Page/state | Purpose | Key defect | Severity | Screenshots |
| --- | --- | --- | --- | --- |
| Dashboard | Research control and telemetry | Page-wide overflow, raw JSON, no pagination | Blocker | [1920](ui-playwright/before/dashboard-1920x1080.png), [390](ui-playwright/before/dashboard-390x844.png) |
| Comparisons | Suite filtering and overview | Dense eleven-column table; weak mobile scan path | High | [1440](ui-playwright/before/comparisons-1440x900.png), [390](ui-playwright/before/comparisons-390x844.png) |
| Empty comparison filter | Empty state | Message exists only after interactive filtering and remains inside a full table shell | Low | [1024](ui-playwright/before/comparisons-empty-filter-1024x768.png) |
| New suite | Plan creation | Crowded grid; inference cap lacks emphasis | Medium | [1440](ui-playwright/before/comparisons-new-1440x900.png), [390](ui-playwright/before/comparisons-new-390x844.png) |
| Comparison detail | Plan, turns, cost, validity and ratings | Raw plan/validity/ratings; lifecycle controls disagree with state | Blocker | [Completed](ui-playwright/before/comparison-completed-1440x900.png), [Mobile](ui-playwright/before/comparison-completed-390x844.png), [Running](ui-playwright/before/comparison-running-1280x720.png), [Timeout](ui-playwright/before/comparison-timeout-1280x720.png), [Historical](ui-playwright/before/comparison-historical-1280x720.png) |
| Blind pairwise | Human comparison | Answers are raw JSON | Blocker | [1280](ui-playwright/before/comparison-blind-1280x720.png), [390](ui-playwright/before/comparison-blind-390x844.png) |
| Cost profiles | Versioned cost configuration | Existing profiles are raw JSON; labels collide | High | [1024](ui-playwright/before/model-cost-profiles-1024x768.png), [390](ui-playwright/before/model-cost-profiles-390x844.png) |
| 404 | Recovery from unknown URL | Browser-default page; no navigation or theme | High | [1024](ui-playwright/before/error-404-1024x768.png) |

## Design direction

The redesign will use a calm editorial laboratory-notebook character: proportional UI typography, monospace only for identifiers and technical evidence, semantic status language, compact expert workflows and bounded lists.

Light and dark themes are equal requirements. The selection will be explicit, keyboard accessible and remembered in the browser. Raw data remains available through `<details>` technical panels and safe artifact links.

## Implementation boundary

This report and its screenshots were completed before any production UI change in Phase B. The machine-readable findings are in `M7_UI_PLAYWRIGHT_AUDIT_BEFORE.json`.

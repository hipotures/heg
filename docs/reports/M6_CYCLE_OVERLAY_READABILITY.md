# M6 cycle-overlay readability

Date: 2026-07-28

## Scope

GitHub issue #1 requested a visualization-only improvement to visible cycle
layers in the live graph view. The implementation changes only static
JavaScript, CSS, focused rendering-contract tests, and current documentation.
The graph API, persistence, search, mutation, scoring, witness counting, and M4
verification are unchanged.

## Rendering contract

- A fixed palette maps a cycle length to the same color on highlighted edges,
  vertex membership sectors, layer controls, and graph legend samples.
- Highlighted edges are canonicalized from the lower endpoint ID to the higher
  endpoint ID.
- When two or more visible bounded cycles share an edge, 12-unit colored
  segments repeat in ascending cycle-length order.
- Layer toggles recompute shared-edge patterns and vertex membership from only
  the remaining visible cycles.
- Vertices render above overlays: hollow for zero memberships, solid for one,
  and as equal clockwise sectors in ascending length order for multiple
  memberships.
- Exact M4 witnesses keep a double authority outline; the inner stroke and
  vertex ring use the stable color assigned to the witness length.
- Ordinary graph edges retain their previous muted stroke.

## Acceptance evidence

Focused automated tests cover the deterministic color source, canonical edge
keys, shared-edge ordering and dash offsets, generated vertex sectors, shared
legend color tokens, and the absence of the former catch-all cycle color.

Rendered browser verification covers 1-, 2-, 3-, and 4-way overlaps, layer
toggle recomputation, exact-witness styling, light and dark themes, desktop and
mobile widths, page overflow, reachable controls, and console errors.

The first browser pass also caught an existing CSS-cascade defect: the hidden
empty-state element retained `display:grid`, pushed the graph SVG below its
clipped stage, and made the otherwise correct drawing invisible. The component
now explicitly applies `display:none` to that hidden state, with a focused
regression assertion.

## Verification results

- `node --check web/observatory.js`: passed.
- Focused visualization module: 12 tests passed.
- `make dashboard-smoke`: passed.
- `make doctor`: passed.
- `make test`: 307 tests passed.
- `make check`: passed.
- `make benchmark-smoke`: passed.
- Playwright/Chromium isolated synthetic fixture:
  - 1440 × 900, light theme: passed;
  - 1440 × 900, dark theme: passed;
  - 390 × 844, light theme: passed;
  - shared edges showed the expected 2-, 3-, and 4-color repeating order;
  - vertices showed hollow, solid, half, third, and quadrant membership states;
  - hiding and restoring C16 recomputed edges, sectors, accessible labels, and
    the legend;
  - no page-wide horizontal overflow, console errors, or failed asset requests.

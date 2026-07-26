# Adding a Dashboard View

## Principles

- semantic view model, not raw SQLite rows;
- bounded result count;
- no credentials/private absolute paths;
- meaningful empty/error/loading states;
- state-based controls;
- responsive desktop/mobile behavior;
- raw technical data only as secondary evidence.

## Steps

1. Define user question.
2. Add read-only view-model builder.
3. Add bounded API response.
4. Add semantic HTML/JS renderer.
5. Add exact status labels and accessible controls.
6. Add local polling only if data must refresh.
7. Add unit/HTTP tests.
8. Add Playwright desktop and mobile checks.
9. Add or update screenshot marker/documentation.

## Graph visualizations

Preserve graph identity independent of layout. 2D/3D coordinates are display
state only. Highlight witnesses without modifying adjacency.

## State-changing controls

- POST only;
- bearer protection;
- fixed allowlisted operation;
- no command/path input;
- persist request before asynchronous execution;
- disable impossible controls.

## Playwright checks

- no page-wide overflow;
- no console/network errors;
- correct lifecycle controls;
- readable long IDs;
- no leaked token/auth/path;
- focus and labels;
- theme persistence.

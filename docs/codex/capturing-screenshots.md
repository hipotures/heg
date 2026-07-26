# Capturing Documentation Screenshots

User docs contain machine-readable markers.

## Tool

Use the `playwright-cdp` MCP browser tools against a deterministic UI-demo
workspace unless a real state is required.

## Procedure

1. Read `docs/user/screenshot-plan.md`.
2. Locate marker by ID.
3. Start the documented workspace/server.
4. Navigate to the named page.
5. Set required viewport.
6. Wait for stable data/render.
7. Take full-page screenshot.
8. Use DOM bounding boxes and marker anchor text to crop precisely.
9. Verify no sensitive data.
10. Save at the specified path.
11. Replace marker with Markdown image and descriptive alt text.
12. Run link checks and Playwright smoke.

## Crop rules

- include section heading and necessary legend;
- exclude browser chrome;
- exclude unrelated sections;
- do not cut status badges or labels;
- keep enough surrounding context to orient the reader;
- use PNG;
- avoid upscaling;
- preserve readable text.

## Sensitive data scan

Reject screenshots containing:

- bearer token;
- auth path/hash/content;
- private runtime absolute path;
- personal browser profile data;
- unreviewed model reasoning;
- synthetic result not visibly labelled as demo.

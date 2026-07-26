# User Documentation Screenshot Plan

This page collects all screenshot markers embedded in the user guide.

## Capture workflow for Codex

1. Start a deterministic UI-demo workspace unless a real runtime state is
   explicitly required.
2. Open the dashboard with `playwright-cdp`.
3. Set the requested viewport.
4. Capture a full-page screenshot.
5. Locate the named headings/labels in the marker.
6. Crop to the smallest rectangle that includes all requested elements.
7. Remove browser chrome unless explicitly requested.
8. Check that no token, auth path, private runtime path, or credential hash is
   visible.
9. Save to the exact path in the marker.
10. Replace the marker with:

```markdown
![Concise descriptive alt text](../assets/screenshots/user/...png)
```

Keep the marker description in image metadata or the commit message.

## Markers

| ID | Source page | Required state |
|---|---|---|
| `USR-HOME-01` | Dashboard | Populated campaign |
| `USR-CONCEPTS-01` | Dashboard | At least two attempts |
| `USR-QUICKSTART-01` | Campaign plan | Prepared, unauthorized |
| `USR-QUICKSTART-02` | Dashboard | Prepared/pre-start |
| `USR-QUICKSTART-03` | Dashboard | Running campaign |
| `USR-WORKSPACE-01` | Dashboard | Visible workspace identity |
| `USR-CAMPAIGN-01` | Dashboard | Assessment and hypotheses |
| `USR-CAMPAIGN-02` | Dashboard | Multiple lane states |
| `USR-RESUME-01` | Resume preview | Fault or terminal campaign |
| `USR-RESUME-02` | Attempt history | Successful Resume |
| `USR-DASHBOARD-01` | Observatory | Live frontier or best graph |
| `USR-DASHBOARD-02` | Dashboard | Mobile 390×844 |
| `USR-COMPARISON-01` | New comparison | Two arms |
| `USR-COMPARISON-02` | Prepared comparison | Fingerprinted plan |
| `USR-COMPARISON-03` | Blind comparison | Two valid responses |
| `USR-VERIFY-01` | Candidate/M4 panel | Exact rejection with witness |
| `USR-TROUBLE-01` | Campaign fault panel | `paused_fault` |

Search all markers:

```bash
rg -n '\[screenshot:' docs/user
```

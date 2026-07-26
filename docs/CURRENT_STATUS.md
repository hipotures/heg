# Current Production Status

Documentation baseline: `a25579d0a6cd088d2c0687664312e9c3b07404b7` (`Bound Director repair context`).

## Current architecture

- Workspace-local SQLite schema: **15**
- Production Director context mode: **stateless turns**
- Campaign continuity: **stable campaign ID with immutable execution attempts**
- Scientific memory: **deterministic, bounded, versioned snapshots**
- Candidate targets: **durable pins and immutable snapshots**
- Exact certification: **M4 independent verification**
- Dashboard: **local standard-library HTTP control plane with semantic views and live scientific visualizations**
- Comparison system: **fingerprinted measurement-only suites with bounded workers**

## Proven continuity behavior

A deterministic two-attempt real-kernel demonstration:

- kept the same campaign ID;
- changed application worker slots from 2 to 16;
- increased cumulative evaluations from 69,995 to 140,918;
- reused verified checkpoints;
- preserved hypotheses and prior M4 outcomes;
- kept scientific memory below the hard limit;
- used no real model or auth.

## Current scientific-memory defaults

| Setting | Value |
|---|---:|
| Soft trigger | 24,576 bytes |
| Hard limit | 32,768 bytes |
| Periodic snapshot | Every 5 valid cycles |
| Boundary snapshots | Pause, stop, fault, budget/deadline, Resume |

## Current operating model

- Fresh campaigns are independent.
- Resume continues the same campaign.
- Invalid Director actions are never executed.
- One bounded stateless repair is available for an invalid state.
- Repair context includes exact validation errors and invalid-response SHA-256,
  not a duplicated full rejected response.
- Hypothesis evidence fields require exact evidence-registry IDs.
- Model tools, shell, code, and arbitrary file actions are not available to the
  Director.
- Only M4 can certify a counterexample.

## Known limitations

- The implemented target is a research target; no mathematical solution is
  claimed.
- Application worker slots are not OS-level CPU isolation.
- Optional external tools require their own installation/version evidence.
- Historical implementation reports remain lengthy and should be read as
  evidence, not current operating instructions.
- Screenshot placeholders in user docs still require capture.

For detailed historical progress, see
[Implementation Status](IMPLEMENTATION_STATUS.md) and [Evidence Reports](reports/README.md).

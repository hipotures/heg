# User Guide

This guide is for researchers and operators who run HEG experiments without
modifying the implementation.

## Start here

1. [Core concepts](concepts.md)
2. [Quickstart](quickstart.md)
3. [Campaigns](campaigns.md)
4. [Pause, continue, stop, and Resume](resume.md)
5. [Dashboard](dashboard.md)
6. [Candidates and exact verification](candidates-and-verification.md)
7. [Troubleshooting](troubleshooting.md)

For model and context experiments, see [Comparisons](comparisons.md).

## What you control

In the normal Active Director workflow, the operator chooses the research
duration or an until-success stop condition. The Director chooses reviewed
scientific actions such as algorithms, graph families, lane parameters,
diagnostics, and verification scheduling.

At Resume, the operator may also change execution resources such as
application worker slots, active-lane limits, lane memory, and verifier
concurrency without changing the campaign's scientific identity.

## What the system controls

- search-lane creation and adaptation;
- bounded graph mutations;
- checkpointing;
- candidate retention;
- exact-verifier scheduling;
- scientific-memory snapshots;
- resource and process lifecycle;
- fail-closed response to integrity or protocol failures.

## What counts as success

Only a persisted M4 certificate produced by the independent exact-verifier
paths counts as a verified counterexample. A low heuristic score, a capped
witness count, or a single verifier result is not success.

> [!IMPORTANT]
> Campaign progress is valuable even when no counterexample is found. The
> workspace retains hypotheses, explored regions, checkpoints, candidates,
> verification outcomes, and scientific-memory snapshots.

[screenshot: ID=USR-HOME-01; save as docs/assets/screenshots/user/dashboard/dashboard-overview.png; open the main dashboard for a populated campaign, crop from the “Research control room” header through the first complete row of campaign summary cards, include the workspace/campaign identity and current state, exclude browser chrome and lower detailed tables.]

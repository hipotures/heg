# Quickstart: First AI-Directed Campaign

This workflow prepares a bounded campaign before any credential access, then
starts the local dashboard and authenticated runtime.

## 1. Install and verify

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
make cyclecheck

make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

## 2. Create a workspace

```bash
sglab init --workspace ./workspace/my-first-campaign
```

The workspace owns its database and scientific artifacts.

For the shortest operator path, a persistent experiment configuration needs
only an ID:

```toml
[experiment]
id = "heg-ranked-001"
```

```bash
sglab experiment run --config ./experiment.toml
```

This creates the non-synthetic marker internally, imports the authorized
`~/.codex/auth.json`, verifies the immutable plan, and starts the campaign.
Running the same ID again resumes the latest resumable attempt. The reviewed
proposal ranker remains opt-in; add
`proposal_ranking = "mutation_forge_stage4r_v1"` under `[search]` only when
you explicitly want ranked mutation lanes. No ranker is selected by default.

The lower-level prepare/auth/start workflow below remains available for
auditing each boundary separately.

## 3. Prepare the campaign

```bash
sglab research-campaign prepare   --workspace ./workspace/my-first-campaign   --time-limit 1h
```

Preparation is deterministic. It creates:

- campaign ID;
- immutable plan artifact;
- plan fingerprint;
- Director, search, verifier, and runtime limits;
- no model turn;
- no auth copy;
- no search lane.

Review the printed plan and fingerprint.

To run without an LLM, prepare the explicit passive contract instead:

```bash
sglab research-campaign prepare \
  --workspace ./workspace/my-first-campaign \
  --time-limit 1h \
  --director-mode passive \
  --passive-seed 37
```

The passive seed and `balanced_v1` policy version are part of the reviewed
plan and fingerprint.

[screenshot: ID=USR-QUICKSTART-01; save as docs/assets/screenshots/user/quickstart/prepared-campaign-plan.png; open the prepared campaign page, crop the complete “Prepared plan” or equivalent immutable plan card including campaign ID, fingerprint, Director contract, stop condition, maximum turns, search limits, and the “not authorized/not started” state; exclude browser chrome and unrelated comparison cards.]

## 4. Import authorized Codex credentials

Skip this step for a passive plan. Passive mode does not read a Codex home,
copy credentials, start App Server, or consume model tokens.

Use an explicitly authorized Codex home. The runtime copies only `auth.json`
into a private campaign home.

```bash
sglab research-campaign auth-import   --workspace ./workspace/my-first-campaign   --campaign-id <campaign-id>   --plan-fingerprint <fingerprint>   --from-codex-home /home/<user>/.codex
```

> [!WARNING]
> Credential import is a separate authorization boundary. Confirm that the
> campaign ID and fingerprint are exactly the values you reviewed.

## 5. Start the dashboard

```bash
sglab serve   --workspace ./workspace/my-first-campaign   --host 127.0.0.1   --port 8788
```

Open `http://127.0.0.1:8788`.

[screenshot: ID=USR-QUICKSTART-02; save as docs/assets/screenshots/user/quickstart/dashboard-prestart.png; crop the main campaign control section before runtime start, including campaign state, Director authentication/connection status, stop condition, and the Start or authorization control; exclude lower telemetry sections.]

## 6. Start the exact prepared plan

```bash
sglab research-campaign start   --workspace ./workspace/my-first-campaign   --time-limit 1h   --plan-fingerprint <fingerprint>
```

The start path recomputes the fingerprint before App Server startup in `llm`
mode or before deterministic scheduler startup in `passive` mode.

## 7. Observe

The dashboard updates automatically. Watch:

- current campaign and attempt state;
- Director assessment and hypotheses;
- lane trajectories and checkpoints;
- candidates and exact-verifier status;
- scientific-memory version and size;
- resource/fault state;
- live search-frontier visualization.

[screenshot: ID=USR-QUICKSTART-03; save as docs/assets/screenshots/user/quickstart/running-campaign.png; crop a running dashboard from the campaign status cards through the top of the live search-frontier visualization, ensuring at least one active lane, one Director decision, current scientific-memory version, and current attempt are visible.]

## 8. Pause or stop

For a live attempt:

```bash
sglab research-campaign pause --workspace ./workspace/my-first-campaign
sglab research-campaign continue --workspace ./workspace/my-first-campaign
sglab research-campaign stop --workspace ./workspace/my-first-campaign
```

Use [Resume](resume.md) to create a new attempt after time exhaustion,
operator stop, process interruption, or a repaired infrastructure fault.

## 9. Check status and export

```bash
sglab research-campaign status --workspace ./workspace/my-first-campaign

sglab research-campaign export   --workspace ./workspace/my-first-campaign   --campaign-id <campaign-id>   --output ./campaign-export.zip
```

> [!IMPORTANT]
> A completed campaign without an M4 certificate is a completed search, not a
> proof that no counterexample exists.

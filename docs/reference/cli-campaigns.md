# Campaign CLI Reference

## Initialize

```bash
sglab init --workspace <workspace>
```

Creates the workspace structure and SQLite database.

For a first-real-graph campaign, the operator-facing initializer can create
the required non-synthetic marker atomically:

```bash
sglab init --workspace <workspace> --kind first-real-graph-campaign
```

`research-campaign prepare` performs the same upgrade only for a fresh,
marker-less workspace. It rejects populated or incompatible workspaces.

## One-command experiment run

The compact operator contract is a persistent TOML identity:

```toml
[experiment]
id = "heg-ranked-001"
```

Run it with:

```bash
sglab experiment run --config experiment.toml
```

The command creates or validates the private workspace marker, prepares the
fixed one-hour Director contract, imports only the authorized `auth.json` from
`~/.codex`, verifies the immutable plan fingerprint, and starts the campaign
in its own session. Re-running the same `experiment.id` resumes the latest
resumable attempt automatically; changing the ID creates a separate
experiment workspace. Internal campaign IDs, attempt IDs, and fingerprints
remain durable provenance rather than operator inputs. Proposal ranking stays
disabled unless the reviewed ID is explicitly present in the optional
`[search] proposal_ranking` field.

## Prepare

```bash
sglab research-campaign prepare   --workspace <workspace>   --time-limit 1h
```

Prepare the no-LLM contract with a reproducible seed:

```bash
sglab research-campaign prepare   --workspace <workspace>   --time-limit 1h   --director-mode passive   --passive-seed 37
```

Preparation creates the campaign and exact fingerprint without auth or model
access.

For an LLM Director campaign, the reviewed proposal ranker is opt-in and
plan-bound:

```bash
sglab research-campaign prepare \
  --workspace <workspace> \
  --time-limit 1h \
  --director-mode llm \
  --proposal-ranking mutation_forge_stage4r_v1
```

Omitting the option keeps ranking disabled. Resume has no ranking switch.

## Compliance and auth

```bash
sglab ai-director preflight --workspace <workspace>
sglab ai-director compliance-audit --workspace <workspace>

sglab research-campaign auth-import   --workspace <workspace>   --campaign-id <campaign-id>   --plan-fingerprint <fingerprint>   --from-codex-home /home/<user>/.codex
```

## Start

```bash
sglab research-campaign start   --workspace <workspace>   --time-limit 1h   --plan-fingerprint <fingerprint>
```

The runtime recomputes the fingerprint before private runtime startup.
For a passive prepared plan, the plan already supplies the mode and seed; no
auth import is required.

An unprepared bounded passive campaign may be started explicitly:

```bash
sglab research-campaign start   --workspace <workspace>   --time-limit 1h   --director-mode passive   --passive-seed 37
```

## Status and live control

```bash
sglab research-campaign status --workspace <workspace>
sglab research-campaign pause --workspace <workspace>
sglab research-campaign continue --workspace <workspace>
sglab research-campaign stop --workspace <workspace>
```

`continue` affects a live paused attempt.

## Resume

Preview:

```bash
sglab research-campaign resume   --workspace <workspace>   --campaign-id <campaign-id>   --additional-time 2h   --cpu-workers 16   --max-active-lanes 8   --lane-memory-bytes 536870912   --verifier-concurrency 2   --repair-acknowledgement "<description>"   --preview
```

Start a new attempt by reviewing the same contract and omitting `--preview`.

Resume preserves campaign ID and scientific state; it creates a new execution
attempt.

Add `--director-mode passive` or `--director-mode llm` only when explicitly
selecting the reviewed mode for the new attempt. Omitting it preserves the
current mode. A transition to `llm` requires an exact-plan auth import; a
passive attempt never accesses auth.

## Export

```bash
sglab research-campaign export   --workspace <workspace>   --campaign-id <campaign-id>   --output ./campaign.zip
```

Verify the frozen ranker identity and one bounded worker call without a
benchmark:

```bash
sglab proposal-ranking doctor
```

## Duration syntax

Where supported, durations accept seconds or suffixes such as `s`, `m`, `h`,
and `d`.

## Normal-versus-legacy boundary

Normal campaigns expose the stop condition, `llm|passive` orchestration mode,
and Resume resource overrides. Scientific algorithms, graph orders, mutation
parameters, and hot-loop operations remain controlled by reviewed contracts,
not arbitrary CLI input.

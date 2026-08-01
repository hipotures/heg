# ADR 0018: Proposal-ranking CLI activation

## Decision

The Mutation Forge Stage 4R ranker is activated only by the reviewed catalog
ID `mutation_forge_stage4r_v1` for an LLM Director campaign on
`research-campaign prepare` (and the equivalent allowlisted start path). The
nullable selection is persisted in and fingerprinted by the immutable campaign
plan. Every attempt, restart, fork, and checkpoint/resume inherits that value;
Resume cannot toggle it.

The supported operator shortcut is a persistent TOML identity containing
`[experiment].id`, executed with `sglab experiment run --config`. It creates
or validates an empty first-real-graph workspace marker, imports the explicitly
authorized Codex home, revalidates the plan fingerprint, and starts or resumes
the matching campaign. Generated campaign/attempt identifiers remain internal
provenance. `prepare` and `init --kind first-real-graph-campaign` share the
same fail-closed marker upgrade rules.

Passive scheduling remains unchanged. Director context advertises the same
capability, while semantic validation rejects disabled activation, omission on
an enabled mutation start, random-restart ranking, and patch attempts. Status,
export, API, and dashboard projections expose the plan-bound selection.

## Consequences

Omitting the option preserves existing lanes and starts no ranking worker. The
reviewed catalog boundary prevents arbitrary source, path, or environment
activation. The worker remains host-owned and fail-closed; HEG scoring and M4
certification remain independent. The retained performance decision is not a
rollout authorization: production activation remains blocked by the existing
`NO_GO` result.

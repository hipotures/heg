# M6 action-applicability contract repair

Date: **2026-07-24**

The deterministic repair started from
`bd85c18023eab9ae305628c19dc3e55c3c54cc5d`. No model inference, auth access,
authenticated App Server turn, graph-search batch, compaction operation, or
tool call was used. `planning/` and the preserved S2 runtime artifacts remain
untouched.

## Corrected contract

The submitted, post-compaction DirectorStateV2 now produces three explicit
reference roles:

- `evidence_ids`: identifiers visible as scientific or historical evidence;
- `advisory_target_ids`: identifiers that may be discussed as recommendation
  targets;
- `executable_target_ids`: current objects that may be used in executable
  action fields.

Each retained registry entry includes the identifier, object kind, lifecycle
status, exact DirectorStateV2 JSON paths, and the three role flags. Each role
is serialized separately with its own SHA-256 beside the turn request.
Round-trip and SQLite-reopen tests prove stable reconstruction.

The applicable action space is rebuilt from the actual submitted state. The
same generated space drives:

- `DirectorStateV2.allowed_action_space`;
- the prompt's explicit action description;
- the structured output schema;
- `DecisionContext.applicable_action_types`;
- executable-target validation.

Lane visibility alone never grants executability. Lane-bound variants are
omitted when no active executable lane exists, and dynamic lane enums contain
only active targets.

## Preserved S2 reclassification

The raw S2 response and runtime evidence were not changed.

```text
S2_schema_valid: true
S2_original_semantic_validation:
  indeterminate_due_to_action_applicability_contract_mismatch
S2_selected_action: stop_lane
S2_target_lane_visible_as_evidence: true
S2_target_lane_executable: false
S2_action_was_exposed_by_submitted_schema: true
```

The response is not valid under the corrected action space because
`stop_lane` should not have been offered. This is a deterministic client
contract defect, not an independent model-quality failure.

## Fresh reduced-screen preparation

The offline preparation again contains exactly `S2 → P1 → P2`, no fourth
slot, no search or lane execution, no action dispatch, no compaction, and a
300-second timeout.

For A1 the applicable actions are:

- `start_lane`: capacity exists for a reviewed lane;
- `request_diagnostic`: submitted evidence subjects exist;
- `set_review_trigger`: review scheduling is lane-independent.

For A4 the applicable actions are:

- `start_lane`: capacity exists for a reviewed lane;
- `promote_candidate`: one retained best candidate exists;
- `request_diagnostic`: submitted evidence subjects exist;
- `schedule_verification`: one retained candidate can be submitted to M4;
- `set_review_trigger`: review scheduling is lane-independent.

All three A4 lane IDs are explicitly historical/stopped evidence. The active
executable lane list is empty, so `patch_lane`, `fork_lane`, `restart_lane`,
`stop_lane`, and `reallocate_resources` are absent from both prompt and
schema. Focused tests construct at least one locally valid output for every
action that remains available.

S2 and P2 remain identical:

| Artifact | SHA-256 |
|---|---|
| DirectorStateV2 | `94347f651d821bcbf502a517f9913f3924d89afee308f667d9adff39ee8db4bd` |
| prompt | `d9ae1fd0e157825b97e4ad8d7b657f744a37c118c0a66bcbd7064f373358139c` |
| output schema | `6f7293c8241d316c4c185b172828ef23c84f3369939f7d89d3a8de79bfde04e2` |
| evidence registry | `48571c03d8b8da9e922fbd0710bf1f98a9a3f51826ea5656333ff0f165cb5428` |
| advisory registry | `2f2c50f29a48c15157abc726997d8bfc1d37fb977873fd7a7d1d3d5e588ac49d` |
| executable registry | `07b0af203732db6b02671870fefc1bd8a54826c78f8b38f5d861f199fbc85b30` |
| applicable action space | `d0709fbf795ba05ae73cbfab19f2cc23ddb0f491b8c4fc542fb6eca842874461` |

The A4 state is 18,111 bytes, ancestry is 5,611 bytes, historical outcomes
are 3,593 bytes, and the conservative client-owned input estimate is 7,827
tokens. Every context budget passes.

## Verification

- targeted action/registry/prompt/timeout suite: 22 passed;
- focused action-applicability suite: 7 passed;
- SQLite v9 migration, integrity, and registry reconstruction: 8 passed;
- non-network safe suite: 128 passed twice;
- `make doctor`, `make check`, and `make benchmark-smoke`: passed;
- SQLite `user_version=9`, `integrity_check=ok`.

The full suite reached 128 passing tests, then five HTTP/dashboard tests
failed because this execution sandbox forbids opening a loopback socket.
`make dashboard-smoke` failed for the same environmental reason. Escalated
execution was requested and rejected by the environment's approval layer.
These are verification-environment blockers, not observed assertion failures.

Fresh authenticated authorization is not requested yet because the loopback
HTTP and dashboard gates are not complete.

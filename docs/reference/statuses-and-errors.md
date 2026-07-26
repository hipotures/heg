# Statuses and Error Codes

## Scientific versus infrastructure

Always distinguish:

- scientific negative evidence;
- invalid model output;
- stale action target;
- exact-verifier rejection;
- infrastructure/protocol/resource fault;
- incomplete/unknown verification.

## Common campaign conditions

| Condition | Meaning | Resume? |
|---|---|---|
| `paused_by_operator` | Live attempt paused | Continue or Resume |
| `stopped_by_operator` | Attempt ended by operator | Yes |
| `deadline_reached` / `budget_exhausted` | Attempt budget ended | Yes, with additional budget |
| `paused_fault` | Fail-closed non-scientific fault | Yes after repair acknowledgement |
| `certified_success` | M4 certificate persisted | No normal Resume |
| `scientifically_invalidated` | Prior scientific results invalid | Start fresh campaign |

## Director validation

| Status | Meaning |
|---|---|
| `completed_valid` | Schema and semantic validation accepted |
| `completed_invalid` | Final response exists but was invalid |
| `schema_invalid` | Structure not allowed |
| `semantic_invalid` | Structure valid but contract violated |
| `stale_target` | Target no longer executable |
| action ID collision | Non-idempotent workspace ID reuse |

## Verification

| Status | Interpretation |
|---|---|
| `INVALID_CANDIDATE` | Explicit rejection/witness |
| `COUNTEREXAMPLE_VERIFIED` | Complete M4 agreement |
| timeout/memory/error | Unknown |
| disagreement | Unknown and review-triggering |

## Runtime failure domains

```text
byte_quota
single_file_quota
log_quota
filesystem_policy
accounting_error
process_lifecycle
app_server_protocol
authentication
model_contract
```

Do not display a numeric quota comparison unless measured current/peak is
actually greater than limit.

## Context

`scientific_state_overflow` means no safe bounded state could be produced
without losing non-droppable facts. No inference should occur.

`DirectorContextBudgetExceeded` means the final reduced Director state or the
complete client-owned request context exceeded its configured gate. Historical
detail that the scientific-memory policy permits dropping is reduced before
this final decision. The complete-request pass uses the exact excess plus
headroom and rebuilds the prompt, registries, and schema; a pre-reduction size
alone is not grounds for the fault.

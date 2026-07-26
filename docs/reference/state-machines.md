# State Machines

## Campaign

Representative states:

```text
prepared
running
paused_by_operator
stopped_by_operator
deadline_reached
budget_exhausted
paused_fault
interrupted
certified_success
scientifically_invalidated
```

Resume support depends on state and fault classification.

## Execution attempt

```text
prepared → running → terminal
```

Terminal outcomes include budget/deadline, operator stop, fault, interruption,
and certified success.

## Director turn

```text
requested
started
in_progress
completed
failed
aborted
timed_out
```

Final answer and usage are nullable.

## Lane

```text
created
starting
running
paused
stopping
stopped
completed
failed
blocked
```

Process generation may change while lane identity remains stable.

## Candidate

Representative states:

```text
retained
promoted
pinned
verification_queued
verification_running
rejected
certified
stale
```

## Verification job

```text
queued
running
completed
timed_out
failed
cancelled
```

A terminal completed job is not repeated on Resume.

## Comparison suite

```text
draft
prepared
authorized
running
completed
failed
stopped
```

## Comparison arm

```text
planned
preflight
auth_prepared
server_started
thread_ready
inference_reserved
inference_started
completed
schema_invalid
semantic_invalid
timed_out
aborted
failed
blocked
stopped
```

Exact persisted values are authoritative. UI labels may derive a safer
human-readable description for legacy rows without rewriting them.

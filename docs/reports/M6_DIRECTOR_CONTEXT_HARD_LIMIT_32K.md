# M6 Director client-context hard limit at 32,000

Date: 2026-07-26

## Change

`CLIENT_ESTIMATED_TOKENS_MAX` increased from 16,000 to 32,000. The
complete-request soft target remains 15,000 tokens, and the byte estimate
remains:

```text
ceil(client-owned UTF-8 bytes / 4)
```

The gate still measures base instructions, prompt, and output schema together
and still runs before inference.

## Deterministic acceptance

A focused regression builds a complete request whose estimate is above 16,000
and at most 32,000. Its measured size is 101,741 bytes / 25,436 estimated
tokens, and it is accepted by the request-size report. The existing
oversized-context regression scales its payload from the configured constant
and confirms that a request above 32,000 still raises
`DirectorContextBudgetExceeded` before a Director turn.

The full test suite, compile gate, benchmark smoke, dashboard smoke, and the
installed Codex App Server protocol audit are the acceptance gates. The
protocol audit uses neither authentication nor a model turn.

## Unchanged safety properties

- deterministic compaction targets 15,000 tokens;
- exact-verifier facts and current executable IDs are non-droppable;
- an irreducible safe-state floor is recovered deterministically;
- the measured hard-gate inequality controls the fault;
- no campaign was resumed as part of this limit change.

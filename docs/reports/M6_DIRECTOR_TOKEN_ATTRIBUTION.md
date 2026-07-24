# M6 Director context and token attribution

Date: **2026-07-24**
Source campaign:
`ai-experiment-163b7b6f9d6c45e1be1352f64e025202`
Source commit: `a9ea28bcf9a86fd5d2332343a26fb3a7e56a3df6`

## Scope and method

This audit read the four preserved application request artifacts, four wire
logs, complete opaque rollout and persisted server usage. It did not read
authentication, start app-server or call a model. The source report and three
outcome hashes still match the values recorded when Phase B completed.

All byte columns below are measured UTF-8 bytes. JSON sections use the exact
canonical serializer used by the application. Definitions:

- Director state: complete `committed_research_snapshot` in the old prompt;
- current outcome: newest batch `observed_effect`;
- historical outcomes: canonical list of older batch `observed_effect` values;
- ancestry: canonical list of all ancestry sections in submitted outcomes;
- prior decisions: `recent_actions` with outcome and measured-result payloads
  removed;
- duplicate bytes: exact encoded bytes of syntactically repeated key names
  after their first occurrence. This is a structural duplication estimate,
  not an attribution of semantic or tokenizer cost;
- application request: retained prompt, output schema and correlation envelope;
- RPC request: exact JSON after the wire log's outbound direction marker.

The protocol does not expose tokenizer attribution by JSON field. No field
byte count is presented as a token count.

## Measured client content

| turn | Director state | base instructions | campaign | current outcome | historical outcomes | ancestry | prior decisions | prompt | app request | RPC request |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A1 | 4,545 | 682 | 182 | 0 | 2 | 2 | 2 | 9,584 | 31,585 | 31,662 |
| A2 | 91,227 | 682 | 184 | 42,025 | 2 | 37,778 | 1,433 | 96,491 | 126,930 | 127,007 |
| A3 | 192,771 | 682 | 178 | 43,949 | 10,199 | 43,592 | 2,964 | 198,206 | 238,391 | 238,468 |
| A4 | 246,329 | 682 | 178 | 41,401 | 22,467 | 49,159 | 4,444 | 251,922 | 297,161 | 297,238 |

The old Director state grew 54.2 times from A1 to A4. Campaign summary and
base-instruction sizes were effectively constant. Outcomes and ancestry caused
most client-owned growth, while persistent conversation history caused
additional server-side input growth that cannot be assigned to individual JSON
fields from the exposed protocol.

Syntactic duplication measurements:

| turn | repeated key names | duplicate occurrences | duplicate-key bytes |
|---:|---:|---:|---:|
| A1 | 41 | 131 | 1,652 |
| A2 | 146 | 3,631 | 42,788 |
| A3 | 211 | 7,877 | 93,011 |
| A4 | 211 | 10,071 | 119,955 |

Repeated score, witness, timing, operator, ancestry and artifact fields explain
the majority of this structural duplication. The estimate does not detect
semantically duplicated values under different keys.

## Server-reported usage

`tokenUsage.last`:

| turn | input | cached input | cache-write input | output | reasoning output | total |
|---:|---:|---:|---:|---:|---:|---:|
| A1 | 8,577 | 0 | 0 | 1,304 | 818 | 9,881 |
| A2 | 42,286 | 7,936 | 0 | 2,337 | 1,552 | 44,623 |
| A3 | 112,209 | 4,864 | 0 | 2,827 | 1,965 | 115,036 |
| A4 | 201,142 | 111,360 | 0 | 1,410 | 734 | 202,552 |

`tokenUsage.total.totalTokens` was:

```text
9881, 54504, 169540, 372092
```

Its successive increments are:

```text
9881, 44623, 115036, 202552
```

Those increments exactly equal the four `tokenUsage.last.totalTokens` values.
Therefore:

- `tokenUsage.last` is per-turn in this rollout;
- `tokenUsage.total` is cumulative for the thread;
- the report's **372,092** is the final cumulative server total;
- 372,092 also equals the sum of the four non-overlapping per-turn totals.

Cached input is a subset of input and reasoning output is a subset of output.
They must not be added to `totalTokens`. The server-provided total remains
authoritative.

## What cannot be attributed

The app-server protocol does not expose separate token counts for:

- baseInstructions;
- platform-owned instructions and environment wrapper;
- output schema;
- current prompt versus retained thread history;
- each outcome, ancestry or decision subsection;
- compacted-summary generation.

The byte measurements prove where client payload growth occurred. They do not
prove how the model tokenizer divided the 201,142 A4 input tokens. The large
A4 cached-input count is consistent with persistent history reuse, but the
protocol does not expose an exact cache attribution.

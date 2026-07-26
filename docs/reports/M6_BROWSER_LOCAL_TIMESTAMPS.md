# M6 browser-local timestamps

Date: 2026-07-26

## Contract

Primary UI timestamps use:

```text
locale: pl-PL
timezone: browser/system local timezone
date order: day-month-year
clock: 24-hour
seconds: visible
timezone abbreviation: visible
```

For a browser in `Europe/Warsaw`,
`2026-07-26T20:39:38Z` is rendered as local time at 22:39:38 on
26.07.2026.

## Coverage

- execution attempts;
- persistent Director turns;
- Director actions and events;
- hypotheses and lane revisions;
- legacy search runs;
- live-frontier publication and retained-candidate history;
- observatory refresh status;
- comparison-suite creation;
- timestamp-shaped values in primary semantic fields.

## Evidence preservation

The persisted/API timestamp is retained as the semantic `<time datetime>`
value and in its tooltip. Technical raw JSON remains unchanged. The change is
browser-only and does not rewrite SQLite, alter ordering, affect polling, or
modify scientific state.

## Acceptance

Static rendering tests require the shared local formatter at each explicit
timestamp surface and through nested semantic values. Dashboard and
observatory smoke checks validate that rendered `time` elements preserve the
source UTC value while their visible text uses the browser timezone, at desktop
and mobile widths.

The loopback browser check used `Europe/Warsaw` and confirmed:

- `2026-07-26T20:39:38Z` rendered as
  `26.07.2026, 22:39:38 CEST`;
- the observatory refresh clock used 24-hour time without an AM/PM suffix;
- no source UTC timestamp was exposed in primary visible text;
- the 390 px mobile viewport had no horizontal overflow.

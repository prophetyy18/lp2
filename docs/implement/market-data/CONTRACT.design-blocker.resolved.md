# design blocker: market-data / series.calendar

- found by: tester
- surface: contract
- conflict: >
  `market-data-api` gives `series.calendar` a **type** for its return value
  (`list[datetime]`) and nothing else. It declares no `behavior` block, so it
  promises neither that the returned datetimes are tz-aware nor what their
  values are — not the time of day a session is stamped at, and not which
  weekdays or holidays count as sessions. The sibling `series.get` in the
  same contract does declare "tz-aware UTC" for its `ts` column, so the
  silence here is an asymmetry within one file rather than a uniform
  convention. The Card routes this to ac-designer and cannot close it.
- evidence: >
  1. A consumer cannot tell a session at `2024-01-02T21:00:00+00:00` from a
     naive local `2024-01-02 16:00:00` — a 5-hour error that is a plausible
     session time and would be silently accepted. `backtest` declares
     `uses: [series.calendar]`, so the exposure is not hypothetical.
  2. The shared fixtures at `modules/market-data/testing.py` export
     `SESSION_HOUR_UTC = 21` and say in a comment that "whether it is the
     *right* hour is `series.calendar`'s Card to decide, not this file's" —
     and the Card does not decide it. The one value both other capabilities
     depend on is owned by nobody.
  3. The committed fixture CSVs carry sessions only on 2024-01-02/03/04, but
     the shared `WINDOW_END` is `2024-01-05T21:00:00+00:00` — a Friday with no
     bar. Whether 2024-01-05 is a session is therefore a live question the
     contract does not answer, and the answer changes what a test may assert.
- decision needed: >
  Should ac-designer extend `series.calendar` in `market-data-api` with a
  `behavior` block (or equivalent) stating the awareness and timezone of the
  returned datetimes and the rule that determines which instants are
  sessions — and should it make `series.get` and `series.calendar` agree?
- resolution: ac-designer changed architecture/contracts/market-data-api.yaml. Half 1 (closed): series.calendar now declares 'behavior: {timezone: tz_aware_utc}', and series.get declares the same, so the asymmetry the blocker named is gone and a consumer cannot receive a naive session time. Half 2 (not a contract question): which instants count as sessions is now stated in the contract as deliberately out of scope -- 'a property of the exchange calendar, not of this contract'. The concrete open case from the blocker's evidence 3 (is 2024-01-05, a Friday with no bar, a session) is therefore a Card decision, and docs/implement/market-data/series.calendar.card.md still does not make it. It is routed to module-designer as a Card refresh, not left open here.

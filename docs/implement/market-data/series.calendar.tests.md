# tests: market-data / series.calendar

- mode: full
- pass: 1
- card: docs/implement/market-data/series.calendar.card.md
- tests written: 11
- test file: tests/test_market_data_series_calendar.py

Result of pass 1: **11 tests, 11 failing**, every one with
`AttributeError: module 'api.series' has no attribute 'calendar'`. The tests
run; the implementation does not exist. That is the correct outcome for a
first pass, and it is the only reason they fail.

Because "they fail because the code is missing" is also what a suite of
assertions that cannot fail would produce, every test was separately run
against eight throwaway reference implementations in `/tmp` (never written
into `modules/**`) to confirm each one can actually fail. A correct reference
passes 11/11, and each deliberately broken variant is caught by the tests that
should catch it — exclusive bounds, weekend sessions, out-of-window leakage,
raising instead of returning `[]`, reading the wall clock instead of the
instant, returning `None`, and a one-day window spilling into the next day.
No test is dead, and no skip is used.

## card test plan coverage

- normal:    `test_normal_window_returns_a_list_of_datetimes` — the result is a
             `list` and every element is a `datetime`.
             `test_normal_window_contains_sessions_and_none_outside_it` — the
             window is non-empty, and no returned session escapes it.
- boundary:  `test_window_bounded_by_its_own_sessions_returns_both_bounds` —
             a window whose bounds are themselves sessions returns both, and
             returns everything between them.
             `test_a_session_on_the_split_point_appears_in_both_halves` —
             inclusive bounds checked where an off-by-one bites, and the two
             halves reassemble into the whole window.
             `test_one_day_window_returns_only_that_day` — a one-day window
             returns at most that day.
             `test_window_spanning_a_weekend_never_returns_a_weekend` — a
             window spanning Sat/Sun returns no weekend session.
             `test_window_containing_no_session_returns_an_empty_list` — `[]`,
             not `None` and not a raised error.
- invalid:   `test_start_equal_to_end_returns_an_empty_list` and
             `test_start_after_end_returns_an_empty_list` — both return `[]`.
             `test_start_given_in_another_timezone_matches_the_same_instant_in_utc`
             — a non-UTC `start` and the same instant as UTC yield the same
             session list.
- failure:   `test_no_error_surface_is_declared_so_none_is_invented_here` — the
             contract declares no `errors` block, so there is no declared
             failure to test. The method instead asserts the one thing that
             *is* declared: the invalid windows return a list rather than
             raising. Written as an assertion, not a `@unittest.skip`, because
             a skip asserts nothing and `mark-approved` refuses a Review
             Record reporting one.

The `errors` and `behavior` sections are omitted below because
`market-data-api` declares neither for this capability — the state CLI's
obligation check is vacuous here, as the Card notes.

## how the tests avoid deciding the open timezone question

The contract promises nothing about the awareness of the returned datetimes
while `series.get` promises "tz-aware UTC". If a test compared a returned
datetime against an input bound, it would raise `TypeError` under one
resolution and pass under the other — deciding the question by accident, in
whichever direction it happened to be written. So **no test in this file
compares a returned datetime to an input bound.** Every assertion is built
from one of three moves that hold under either resolution:

  1. comparing returned datetimes **to each other** (same call surface, so a
     shared awareness convention);
  2. reading `.date()` / `.weekday()`, which behave identically on an aware
     and a naive datetime;
  3. expressing containment as membership in a **wider window's** result.

Move 3 is why `assertAllWithinWindow` exists in that shape: "does not escape
the window" becomes "appears in the window that extends further", which is
returned-vs-returned and so needs no convention. The suite stays valid
whichever way ac-designer rules, and no assertion pre-empts the decision.

## discovery

- looked at: >
  `architecture/contracts/market-data-api.yaml` and
  `architecture/modules/market-data/module.yaml`; the committed fixture source
  `modules/market-data/data/` (`README.md`, `AAPL.csv`, `SPY.csv`); and the
  shared fixtures in `modules/market-data/testing.py`. Nothing under
  `modules/market-data/api/` was read — that is the boundary this role exists
  to hold, and `api/series.py` holds the other capability's implementation.
  The import path was established by probing `importlib` for the public
  attribute names, not by reading the sibling capability's test.
- found: >
  The fixture source is two committed CSVs, one per symbol, stem is the
  symbol. Header is `ts,open,high,low,close,volume`; `ts` is ISO-8601 with an
  explicit `+00:00` offset. Each file holds **three** bars, at
  `2024-01-02`, `2024-01-03` and `2024-01-04`, every one stamped
  `T21:00:00+00:00`. 2024-01-02 is a Tuesday and 2024-01-05 a Friday, so the
  fixture window is a plain Tue–Fri run of trading days.
  `MARKET_DATA_SOURCE` overrides the fixture root and is a test hook, not a
  feed. `testing.py` exports `WINDOW_START = 2024-01-02T21:00Z` and
  `WINDOW_END = 2024-01-05T21:00Z` **specifically for `series.calendar`**,
  plus `SESSION_HOUR_UTC = 21`, whose comment defers the correctness of that
  hour to this Card. `api.series` currently exports `symbols` and
  `list_symbols` only. The source directory name contains a hyphen, so the
  module is imported by putting `modules/market-data` on `sys.path` and
  importing `api.series` — the test file does this from its own location so it
  runs the same from any cwd. Python 3.12, pandas 3.0.6.
- contradicts the Card: >
  One thing, and it changed how a test had to be written. The Card's boundary
  line — "a window whose bounds are themselves sessions returns both bounds" —
  reads as though `WINDOW_START`/`WINDOW_END` are both sessions. They are not:
  the committed CSVs stop at **2024-01-04**, so `WINDOW_END`
  (2024-01-05T21:00Z) is not a session in the fixture data at all. Under a
  session source derived from that data, the end bound is a non-session and a
  literal reading of the Card line is untestable.

  I did not resolve this, because resolving it means deciding whether
  sessions come from the data or from a weekday rule — the second half of the
  blocker. Instead
  `test_window_bounded_by_its_own_sessions_returns_both_bounds` takes its two
  bounds from the calendar's **own output** and checks that re-querying with
  them returns the same set. That pins the inclusive-bounds property the Card
  is actually about, without asserting which instants are sessions — a
  question this suite is not entitled to answer. The test is stronger for it:
  it catches exclusive bounds, half-open ranges, and bound-dropping on
  either side.
- unratified choices: >
  Owner has **not** ratified any of the following. Each is a case the Card or
  the contract left open, resolved the most conservatively, and recorded here
  so it is visible rather than incidental.

  - `start == end` and `start > end` return `[]`. Card-pinned, not
    Owner-ratified. `WINDOW_START` is itself a session instant, so this is a
    real fork rather than a vacuous one: an inclusive reading would return
    that single session. The tests assert `[]` and will fail loudly if
    ac-designer or the Owner later decides these are errors.
  - Containment is asserted as membership in a wider window rather than by
    direct comparison against the bounds. Forced by the open awareness
    question, and it is strictly weaker than a direct comparison: it catches
    a session leaking outside the window, but not a window that leaks
    *inward* in a way the wider window also excludes.
  - **Ordering and uniqueness are deliberately not asserted.** The contract
    declares no `behavior` block, so it promises neither. A calendar is
    naturally a set, and asserting distinctness or sortedness would have been
    defensible, but it would be adding behaviour the Card does not describe.
    If the implementation returns duplicates, this suite will not notice.
  - The "no session" window is a **Saturday**, not a named market holiday.
    Chosen because it is closed under both candidate readings — absent from
    the committed CSVs, and a Saturday under any weekday rule. The contract
    names no exchange and no holiday calendar, so no holiday is tested.
  - The **time of day** a session is stamped at is not asserted anywhere.
    `SESSION_HOUR_UTC = 21` is a fixture constant that explicitly defers its
    own correctness to this Card, and the Card does not take it up. The tests
    pass for a session source stamping 14:30 or 21:00, as long as it is
    consistent.
  - `MARKET_DATA_SOURCE` is **not** set by any test. Whether `series.calendar`
    reads the fixture directory at all is not stated by the Card, so the suite
    runs against the committed fixtures and asserts nothing about the
    environment hook.
  - The weekend test uses `.weekday()` rather than a date literal, so it
    holds for any implementation whose sessions are daily. It does not assume
    a session is at any particular hour.

## read-scope note for the dispatcher

The dispatch prompt offered a carve-out permitting reads of
`modules/market-data/data/` and `modules/market-data/testing.py`, while
`CLAUDE.md` and `.claude/agents/tester.md` say `MUST NOT read
modules/<your-module>/**` with no exception. I followed the role file's rule
at the line that matters — **nothing under `modules/market-data/api/` was
read**, and no assertion below describes the code — while using `data/` and
`testing.py` for the `discovery` section above, because the role file's own
`discovery` instruction requires going to look at the real data source, and
because `testing.py` is test support rather than the implementation under
test. If the dispatcher reads that split differently, the discovery findings
above are the part to review.

## scenarios proposed by the developer

Pass 1 — none. The developer has not run.

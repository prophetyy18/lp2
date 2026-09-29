> # ⛔ VOID — 2026-09-29, do not build from this Card
>
> **This Card is void. It must not be used as a specification, and no tester
> or developer may be dispatched against it.**
>
> **Why.** Every decision in it rests on a premise that was never true. The
> capability is described as returning *trading sessions*, and this Card
> decided that a session is "21:00 UTC on a weekday, holidays excluded". That
> rule was inherited from a **securities-market** shape of the contract
> (`series.get` → `OHLCV`, a `symbol`, a `tf`) that does not belong to this
> system: the surrounding modules replay Uniswap V4 logs, reconstruct pool
> state from `sqrt_price_x96` / `tick`, and range over **block numbers**. There
> is no exchange in this repository.
>
> **The specific fabrication.** `SESSION_HOUR_UTC = 21` has no source anywhere.
> It was invented as a fixture constant in `modules/market-data/testing.py`
> during the first run, restated as a rule in this Card, and then ratified at
> an Owner gate — three documents later it read as an established fact. The
> Owner approval recorded against it is void too: it approved a number that had
> never been checked against anything. A follow-on investigation then went and
> researched a US exchange calendar to justify it, which was a category error
> twice over — the system has no exchange, and the number was not derived from
> one to begin with.
>
> **What this Card is kept for.** It is the worked example behind
> `AGENTS.md` §4 and the `UNKNOWN` rule. It is not deleted, because the record
> of how a fabricated constant survived three documents is the evidence for
> those rules. Do not repair it and do not re-run the flow against it.
>
> **What replaces it.** Nothing. And the obvious replacement was wrong too.
> `robinhood-features-api` did declare the capability, as
> `features.bars.compute(pool_id, start, end, interval) -> list[Bar]` — which
> looked like the correct home for it, because it was keyed by `PoolId` and
> ranged over block numbers while `market-data` had spoken in sessions and
> symbols. **On 2026-09-29 ac-designer was asked to check that, and `Bar` was
> retired as well.** Every field it would have carried is already available
> from `replay.state.checkpoint(cursor)` at an arbitrary block, so `Bar` was a
> cache promoted to a contract-level type; its one non-point field,
> `realized_volatility`, was a derivable function of the checkpoint sequence.
> The performance saving was real and did not justify a public type that every
> downstream Card would have to inherit and trust.
>
> This is the second half of the same lesson, and it is the half that is easy
> to miss: **an existing declaration is not a justification.** Repointing the
> consumers at a better-shaped sibling felt like the end of the matter, and it
> took a further challenge to notice that the sibling had the same problem in a
> subtler form. See the vocabulary rule in `.claude/agents/ac-designer.md`.
>
> The contract-level blocker that preceded this
> (`CONTRACT.design-blocker.resolved.md`) added `behavior.timezone` to a
> capability whose existence is now in question. Its *finding* — that the
> contract was silent about timezone — was sound; its *resolution* is not
> evidence of anything about the world and should not be cited as one.
>
> **The fixture files settle it.** `modules/market-data/data/` held `AAPL.csv`
> and `SPY.csv`. This is a Uniswap V4 liquidity-position system on an
> EVM chain; its market-data module was seeded with US equity tickers. The
> `market-data-api` contract was retired on 2026-09-29 — the contract, the
> module declaration, and the module's source and tests are gone. `backtest`,
> `pricing` and `web` were retired the same day; `backtest.run` was a
> byte-for-byte duplicate of `strategy.registry.register`, and `pricing`
> carried a `stale_tolerance: 5min` on an `event_time` value, which is a
> securities-market concept in a system that ranges over block numbers.
> `position.risk_factors` — the one capability in `pricing` that was not a
> restatement of something `robinhood-features` already declared — moved to
> `robinhood-risk-api` as `risk.factors`.

# card: market-data / series.calendar

*(void — see the banner above; the text below is preserved unchanged as the
historical record)*

- mode: full
- contract: architecture/contracts/market-data-api.yaml
- capability: series.calendar
- signature: "series.calendar(start: datetime, end: datetime) -> list[datetime]"
- input schema:  none declared — `start` and `end` are the bare `datetime`s of
   the signature; no `architecture/schemas/` entry exists for them, and
   `architecture/` contains only `contracts/` and `modules/`
- output schema: none declared — the shape is the bare `list[datetime]` of the
   signature, with the awareness of each element now stated by the contract's
   `behavior` block rather than by any schema reference. The contract did not
   change these two facts in this revision, so this Card does not change them
   either; what changed is `behavior`, below.
- payload schema: not applicable (kind is `operation`, not `event`)
- behavior:
   timezone: tz_aware_utc
- errors: none declared — the contract lists no `errors` block, so this
   capability has no declared error surface, and none may be invented here.
   The contract now settles one case that previously sat in the gap, and it
   settles it in the *return value*: "A window with no sessions returns `[]` —
   an empty list, never `None` and never an error." So the empty case is
   contract text, not a Card pinning. What is still unspecified is whether a
   naive `start`/`end` is a permitted argument; see `session membership` and
   `notes`.

## behavior guarantees

Everything in this section is either **declared by the contract** or **decided
by this Card**. The developer must not add a fourth category, and a tester may
assert every line.

### Declared by the contract — `behavior.timezone: tz_aware_utc`

Every `datetime` in the returned list is tz-aware and its UTC offset is
`timedelta(0)`. A consumer can therefore compare a returned session directly
against `series.get`'s `ts` column and against this Card's own `start`/`end`
arguments, with no conversion step. Four things a tester can observe:

1. `dt.tzinfo is not None` and `dt.utcoffset() == timedelta(0)` for every `dt`.
2. `dt == dt.astimezone(timezone(timedelta(hours=-5)))` — equal to the same
   instant expressed in another offset. Equivalently, for a 21:00 UTC session,
   `dt == datetime(2024, 1, 2, 16, 0, tzinfo=timezone(timedelta(hours=-5)))`.
3. `dt != dt.replace(tzinfo=None)` — an aware value does **not** compare equal
   to its own naive form. (Python's `==` between an aware and a naive datetime
   returns `False` rather than raising, so this is a usable assertion; note
   that `<` and `>` *do* raise, which is guarantee 4.)
4. `dt <= end` and `dt >= start` evaluate without raising `TypeError`. This is
   the guarantee the contract's own sentence exists for — "backtest consumes
   both and cannot compare a naive value against an aware one" — and it is the
   one the previous Card could not test. Each of 1–4 fails if the
   implementation returns naive datetimes.

### Declared by the contract — a window with no sessions returns `[]`

`[]`, not `None`, not an exception. A tester can observe it directly: the
result is a `list`, it is empty, and no call in the whole test plan raises.

### Declared as out of scope by the contract — which instants are sessions

The contract states: "Whether an instant is a session is a property of the
exchange calendar, not of this contract, and the contract does not enumerate
it." It therefore delegates this to the Card, and this Card decides it below.
A tester **may** assert the decided rule; a tester may not invent a different
one.

## session membership — DECIDED

    A session is the instant  YYYY-MM-DT21:00:00+00:00  for every date whose
    UTC weekday is Monday, Tuesday, Wednesday, Thursday or Friday.

Stated as a rule a tester can implement and assert without reading any
implementation:

- **Weekday rule.** The date is evaluated in **UTC** — the same tz the values
  are returned in — and sessions exist on Monday–Friday only. Saturday and
  Sunday are never sessions. `dt.weekday() < 5` on the returned value is the
  whole test; there is no exchange-local calendar, no timezone conversion of
  the date, and no half-day or early-close concept.
- **Stamping time.** Every session is stamped at **21:00:00 UTC**
  (`SESSION_HOUR_UTC` in `modules/market-data/testing.py` defers exactly this
  decision to this Card). It is also the hour every committed fixture bar
  carries, so the calendar and the bar data agree by construction.
- **Holidays are not modelled.** No date is excluded for being a holiday.
  This was the Card's one assumed fact; the **Owner ratified it on 2026-09-29**
  — 「不排除」 ("do not exclude [them]") — so it is a decision of this Card.
  See `notes` for what was checked to reach it, and for the record of the fact
  having been chosen rather than discovered.
- **The calendar is not derived from bar data.** The signature takes no
  `symbol`, so a calendar built from the bar rows could not be a per-symbol
  union of bars; it is an exchange-wide property, exactly as the contract says.
  The consequences are load-bearing:
  - **2024-01-05 (a Friday) IS a session**, at `2024-01-05T21:00:00+00:00`,
    even though the committed fixture CSVs carry no bar for it. The fixtures
    hold three synthetic bars because `synthetic_bars` defaults to
    `count=3`, not because the calendar ends on 2024-01-04.
  - Therefore, over the shared fixture window, the result is **exactly four**
    sessions: 2024-01-02, 2024-01-03, 2024-01-04, 2024-01-05, each at 21:00
    UTC. (2024-01-01 was a Monday, so 01-02 is a Tuesday and 01-05 a Friday.)
- **Range is closed at both ends**, compared as absolute instants: a session
  is returned when `start <= dt <= end`. `WINDOW_START` and `WINDOW_END` are
  both sessions under this rule, so the shared fixture window is the easy case
  — the inclusive-bounds property must therefore be tested on a window whose
  bounds are *not* both sessions as well, or it proves nothing.
- **Degenerate windows.** `start > end` contains no sessions, so it returns
  `[]` by the contract's `[]` sentence. `start == end` is a zero-width closed
  interval: it returns `[start]` if `start` is a session, and `[]` if it is
  not. **This reverses the previous Card**, which pinned `start == end` to
  `[]` unconditionally; see `notes`.
- **Ordering and uniqueness** — *decided by this Card, not by the contract.*
  The result is strictly ascending with no duplicates, so
  `result == sorted(set(result))`. A calendar list a caller cannot merge or
  index by position is a defect, and the contract's `list[datetime]` shape
  permits this without promising it. Do not record this as a contract
  guarantee.
- **Naive bounds** — *decided by this Card, not by the contract.* The contract
  does not say whether a naive `start`/`end` is permitted, and a naive bound is
  ambiguous (UTC, or the machine's local time?). Decision: a naive bound is
  interpreted as **UTC** and is not an error, since the contract declares no
  error surface. An aware bound in any offset is compared as an instant, so it
  may be in any timezone.

- test plan:
   - normal:    `series.calendar(WINDOW_START, WINDOW_END)` returns a `list`
                whose every element is a `datetime`, containing exactly the
                four sessions the weekday rule above yields for that window
                (2024-01-02/03/04/05, each `21:00:00+00:00`), and nothing
                else. Also assert `result == sorted(set(result))`.
                Also assert each element's `.date()` and `.weekday()` agree
                with the rule, so a test does not hard-code the dates and stay
                true if the fixture window ever moves.
   - boundary:  **the timezone guarantees, all four, as their own cases** —
                `tzinfo`/`utcoffset`; equality with the same instant in a
                −05:00 offset; inequality with the naive form; and `dt <= end`
                / `dt >= start` evaluating without `TypeError`. At least the
                first and last must be separate tests, because they fail for
                different mistakes (dropping the offset vs. dropping
                awareness while keeping a wrong offset). Additionally: a
                window whose bounds are both sessions returns both; a window
                that starts mid-session-run and ends before its last session
                returns the interior sessions and neither leaked bound; a
                one-day window returns at most that one day and never spills
                into the next; a window spanning Saturday 2024-01-06 and
                Sunday 2024-01-07 returns only the Friday's session; a window
                of a single Saturday returns `[]`; a window entirely outside
                the fixture range returns `[]`.
   - invalid:   `start > end` returns `[]`. `start == end` returns `[start]`
                when `start` is a session and `[]` when it is not (use
                `WINDOW_START` for the first and a Saturday for the second).
                A `start` given at the same instant in a non-UTC offset — e.g.
                `WINDOW_START.astimezone(timezone(timedelta(hours=-5)))` —
                yields the same list as the UTC form. A **naive** bound equal
                to the same instant as an aware one yields the same list too.
                None of these raise.
   - failure:   no error code is declared, so there is no declared failure to
                test — but the contract's `[]` sentence is a *negative*
                guarantee ("never `None` and never an error") and it is
                testable. One case asserts that no window shape in this plan
                raises and none returns `None`: empty, inverted, zero-width,
                naive-bound, non-UTC-bound, pre-history, post-history, a
                weekend, and the full fixture window. Write it as an assertion
                over that matrix, not as a `@unittest.skip`.
- reads allowed:
   - modules/market-data/**
   - architecture/**
   - framework/architecture/__init__.py
- reads denied:
   - modules/<other>/**
   - framework/architecture/_internals/**
- notes:
  Build this one second. It is upstream-free, but it fixes the module's session
  source, and that same source has to back `series.get` — so the two Cards are
  sequenced to make the shared decision once, here. **The single most important
  thing this Card can get right:** implement the session source once, in a place
  `series.get` reuses. If `series.get` ends up with its own calendar logic, the
  two will disagree and no test in either Card will catch it. The weekday rule
  above is that shared source's whole content, and `series.get`'s Card already
  says so.

  Tests live at `tests/test_market_data_series_calendar.py`; run them with
  `./bin/python -m unittest tests.test_market_data_series_calendar -v`. Reuse
  the fixtures established by the `series.symbols` Card rather than writing new
  ones — in particular `WINDOW_START`, `WINDOW_END`, `SESSION_HOUR_UTC` and
  `synthetic_bars`.

  **Ratified — the Card's one assumed fact is now the Owner's decision.** This
  Card originally treated the exchange calendar as a plain Monday–Friday
  weekday calendar with **no holiday exceptions** on an explicitly unratified
  assumption, and asked the Owner to ratify or correct it at the Card gate.
  **The Owner ratified it on 2026-09-29**: 「不排除」 — "do not exclude
  [them]". The rule is no longer open.

  The basis for reaching the answer is unchanged and is recorded here so a
  later reader can retrace it: the contract names no exchange and no holiday
  calendar, and the three committed fixture bars span three consecutive
  weekdays, which cannot distinguish "weekday rule" from "exactly these three
  days". So the fixtures could not settle the question either way — they ruled
  nothing out, and they ruled nothing in.

  **The fact was never researched, and that is the part worth keeping.** The
  Owner's reason for ruling was that whether an exchange closes on holidays is
  exactly the kind of thing information research is supposed to surface, and a
  Card having to *assume* it is a gap in the process rather than in the answer.
  So this rule was **chosen, not discovered** — no holiday calendar was looked
  up, and no holiday was observed. The ruling makes the Card correct; it does
  not make the underlying research any less owed. If a real exchange calendar
  is ever introduced, this rule and its test cases change together, and that is
  a new decision for ac-designer, not a Card edit.

  **The degenerate-window rule reverses the previous Card.** The old Card
  pinned `start == end` to `[]` unconditionally. This Card returns `[start]`
  when `start` is a session, because the contract's `[]` sentence is
  conditioned on "a window with no sessions" and a zero-width closed interval
  at a session instant contains one. `tests/test_market_data_series_calendar.py`
  currently asserts the old rule in
  `test_start_equal_to_end_returns_an_empty_list`; **that test must be
  rewritten to this Card's rule, not worked around.** Flagging it here because
  the tester will otherwise read the old assertion as still binding.

  **The old "no session" window was a Saturday, and that stays correct** — a
  Saturday is closed under this rule as well as under every other candidate.
  No holiday is tested, because no holiday is a session-exception in this
  module; see the ruling above.

  The tester's pass-1 suite deliberately compared no returned datetime to an
  input bound, because the contract then promised nothing about awareness and
  such a comparison would have raised `TypeError` under one resolution and
  passed under the other. That constraint is gone. Guarantee 4 above exists
  precisely to close the gap the previous Card left, and a suite that still
  avoids bound comparisons is under-testing a contract obligation that is now
  declared. At least one test must fail if the implementation returns naive
  datetimes.

  Two files in this directory are now stale and are **not** mine to edit:
  `series.get.card.md` still says `series.get` has "no `behavior` block" (it
  has one now), and `PLAN.md` §2 still says no capability in this module
  declares `behavior`. Expect the `series.get` Card to need the same refresh
  when that capability is dispatched.

  Ordering, uniqueness, the naive-bound reading, and the `21:00` stamping hour
  are **this Card's decisions**, not contract promises. Record all four in the
  Manifest as unratified so a later reviewer can see exactly which obligations
  the tests are holding the implementation to on the Card's authority alone.

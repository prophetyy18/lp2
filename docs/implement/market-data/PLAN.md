# PLAN — market-data

Module: `market-data`
Contract: `architecture/contracts/market-data-api.yaml` (v1)
Declaration: `architecture/modules/market-data/module.yaml`
Source root: `modules/market-data` (does not exist yet — first module in this repository)
Depends on: nothing (`depends_on: []`)

## 1. Module purpose

Read-only access to price/volume time series — the lowest layer, depending on no
other contract, so every other contract may build on it.

(Note the split: the contract's `description` states the *read interface* it
publishes; the module declaration describes the *work behind it* — "ingestion,
normalisation and storage of market time series". The three capabilities below
cover only the read side. See §6, risk 1: where ingestion and storage fit.)

## 2. Capability inventory

| id | mode | depends on upstream state | test plan summary |
|---|---|---|---|
| `series.get` | full | none — `market-data` declares `depends_on: []`, so `./bin/python -m tools.implement.state upstream market-data series.get` is green from the start | Columns `ts, open, high, low, close, volume`; tz-aware UTC `ts`; empty frame (declared columns, not `None`, not a raised error) when no bars exist; window and `tf` filtering; unknown symbol behaves as a no-bar query. |
| `series.symbols` | full | none — same empty upstream set | Returns a `list[str]`; empty list is a legal answer; entries are the symbols `series.get` accepts; order and duplicates are unspecified by the contract (see §6, risk 3). |
| `series.calendar` | full | none — same empty upstream set | `list[datetime]` of sessions between `start` and `end`; the range's own bounds are honoured; a range with no sessions returns `[]`; endpoints come from a single shared session source shared with `series.get`. |

No capability declares `errors` or `behavior` in the contract, so every Card
carries an explicit "none declared" in those fields and the state CLI's
`tests by obligation:` check is vacuous for all three. If Owner wants that check
to bite, the contract has to grow those blocks first — that is ac-designer's
call, not this plan's (§6, risk 2).

## 3. Implementation order

1. **`series.symbols`** — depends on nothing, and it is the cheapest read path
   (a listing, no windowing, no frame assembly). Doing it first proves the
   module skeleton: package layout under `modules/market-data/`, how the contract's
   three operations are exposed as one importable surface, and the test harness
   that the other two Cards reuse.
2. **`series.calendar`** — also upstream-free, but it needs a session-source
   decision that `series.symbols` does not. It comes second because it shares
   that decision with step 3 and the two must not diverge.
3. **`series.get`** — last, because it is the only capability that assembles a
   DataFrame and the only one that both consumes and must stay consistent with
   the two above. `backtest` and `pricing` are waiting on this specific
   capability (§4), so the ordering front-loads nothing that matters to them and
   puts the riskiest one where it is cheapest to revise.

Grouping that shares helpers: all three share one internal session/calendar
source, one symbol-normalisation helper, and one place where tz-aware UTC
coercion happens. The developer for `series.symbols` owns the module skeleton;
`series.calendar` extends it with the session source; `series.get` reuses both.
The developer must not fork a second calendar implementation inside `series.get`
— that is the one duplication the Cards are written to prevent.

Sequencing note: these are one developer run each, but capability 1's skeleton
is a prerequisite for the other two being reviewable, so the dispatcher should
not run 2 and 3 in parallel against an empty `modules/market-data/`.

## 4. Gates

Same sequence for all three capabilities; only the names change. The state CLI's
own vocabulary (`register`, `mark-changes`, `retry`, `mark-approved`,
`mark-mvp`, `abandon`) is what the Gates section of each Card refers to.

1. **Upstream gate** — `./bin/python -m tools.implement.state upstream market-data <cap>`
   Green immediately: `depends_on: []` means there is nothing to wait for. Still
   run it; it is the check that would catch a future `depends_on` edit.
2. **Register** — `./bin/python -m tools.implement.state register market-data <cap> --mode full`
   (run by the dispatcher after Owner approves the Card, not by the developer).
3. **Developer** — implement to the Card; run the tests named in the Card's
   `test plan`; write `docs/implement/market-data/<cap>.manifest.md`.
4. **Reviewer** — read the contract, not the Card, as the statement of what was
   promised; write `docs/implement/market-data/<cap>.review.md` with exactly one
   verdict.
5. **Dispatch, per verdict** —
   - `APPROVED` → `./bin/python -m tools.implement.state mark-approved market-data <cap> --review <cap>.review.md --manifest <cap>.manifest.md`
   - `CHANGES_REQUESTED` → `./bin/python -m tools.implement.state mark-changes market-data <cap> --review <cap>.review.md --manifest <cap>.manifest.md`, then `retry market-data <cap>`, then back to step 3 with the reviewer's reason codes.
   - `ABANDON` → `./bin/python -m tools.implement.state abandon market-data <cap> --review <cap>.review.md`

MVP mode was not chosen for any capability, so the `mark-mvp` path is not part of
this plan. See §5 for why two of these three should not go there anyway.

## 5. Cross-module MVP exposures

Capabilities of this module that another module's contract depends on, read from
the architecture (`python3 -m framework.architecture.cli consumers market-data-api`):

| capability | declared dependers | impact if it changes | recommended mode |
|---|---|---|---|
| `series.get` | `backtest` (`uses: [series.get, series.calendar]`), `pricing` (`uses: [series.get]`) | `backtest` and `pricing` directly, and `web` at distance 2 via `pricing-api`. A change to the returned columns, the tz of `ts`, or the empty-frame behaviour is a change to two live consumers at once. | **full** — mandatory, not a preference |
| `series.calendar` | `backtest` (`uses: [series.get, series.calendar]`) | `backtest` directly. | **full** — mandatory |
| `series.symbols` | none declared | none today; it becomes an exposure the moment another module names it. | full (Owner's default) |

Recommendation is `full` for all three, and for the two exposures the reason is
structural rather than a matter of taste: only `fully_approved` is consumable, so
an `mvp_developed` `series.get` is **red** to `backtest` and `pricing` — not a
warning. Running these in MVP mode would produce capability that the two waiting
modules cannot consume and would have to be reopened with
`retry <module> <cap> --mode full`, redoing the work.

`series.symbols` has no declared consumer, so it is the one capability where
Owner could choose `mvp` without stranding anybody. Even there, it is the module
skeleton the other two Cards build on (§3), and an MVP's code is disposable while
its structure is what gets re-derived. Recommend `full` and let the review pass
be the cost.

## 6. Risks / open questions

1. **The contract declares a read surface; the module declares ingestion and
   storage.** `module.yaml` says "Ingestion, normalisation and storage of market
   time series", and `requires: []` means no other contract supplies the raw
   source. This plan covers only the three declared operations, which means the
   developer will be building a read path over no declared ingestion
   mechanism — no vendor, no file layout, no fetch contract. This is a
   contract gap, not an implementation detail. Owner should decide, before
   dispatching, whether: (a) a fourth capability is added to the contract (an
   ingest/refresh operation) — ac-designer's work, and the two Cards below stay
   valid either way; or (b) the data is seeded by fixture files committed inside
   the module, and the module's description is amended to match. **Recommendation:
   (b) for the first pass, (a) later** — the three Cards are consumer-facing and
   unaffected by which, so no Card is blocked. But the developer must not invent
   an ingestion mechanism either way; that is the one place this plan cannot
   answer from the contract.
2. **No `errors` and no `behavior` anywhere in `market-data-api`.** The state
   CLI derives `tests by obligation:` from exactly those two blocks, so it will
   require no `tests by obligation:` mapping for any of these three
   capabilities — "the check is then vacuous, not absent." That is honest for a
   pure read module, but it means the error surface (`get` on a symbol the
   source does not have; `tf` the source does not support; a `start` after
   `end`) is currently unspecified rather than empty, and each Card says so
   instead of guessing. Owner should decide whether to escalate to ac-designer
   for a `behavior` block (at minimum `unit`/`time`/`idempotent` on `series.get`,
   which is the one capability two modules consume as a data source). If a
   capability is genuinely unspecified, the developer must pick the least
   surprising reading — unknown symbol and unsupported `tf` as a no-bar query,
   `start > end` as an empty frame — and record the choice in the Manifest's
   notes as a decision Owner has not yet ratified. That is a design blocker if
   Owner disagrees, not a licence to widen the contract from inside the module.
3. **`series.symbols` promises a list, not a set.** The contract does not state
   order, case, or uniqueness. The Card's tests therefore assert only what is
   declared (it is a `list[str]`; `series.get` accepts its entries; empty is
   legal). The developer must not add sorting or de-duplication "for
   determinism" without saying so in the Manifest — sorting is observable to
   `backtest` and is a behaviour the contract does not promise.
4. **No shared test fixtures exist yet.** This is the first module, so there is
   no `tests/conftest.py`, no fixture directory, and no other module's tests to
   imitate. The `series.symbols` Card owns establishing whatever the three share
   (a minimal synthetic OHLCV builder, a fixed UTC window). The other two
   developers should reuse it rather than write their own — a second, subtly
   different calendar fixture in `series.get` is how the two drift apart.
5. **First module written means first run of the whole pipeline.** Every gate
   command in §4, the review path, and the Manifest's obligation block are being
   exercised for the first time on this module. Expect the *process* to need a
   fix, not just the code; the first run's friction belongs in the workflow
   backlog, not in a CHANGES_REQUESTED against a correct implementation.

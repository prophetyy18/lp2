# review: market-data / series.symbols

- reviewer model: MiniMax-M3
- reviewed: 2026-09-28T23:22:41+08:00
- scores (4 项,每项 OK / ISSUE):
   contract_conformance: OK   # contract and Card match; no undeclared public behavior
   boundary:             OK   # ./bin/python -m tools.check_imports <module> clean
   test_coverage:        OK   # normal / boundary / invalid / failure paths covered
   implementation_quality: OK # errors, bounded I/O, cleanup, readable code, useful types
- verdict: APPROVED
- tests run: 16 passed, 0 skipped
- reason codes: []
- notes (≤ 2 lines per ISSUE):
   - none — all four scores OK.

## What I ran myself

- `./bin/python -m tools.check_imports market-data` → exit 0, no findings (also exit 0
  under `--strict`). The Manifest's `boundary: OK` claim is accurate.
- `./bin/python -m tools.implement.naming market-data series.symbols` →
  `./bin/python -m unittest tests.test_market_data_series_symbols -v`
  → `Ran 16 tests ... OK`, 0 skipped. This agrees with the Manifest's
  `tests passing: 16 unit, 0 contract-conformance`; no disagreement to report.
  The unreadable-directory test ran rather than skipped on this host (non-root),
  so the skip branch exists but asserted nothing lost. Note for whoever runs
  this as root: that test will then skip, and `mark-approved` refuses a
  non-zero skip count.

## Score rationale

**contract_conformance: OK.** `series.symbols() -> list[str]` is implemented
argument-free at `modules.market-data.api.series.symbols`, matching the
contract's signature exactly; `api.__all__ == ["series"]` is the single
importable surface the Card asks for. The contract declares no input schema, no
output schema, no `errors` and no `behavior` for this capability, and the
Manifest claims none — so there is nothing to over- or under-claim. The two
extra surfaces a reader might suspect are undeclared public behavior are not:
the `MARKET_DATA_SOURCE` override and the warning log both live in the private
`_source` module and are not reachable through `api`, so no consumer of the
contract can observe them as behavior. The warning is, if anything, the honest
counterweight to returning `[]` silently.

**boundary: OK.** `market-data` declares `depends_on: []`, and the module
imports only stdlib (`logging`, `os`, `pathlib`) plus `pandas` in the
non-contract `testing.py`. No `modules/<other>/` import anywhere. The
`importlib.import_module("modules.market-data.api")` form in the test file is a
consequence of the hyphen in the declared source root, not a boundary dodge,
and it imports the module under review, not another one.

**test_coverage: OK.** All four Card lines are present: normal (declared shape,
committed default, per-symbol source file), boundary (one symbol, empty source,
non-symbol files, fresh list per call, and quiet-on-empty), invalid (absent
source, empty override), failure (root is a file, root unreadable). The Card's
`failure` line is explicitly not specifiable and the unavailable-source cases
stand in for it. `tests by obligation:` is correctly omitted — with no `errors`
and no `behavior` declared, the obligation set is empty, not forgotten. Tests
assert observable results through the public function; nothing reaches into
`_source` internals.

**implementation_quality: OK.** The `OSError` from `iterdir()` is caught
explicitly and turned into a logged warning plus `[]`; `Path.is_file()` is used
so a directory named `X.csv`, a broken symlink or a vanished entry is skipped
rather than fatal. No I/O that can hang, no retry loop to bound, no handles left
open (the CSV writers use `with`). Types are precise (`list[str]`, `Path`,
`NamedTuple`, `__all__` on both modules), the docstrings state which choices are
contract facts and which are the developer's, and every unratified decision is
mirrored in the Manifest's risk notes.

## Two judgements the dispatcher asked for

**The half round-trip.** The Card's `normal` line asks that every returned
symbol be accepted by `series.get`. That call cannot be made today:
`series.get` has no Card-approved implementation, and calling or stubbing it
from this test file would be inventing a second capability, which is exactly
what the Card's own notes forbid. Testing the source-side half — every reported
symbol names a real file in the same source, and is a bare, non-empty,
separator-free stem — is the furthest the Card can be honoured right now, and
the open half is recorded in Manifest risk note 7 and deferred to the
`series.get` Card, which is the right place for it. Not a test gap I am charging
against this capability.

**The `invalid` line and PLAN.md §6.** The Card points the `invalid` case at
"the agreed §6 risk-1 answer in `PLAN.md`", but §6 risk 1 is the
ingestion-vs-fixtures question and states nothing about what a missing source
returns. The line that does cover it is §6 risk 2, which instructs that a
genuinely unspecified capability gets "the least surprising reading", recorded
in the Manifest as a decision Owner has not ratified. The developer did exactly
that: pinned `[]` plus a warning, with the reasoning (absence of data is a
result, matching `series.get`'s declared empty frame) written down and labelled
unratified. That is what the plan asked for, so this is a Card cross-reference
that points one risk off, not an implementation defect. The committed-fixture
answer itself is Owner's, recorded in risk note 1.

## Carried forward (not charged against this capability)

- `testing.py` (`synthetic_bars`, `WINDOW_START`/`WINDOW_END`, `ohlcv_frame`)
  and the package layout are unexercised scaffolding; `ohlcv_frame` has no test
  at all. Intentional — the other two Cards own those decisions — and recorded
  in risk note 8.
- `test_reports_the_committed_source_by_default` pins `{AAPL, SPY}`. Correct
  today; it will need widening if a later capability commits more fixtures.
- The module declaration still claims ingestion and storage that no contract
  provides. That is ac-designer's to close, as risk note 1 says.

# consumed by dispatcher; Owner decides before dispatcher updates STATE

# manifest: market-data / series.symbols

- mode: full
- new files:
   - modules/market-data/__init__.py
   - modules/market-data/api/__init__.py
   - modules/market-data/api/series.py
   - modules/market-data/api/_source.py
   - modules/market-data/testing.py
   - modules/market-data/data/README.md
   - modules/market-data/data/AAPL.csv
   - modules/market-data/data/SPY.csv
   - tests/test_market_data_series_symbols.py
- modified files: none — first implementation, the tree was empty
- capability ids touched: series.symbols
- contract conformance:
   - signature matches:    YES — `series.symbols() -> list[str]`, argument-free,
                           exactly as `market-data-api` declares it
   - input schema parsed:  N/A — the contract declares no input schema and the
                           signature takes no arguments
   - output schema:        N/A — the contract declares no output schema and no
                           `architecture/schemas/` entry; the shape tested is
                           the bare `list[str]` of the signature
   - errors emitted:       none — the contract declares no `errors` block for
                           this capability, and the Card agrees
   - behavior tags:        none — the contract declares no `behavior` block for
                           this capability. `unit`, `time`, `idempotent` and
                           `ordering` are all undeclared, so none is claimed
                           and none is tested as a guarantee. (The function is
                           in fact repeatable, but the contract does not promise
                           it and the Manifest does not claim it.)
- pre-handoff checks (run by developer; dispatcher re-runs):
   - archctl validate:           OK
   - import-isolation:           OK — `./bin/python -m tools.check_imports
                                 market-data`, exit 0, no ERROR findings (also
                                 clean under `--strict`)
   - tests passing:              16 unit, 0 contract-conformance
- test plan coverage:
   - normal:    YES — `test_returns_a_list_whose_every_element_is_a_str`,
                 `test_reports_the_committed_source_by_default`,
                 `test_every_reported_symbol_names_a_file_in_the_source`,
                 `test_reported_symbols_are_usable_as_symbol_arguments`
   - boundary:  YES — `test_a_source_holding_exactly_one_symbol_returns_a_one_element_list`,
                 `test_an_empty_source_returns_an_empty_list`,
                 `test_files_that_are_not_symbol_files_are_ignored`,
                 `test_the_result_is_a_fresh_list_each_call`,
                 `test_the_empty_directory_case_is_not_warned_about`
   - invalid:   YES — `test_a_source_that_does_not_exist_returns_an_empty_list`
                 (the "fresh module with no data source configured yet" case,
                 pinned to `[]`), `test_an_empty_override_falls_back_to_the_committed_source`
   - failure:   YES — `test_a_source_path_that_is_a_file_returns_an_empty_list`,
                 `test_an_unreadable_source_directory_returns_an_empty_list`
- pins beyond the Card's four lines (the Card asks for none of these; they
  exist so the decisions in risk notes 2 and 5 cannot be quietly reversed by
  the next developer): `test_order_is_not_promised_so_order_is_not_asserted`,
  `test_symbol_case_is_not_normalised`,
  `test_the_csv_suffix_is_matched_case_sensitively`
- tests by obligation: **omitted, deliberately.** `market-data-api` declares
  no `errors` and no `behavior` for `series.symbols`, so there is no error code
  and no behavior guarantee to map, and `mark-approved` will find no obligation
  to check. The block is absent because it is empty, not because it was
  forgotten. The tests that would have filled it are in the invalid/failure
  lines above, where the Card's two unwritten lines were.
- cross-module imports in new code: NONE
- upstream state at dispatch: none — `market-data` declares `depends_on: []`,
  so the upstream gate is vacuously green

## risk notes

**Owner decisions, ratified at the Card gate (not contract facts).**

1. *The data is fixture files committed inside the module.* There is no
   ingestion and none was invented. The committed source is
   `modules/market-data/data/`, one `<SYMBOL>.csv` per symbol. An
   ingest/refresh capability may be added to `market-data-api` later by
   ac-designer; the three read-side Cards are unaffected by it. The module
   declaration's description still mentions ingestion and storage, which the
   contract does not provide — a known, accepted gap that is not this
   capability's to close.
2. *No sorting, no de-duplication.* `series.symbols()` returns directory
   order. The implementation does not sort, does not de-duplicate, and does
   not case-fold. Sorting would be observable to every consumer and is not a
   behaviour the contract promises, so it was left out. The tests compare by
   set, deliberately, so that no test enforces an order either.

**My decisions, unratified — the contract says nothing on any of these.**

3. *The failure surface is unspecified, and I chose empty-list.* A source that
   is missing, is not a directory, or cannot be listed returns `[]` and logs a
   warning. The reasoning is the contract's own: the sibling `series.get`
   "returns an empty frame when no bars exist", so absence of data is a
   *result*, not an exception. Raising would also have meant inventing an
   error code the contract does not declare. The warning is what makes `[]`
   defensible — without it a missing source and a market with no symbols
   would be indistinguishable — so every unusable-source test asserts both,
   through `assert_unusable_source`. This is the reading I would want Owner to
   ratify; if Owner would rather it raise, it is a one-line change plus a new
   contract `errors` entry by ac-designer.
4. *A `MARKET_DATA_SOURCE` environment variable overrides the source root.*
   It exists so tests can point the operation at a directory they built
   themselves (one symbol, none, unreadable) without adding a parameter to a
   signature the contract fixed as argument-free. It selects a fixture root;
   it is not a data feed and not an ingestion hook. An empty value counts as
   unset, because `Path("")` is the working directory and honouring it would
   silently scan wherever the process was started.
5. *The `.csv` suffix is matched case-sensitively, and the stem is reported
   as written.* `AAPL.CSV` is not a symbol file; `aapl.csv` and `AAPL.csv` are
   two symbols, not one. The contract promises no case convention. Both are
   pinned by tests so the next developer does not quietly widen either.
6. *A directory named `X.csv` is not a symbol.* The `is_file()` guard skips it
   rather than reporting a name that every later read would fail on.

**Known gaps in this capability.**

7. *The Card's round-trip cannot be executed yet.* The normal line asks that
   every returned symbol be accepted by `series.get` as its `symbol`
   argument. `series.get` has no Card-approved implementation, so calling it
   from this test file would be inventing that capability. What is tested
   instead is the source-side half — every reported symbol names a file in the
   same source, and is a bare, non-empty, separator-free name, which is what
   makes it a valid argument. **The other half is untested and stays untested
   until the `series.get` Card is built; whoever builds it should add the
   round-trip there.**
8. *The module skeleton is mine and is unratified.* Package layout
   (`__init__` / `api/` / `api/series.py` / `api/_source.py` / `testing.py` /
   `data/`), the single importable surface at `modules.market-data.api`, and
   the shared fixtures in `testing.py` were all created by this capability,
   as its Card's `notes` require, but no other Card has been written against
   them. The `series.get` and `series.calendar` developers must reuse
   `testing.py` rather than write their own — that is the whole point of
   putting `synthetic_bars`, `WINDOW_START` / `WINDOW_END` and `ohlcv_frame`
   there. `ohlcv_frame` and the fixed window are currently unexercised by any
   test: they are built for the other two Cards and deliberately make no
   decision about session semantics, which is `series.calendar`'s to make.
9. *The hyphen in the module's source root shapes the import.* The source
   root is `modules/market-data` as `module.yaml` declares it, and a hyphen is
   legal in a directory name but not in an `import` statement. The package is
   therefore reached through
   `importlib.import_module("modules.market-data.api")`, not with an `import`
   line. Internal imports are relative and unaffected. This is a consequence
   of the declared source root, not a choice of mine — but a consumer who
   assumes `from modules.market_data...` will get an error, so it is recorded
   here.
10. *No stubs for `series.get` / `series.calendar`.* `api/series.py` names
    them and does not implement them. A `NotImplementedError` stub would be a
    second, unreviewed statement about an operation whose Card does not exist
    yet, and would let a consumer mistake a stub for a capability.

# consumed by reviewer + dispatcher

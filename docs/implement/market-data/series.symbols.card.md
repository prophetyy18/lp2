# card: market-data / series.symbols

- mode: full
- contract: architecture/contracts/market-data-api.yaml
- capability: series.symbols
- signature: "series.symbols() -> list[str]"
- input schema:  none declared — the signature takes no arguments
- output schema: none declared — the shape is the bare `list[str]` of the signature; no `architecture/schemas/` entry exists for it
- payload schema: not applicable (kind is `operation`, not `event`)
- behavior: none declared — `market-data-api` gives this capability no `behavior`
   block. The state CLI's obligation check is therefore vacuous for this
   capability, and nothing in it is a promise the developer is being held to.
   Do not treat the template's unit/time/idempotent/ordering placeholders as
   filled in.
- errors: none declared — the contract lists no `errors` block, so this
   capability has no declared error surface. Whatever the source of the symbol
   list does when it is unavailable is unspecified, not empty; see `notes`.
- test plan:
   - normal:    `series.symbols()` returns a `list` whose every element is a
                `str`, and every returned symbol is accepted by `series.get`
                as the `symbol` argument (round-trip against the same source).
   - boundary:  a source holding exactly one symbol returns a one-element list;
                a source holding none returns `[]` — an empty list, not `None`
                and not a raised error, since the contract declares neither.
   - invalid:   a fresh module with no data source configured yet — the first
                thing this Card gets built against — yields whatever the agreed
                §6 risk-1 answer in `PLAN.md` says, and the test pins that
                answer rather than leaving it undefined.
   - failure:   not specifiable. No error code is declared for this capability,
                so there is no declared failure to write a test for. The only
                honest case here is the unavailable-source one above, and only
                once Owner has ruled on it.
- reads allowed:
   - modules/market-data/**
   - architecture/**
   - framework/architecture/__init__.py
- reads denied:
   - modules/<other>/**
   - framework/architecture/_internals/**
- notes:
  Build this one first. It is the cheapest read path in the module and it owns
  the module skeleton the other two Cards build on: the package layout under
  `modules/market-data/`, the single importable surface that exposes all three
  contract operations, and whatever test fixtures the three capabilities share
  (a synthetic OHLCV builder and a fixed UTC window). The `series.get` and
  `series.calendar` developers must reuse those fixtures rather than write
  their own — two subtly different calendar fixtures is exactly how the three
  capabilities drift apart.

  Tests live at `tests/test_market_data_series_symbols.py`; run them with
  `./bin/python -m unittest tests.test_market_data_series_symbols -v`.

  The contract promises a list and nothing else. No order, no case convention,
  no uniqueness. Write the tests against what is declared — assert it is a
  `list[str]`, that its entries are accepted by `series.get`, and that empty is
  legal. Do **not** add sorting or de-duplication "for determinism": sorting is
  observable to `backtest` and is a behaviour the contract does not promise. If
  the implementation sorts anyway, say so in the Manifest as a decision Owner has
  not ratified.

  This capability has no cross-module consumer today, so it is the one place
  Owner could pick `mvp` without stranding anybody. Even so it is the skeleton
  the other two sit on, and an MVP's code is disposable while its structure gets
  re-derived — recommend `full`. See `PLAN.md` §5.

  Two things this Card deliberately does not settle, because the contract does
  not: what `series.symbols()` does when no source is configured, and whether
  the module has an ingestion mechanism at all. Both are in `PLAN.md` §6
  (risks 1 and 2). Owner rules before the developer starts; the developer does
  not invent either.

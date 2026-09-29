# card: market-data / series.get

- mode: full
- contract: architecture/contracts/market-data-api.yaml
- capability: series.get
- signature: "series.get(symbol: str, start: datetime, end: datetime, tf: str) -> pd.DataFrame"
- input schema:  none declared — `symbol`, `start`, `end`, `tf` are the bare
   types of the signature; no `architecture/schemas/` entry exists for them
- output schema: none declared — the contract carries the frame's shape in prose
   ("Columns: ts, open, high, low, close, volume. tz-aware UTC") rather than as a
   `architecture/schemas/` reference, so that prose is the whole obligation.
   There is no `architecture/schemas/` directory in this repository.
- payload schema: not applicable (kind is `operation`, not `event`)
- behavior: none declared — `market-data-api` gives this capability no
   `behavior` block, even though the prose description makes two guarantees a
   consumer can rely on: the six named columns, and tz-aware UTC. The prose is
   part of the contract and the tests below hold the implementation to it; the
   state CLI's `tests by obligation:` check, which reads only the `behavior`
   block, is nonetheless vacuous for this capability. See `notes`.
- errors: none declared — the contract lists no `errors` block. The obvious
   candidates (a symbol the source does not have, a `tf` it does not support)
   are **unspecified, not empty**: a consumer has no promise either way. The
   contract does settle one failure case, and it is not an exception — "Returns
   an empty frame when no bars exist." See `notes`.
- test plan:
   - normal:    a window containing bars returns a `pd.DataFrame` whose columns
                are exactly `ts, open, high, low, close, volume`; `ts` is
                tz-aware and in UTC; rows fall within `[start, end]`.
   - boundary:  the declared empty case — a window with no bars returns an empty
                DataFrame that still carries the six declared columns, not
                `None`, not a raised error, and not a frame with the columns
                dropped. Also: a window whose bounds are themselves bar
                timestamps returns both; a single-session window returns that
                session's bars and no more; an `end` before the first available
                bar returns the same empty frame as a window in a gap.
   - invalid:   a symbol absent from `series.symbols()`, a `tf` the source does
                not support, and `start > end` each return the empty frame —
                the same result as "no bars exist", since the contract declares
                no error for any of them. Pin all three so the choice is
                deliberate. Also: the same window requested at two different
                `tf` values returns bars of each requested resolution rather
                than silently resampling to one of them.
   - failure:   not specifiable. No error code is declared, so there is no
                declared failure to write a test for. The nearest real thing is
                the empty-frame case above, which the contract routes through
                the return value rather than an error.
- reads allowed:
   - modules/market-data/**
   - architecture/**
   - framework/architecture/__init__.py
- reads denied:
   - modules/<other>/**
   - framework/architecture/_internals/**
- notes:
  Build this one last. It is the only capability that assembles a DataFrame, and
  the only one that must stay consistent with the two already built. It is also
  the capability two modules are blocked on: `backtest` and `pricing` both
  declare `uses: [series.get]`, and `web` depends on `pricing` at distance 2.

  Reuse, do not reimplement: the session source built by the `series.calendar`
  Card, the symbol handling from `series.symbols`, and that Card's test
  fixtures. A second calendar implementation inside this module is the one
  failure mode the Cards are written to prevent — `series.get` and
  `series.calendar` disagreeing about what a trading session is, with every test
  in both Cards still green.

  Tests live at `tests/test_market_data_series_get.py`; run them with
  `./bin/python -m unittest tests.test_market_data_series_get -v`.

  `pandas` is named in the return type, so it is a real dependency of this
  module and its import is a change to the module's own environment, not to
  `depends_on: []` — that field declares *contract* dependencies, and this
  module still declares none. If pandas is not yet available in the environment,
  stop and say so rather than stubbing the return type.

  The three unspecified cases under `invalid` are pinned to the empty frame
  because the contract promises an empty frame when no bars exist and promises
  no error otherwise. That is the least-surprising reading, not a decision the
  developer is authorised to make silently: if any of them should be a declared
  error, that is a contract change for ac-designer, and these test cases change
  with it. Record the choice in the Manifest's notes as unratified.

  The empty frame must keep its six columns. Consumers read the columns to
  discover the schema; an empty frame without them forces every caller to
  special-case "no data", which is the opposite of what the contract's sentence
  is for.

  This is the capability where `PLAN.md` §6 risk 2 bites hardest: it is the one
  two live modules consume as a data source, and it has no `behavior` block, so
  the framework's obligation machinery cannot hold it to idempotence or
  ordering. Owner should decide whether to escalate to ac-designer for a
  `behavior` block before the developer starts. Absent that, the tests above
  are the only thing standing between `backtest` and `pricing` and an
  unguaranteed data source.

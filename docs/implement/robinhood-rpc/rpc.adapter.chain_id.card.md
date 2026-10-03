# card: robinhood-rpc / rpc.adapter.chain_id

- mode: full
- contract: architecture/contracts/robinhood-rpc-api.yaml
- capability: rpc.adapter.chain_id
- signature: "rpc.adapter.chain_id(url: str) -> ChainId"
- input schema: none — the contract declares a bare `url: str`, not a request type
- output schema: robinhood-protocol-api.ChainId
- behavior:
   unit: decimal
   time: wall_clock
   timezone: tz_aware_utc
   idempotent: true
   ordering: total
   stale_tolerance: none. A chain id is a network constant; re-probing the same endpoint returns the same value. If two reads of one url disagree, that is a failure, not a fresher value.
- errors:
   - code: RPC_ENDPOINT_UNREACHABLE
     recoverable: transient
   - code: RPC_CHAIN_ID_MISMATCH
     recoverable: permanent
   - code: RPC_CHAIN_ID_MALFORMED
     recoverable: permanent
   - code: RPC_RATE_LIMITED
     recoverable: transient
- test plan:
   - normal: >
       one url, `eth_chainId` returns a hex QUANTITY, decoded to the declared
       `robinhood-protocol-api.ChainId`. Verified against the live endpoint:
       `0x1237` = 4663 on `https://rpc.mainnet.chain.robinhood.com`.
  - boundary: >
       a url that is syntactically valid but answers on another chain returns
       `RPC_CHAIN_ID_MISMATCH`, not a value. FIXTURE: a stub transport that
       answers `{"result": "0xb626"}` for `eth_chainId`. This case used to name
       a live testnet endpoint and used to insist on not being mocked; Owner
       decision 2026-10-02 retired the testnet chain, and the notes record the
       downgrade and why it costs this test nothing.
   - invalid: >
       the contract declares `url: str` with no validation rule, so an empty
       string and a non-URL string are both in scope for the tester. Expected
       behaviour is `RPC_ENDPOINT_UNREACHABLE`. If the Owner wants these
       classified as `user_input` instead, that is a Card edit to route through
       the Owner — the contract does not say.
   - failure: >
       transport error, non-JSON body, and a JSON body that is missing `result`.
       All three must raise, none may return a default. A rate-limited response
       must surface as `RPC_RATE_LIMITED` and be retryable.
- reads allowed:
   - modules/robinhood-rpc/**
   - architecture/**
   - framework/architecture/__init__.py
   - modules/robinhood-protocol/api/**
- reads denied:
   - modules/robinhood-protocol/impl/**
   - modules/<other>/**
   - framework/architecture/_internals/**
- notes: |

  **This is the first capability in the module and it carries the shared
  machinery.** JSON-RPC envelope construction, error classification, retry
  policy and 429 handling all land here; the other four capabilities inherit
  them. Budget for that. Nothing else in the module is this cheap.

  ### Facts verified before writing this Card

  All from `https://rpc.mainnet.chain.robinhood.com`, chain id 4663, retrieved
  2026-09-30, `web3_clientVersion`
  `nitro/v3.12.0-rc.3+ebe9e83-20260916T211740Z/linux-amd64/go1.25.12`.

  - `eth_chainId` returns `0x1237`. Confirms the 4663 in
    `architecture/project.yaml`; no re-verification of the PoolManager was
    needed for this capability.
  - `eth_chainId` takes no parameters. Result is a hex QUANTITY string, per the
    Ethereum JSON-RPC spec (ethereum.org/en/developers/docs/apis/json-rpc/,
    retrieved 2026-09-30).
  - The endpoint rate-limits. Under rapid bursts it returns
    `{"code":429,"message":"Too Many Requests"}` — an HTTP-level 429 surfaced
    inside a JSON-RPC-shaped body, with **no `id` field**. Observed repeatedly;
    pacing requests ~3-5s apart stopped it. `RPC_RATE_LIMITED` is therefore a
    real path, not a hypothetical one, and the retry policy has to be written
    against it.
  - A genuinely unknown method returns
    `-32601 "the method … does not exist/is not available"`, confirming the node
    does distinguish "no such method" from other failures. Relevant because it
    tells the developer a closed-set violation is detectable at runtime rather
    than silently returning `null`.

  ### Not verified — the tester must not treat these as known

  - **Which endpoints exist.** Settled by Owner decision on 2026-10-02: two
    mainnet endpoints, recorded by environment variable name in
    `architecture/project.yaml` -> `rpc_endpoints`. The values live in `.env`
    and carry API keys, so the tester reads them from there; nothing tracked in
    this repository names a url for the second one, and none should. This
    capability takes a single `url` and is unaffected either way.
  - **What the second endpoint can do.** UNKNOWN, and no amount of reading this
    Card establishes it: no cap, no window, no rate limit, not even a chain id
    has been measured on `ROBINHOOD_MAINNET_RPC_URL`. Every number in this
    repository belongs to the official endpoint. `capability_probe` is the
    capability that settles it, and its Card has to probe both variables rather
    than carry a number across.
  - **The error codes above are mine, not the contract's.** The contract declares
    no `errors:` block for any `rpc.adapter.*` capability. I chose these four to
    cover the failure modes actually observed. The Owner should confirm the
    vocabulary at the Card gate, because these strings are what callers branch
    on and renaming one later is breaking.

  ### `ChainId` is declared; the input side is not

  `robinhood-protocol-api.ChainId` has a real schema
  (`type: integer, minimum: 1`). The input does not: the contract writes
  `url: str` in the signature and declares no request type, so there is nothing
  for the tester to validate a url against. That is a gap in the contract, not
  something this Card papers over — recorded rather than filled with an invented
  `EndpointUrl` type.

  ### This test was a live-endpoint test until 2026-10-02, and is not any more

  Recorded rather than quietly rewritten, because a test plan that changed
  without a trace is the shape this repository has already retired things for.

  Until Owner decision 「testnet 彻底删除」 on 2026-10-02, the boundary case
  named `https://rpc.testnet.chain.robinhood.com` — which answers `0xb626` =
  46630 — and this Card claimed the test "must be tested with the real testnet
  endpoint, not a mock". The chain id and the endpoint left
  `architecture/project.yaml` that day, and the claim went with its object: a
  test that needs an endpoint nobody may dial is not a test, it is an outage
  waiting to be reported as a defect.

  The fixture is now a stub transport answering `{"result": "0xb626"}`. The
  downgrade costs this test nothing, and the reason is worth keeping:

  - What this case guards is the adapter's comparison: given an endpoint that
    answers but is not this chain, raise rather than return. `0xb626` IS what a
    real different-chain endpoint returns, so the fixture value is the real
    one, and the only parts of the path it does not exercise are the adapter's
    own hex parse and integer compare — which are the parts under test.
  - A live endpoint welds the assertion to reachability, key validity, chain
    liveness and rate-limit state. Any one of those failing produces a failure
    that is about the network, and a tester cannot tell it from a real defect.
  - The conversion is arithmetic. `0xb626` = 46630 and `0x1237` = 4663 need no
    chain to confirm, and the expected side is already established in
    `project.yaml`.

  What the tester gives up is confirmation that a real node's mismatch response
  parses into the adapter's error path. If that is wanted back, the cheap form
  is one manual probe of a real endpoint with the response shape recorded in
  `project.yaml` — a fact recorded once, rather than a dependency the suite
  carries on every run.

  ### The chain-id door is still a door, and deleting the constant did not close it

  `protocol.identity.chain_id.parse` accepts an arbitrary ChainId string by
  design; it is a parser, and refusing chains is not its job. This capability is
  the second such door: the endpoint is a parameter, so its answer is unverified
  input. `RPC_CHAIN_ID_MISMATCH` is what stops a wrong chain becoming a live
  value downstream, so it has to be implemented and tested for real — which the
  boundary case above now does, without a network. The rewritten paragraph in
  `project.yaml` says the same thing about the same two functions.

  ### No consumers yet

  `state dependers-of rpc.adapter.chain_id` returns `declared_dependers: []`.
  The contract's own prose calls this the "chain-id verification gate", so the
  consumer is intended but not declared anywhere. Recorded so the Owner
  decides it deliberately; not a reason to hold the build.

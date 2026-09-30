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
       `RPC_CHAIN_ID_MISMATCH`, not a value. The testnet endpoint
       `https://rpc.testnet.chain.robinhood.com` answers `0xb626` = 46630 and is
       the natural fixture for this — see notes, it is a policy exclusion, not a
       technical impossibility.
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

  - **Whether more than one endpoint exists.** Only the one above is
    established anywhere in this repository. The signature takes a single `url`,
    so this capability is unaffected — but `capability_probe` takes
    `urls: list[str]` and cannot be written until the Owner says where a list
    comes from.
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

  ### Chain 46630 is a policy exclusion, and this Card is where it could leak

  The testnet endpoint answers and returns 46630. `architecture/project.yaml`
  records that "mainnet only" is a POLICY, and names
  `protocol.identity.chain_id.parse` as the place a testnet connection would
  enter the system — because it accepts an arbitrary chain id string by design.
  This capability is a second such door: it returns a `ChainId` straight from
  whatever endpoint it is handed. The `RPC_CHAIN_ID_MISMATCH` error is what stops
  46630 becoming a live value downstream, so it must actually be implemented and
  must be tested with the real testnet endpoint, not a mock.

  ### No consumers yet

  `state dependers-of rpc.adapter.chain_id` returns `declared_dependers: []`.
  The contract's own prose calls this the "chain-id verification gate", so the
  consumer is intended but not declared anywhere. Recorded so the Owner
  decides it deliberately; not a reason to hold the build.

# PLAN: robinhood-rpc

## 1. Module purpose

Bounded JSON-RPC adapter — the only RPC surface V1 exposes is the closed method
set `eth_blockNumber`, `eth_getBlockByNumber`, `eth_getLogs`,
`eth_getTransactionReceipt`, `eth_call`, `eth_chainId`, `eth_getCode`; no
arbitrary RPC, no signing, no broadcasting.

## 2. Capability inventory

| id | mode | upstream state | test plan summary |
|---|---|---|---|
| `rpc.adapter.chain_id` | full | `pending` (robinhood-protocol) | chain id parse rejects non-decimal; hex result decodes to declared `ChainId`; per-endpoint, one url |
| `rpc.adapter.block_header` | full | `pending` | non-hydrated fetch by number; `null` for a future block; retry on 429/5xx; no retry on malformed param |
| `rpc.adapter.logs` | full | `pending` | five-topic0 OR + topic1 filter; adaptive range splitting under the measured caps; no-match returns `[]` not an error |
| `rpc.adapter.call` | full | `pending` | block-pinned `eth_call`; revert surfaces as error not `0x`; no retry on malformed call |
| `rpc.adapter.capability_probe` | full | `pending` | per-endpoint probe; the numbers it reports are measured at runtime, not asserted |

All five are `unregistered` in `STATE.yaml`. `modules/robinhood-rpc/` does not
exist; the module has no source and no tests.

Upstream `robinhood-protocol` state: `robinhood-protocol` itself is not
registered either, so the three `uses:` entries
(`protocol.pool_key.parse`, `protocol.identity.chain_id.parse`,
`protocol.identity.address.parse`) resolve to a contract that exists but has no
approved capability behind it. **This is a gate question for the Owner, not
something I can decide** — see Risks.

## 3. Implementation order

`rpc.adapter.chain_id` first. It is the only capability whose whole job is one
method with no block pinning, and it is the natural place to settle the shared
concerns: JSON-RPC envelope, error classification, retry policy, 429 handling.
Every other capability inherits those.

`rpc.adapter.block_header` second. It adds block-ref resolution and the
`eth_blockNumber` head read, and it is the cheapest place to pin down what a
`BlockHeader` is allowed to contain.

`rpc.adapter.call` third, `rpc.adapter.logs` fourth, `rpc.adapter.capability_probe`
last. The ordering of the last two is a real dependency: `capability_probe`
measures the caps that `logs` then has to split ranges under, so building `logs`
first means writing the splitting heuristic against guessed numbers. Build the
probe first and `logs` gets its constants from a measurement.

`logs` and `call` share the endpoint-selection and failover helper; the module
description promises endpoint failover and redacted metrics, and both belong in
`chain_id`'s groundwork rather than being written twice.

## 4. Gates

Per capability, in order: module-designer Card → Owner Card gate → tester writes
tests → developer writes `modules/robinhood-rpc/**` + Manifest → tester re-runs
if the Card's test plan was under-specified → reviewer audits → APPROVED →
`fully_approved`.

No capability here should be `mvp`ed. Reason below, under Cross-module exposures.

## 5. Cross-module MVP exposures

**None.** `archctl consumers robinhood-rpc-api` reports no consumer, and
`state dependers-of` returns `declared_dependers: []` for all five capabilities.
No other module's contract declares a `uses:` on `robinhood-rpc-api`.

That cuts both ways, and the honest reading is uncomfortable: the module whose
job is to be the only door to the chain has no declared customer. The contract
prose says "The ingestion router uses this to choose endpoints and ranges", but
no `ingestion` module or capability exists in `architecture/`. Under
`docs/design/DECLARATION-PROVENANCE.md` step 2 ("find the load-bearing
consumer"), five capabilities whose only support is a sentence in their own
contract are exactly the shape that has already produced three retirements in
this repository.

This does not block starting the module — an adapter with no consumer yet is
still the right place to begin, and the alternative (build nothing, wait for a
consumer) is not a plan. But it should be an explicit Owner decision rather
than a silence, and it is the first entry under Risks.

Mode recommendation: **full for all five.** The MVP argument is weak here
specifically because there is no consumer to serve quickly. An MVP would produce
disposable code plus a `## discovery` section, and the next thing that needs
this module is a full Card anyway.

## 6. Risks and open questions

1. **A contract-scoped Design Blocker is filed and unresolved.**
   `docs/implement/robinhood-rpc/CONTRACT.design-blocker.md` — the closed topic0
   set in the contract is derived from v4-core `main` signatures where `PoolId`
   is `address`, and it matches nothing on this chain. This stops
   `rpc.adapter.logs` and cannot be resolved by editing a Card. Owner action:
   route to ac-designer before dispatching the `logs` developer.

2. **Five types have no declared schema.** `BlockRef`, `BlockHeader`,
   `TopicFilter`, `LogRecord` and `CapabilityReport` all report as
   `SCHEMA_UNDECLARED`; there is no `architecture/schemas/robinhood-rpc-api.yaml`
   at all. A tester cannot state an expected value for a type with no fields, so
   the Card below names the fields as required outputs and flags the missing
   schema. Schema authoring is ac-designer's, not mine.

3. **`protocol.pool_key.parse` has no consumer in this module.** The `module.yaml`
   `reason` says the dependency exists to "validate the chain_id, contract
   address and topic filter", but no `rpc.adapter.*` signature takes a `PoolKey`.
   Either the `TopicFilter` shape turns out to embed one, or the `uses:` entry is
   a declaration with no load-bearing consumer. Do not resolve this by Card edit —
   it is a `module.yaml` question for ac-designer.

4. **`T020` and `T024` cite documents that do not exist here.** `grep` finds
   those strings only in the two files that cite them plus
   `docs/design/DECLARATION-PROVENANCE.md`, which records that the `T020`–`T113`
   numbering was itself one of the borrowed-numbering retirements. Per
   DECLARATION-PROVENANCE step 4, a citation must resolve inside this repository.
   `UNKNOWN` provenance for the closed method set and the probe spec.

5. **Which chain the limits below belong to.** Every measured number in this PLAN
   comes from one endpoint, `https://rpc.mainnet.chain.robinhood.com`, on chain
   4663. A second endpoint is not established anywhere in this repository. The
   probe exists precisely because limits are per-endpoint — so a Card asserting
   "the log cap is 10000" would be asserting a fact about one host as though it
   were a fact about the adapter.

## 7. What was measured, and where

All reads: chain id 4663, endpoint `https://rpc.mainnet.chain.robinhood.com`,
retrieved 2026-09-30, `web3_clientVersion`
`nitro/v3.12.0-rc.3+ebe9e83-20260916T211740Z/linux-amd64/go1.25.12`.

| fact | value | how established |
|---|---|---|
| PoolManager runtime code | 24009 bytes, keccak `0xbd3881…5626` at block `0x48ad6c0` | `eth_getCode` + local keccak256; matches `architecture/project.yaml` |
| `eth_getLogs` result cap | 10000 matches, then `-32000 "logs matched by query exceeds limit of 10000"` | triggered repeatedly, several filter shapes |
| `eth_getLogs` range cap, **no** address filter | 30000 blocks, then `-32602 "query spans N blocks … only 30000 are allowed"` | 30000 OK, 30001 rejected |
| `eth_getLogs` range cap, **with** address filter | 10000000 blocks, then `-32602` | 1M OK, full-history 76213404 rejected |
| Historical state retention | rolling window, roughly the most recent 5000-7000 blocks at measurement time | `eth_call` at `head-N`: OK to N=6000, ERR at N=7000, N=8000, N=16000 |
| `eth_call` at `finalized` | **fails**, `-32000 "historical state … is not available"` | reproduced at three different heads |
| `eth_call` at `safe` / `latest` / `pending` | succeeds | `owner()` returns the address in `project.yaml` |
| Rate limiting | `{"code":429,"message":"Too Many Requests"}` under rapid bursts | hit repeatedly; needed ~3-5s pacing |
| Finality tags | `safe` and `finalized` both resolve; `finalized` was 11955 blocks behind head at one sample | `eth_getBlockByNumber` |
| Block object extras | `baseFeePerGas`, `l1BlockNumber`, `sendCount`, `sendRoot` present; **`totalDifficulty` absent** | read at `0x48ad6c0` |
| Log object extras | `blockTimestamp` present, not in the Ethereum JSON-RPC spec | observed on every log |
| Receipt object extras | `gasUsedForL1`, `l1BlockNumber` present | `eth_getTransactionReceipt` |

The `totalDifficulty` absence and the three `l1*` extras are chain facts a
developer would otherwise discover by writing a strict decoder and having it
throw. They belong in `BlockHeader`'s required outputs.

Not established — recorded as `UNKNOWN`, not guessed:

- whether `ProtocolFeeUpdated` ever fires on this chain (topic0 is in the
  bytecode; zero logs in 10 sampled windows)
- whether any endpoint other than the one above exists, and therefore whether
  the per-endpoint limits are per-host or per-chain
- the archive-node story: no archive endpoint was found, and no document in this
  repository claims one

## 8. Why `capability_probe` is not a Card that can be written yet

The task asked for a judgement here, and it is a Design Blocker, for a reason
worth stating precisely — not because the capability is un-specifiable, but
because of what the measurements showed about the endpoint it must probe.

`capability_probe` reports four things: measured block range cap, log interval
cap, archive support, and finality. A Card cannot pre-write any of the four,
and that is correct: the whole point is that these are facts about a specific
endpoint at a specific moment. Nothing in the contract asks the Card to know
them in advance. **On its own terms this capability is well-formed.**

What blocks it is different. Two of the four fields it must report cannot be
filled in at all against the endpoint that exists:

- **archive support** — there is no archive endpoint in this repository and the
  one public endpoint serves a rolling window of roughly the most recent
  5000-7000 blocks. "Archive support: false" is a reportable value, so this one
  is fine.
- **finality** — this is the blocker. The contract's `rpc.adapter.call` is
  specified as a *block-pinned* `eth_call`, and `block_header` resolves a
  `BlockRef`. But `eth_call` at the `finalized` tag **fails** on this endpoint,
  reproduced at three different heads, with
  `-32000 "historical state … is not available"`. A capability that promises
  "block-pinned, and here is the block" cannot keep that promise for any block
  outside a rolling ~6000-block window, and cannot honour `finalized` at all.

That is not a Card defect. It is the adapter discovering, at runtime, that the
promise its own contract makes is not one this endpoint can keep. The question
— does V1 require replay against historical state, and if so from where — is an
Owner decision, and it decides whether `rpc.adapter.call` is implementable as
written or needs its contract clause revised. It is filed as item 1 of the
Design Blocker's surrounding evidence rather than as a second blocker, because
one blocker per defect is the rule and this is the same defect seen from the
probe's side: the closed world the contract describes and the world the endpoint
offers do not line up.

**Recommendation: build `chain_id` first and defer the probe Card until the
Owner rules on historical state.** The probe is the capability that will produce
the evidence for that ruling, so writing its Card first would fix in prose the
very numbers the probe exists to measure.

# Robinhood Chain observations

Measurements taken against Robinhood Chain mainnet (chain id **4663** /
`0x1237`) between 2026-09-29 and 2026-10-02, by ac-designer and the
dispatcher, while designing an RPC adapter that is **not** currently in this
repository.

## Why this file exists

Between 2026-09-28 and 2026-10-02 this repository carried twelve
`robinhood-*` contracts and modules. They were mapped in at the root commit
from an external "lp project"; none of them had a line of implementation, and
the 35 task numbers their descriptions cite resolve to no task list anywhere
— only to each other. They were withdrawn on 2026-10-03 as a design that
described some other system.

That withdrawal must not throw away the reads. The observations below are
facts about a public chain, established by block-pinned reads, and they are
the expensive part: nothing in this repository can produce them again
without re-running the probes. `AGENTS.md` §4 requires exactly this shape —
the coordinates, not the conclusion — and the withdrawal does not discharge
that requirement.

**Nothing here is a contract.** No capability is declared, and no module
depends on this file. If an RPC module is ever designed, this is the
evidence it starts from, re-verified rather than trusted: a fact about a
chain rots, and three of the entries below had already been revised once by
the time they were written down.

## The endpoint

| | |
|---|---|
| URL | `https://rpc.mainnet.chain.robinhood.com` |
| chain id | 4663 (`eth_chainId`, 2026-09-29T04:22:37Z, head `0x47e02c7`) |
| credential | in `.env` (gitignored); never in a tracked file |

A second endpoint variable, `ROBINHOOD_MAINNET_RPC_URL`, is configured for
redundancy and has **never been read from this repository** — not its chain
id, not its limits, nothing. Its chain id is `UNKNOWN` here rather than
copied from the entry above: the variable *name* says mainnet, and a name is
metadata, not evidence (`AGENTS.md` §4, "Names are not evidence").

## The Uniswap V4 deployment

| | |
|---|---|
| address | `0x8366a39cc670b4001a1121b8f6a443a643e40951` |
| runtime code hash | `0xbd3881180b547f5fe817545743cfb4343e96b1bc6640dcd70c106b0066e95626` |
| size | 24009 bytes |
| `owner()` | `0x2bad8182c09f50c8318d769245bea52c32be46cd` |
| read at | block `0x48109fa`, 2026-09-29T09:56:10Z |
| re-read at | block `0x48b6c31`, 2026-09-30T04:55:43Z — hash unchanged |

The address came from Uniswap's published deployments page, which is
**third-party** for the purpose of pinning it. The chain read is the
verification: code at the address, and `owner()` answering with the address
the docs name. That is weaker than it looks — a code hash proves a contract
exists, not that it is a PoolManager. Treat "this is the V4 PoolManager" as
confirmed-at-this-block, and re-verify by behaviour (an `Initialize` event, a
`Swap` event) before depending on it.

### The five PoolManager events use `bytes32` PoolId

This is the one finding that reversed an earlier decision, so it carries its
own refutation. Upstream v4-core types PoolId as `address`; here it is
`bytes32`.

Evidence (block `0x48b6c31`, hash
`0x7e5a524dc66f3ed9b2519468651a5d11b470eaca63ca63479b2934322e6275d0`):
all five topic0 values were recomputed locally by keccak256 over their
signature strings and match; each occurs exactly once as a `PUSH32` immediate
in the 24009 runtime bytes. The five `address`-typed signatures are
**absent from the bytecode** and returned 0 logs over five 50000-block
windows in which the `bytes32` set returned logs. Independently of the
topic0 values: decoding an observed `Initialize` log and recomputing
`keccak256(abi.encode(PoolKey))` reproduces its `topics[1]` exactly.

### The event set, as emitted by this chain

`ProtocolFeeUpdated` (2 topics), `Swap` (3), `ModifyLiquidity` (3),
`Initialize` (4), `Donate` (observed 0 logs in both sampled ranges, so its
topic count is **not** established).

`ProtocolFeeUpdated` fires on this chain: 41372 occurrences across 1220
distinct blocks spanning `0x402776e`–`0x48b87cc`. An earlier Design Blocker
recorded it as `UNKNOWN` because ten 40-block windows at stride `0x4000`
returned zero. That sampling covers 0.24% of the span, and re-running the
same ten windows reproduced the zero. **The event is common, and its absence
from a sample is a fact about the sample.**

Two more events appear on this address and belong to no pool:
`Transfer(address,address,address,uint256,uint256)` =
`0x1b3d7edb2e9c0b0e7c525b20aaaef0f5940d2ed71663c7d39266ecafac728859`
(4 topics, ERC-6909 id+amount) in every sampled window, and
`0xceb576d9f15e4e200fdb5096d64d5dfd667e16def20c1eefd14256d8e3faa267`
(3 topics, 2 occurrences in ~480000 blocks). **UNKNOWN** what the second one
is — none of 33 candidate signatures hashes to it.

## What the endpoint answers

### `eth_getBlockByHash` is available; EIP-1898 is not

Block `0x48ad6c0`, 2026-10-02.
`eth_getBlockByHash("0x4abf12cc…33b66", false)` answered with number
`0x48ad6c0` and that same hash. The number was independently established by
`eth_getBlockByNumber`, so the two methods corroborate each other rather
than the endpoint merely accepting a string. Same 23 fields as
`eth_getBlockByNumber`, same six-element non-hydrated `transactions`, same
absence of `totalDifficulty`.

The second argument is a bool and only a bool. A block tag gives `-32602
"invalid argument 1: json: cannot unmarshal string into Go value of type
bool"`, so the `(hash, blockTag)` form is **not implemented** — a caller
wanting a pinned read has nothing to pin to and must pass `false`.

This entry exists because the method was nearly deleted on a bad
reasoning: a `grep` found no mention of it in this repository, which is
evidence about *this repository*, not about the chain.

### The block object is not the Ethereum block object

At `0x48ad6c0` and `0x4a4c810`, 2026-10-02. Four fields **present** that the
Ethereum spec does not have: `baseFeePerGas` `0x172d980`, `l1BlockNumber`
`0x18e1128`, `sendCount` `0xb37`, `sendRoot` `0xd85d55b4…`. One field
**absent** that it does: `totalDifficulty`, at both blocks.

A strict decoder written against the Ethereum spec therefore throws on a
real response from this chain — on the extras and the omission together.
`sendRoot` equalled `extraData` at `0x48ad6c0`; whether that is a fact or a
coincidence of one block is **not established**.

The meaning of `l1BlockNumber`, `sendCount` and `sendRoot` is **UNKNOWN** in
this repository. No document here defines them, and a guessed meaning would
be inherited by every Card written from it.

Full field list at `0x48ad6c0`: baseFeePerGas, difficulty, extraData,
gasLimit, gasUsed, hash, l1BlockNumber, logsBloom, miner, mixHash, nonce,
number, parentHash, receiptsRoot, sendCount, sendRoot, sha3Uncles, size,
stateRoot, timestamp, transactions, transactionsRoot, uncles.

### The log object carries a `blockTimestamp` that is always zero

`0x4a4ca04` and `0x4800000`–`0x4810000`, 2026-10-02. `blockTimestamp` is
present on the log object (it is not in the Ethereum log object) and read
`"0x0"` on **all 1351 records inspected** — 1067 over `0x4a4c810`–`0x4a4ca04`
and 284 over the second range under a `ProtocolFeeUpdated` filter, two ranges
about 2.6 million blocks apart. The containing block's own `timestamp` at
`0x4a4c810` read `0x6abf2393`, so the zero is not a block with no clock.

Every record carried exactly: address, topics, data, blockNumber,
transactionHash, transactionIndex, blockHash, blockTimestamp, logIndex,
removed. `removed` read false in all 1351.

### `eth_call` cannot serve a `finalized` block

Block `0x48b76f1`, 2026-09-30T04:59:00Z. `eth_call` at tag `finalized` gives
`-32000 "historical state ... is not available"`; `safe`, `latest` and
`pending` all answer. So the block is *known* —
`eth_getBlockByNumber("finalized")` resolves its number and hash — but its
state is not served.

### The state window has no stable edge

Block `0x48b8abf`, swept over ~30 minutes on 2026-09-30T05:12:00Z. Readable
to roughly head-6000 and failing by head-6500 in one sweep; head-5000 failed
in an earlier sweep and succeeded in a later one at a later head. Probing
**one fixed block ten times** returned OK seven times, then `-32000` twice.

So the edge is neither a constant offset from head nor a function of the
block number: availability is a property of the serving node at request time.
**No number of blocks can be written down as the boundary**, because it was
already wrong twice on the afternoon it was measured.

### Headers and logs are retained far wider than state

- headers served at head-20000000; all four tags resolved (`0x48ba191`)
- `ProtocolFeeUpdated` logs served from head-1000000 (7290 of them) and from
  as far back as `0x402776e`; `Swap` from head-100000

So the three horizons differ, and a replay that fetches a wide log range then
reads state across it hits the state window partway through. `Swap` did
**not** come back from head-1000000 — that query hit the 10000-result cap,
which is a result-count limit, not a retention limit, and says nothing about
how far back `Swap` goes.

Other limits on this endpoint: `eth_getLogs` caps at 10000 results (at a
30000-block range with no address filter, 10000000 with one); HTTP 429 under
rapid bursts, needing ~3–5s of pacing.

### `eth_getTransactionReceipt` serves old receipts but takes no pin

`0x4aac83b` and `0x4800b65`, 2026-10-02. Sixteen fields, including two the
Ethereum receipt object does not have — `l1BlockNumber` (`0x18e5589` and
`0x18dfa19` on the two reads) and `gasUsedForL1` (`0x0` and `0x61c`). The
values differ between the two reads, so **neither is a constant**.

**The limiting fact: this method takes one argument.** A second — a block
number, or the EIP-1898 object — is refused whatever it is, with `-32602
"too many arguments, want at most 1"`. The refusal arrives as **HTTP 200
carrying a JSON-RPC error object**, so a client that checks only the HTTP
status sees a success.

What that rules out is *pinning*, not history: a receipt 50000 blocks back
(`0x4aa0564`) was served without complaint. An earlier version of this entry
said "receipts are tip-only", and the 50000-block read refutes it. The
limitation's actual shape is that a receipt read carries no block pin while
every other read here is addressed by one.

### The endpoint refuses Python's default urllib User-Agent

2026-10-02, identical request, six User-Agent values. HTTP 403 with body
`error code: 1010` for `Python-urllib/3.12`, `Python-urllib/3.11` and
`Python-urllib`. HTTP 200 for an **empty** User-Agent, and for `curl/8.5.0`,
`python-requests/2.31`, `Mozilla/5.0`, `node-fetch/1.0`, and a custom
string. Matching is on exact capitalisation: lower-case
`python-urllib/3.12` answers 200.

So the rule is **not** "send a User-Agent" — an absent one is fine. It is
"do not send Python's default urllib User-Agent", which is a bot-string list
matching on prefix. A `requests` client is unaffected; a
`urllib.request` client that does not override the header gets a 403 that
looks exactly like a network fault and would be misread as one. The 403
arrives before any JSON-RPC processing, so there is no `error` object to
classify it by — the HTTP status has to be read first.

## Testnet

A testnet chain id, endpoint and verification entry existed in
`architecture/project.yaml` until Owner decision 2026-10-02 removed them
rather than commenting them out: a value living in a comment is one the next
reader treats as a fixture. There is no testnet in this file, and no
excluded-chain constant either.

## Re-verification

Every entry carries the block or date it was read at, per `AGENTS.md` §4.
Three of them were **revised** while being written — the receipt's
limitation, the `ProtocolFeeUpdated` absence, and the `bytes32` PoolId — each
because an earlier version stated more than the read supported. Re-verify
before citing; do not cite this file as current.

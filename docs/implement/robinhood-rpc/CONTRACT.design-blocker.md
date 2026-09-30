# design blocker: robinhood-rpc / (contract)

- found by: module-designer
- surface: contract
- conflict: >
  `rpc.adapter.logs` declares a CLOSED topic0 set of five PoolManager events and
  states that the query shape is
  `topic0 IN (<the five>) AND topic1 = <poolId>`. The five topic0 values implied
  by the signatures in `architecture/contracts/robinhood-rpc-api.yaml` (taken
  from Uniswap v4-core `main`, where `PoolId` is ABI-typed as `address`) match
  **zero** logs on chain 4663 and are **absent** from the deployed PoolManager
  runtime bytecode. The deployed contract declares `PoolId` as `bytes32`, so
  every topic0 differs. A developer following this contract builds a filter that
  matches nothing and returns an empty stream forever, with no error.
- evidence: >
  Chain 4663, block 0x48ad6c0 (76207808), endpoint
  https://rpc.mainnet.chain.robinhood.com, retrieved 2026-09-30.
  `eth_getCode(0x8366a39cc670b4001a1121b8f6a443a643e40951, 0x48ad6c0)` returns
  24009 bytes, keccak256
  `0xbd3881180b547f5fe817545743cfb4343e96b1bc6640dcd70c106b0066e95626`,
  matching `architecture/project.yaml` -> `contracts.pool_manager`. A raw
  substring scan of that bytecode finds the five observed topic0 values
  present and all five v4-core-`main` values absent. `eth_getLogs` against that
  address over block windows `0x489d000..0x489d032`, `0x489d100..0x489d132`,
  `0x489f000..0x489f032`, `0x48a0000..0x48a0032` returns 151-219 logs each,
  every one carrying a topic0 in the observed set. Recomputed keccak256
  confirms the mapping (see table below).
- decision needed: >
  ac-designer must publish the five topic0 constants and their `bytes32`-PoolId
  event signatures as the authoritative closed set, replacing the v4-core-`main`
  signatures the contract currently implies, and must state that the closed set
  is a property of THIS deployment (pinned by the code hash in `project.yaml`)
  rather than of V4 upstream.
- resolution:

## Observed closed set, verified at block 0x48ad6c0 on chain 4663

Recomputed locally with keccak256 over the exact signature string; each value
was also located as a PUSH32 constant in the deployed runtime bytecode.

| event | signature with `bytes32` PoolId | topic0 |
|---|---|---|
| Initialize | `Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)` | `0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438` |
| ModifyLiquidity | `ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)` | `0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec` |
| Swap | `Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)` | `0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f` |
| Donate | `Donate(bytes32,address,uint256,uint256)` | `0x29ef05caaff9404b7cb6d1c0e9bbae9eaa7ab2541feba1a9c4248594c08156cb` |
| ProtocolFeeUpdated | `ProtocolFeeUpdated(bytes32,uint24)` | `0xe9c42593e71f84403b84352cd168d693e2c9fcd1fdbcc3feb21d92b43e6696f9` |

The contract's `topic1 = <poolId>` half of the query shape **is** correct and
survives: every observed non-Initialize log carries the pool id in `topics[1]`.

## Two further findings that belong in the same decision

**1. A sixth event exists at the same address.** The closed set is not closed.
`Transfer(address,address,address,uint256,uint256)` =
`0x1b3d7edb2e9c0b0e7c525b20aaaef0f5940d2ed71663c7d39266ecafac728859` is
emitted by the PoolManager address and appears in every sampled window (1-21
per 50-block window). The contract says "There is no sixth event and no 'any
other PoolManager log' mode" — the first half is false as a statement about the
chain, and true only as a statement about what the adapter will filter to. That
distinction needs to be written down, because a reader currently takes it as a
claim about the deployment.

**2. `ProtocolFeeUpdated` is in the bytecode but was never observed firing.**
Its topic0 is present in the deployed runtime bytecode, so the event exists on
this deployment. Ten 40-block windows spanning `0x48a0000` to `0x48c4000` at
stride `0x4000` returned zero matching logs. Absence of observation over 10
sampled windows is **not** evidence of absence — `UNKNOWN` whether this chain
ever emits it. The contract's insistence that this event is the one that gets
forgotten is well-founded and must survive into the Card; the Card must not
assert a firing rate, because none was measured.

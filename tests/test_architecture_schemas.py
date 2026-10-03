"""Do the declared schemas in `architecture/schemas/` actually constrain anything?

A schema that accepts every instance is worse than no schema: it turns "the
type has no declared shape" into "the type has a declared shape that says
nothing", and the second is much harder to notice. That is exactly what
happened the first time these were written — `PoolKey.fee` was bounded at the
uint24 range (16777215) while its own description said the maximum was
1_000_000, so a fee V4 would reject validated clean.

These tests live here rather than in `framework/` on purpose. The framework
depends on nothing outside the standard library and PyYAML, and this needs
`jsonschema`. Adding a third-party validator to the framework to check the
framework's own data files would be the wrong trade; the schemas are project
data, so their tests are project tests.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

try:
    from jsonschema import Draft7Validator as _Validator, RefResolver
except ImportError:  # pragma: no cover - exercised only without the dependency
    _Validator = None

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "architecture" / "schemas"


def _load_all() -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for f in sorted(SCHEMA_DIR.glob("*.yaml")):
        for type_name, body in yaml.safe_load(f.read_text(encoding="utf-8")).items():
            docs[type_name] = body
    return docs


# --- instances for robinhood-rpc-api -----------------------------------------
#
# Every value below is SYNTHETIC. It is a test input chosen to be shaped like
# the thing, and it is never cited as evidence about the chain: the hashes, the
# height and the timestamp here are not measurements and nothing in this file
# may be read as a measurement. What the schema file pins to a block and a
# retrieval time is a claim about the world, and those coordinates live in
# `architecture/project.yaml`, not here.
#
# They are module constants rather than inline because the projected forms are
# the positive half of every refusal below, and retyping a nine-field record in
# each case would leave the reader comparing two literals instead of one
# instance and one mutation of it.
ADDR = "0x" + "11" * 20
POOL_ID = "0x" + "22" * 32
BLOCK_HASH = "0x" + "33" * 32
TX_HASH = "0x" + "44" * 32
PARENT_HASH = "0x" + "55" * 32
HEIGHT = 4_760_240

# The five topic0 constants, spelled as the schema file spells them, so a
# refusal below is about the SCHEMA and not about a transcription.
INITIALIZE = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
MODIFY_LIQUIDITY = "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec"
SWAP = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
DONATE = "0x29ef05caaff9404b7cb6d1c0e9bbae9eaa7ab2541feba1a9c4248594c08156cb"
PROTOCOL_FEE_UPDATED = "0xe9c42593e71f84403b84352cd168d693e2c9fcd1fdbcc3feb21d92b43e6696f9"
FIVE_TOPICS = [INITIALIZE, MODIFY_LIQUIDITY, SWAP, DONATE, PROTOCOL_FEE_UPDATED]

# Two values this deployment's PoolManager emits that the contract's five do
# NOT name, quoted from robinhood-rpc-api -> rpc.adapter.logs description:
# `Transfer` "appeared in every sampled window", and an unidentified topic0
# "appeared twice in 480000 sampled blocks. UNKNOWN what the second one is".
# Both are refusals the schema has to make, and both are here for that reason.
TRANSFER_TOPIC0 = "0x1b3d7edb2e9c0b0e7c525b20aaaef0f5940d2ed71663c7d39266ecafac728859"
UNIDENTIFIED_TOPIC0 = "0xceb576d9f15e4e200fdb5096d64d5dfd667e16def20c1eefd14256d8e3faa267"

# The projected forms. Each is the value a decoder returns after selecting the
# declared fields and dropping the ones named in `x-wire-ignored`.
HEADER = {
    "number": HEIGHT,
    "hash": BLOCK_HASH,
    "parent_hash": PARENT_HASH,
    "timestamp": 1_789_546_387,
    "transactions": [],
}
LOG = {
    "address": ADDR,
    "topics": [SWAP, POOL_ID],
    "data": "0x",
    "block_number": HEIGHT,
    "block_hash": BLOCK_HASH,
    "transaction_hash": TX_HASH,
    "transaction_index": 0,
    "log_index": 3,
    "removed": False,
}
FILTER = {"address": ADDR, "pool_id": POOL_ID, "topic0": [INITIALIZE, SWAP]}

# `CapabilityReport.finality` is one entry per block tag, and the array is
# TOTAL — four entries, always, one per tag. These four rows are shaped like
# the reading the schema file pins: eth_getBlockByNumber answers for all four
# tags, and eth_call answers for three of them, because `safe`, `latest` and
# `pending` all answer while `finalized` raises -32000 "historical state ... is
# not available". The block is known and its state is not served, which is the
# distinction the shape exists to keep. The coordinates for that reading are in
# architecture/project.yaml -> endpoint_facts ("eth_call cannot serve a
# `finalized` block on this endpoint"), chain 4663, block 0x48b76f1, retrieved
# 2026-09-30 — they are there and not here, because this is a test input and a
# test input is not evidence about the world.
FINALITY_MEASURED = [
    {"tag": "latest", "block_resolved": True, "state_served": True},
    {"tag": "safe", "block_resolved": True, "state_served": True},
    {"tag": "pending", "block_resolved": True, "state_served": True},
    {"tag": "finalized", "block_resolved": True, "state_served": False},
]
# What "the probe resolved nothing" is now spelled. Under the two-array shape
# this was `{"resolved_tags": [], "state_served_tags": []}`, and it meant both
# "not tested" and "tested and failed"; the total array removes the ambiguity,
# so the same answer is four rows with both flags false. Built by comprehension
# so the four tags are the enum's and not a second hand-typed list.
FINALITY_NOTHING_RESOLVED = [
    {"tag": tag, "block_resolved": False, "state_served": False}
    for tag in ("latest", "safe", "pending", "finalized")
]

ENDPOINT = {
    # Deliberately not a real host. The contract keeps every url out of every
    # tracked file because they carry API keys, and a test that pasted one in
    # would undo that.
    "url": "https://endpoint.invalid",
    "measured_at_block": HEIGHT,
    "state_block_window": None,
    "log_block_window": None,
    "archive_supported": None,
    "finality": FINALITY_MEASURED,
}
REPORT = {"endpoints": [ENDPOINT]}


@unittest.skipIf(_Validator is None, "jsonschema is not installed")
class SchemaBehaviourTests(unittest.TestCase):
    """Each case is an instance that must be accepted or must be rejected.

    A schema's value is entirely in what it refuses. These are the refusals
    that matter, written as instances so a later edit that loosens a
    constraint has to be a deliberate change to a named expectation.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.docs = {}
        for f in sorted(SCHEMA_DIR.glob("*.yaml")):
            cls.docs[f.stem] = yaml.safe_load(f.read_text(encoding="utf-8"))

    def accepts(self, type_name: str, instance) -> bool:
        doc = next(d for d in self.docs.values() if type_name in d)
        resolver = RefResolver.from_schema(doc)
        errors = list(_Validator(doc[type_name], resolver=resolver).iter_errors(instance))
        return not errors

    def assertVerdict(self, type_name: str, instance, verdict: bool) -> None:
        got = self.accepts(type_name, instance)
        self.assertEqual(
            got, verdict,
            f"{type_name} {'accepted' if got else 'rejected'} {instance!r}, "
            f"expected the opposite",
        )

    def _tag_enum(self, *path: str) -> list[str]:
        """The `enum` a `tag` property declares, reached by its real path.

        A structural read rather than an instance probe, because a claim that
        two declarations are the SAME vocabulary is a claim about the two
        declarations. `KeyError` here means the file moved the property, and
        the test should fail loudly rather than quietly compare nothing.
        """
        node = self.finality_schema()
        for key in path:
            node = node[key]
        return list(node["enum"])

    def finality_schema(self) -> dict:
        """The `finality` subschema, as the file declares it."""
        doc = next(d for d in self.docs.values() if "CapabilityReport" in d)
        return doc["CapabilityReport"]["properties"]["endpoints"]["items"]["properties"]["finality"]

    def finality_tag_enum(self) -> list[str]:
        return self._tag_enum("items", "properties", "tag")

    def block_ref_tag_enum(self) -> list[str]:
        """`BlockRef`'s tag enum, found by shape: the `oneOf` branch with a `tag`.

        Located by looking rather than by index, so adding a branch to `BlockRef`
        does not make this read a different branch's vocabulary by accident.
        """
        doc = next(d for d in self.docs.values() if "BlockRef" in d)
        branches = [
            b for b in doc["BlockRef"]["oneOf"]
            if "tag" in b.get("properties", {})
        ]
        self.assertEqual(
            len(branches), 1,
            f"expected exactly one tag-addressed branch on BlockRef, found {len(branches)}",
        )
        return list(branches[0]["properties"]["tag"]["enum"])

    # -- EVM primitives ----------------------------------------------------

    def test_address_is_normalised_to_lowercase(self) -> None:
        self.assertVerdict("Address", "0x" + "ab" * 20, True)
        # The checksummed spelling is a different value to this type; it is
        # what AddressString accepts and what parse turns into this.
        self.assertVerdict("Address", "0x" + "AB" * 20, False)

    def test_address_string_accepts_either_casing_but_not_a_short_one(self) -> None:
        self.assertVerdict("AddressString", "0x" + "AB" * 20, True)
        self.assertVerdict("AddressString", "0x" + "ab" * 20, True)
        self.assertVerdict("AddressString", "0x" + "ab" * 19, False)

    def test_chain_id_must_be_positive(self) -> None:
        self.assertVerdict("ChainId", 4663, True)
        self.assertVerdict("ChainId", 0, False)
        self.assertVerdict("ChainId", -1, False)

    def test_chain_id_string_is_decimal_only(self) -> None:
        # "0x1237" is the same chain id in another base. Accepting it would
        # mean two spellings of one value, which is how a dedup key or an
        # equality check quietly stops matching.
        self.assertVerdict("ChainIdString", "4663", True)
        self.assertVerdict("ChainIdString", "0x1237", False)
        self.assertVerdict("ChainIdString", "+4663", False)

    # -- V4 pool identity --------------------------------------------------

    def test_pool_id_is_thirty_two_bytes_of_lowercase_hex(self) -> None:
        self.assertVerdict("PoolId", "0x" + "ab" * 32, True)
        self.assertVerdict("PoolId", "0xabab", False)

    def test_pool_key_requires_all_five_fields(self) -> None:
        key = {
            "currency0": "0x" + "00" * 19 + "01",
            "currency1": "0x" + "00" * 19 + "02",
            "fee": 3000,
            "tick_spacing": 60,
            "hooks": "0x" + "00" * 20,
        }
        self.assertVerdict("PoolKey", key, True)
        for field in key:
            partial = {k: v for k, v in key.items() if k != field}
            with self.subTest(missing=field):
                self.assertVerdict("PoolKey", partial, False)

    def test_pool_key_rejects_an_unknown_field(self) -> None:
        # PoolId hashes the struct, so a key carrying an extra field is a
        # different object than the one V4 would hash.
        self.assertVerdict(
            "PoolKey",
            {
                "currency0": "0x" + "00" * 19 + "01",
                "currency1": "0x" + "00" * 19 + "02",
                "fee": 3000, "tick_spacing": 60,
                "hooks": "0x" + "00" * 20,
                "salt": 1,
            },
            False,
        )

    def test_pool_key_fee_respects_max_lp_fee_not_the_uint24_range(self) -> None:
        """A uint24 holds 16777215, but V4 reverts above MAX_LP_FEE.

        Bounding at the uint24 range would validate a key V4 rejects, and the
        failure would appear later as a revert at Initialize instead of as a
        rejected key here.
        """
        def key(fee: int) -> dict:
            return {
                "currency0": "0x" + "00" * 19 + "01",
                "currency1": "0x" + "00" * 19 + "02",
                "fee": fee, "tick_spacing": 60,
                "hooks": "0x" + "00" * 20,
            }

        self.assertVerdict("PoolKey", key(1000000), True)      # MAX_LP_FEE
        self.assertVerdict("PoolKey", key(8388608), True)      # DYNAMIC_FEE_FLAG
        self.assertVerdict("PoolKey", key(1000001), False)
        self.assertVerdict("PoolKey", key(16777215), False)     # fits uint24, not V4
        self.assertVerdict("PoolKey", key(-1), False)

    def test_pool_key_tick_spacing_fits_int16(self) -> None:
        self.assertVerdict(
            "PoolKey",
            {
                "currency0": "0x" + "00" * 19 + "01",
                "currency1": "0x" + "00" * 19 + "02",
                "fee": 3000, "tick_spacing": 40000, "hooks": "0x" + "00" * 20,
            },
            False,
        )

    # -- V4 price ----------------------------------------------------------

    def test_sqrt_price_is_never_negative(self) -> None:
        self.assertVerdict("SqrtPriceX96", 79228162514264337593543950336, True)
        self.assertVerdict("SqrtPriceX96", -1, False)

    def test_sqrt_price_tick_requires_the_whole_ordering_triple(self) -> None:
        """The contract promises total order and dedup by the triple.

        A payload missing one of the three cannot support either promise, so
        the schema requires all of them rather than treating them as optional
        metadata.
        """
        obs = {
            "pool_id": "0x" + "cd" * 32,
            "sqrt_price_x96": 79228162514264337593543950336,
            "tick": 201234,
            "block_number": 100,
            "transaction_index": 2,
            "log_index": 5,
        }
        self.assertVerdict("SqrtPriceTick", obs, True)
        for field in ("pool_id", "sqrt_price_x96", "tick",
                      "block_number", "transaction_index", "log_index"):
            with self.subTest(missing=field):
                self.assertVerdict(
                    "SqrtPriceTick", {k: v for k, v in obs.items() if k != field}, False
                )

    def test_sqrt_price_tick_respects_int24(self) -> None:
        obs = {
            "pool_id": "0x" + "cd" * 32,
            "sqrt_price_x96": 1, "tick": 887272,
            "block_number": 0, "transaction_index": 0, "log_index": 0,
        }
        self.assertVerdict("SqrtPriceTick", obs, True)
        self.assertVerdict("SqrtPriceTick", dict(obs, tick=887273), False)

    def test_display_price_is_a_string_with_at_most_eighteen_fractional_digits(self) -> None:
        """More precision than the contract rounds to is not a display price.

        This is the same bound that makes PROTOCOL_DISPLAY_OUT_OF_RANGE a real
        error rather than a dead code: a price needing more than 18 fractional
        digits is rejected here and raised there.
        """
        self.assertVerdict("DisplayPrice", "1.2345", True)
        self.assertVerdict("DisplayPrice", "0.000000000000000001", True)   # 18 digits
        self.assertVerdict("DisplayPrice", "0." + "0" * 21 + "1", False)   # 22 digits
        # A JSON number is an IEEE double: 18 fractional digits do not
        # survive one, so a numeric price is silently rounded.
        self.assertVerdict("DisplayPrice", 1.2345, False)

    # -- vocabularies ------------------------------------------------------

    def test_lock_state_is_exactly_two_values(self) -> None:
        # An UNKNOWN that is not in the enum could not be refused against by
        # the execution layer's "refuse on LOCKED" rule.
        self.assertVerdict("LockState", "LOCKED", True)
        self.assertVerdict("LockState", "UNLOCKED", True)
        self.assertVerdict("LockState", "UNKNOWN", False)

    def test_lock_state_vocabulary_enumerates_both_values_without_repeats(self) -> None:
        self.assertVerdict("LockStateVocabulary", ["LOCKED", "UNLOCKED"], True)
        self.assertVerdict("LockStateVocabulary", ["LOCKED", "LOCKED"], False)
        self.assertVerdict("LockStateVocabulary", [], False)

    def test_sizing_error_vocabulary_is_closed(self) -> None:
        self.assertVerdict("SizingErrorVocabulary", ["PROTOCOL_TICK_NOT_ALIGNED"], True)
        self.assertVerdict("SizingErrorVocabulary", ["SOMETHING_ELSE"], False)

    def test_public_address_request_names_a_non_empty_key(self) -> None:
        self.assertVerdict("PublicAddressRequest", {"key_id": "lp-1"}, True)
        self.assertVerdict("PublicAddressRequest", {"key_id": ""}, False)
        self.assertVerdict("PublicAddressRequest", {}, False)

    def test_lock_state_request_takes_no_argument_at_all(self) -> None:
        """The refusal is the content of this schema, so it is what gets pinned.

        `signer.lock_state` reads the state of the signer process, not of a
        named key — its sibling `signer.public_address` is the one that takes a
        `key_id`. `additionalProperties: false` with `maxProperties: 0` says a
        caller passing a key is turned away rather than quietly ignored, which
        is what makes "lock_state takes no argument" something a test can state
        instead of something it has to infer. An empty object is the whole of
        the accepted set; a `key_id` here would be the per-key reading this
        schema exists to rule out.
        """
        self.assertVerdict("LockStateRequest", {}, True)
        self.assertVerdict("LockStateRequest", {"key_id": "lp-1"}, False)
        self.assertVerdict("LockStateRequest", {"any": 1}, False)

    # -- robinhood-rpc-api: the three forms of a block reference -------------

    def test_block_ref_accepts_exactly_its_three_addressing_forms(self) -> None:
        """A nominal union, not a constrained string.

        The file's own reason for three branches: the three forms are three
        different requests through three different methods, and a string would
        leave a consumer guessing which one was meant before it could issue a
        call. A schema that collapsed them would accept the guess.
        """
        self.assertVerdict("BlockRef", {"number": HEIGHT}, True)
        self.assertVerdict("BlockRef", {"number": 0}, True)
        self.assertVerdict("BlockRef", {"hash": BLOCK_HASH}, True)
        for tag in ("latest", "safe", "pending", "finalized"):
            with self.subTest(tag=tag):
                self.assertVerdict("BlockRef", {"tag": tag}, True)

    def test_block_ref_keeps_the_three_forms_distinct(self) -> None:
        """One branch's payload in another branch's envelope is refused.

        `{"hash": "latest"}` is the shape a caller writes when the type used to
        be a string, and it matches no branch: the hash branch wants 32 bytes
        of lowercase hex, the tag branch wants a `tag` key. The file's
        `x-arg-shape` on the hash branch records that there is no EIP-1898
        blockTag form to declare, so the refusal is the decision.
        """
        self.assertVerdict("BlockRef", {"hash": "latest"}, False)
        self.assertVerdict("BlockRef", {"tag": BLOCK_HASH}, False)
        self.assertVerdict("BlockRef", {"number": "1"}, False)
        # two branches at once is not a fourth form
        self.assertVerdict("BlockRef", {"number": HEIGHT, "tag": "latest"}, False)
        self.assertVerdict("BlockRef", {"number": HEIGHT, "hash": BLOCK_HASH}, False)
        self.assertVerdict("BlockRef", {}, False)

    def test_block_ref_refuses_the_earliest_tag(self) -> None:
        """`earliest` is a standard JSON-RPC tag this contract never mentions.

        The file says so twice, and says why admitting it would be wrong: it
        would be vocabulary invented by a schema rather than carried by a
        capability, and an `enum` makes a fifth tag inexpressible rather than
        merely discouraged.
        """
        self.assertVerdict("BlockRef", {"tag": "earliest"}, False)
        self.assertVerdict("BlockRef", {"tag": "Latest"}, False)
        self.assertVerdict("BlockRef", {"tag": "finalized "}, False)

    def test_block_ref_refuses_a_window_on_every_branch(self) -> None:
        """The one field the contract forbids this shared type from growing.

        `x-note` on `BlockRef`: the window belongs to
        `rpc.adapter.capability_probe`, because the two capabilities sharing
        this type are served over different horizons. `additionalProperties:
        false` per branch is what makes the refusal real rather than advisory,
        so each of the three branches is checked with a window on it — the
        spellings the note names, plus the capability's own parameter name.
        """
        for field in ("window", "lookback", "max_range", "from_block"):
            for branch in (
                {"number": HEIGHT},
                {"hash": BLOCK_HASH},
                {"tag": "latest"},
            ):
                with self.subTest(field=field, branch=sorted(branch)):
                    self.assertVerdict(
                        "BlockRef", dict(branch, **{field: 1000}), False
                    )

    def test_block_ref_number_is_a_non_negative_height(self) -> None:
        """`minimum: 0`, with deliberately no maximum.

        The `x-note` on the property gives the reason for the missing upper
        bound: a maximum would be a claim about this chain's head at the
        moment it was written, and heads only grow. The floor is the half that
        is a fact about the type rather than about a host.
        """
        self.assertVerdict("BlockRef", {"number": -1}, False)

    # -- robinhood-rpc-api: the projected header ---------------------------

    def test_block_header_accepts_the_projected_form(self) -> None:
        """The value a decoder returns, and the one a caller receives."""
        self.assertVerdict("BlockHeader", HEADER, True)

    def test_block_header_refuses_the_raw_response_object(self) -> None:
        """Documented behaviour, not a defect — and the file says so twice.

        Rule 1 in the file's header: a type here is the PARSED, PROJECTED value
        the adapter returns, not the JSON-RPC response object, and validating a
        raw response "fails by design, and that is stated rather than left to
        be discovered". The instance below is that raw object, assembled from
        the field names the file itself lists in `x-wire-ignored` plus
        `totalDifficulty` from `x-note-absent`.
        """
        raw = dict(
            HEADER,
            parentHash=PARENT_HASH,  # wire spelling of parent_hash
            difficulty="0x0", extraData="0x", gasLimit="0x1c9c380",
            gasUsed="0x0", logsBloom="0x" + "00" * 256, miner="0x" + "00" * 20,
            mixHash="0x" + "00" * 32, nonce="0x0000000000000000",
            receiptsRoot="0x" + "00" * 32, sha3Uncles="0x" + "00" * 32,
            size="0x220", stateRoot="0x" + "00" * 32,
            transactionsRoot="0x" + "00" * 32, uncles=[],
            baseFeePerGas="0x172d980", l1BlockNumber="0x18e1128",
            sendCount="0xb37",
            sendRoot="0xd85d55b464c9971287a5d516a3ddb19635a27e3b0592f41c5fa44331de32b70a",
        )
        self.assertVerdict("BlockHeader", raw, False)

    def test_block_header_refuses_total_difficulty(self) -> None:
        """`x-note-absent`: absent from THIS chain, and the absence is enforced.

        A decoder that requires the field — the pre-merge shape, which most
        Ethereum documentation still shows — throws on a real response from
        this deployment. Relaxing `additionalProperties` would turn the
        refusal back into a tolerance and lose the only check that the absence
        still holds.
        """
        self.assertVerdict("BlockHeader", dict(HEADER, totalDifficulty="0x0"), False)

    def test_block_header_refuses_the_four_chain_specific_fields(self) -> None:
        """Tolerated on the wire, refused in the published value.

        `x-wire-ignored` records the hazard precisely: a strict decoder
        written against the Ethereum block object throws on a real response
        because these four are there and `totalDifficulty` is not. It is now
        handled by NAMING them rather than by REQUIRING them — "demand is a
        claim that the value is wanted; tolerance is a claim that the key
        exists. Only the second one is true of `sendCount`." So a header that
        carries any of them, in the wire spelling the file quotes or the
        snake_case spelling the rest of this directory uses, does not validate.
        """
        for field in ("baseFeePerGas", "l1BlockNumber", "sendCount", "sendRoot"):
            with self.subTest(wire_name=field):
                self.assertVerdict("BlockHeader", dict(HEADER, **{field: "0x1"}), False)
        for field in (
            "base_fee_per_gas", "l1_block_number", "send_count", "send_root",
        ):
            with self.subTest(snake_name=field):
                self.assertVerdict("BlockHeader", dict(HEADER, **{field: 1}), False)

    def test_block_header_requires_all_five_fields(self) -> None:
        """Five required, and each one load-bearing enough to name here:
        identity (`number`, `hash`), continuity (`parent_hash`), the only
        clock in the architecture (`timestamp`), and the array that carries the
        capability's own adjective "non-hydrated" (`transactions`).
        """
        for field in HEADER:
            with self.subTest(missing=field):
                self.assertVerdict(
                    "BlockHeader",
                    {k: v for k, v in HEADER.items() if k != field},
                    False,
                )

    def test_block_header_transactions_are_hashes_and_nothing_else(self) -> None:
        """`non-hydrated` is a property of this object, so it is refusable.

        The `x-why` on the field: a decoder that hydrated transactions would
        return megabytes per block where a header is meant to be a few hundred
        bytes, which is what makes the two reads cheap enough to issue per
        block. An object element is refused, and `x-note` records that an EMPTY
        array is accepted — a block with no transactions is a value, not an
        absence, so this is not `minItems: 1`.
        """
        self.assertVerdict("BlockHeader", dict(HEADER, transactions=[]), True)
        self.assertVerdict("BlockHeader", dict(HEADER, transactions=[TX_HASH]), True)
        self.assertVerdict(
            "BlockHeader", dict(HEADER, transactions=[{"hash": TX_HASH}]), False
        )
        self.assertVerdict("BlockHeader", dict(HEADER, transactions=[1]), False)

    def test_block_header_refuses_a_misspelled_field_name(self) -> None:
        """The reason `additionalProperties: false` survives on this type.

        `x-wire-ignored` on `LogRecord` states the trade in full: relaxing it
        so the raw object's keys validate through "leaves `topics[i]`, `data`
        and the three ordering fields unconstrained against a misspelled name,
        and a misspelled constraint is a constraint nobody is enforcing". A
        typo has to be a refusal for that to be true of the whole file, so
        both a plausible typo and the wire spelling of a declared field are
        checked — the second because `x-wire-name` records that the wire says
        `parentHash` and the published type does not.
        """
        self.assertVerdict("BlockHeader", dict(HEADER, hasj=BLOCK_HASH), False)
        self.assertVerdict("BlockHeader", dict(HEADER, parentHash=PARENT_HASH), False)
        self.assertVerdict("BlockHeader", dict(HEADER, Number=HEIGHT), False)

    def test_block_header_hashes_are_lowercase_hex(self) -> None:
        """No consumer re-parses a wire quantity to compare two hashes.

        The `x-why` on `hash` ties this to the rule
        `robinhood-protocol-api.Address` already sets, and the tests for that
        type pin the same refusal from the other side.
        """
        self.assertVerdict("BlockHeader", dict(HEADER, hash="0x" + "AB" * 32), False)
        self.assertVerdict("BlockHeader", dict(HEADER, parent_hash="0xabcd"), False)
        self.assertVerdict("BlockHeader", dict(HEADER, number=-1), False)

    # -- robinhood-rpc-api: one log record ----------------------------------

    def test_log_record_accepts_the_projected_form(self) -> None:
        self.assertVerdict("LogRecord", LOG, True)

    def test_log_record_refuses_block_timestamp(self) -> None:
        """OWNER DECISION 2026-10-02, recorded in the file's own header.

        「如果获取的信息都是 0 就说明不支持这个数据,那就不要放进去」 — the log
        object's `blockTimestamp` read 0x0 on all 1351 logs read, at two blocks
        more than two million apart, so it is not a timestamp. It is in
        `x-wire-ignored` as ONE field a decoder MUST drop, and the
        replacement is `BlockHeader.timestamp` addressed by this record's
        `block_number`. Both spellings are refused, in both roles: a record
        that still carries the key, and a record carrying a snake_case field
        that means the same thing.
        """
        self.assertVerdict("LogRecord", dict(LOG, blockTimestamp="0x0"), False)
        self.assertVerdict("LogRecord", dict(LOG, block_timestamp=0), False)

    def test_log_record_refuses_a_window_folded_into_the_type(self) -> None:
        """`x-note-no-window`, with its reason.

        How far back logs are served is far wider than how far back state is
        served, and it moves; a range here would be a claim about one host at
        one moment sitting in a place every downstream Card would read as
        settled. The bounds arrive as the capability's own `from_block` /
        `to_block` parameters, and `rpc.adapter.logs`'s signature is where
        that is written down.
        """
        for field in ("from_block", "to_block", "window", "max_range"):
            with self.subTest(field=field):
                self.assertVerdict("LogRecord", dict(LOG, **{field: HEIGHT}), False)

    def test_log_record_requires_the_whole_ordering_triple(self) -> None:
        """`robinhole-replay-api` promises a total order on
        (block_number, transaction_index, log_index), and `x-why` on
        `transaction_index` says why that makes all three required rather
        than optional: the endpoint would send all three anyway, and the
        promise would still be unimplementable if any of them were nullable.
        """
        for field in ("block_number", "transaction_index", "log_index"):
            with self.subTest(missing=field):
                self.assertVerdict(
                    "LogRecord", {k: v for k, v in LOG.items() if k != field}, False
                )

    def test_log_record_requires_removed_without_pinning_it(self) -> None:
        """Required BOOLEAN, deliberately not pinned to `false`.

        `x-why` on the field: what an adapter or a replayer must DO with a
        `true` is not decided anywhere in this architecture, and pinning the
        field to a constant "would make that open question unrepresentable
        instead of unanswered, which is strictly worse". So a missing key is
        refused and both values are accepted.
        """
        self.assertVerdict(
            "LogRecord", {k: v for k, v in LOG.items() if k != "removed"}, False
        )
        self.assertVerdict("LogRecord", dict(LOG, removed=False), True)
        self.assertVerdict("LogRecord", dict(LOG, removed=True), True)

    def test_log_record_needs_topic0_and_the_pool_id(self) -> None:
        """`minItems: 2`, and the `x-note` gives the count: 2 observed for
        `ProtocolFeeUpdated`, 3 for `Swap` and `ModifyLiquidity`, 4 for
        `Initialize`. The floor is 2 because all five events take `PoolId` as
        their first indexed parameter, so no record this capability returns
        can have fewer.
        """
        self.assertVerdict("LogRecord", dict(LOG, topics=[SWAP]), False)
        self.assertVerdict("LogRecord", dict(LOG, topics=[]), False)
        self.assertVerdict("LogRecord", dict(LOG, topics=[INITIALIZE, POOL_ID]), True)
        self.assertVerdict(
            "LogRecord", dict(LOG, topics=[INITIALIZE, POOL_ID, TX_HASH, TX_HASH]), True
        )

    def test_log_record_refuses_a_derived_pool_id_or_event_field(self) -> None:
        """`x-note-no-duplicates`: neither `pool_id` nor `event` is a field.

        Both are readable already — the pool id is `topics[1]` and the event
        is `topics[0]` — and "a consumer that trusted `pool_id` would have two
        sources of truth for one value and no way to learn which one a decoder
        filled in".
        """
        self.assertVerdict("LogRecord", dict(LOG, pool_id=POOL_ID), False)
        self.assertVerdict("LogRecord", dict(LOG, event="Swap"), False)

    def test_log_record_data_is_bytes_and_may_be_empty(self) -> None:
        """Required, opaque, and permitted to be `0x`.

        The `x-why` names the one place where "required" and "may be empty"
        are not in tension: an event with no unindexed data yields `0x`, and a
        decoder that rejected that would throw on a valid record. Not decoded
        here — "which words mean what is event-specific".
        """
        self.assertVerdict("LogRecord", dict(LOG, data="0x"), True)
        self.assertVerdict("LogRecord", dict(LOG, data="0x1234"), True)
        self.assertVerdict("LogRecord", dict(LOG, data=""), False)
        self.assertVerdict("LogRecord", dict(LOG, data=1234), False)

    # -- robinhood-rpc-api: the log query -----------------------------------

    def test_topic_filter_accepts_the_query_the_contract_specifies(self) -> None:
        """`topic0 IN (...) AND topic1 = <poolId>` over one address."""
        self.assertVerdict("TopicFilter", FILTER, True)
        self.assertVerdict("TopicFilter", dict(FILTER, topic0=FIVE_TOPICS), True)
        self.assertVerdict("TopicFilter", dict(FILTER, topic0=[INITIALIZE]), True)

    def test_topic_filter_refuses_an_empty_topic0(self) -> None:
        """The single most load-bearing constraint in the file.

        `x-why` on the field: an empty list "would be 'every event at this
        address', which is a VALID JSON-RPC query returning logs the adapter
        cannot decode, and a value outside the five is not in the enum at
        all". `x-note` adds why that is worse than a typo — it "would not be a
        typo the endpoint catches", it is a valid query that streams `Transfer`
        and unidentified logs this adapter does not decode.
        """
        self.assertVerdict("TopicFilter", dict(FILTER, topic0=[]), False)

    def test_topic_filter_refuses_the_two_topics_the_address_really_emits(self) -> None:
        """Widening is impossible, and these are the values that would do it.

        The contract records both: `Transfer(address,address,address,uint256,uint256)`
        "appeared in every sampled window" and an unidentified topic0 "appeared
        twice in 480000 sampled blocks. UNKNOWN what the second one is". The
        `x-note` on `topic0` states the consequence — there is no "any other
        PoolManager log" mode, and a value outside the five "is not in the
        list, so [the upstream signatures] cannot be expressed here at all".
        """
        for value, why in (
            (TRANSFER_TOPIC0, "Transfer, emitted in every sampled window"),
            (UNIDENTIFIED_TOPIC0, "unidentified, UNKNOWN what it is"),
        ):
            with self.subTest(value=why):
                self.assertVerdict("TopicFilter", dict(FILTER, topic0=[value]), False)
                self.assertVerdict(
                    "TopicFilter", dict(FILTER, topic0=[INITIALIZE, value]), False
                )

    def test_topic_filter_refuses_more_than_five_topics(self) -> None:
        """A widened set is inexpressible rather than discouraged.

        The refusal is real, but it is NOT `maxItems` doing the work, and the
        file should not be read as though it were: `items.enum` has exactly
        five values and `uniqueItems` forbids repeats, so no list longer than
        five can be assembled out of them and `maxItems: 5` is never the
        binding constraint. Removing it changes no verdict (checked by
        mutation). The file states the effect it wants — "ineffpressible
        rather than merely discouraged" is its own phrase for the enum — so
        the test pins the effect and does not credit a keyword that is
        standing behind it. REPORTED as a redundancy in this schema, not
        fixed here: see the dispatch note.
        """
        self.assertVerdict(
            "TopicFilter", dict(FILTER, topic0=FIVE_TOPICS + ["0x" + "ee" * 32]), False
        )
        self.assertVerdict(
            "TopicFilter", dict(FILTER, topic0=["0x" + "ee" * 32] * 6), False
        )

    def test_topic_filter_topic0_is_a_set_not_a_multiset(self) -> None:
        """`uniqueItems: true`, against a field the file calls a SUBSET.

        A repeated value asks the same question twice and returns the same
        logs twice, so it is not a subset of the five in any sense the
        contract's "MAY narrow this set with a subset" describes.
        """
        self.assertVerdict("TopicFilter", dict(FILTER, topic0=[INITIALIZE, INITIALIZE]), False)
        self.assertVerdict("TopicFilter", dict(FILTER, topic0=INITIALIZE), False)

    def test_topic_filter_refuses_a_range_folded_into_the_query(self) -> None:
        """The block range is NOT here, and the file says where it is.

        `description`: "The block range is NOT here — it is the capability's
        own `from_block` / `to_block` parameters, and a filter carrying a
        range would be the window this contract keeps out of shared types."
        The signature is the record: `rpc.adapter.logs(chain_id, from_block,
        to_block, topic_filter)`.
        """
        for field in ("from_block", "to_block", "window", "max_range"):
            with self.subTest(field=field):
                self.assertVerdict("TopicFilter", dict(FILTER, **{field: HEIGHT}), False)

    def test_topic_filter_requires_an_address_and_a_pool_id(self) -> None:
        """Two refusals with two different reasons, both in the file.

        `address` is required because the query the contract specifies is
        scoped to ONE address, and a filter without it is the unbounded query.
        `pool_id` is required because that is the half which makes the read
        POOL-scoped rather than address-scoped: "a filter with no topic1 is
        the 'every event at this address' mode again, one position over".
        """
        for field in ("address", "pool_id", "topic0"):
            with self.subTest(missing=field):
                self.assertVerdict(
                    "TopicFilter", {k: v for k, v in FILTER.items() if k != field}, False
                )

    def test_topic_filter_address_is_the_wire_lowercase_spelling(self) -> None:
        """`x-why` on `address`: not frozen to the PoolManager value.

        The contract "calls the closure a property of this ADAPTER and not of
        the deployment, and a constant address in a schema would make it a
        property of both" — so the type takes any lowercase address and a
        second deployment on this chain validates against a correct filter.
        Uppercase is not that: the file's `x-note` on the wire spelling and
        the `Address` type's own test both parse to lowercase at the edge.
        """
        self.assertVerdict("TopicFilter", dict(FILTER, address="0x" + "AB" * 20), False)
        self.assertVerdict("TopicFilter", dict(FILTER, address="0x" + "11" * 19), False)

    # -- robinhood-rpc-api: the probe report --------------------------------

    def test_capability_report_accepts_two_null_windows(self) -> None:
        """Not measured is a legal report, and no fallback constant may stand
        in for it.

        `x-note-window-not-a-constant`: nothing here defaults to a measured
        number — the ~6000-block state window, the ~1000000-block log window,
        the 10000-result log cap are measurements from one host at named
        blocks, and "a default carrying any of them would be a probe that
        reports a remembered number instead of a measured one, which is the
        failure this capability exists to remove". So both windows null is
        accepted, and `x-why` on `state_block_window` says required-even-when-
        null is what makes "the probe did not establish it" distinguishable
        from "this endpoint has no limit".
        """
        self.assertVerdict("CapabilityReport", REPORT, True)
        measured = dict(
            ENDPOINT, state_block_window=6_000, log_block_window=1_000_000,
            archive_supported=True,
        )
        self.assertVerdict("CapabilityReport", {"endpoints": [measured]}, True)

    def test_capability_report_requires_a_measured_at_block_beside_each_window(self) -> None:
        """A window reported without the block it was measured against cannot
        be compared against anything, which is the entire purpose of the probe.

        `x-why` on `measured_at_block`: "state served to block 76000000" means
        nothing without the head it was 6000 behind, and the head moves.
        """
        self.assertVerdict(
            "CapabilityReport",
            {"endpoints": [{k: v for k, v in ENDPOINT.items()
                            if k != "measured_at_block"}]},
            False,
        )
        # and the refusal does not soften once the windows carry numbers
        self.assertVerdict(
            "CapabilityReport",
            {"endpoints": [dict(
                {k: v for k, v in ENDPOINT.items() if k != "measured_at_block"},
                state_block_window=6_000, log_block_window=1_000_000,
            )]},
            False,
        )

    def test_capability_report_refuses_the_two_windows_collapsed_into_one(self) -> None:
        """The reason these are two fields and not one, and it is measured.

        `x-why` on `log_block_window`: on the measured endpoint logs were
        served from head-1000000 while state was not, so one "block range cap"
        "is a number that is wrong for one of the two consumers" — the one
        that fetches a wide log range and then reads state across it and hits
        the edge partway through. Collapsing them also makes the two `null`s
        indistinguishable, so a probe that established neither could not say
        so. Both shapes are refused: one field in place of two, and one field
        beside them.
        """
        collapsed = {k: v for k, v in ENDPOINT.items() if k != "log_block_window"}
        collapsed["block_range_cap"] = 1_000_000
        self.assertVerdict("CapabilityReport", {"endpoints": [collapsed]}, False)
        self.assertVerdict(
            "CapabilityReport", {"endpoints": [dict(ENDPOINT, block_range_cap=1_000_000)]},
            False,
        )
        # the two caps the contract does NOT name stay out too — they are
        # properties of one host's query limits, read from its error text
        for field in ("log_interval_cap", "result_cap", "range_cap"):
            with self.subTest(field=field):
                self.assertVerdict(
                    "CapabilityReport", {"endpoints": [dict(ENDPOINT, **{field: 10_000})]},
                    False,
                )

    def test_capability_report_requires_endpoints(self) -> None:
        """The signature takes `urls: list[str]` and the limits are per-host,
        so a report has to say which host produced which numbers. An empty
        list is not a report of nothing found; it is a probe that ran against
        no endpoint, and `minItems: 1` is what tells those apart.
        """
        self.assertVerdict("CapabilityReport", {}, False)
        self.assertVerdict("CapabilityReport", {"endpoints": []}, False)
        self.assertVerdict("CapabilityReport", {"endpoints": [ENDPOINT, {}]}, False)
        self.assertVerdict("CapabilityReport", dict(REPORT, endpoint=[ENDPOINT]), False)

    def test_capability_report_requires_every_field_of_an_entry(self) -> None:
        """All six, and each required for a reason the file records: `url` so
        a two-endpoint report is not read as one measurement, `archive_supported`
        because the contract names archive support as one of the four things
        this probe reports, and `finality` because the contract forbids the
        verdict it would otherwise carry.
        """
        for field in ENDPOINT:
            with self.subTest(missing=field):
                self.assertVerdict(
                    "CapabilityReport",
                    {"endpoints": [{k: v for k, v in ENDPOINT.items() if k != field}]},
                    False,
                )
        self.assertVerdict(
            "CapabilityReport", {"endpoints": [dict(ENDPOINT, url="")]}, False
        )

    def test_capability_report_refuses_a_finality_verdict(self) -> None:
        """Two observations per tag, and no verdict about any of them.

        `x-why` on `finality`: "which tag is final" is a judgement about the
        chain that no probe can make from a handful of reads, while "which
        tags answered" and "which of those served state" are two
        measurements. A verdict is inexpressible rather than discouraged, and
        three separate constraints each close one way of writing one:

          - a bare string, which is `type: array` refusing a scalar;
          - a tag outside `BlockRef`'s four, which the per-tag `enum` refuses;
          - an extra key on an otherwise well-formed entry naming the verdict
            ("is_final"), which `items.additionalProperties: false` refuses.
            The entry already carries two booleans, so a third one reading
            "and this one is THE final tag" is exactly the judgement the file
            says no probe can make, and an open `items` would let it through
            under a misspelled name nobody is checking.
        """
        # a bare string verdict
        self.assertVerdict(
            "CapabilityReport",
            {"endpoints": [dict(ENDPOINT, finality="finalized")]}, False,
        )
        # a tag outside the enum, in place of one of the four
        for outsider in ("earliest", "Latest", "finalized "):
            with self.subTest(tag=outsider):
                rows = [dict(row) for row in FINALITY_MEASURED]
                rows[0]["tag"] = outsider
                self.assertVerdict(
                    "CapabilityReport", {"endpoints": [dict(ENDPOINT, finality=rows)]}, False
                )
        # a verdict smuggled in as a fourth key on an otherwise legal entry
        for key in ("is_final", "final", "finality"):
            with self.subTest(extra_key=key):
                rows = [dict(row) for row in FINALITY_MEASURED]
                rows[3] = dict(rows[3], **{key: True})
                self.assertVerdict(
                    "CapabilityReport", {"endpoints": [dict(ENDPOINT, finality=rows)]}, False
                )
        # and the report that resolved nothing is still a legal report: the
        # array is total, so "nothing resolved" is four rows of two false flags
        # rather than an absent tag that could also mean "never looked"
        self.assertVerdict(
            "CapabilityReport",
            {"endpoints": [dict(ENDPOINT, finality=FINALITY_NOTHING_RESOLVED)]}, True,
        )

    def test_capability_report_reuses_the_block_ref_tag_vocabulary(self) -> None:
        """The per-tag `enum` is `BlockRef`'s four tags, read off both sides.

        `x-why` on the `tag` property: the enum "reuses `BlockRef`'s four
        tags rather than declaring a second tag vocabulary: two contracts
        declaring one name is SCHEMA_AMBIGUOUS, and these are the same four by
        the same contract clause". That claim is about two declarations being
        EQUAL, so it is checked by comparing the two enums directly rather
        than by refusing an instance — an instance-level refusal of `earliest`
        would pass just as well against a differently-spelled four, which is
        the drift the claim exists to prevent. `earliest` is still refused
        here, for the reason it is refused on `BlockRef`.
        """
        report_enum = self.finality_tag_enum()
        block_ref_enum = self.block_ref_tag_enum()
        self.assertEqual(
            report_enum, block_ref_enum,
            "finality's per-tag enum and BlockRef's tag enum must be the same "
            f"four tags: {report_enum!r} vs {block_ref_enum!r}",
        )
        self.assertEqual(sorted(report_enum), ["finalized", "latest", "pending", "safe"])
        for outsider in ("earliest", "Latest", "finalized "):
            with self.subTest(tag=outsider):
                rows = [dict(row) for row in FINALITY_MEASURED]
                rows[0]["tag"] = outsider
                self.assertVerdict(
                    "CapabilityReport", {"endpoints": [dict(ENDPOINT, finality=rows)]}, False
                )


@unittest.skipIf(_Validator is None, "jsonschema is not installed")
class SchemaDocumentTests(unittest.TestCase):
    """Checks on the files themselves, independent of any instance."""

    def test_every_type_is_structurally_valid_json_schema(self) -> None:
        for type_name, body in _load_all().items():
            with self.subTest(type=type_name):
                _Validator.check_schema(body)

    def test_no_ungoverned_keyword_outside_the_x_namespace(self) -> None:
        """A typo'd keyword is silently ignored, and a typo'd constraint
        means the constraint nobody is enforcing.

        `additional_notes:` and `minimun:` both parse cleanly and both do
        nothing. The `x-` namespace is what makes a mistake visible.
        """
        # The 2020-12 core/validation/applicator vocabulary, as a validator
        # actually applies. Annotations are included so `description` and
        # `title` are not flagged.
        allowed = {
            # core
            "$schema", "$id", "$anchor", "$dynamicRef", "$ref", "$defs",
            "$comment", "$vocabulary",
            # applicators
            "prefixItems", "items", "contains", "additionalProperties",
            "properties", "patternProperties", "additionalItems",
            "unevaluatedItems", "unevaluatedProperties", "propertyNames",
            "dependentSchemas", "allOf", "anyOf", "oneOf", "not", "if",
            "then", "else", "dependentRequired",
            # validation
            "type", "enum", "const", "multipleOf", "maximum", "exclusiveMaximum",
            "minimum", "exclusiveMinimum", "maxLength", "minLength", "pattern",
            "maxItems", "minItems", "uniqueItems", "maxContains", "minContains",
            "maxProperties", "minProperties", "required", "dependentRequired",
            "format", "contentEncoding", "contentMediaType", "contentSchema",
            # annotations
            "title", "description", "default", "deprecated", "readOnly",
            "writeOnly", "examples",
        }
        offenders: list[str] = []
        # Under these, the keys are names the schema declares, not keywords.
        # Descending into them normally would flag `currency0` as a keyword.
        by_name = {"properties", "patternProperties", "dependentSchemas", "$defs"}
        for type_name, body in _load_all().items():
            stack = [(type_name, body)]
            while stack:
                path, node = stack.pop()
                if isinstance(node, dict):
                    for key, val in node.items():
                        if key not in allowed and not key.startswith("x-"):
                            offenders.append(f"{path}.{key}")
                        if key in by_name and isinstance(val, dict):
                            for name, sub in val.items():
                                stack.append((f"{path}.{key}({name})", sub))
                        else:
                            stack.append((f"{path}.{key}", val))
                elif isinstance(node, list):
                    for i, val in enumerate(node):
                        stack.append((f"{path}[{i}]", val))
        self.assertEqual(offenders, [], f"unknown JSON Schema keywords: {offenders}")

    def test_every_x_encoding_keyword_carries_a_source(self) -> None:
        """An encoding asserted without a source is a guess in citation
        clothing, which is the thing AGENTS.md §4 exists to prevent.
        """
        offenders: list[str] = []
        for type_name, body in _load_all().items():
            stack = [(type_name, body)]
            while stack:
                path, node = stack.pop()
                if isinstance(node, dict):
                    if "x-encoding" in node and "x-source" not in node:
                        offenders.append(f"{path}.x-encoding without x-source")
                    for key, val in node.items():
                        stack.append((f"{path}.{key}", val))
                elif isinstance(node, list):
                    for i, val in enumerate(node):
                        stack.append((f"{path}[{i}]", val))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

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

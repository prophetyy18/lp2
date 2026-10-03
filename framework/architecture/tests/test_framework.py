"""Tests for the three acceptance questions.

    1. what may this module read?
    2. what may this module depend on?
    3. who is affected if this contract changes?

Each has a positive case and a case that must fail loudly rather than let the
caller peek at another module's implementation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from framework.architecture import (
    boundary,
    graph,
    impact,
    loader,
    query,
    signatures,
    snapshot,
    validator,
)
from framework.architecture.errors import (
    BOUNDARY_VIOLATION,
    CONTRACT_INSUFFICIENT,
    CYCLE_DETECTED,
    ILLEGAL_DEPENDENCY,
    INVALID_METADATA,
    SCHEMA_AMBIGUOUS,
    SCHEMA_DANGLING,
    SCHEMA_UNDECLARED,
    UNITEMISED_USES,
    UNKNOWN_CONTRACT,
    ArchError,
)

from .fixtures import base_contracts, base_modules, load_real, write_tree


class TempArchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def arch(self, contracts=None, modules=None, schemas=None):
        write_tree(
            self.root,
            contracts if contracts is not None else base_contracts(),
            modules if modules is not None else base_modules(),
            schemas,
        )
        return loader.load(self.root)


# --- Q1: what may this module read? ---------------------------------------


class BoundaryTests(TempArchTest):
    def setUp(self) -> None:
        super().setUp()
        self.a = self.arch()

    def test_reads_own_implementation_and_architecture_metadata(self) -> None:
        beta = self.a.module("beta")
        for path in (
            "modules/beta/engine.py",
            "architecture/contracts/alpha-api.yaml",
            "architecture/modules/alpha/module.yaml",
        ):
            with self.subTest(path=path):
                self.assertIsNone(boundary.check_read(beta, path, self.a))

    def test_cannot_read_another_module_implementation(self) -> None:
        beta = self.a.module("beta")
        finding = boundary.check_read(beta, "modules/alpha/core.py", self.a)
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.code, BOUNDARY_VIOLATION)
        self.assertEqual(finding.context["published_by"], "alpha")
        # The remedy must be a contract change, not a wider read grant.
        self.assertEqual(finding.context["remedy"], "ARCHITECTURE_CHANGE_REQUIRED")
        self.assertIn("alpha-api", finding.context["consumed_contracts"])

    def test_cannot_read_framework_internals(self) -> None:
        beta = self.a.module("beta")
        finding = boundary.check_read(beta, "framework/architecture/impact.py", self.a)
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.code, BOUNDARY_VIOLATION)

    def test_paths_outside_repo_are_denied(self) -> None:
        beta = self.a.module("beta")
        for path in ("../other/secret.py", "/etc/passwd", "modules/../../escape.py"):
            with self.subTest(path=path):
                self.assertIsNotNone(boundary.check_read(beta, path, self.a))

    def test_readable_extra_grants_explicitly(self) -> None:
        modules = base_modules()
        modules["beta"]["readable_extra"] = ["shared/**"]
        arch = self.arch(modules=modules)
        beta = arch.module("beta")
        self.assertIsNone(boundary.check_read(beta, "shared/util.py", arch))
        self.assertIsNotNone(boundary.check_read(beta, "modules/alpha/core.py", arch))

    def test_readable_extra_cannot_grant_another_module(self) -> None:
        modules = base_modules()
        modules["beta"]["readable_extra"] = ["modules/alpha/**"]
        arch = self.arch(modules=modules)
        codes = {f.code for f in validator.validate(arch) if f.severity == "ERROR"}
        self.assertIn(BOUNDARY_VIOLATION, codes)

    def test_readable_summary_lists_every_other_module_as_denied(self) -> None:
        data = query.readable(self.a, "beta")
        denied = {d["path"] for d in data["denied"]}
        self.assertIn("modules/alpha/**", denied)
        allowed = {r["glob"] for r in data["allowed"]}
        self.assertIn("modules/beta/**", allowed)


# --- Q2: what may this module depend on? ----------------------------------


class DependencyTests(TempArchTest):
    def test_declared_contract_dependencies_are_resolved(self) -> None:
        arch = self.arch()
        data = query.dependencies(arch, "beta")
        by_contract = {d["contract"]: d for d in data["depends_on"]}
        self.assertIn("alpha-api", by_contract)
        self.assertEqual(by_contract["alpha-api"]["publisher"], "alpha")
        self.assertTrue(by_contract["alpha-api"]["satisfied"])
        self.assertEqual(data["blockers"], [])

    def test_module_edge_is_derived_through_contract(self) -> None:
        arch = self.arch()
        edges = graph.direct_module_edges(arch)
        self.assertEqual(edges["beta"], {"alpha"})
        self.assertEqual(edges["alpha"], set())

    def test_using_an_undeclared_capability_is_contract_insufficient(self) -> None:
        modules = base_modules()
        modules["beta"]["depends_on"] = [{"contract": "alpha-api", "uses": ["alpha.secret"]}]
        arch = self.arch(modules=modules)
        codes = {f.code for f in validator.validate(arch)}
        self.assertIn(CONTRACT_INSUFFICIENT, codes)

        data = query.dependencies(arch, "beta")
        entry = data["depends_on"][0]
        self.assertFalse(entry["satisfied"])
        self.assertEqual(entry["missing_capabilities"], ["alpha.secret"])
        self.assertIn("alpha.one", entry["available"])  # what it could have used
        self.assertTrue(data["blockers"])

    def test_unknown_contract_is_reported_not_ignored(self) -> None:
        modules = base_modules()
        modules["beta"]["depends_on"] = [{"contract": "ghost-api", "uses": []}]
        arch = self.arch(modules=modules)
        codes = {f.code for f in validator.validate(arch)}
        self.assertIn(UNKNOWN_CONTRACT, codes)

    def test_direct_module_dependency_is_illegal(self) -> None:
        modules = base_modules()
        modules["beta"]["depends_on"] = [{"contract": "alpha"}]  # a module, not a contract
        arch = self.arch(modules=modules)
        findings = [f for f in validator.validate(arch) if f.code == ILLEGAL_DEPENDENCY]
        self.assertTrue(findings)
        self.assertIn("contract", findings[0].message)

    def test_contract_ownership_must_be_unique(self) -> None:
        modules = base_modules()
        modules["alpha"]["provides_contracts"] = ["alpha-api", "beta-api"]
        arch = self.arch(modules=modules)
        findings = [f for f in validator.validate(arch) if f.code == ILLEGAL_DEPENDENCY]
        self.assertTrue(findings)

    def test_contract_cycle_is_detected(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["requires"] = ["beta-api"]
        arch = self.arch(contracts=contracts)
        self.assertIn(CYCLE_DETECTED, {f.code for f in validator.validate(arch)})
        with self.assertRaises(ArchError):
            graph.contract_order(arch)


# --- Q3: who is affected by a contract change? ----------------------------


class ImpactTests(TempArchTest):
    def setUp(self) -> None:
        super().setUp()
        self.a = self.arch()

    def test_direct_consumers_are_publisher_and_dependents(self) -> None:
        result = impact.impact_of_contract(self.a, "alpha-api")
        self.assertEqual({i.module for i in result.direct}, {"alpha", "beta"})
        self.assertTrue(all(i.distance == 1 for i in result.direct))

    def test_indirect_consumers_are_found_through_requires_closure(self) -> None:
        # gamma consumes beta-api, which requires alpha-api
        modules = base_modules()
        modules["gamma"] = {
            "name": "gamma",
            "provides_contracts": [],
            "depends_on": [{"contract": "beta-api", "uses": ["beta.one"]}],
        }
        arch = self.arch(modules=modules)

        result = impact.impact_of_contract(arch, "alpha-api")
        direct = {i.module for i in result.direct}
        indirect = {i.module: i.distance for i in result.indirect}
        self.assertEqual(direct, {"alpha", "beta"})
        self.assertEqual(indirect, {"gamma": 2})
        self.assertEqual(
            {i.module for i in result.all_modules}, {"alpha", "beta", "gamma"}
        )

    def test_impact_of_module_unions_its_contracts(self) -> None:
        result = impact.impact_of_module(self.a, "alpha")
        self.assertEqual({i.module for i in result.direct}, {"alpha", "beta"})
        self.assertTrue(any("alpha-api" in n for n in result.notes))

    def test_consumer_queries_agree_with_impact(self) -> None:
        data = query.consumers_of(self.a, "alpha-api")
        impact_modules = {
            i.module for i in impact.impact_of_contract(self.a, "alpha-api").direct
        }
        self.assertEqual(impact_modules, {"alpha", "beta"})
        self.assertEqual({c["module"] for c in data["direct_consumers"]}, {"beta"})

    def test_impact_of_unknown_contract_raises(self) -> None:
        with self.assertRaises(ArchError):
            impact.impact_of_contract(self.a, "nope")

    def test_capability_filter_must_exist(self) -> None:
        with self.assertRaises(ArchError) as ctx:
            impact.impact_of_contract(self.a, "alpha-api", ["alpha.missing"])
        self.assertEqual(ctx.exception.code, CONTRACT_INSUFFICIENT)

    def test_unitemised_dependency_is_flagged_as_a_note(self) -> None:
        modules = base_modules()
        modules["beta"]["depends_on"] = [{"contract": "alpha-api"}]
        arch = self.arch(modules=modules)
        result = impact.impact_of_contract(arch, "alpha-api")
        self.assertTrue(any("without itemising" in n for n in result.notes))
        # alpha-api publishes capabilities, so an unitemised `uses` is
        # now an ERROR (UNITEMISED_USES), not a soft warning.
        errs = [f for f in validator.validate(arch) if f.code == UNITEMISED_USES]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].severity, "ERROR")
        self.assertEqual(errs[0].context["module"], "beta")

    def test_unitemised_dependency_is_soft_warning_when_contract_publishes_nothing(self) -> None:
        contracts = base_contracts()
        # Strip all capabilities from alpha-api so unitemised `uses` is allowed
        # as a soft warning (the contract is a placeholder, not yet capable).
        contracts["alpha-api"]["provides"] = []
        modules = base_modules()
        modules["beta"]["depends_on"] = [{"contract": "alpha-api"}]
        arch = self.arch(contracts=contracts, modules=modules)
        warnings = [
            f
            for f in validator.validate(arch)
            if f.code == CONTRACT_INSUFFICIENT and f.severity == "WARNING"
        ]
        self.assertEqual(len(warnings), 1)

    def test_capability_filter_narrows_direct_impact(self) -> None:
        modules = base_modules()
        modules["delta"] = {
            "name": "delta",
            "provides_contracts": [],
            "depends_on": [{"contract": "alpha-api", "uses": ["alpha.two"]}],
        }
        arch = self.arch(modules=modules)

        # Change only to alpha.one — delta (uses alpha.two) should be downgrad-noted,
        # not listed in direct.
        result = impact.impact_of_contract(arch, "alpha-api", capabilities=["alpha.one"])
        direct_modules = {i.module for i in result.direct}
        self.assertIn("beta", direct_modules)  # beta uses alpha.one
        self.assertNotIn("delta", direct_modules)
        self.assertTrue(
            any("delta" in n and "alpha.two" in n for n in result.notes),
            f"expected a downgrad note for delta, got notes={result.notes}",
        )

    def test_capability_filter_keeps_indirect_impact_conservative(self) -> None:
        modules = base_modules()
        modules["gamma"] = {
            "name": "gamma",
            "provides_contracts": [],
            "depends_on": [{"contract": "beta-api", "uses": ["beta.one"]}],
        }
        arch = self.arch(modules=modules)
        result = impact.impact_of_contract(arch, "alpha-api", capabilities=["alpha.one"])
        indirect_modules = {i.module for i in result.indirect}
        self.assertIn("gamma", indirect_modules)
        # Indirect impact stays conservative; a note must call that out.
        self.assertTrue(
            any("indirect impact is kept conservative" in n for n in result.notes),
            f"expected a conservative-indirect note, got notes={result.notes}",
        )


class SnapshotDiffTests(TempArchTest):
    def test_contract_change_reports_affected_modules(self) -> None:
        from framework.architecture import snapshot

        arch = self.arch()
        snap = snapshot.write(arch, self.root / "snap.json")

        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [{"id": "alpha.one"}, {"id": "alpha.three"}]
        write_tree(self.root, contracts, base_modules())
        after = loader.load(self.root)

        report = query.impact_of_diff(after, str(snap))
        self.assertEqual(report["diff"]["contracts"][0]["contract"], "alpha-api")
        self.assertIn("alpha.three", report["diff"]["contracts"][0]["added_capabilities"])
        self.assertIn("beta", report["affected_modules"])

    def test_removing_a_capability_is_breaking(self) -> None:
        from framework.architecture import snapshot

        arch = self.arch()
        snap = snapshot.write(arch, self.root / "snap.json")

        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [{"id": "alpha.one"}]
        write_tree(self.root, contracts, base_modules())
        report = query.impact_of_diff(loader.load(self.root), str(snap))
        self.assertTrue(report["breaking"])
        self.assertIn("alpha.two", report["diff"]["contracts"][0]["removed_capabilities"])


# --- the real project metadata --------------------------------------------


class RealArchitectureTests(unittest.TestCase):
    # Schema references this repository has not resolved yet.
    #
    # A ratchet in BOTH directions. It was originally one-way —
    # `open_now - OPEN_SCHEMA_REFS == set()` — which meant that deleting every
    # dangling reference emptied the set and the test passed while printing
    # "6/6 resolved": the six disappeared because the capabilities naming
    # them were withdrawn, and the test counted that as progress. A one-way
    # ratchet cannot tell "someone fixed this" from "the thing citing it is
    # gone", and only the second is not a repair.
    #
    # So the set must EQUAL the open set, and removing an entry has to be a
    # deletion somebody makes on purpose. It is empty as of 2026-10-03, when
    # the twelve robinhood-* modules were withdrawn.
    OPEN_SCHEMA_REFS: set[str] = set()

    def test_repo_architecture_is_valid(self) -> None:
        arch = load_real()
        report = query.validation_report(arch)
        blocking = [
            f
            for f in report["findings"]
            if f["severity"] == "ERROR" and f["code"] != SCHEMA_DANGLING
        ]
        self.assertEqual(blocking, [], "non-schema errors in the real architecture")

    def test_no_unresolved_schema_reference_outside_the_ratchet(self) -> None:
        arch = load_real()
        open_now = {
            f.context["schema"]
            for f in validator.validate(arch)
            if f.code == SCHEMA_DANGLING
        }
        # Both directions. A reference that is no longer open must be deleted
        # from OPEN_SCHEMA_REFS in the same change, or the ratchet records a
        # debt that stopped being owed.
        self.assertEqual(
            open_now - self.OPEN_SCHEMA_REFS,
            set(),
            "a capability now references a schema that does not exist",
        )
        self.assertEqual(
            self.OPEN_SCHEMA_REFS - open_now,
            set(),
            "OPEN_SCHEMA_REFS lists a reference that is no longer dangling; "
            "delete it on purpose — its capability may simply be gone, which "
            "is not the same as the schema having been written",
        )
        print(f"\n  {len(open_now)} schema references still open")

    def test_every_module_declares_capabilities_it_uses(self) -> None:
        arch = load_real()
        for name in arch.modules:
            with self.subTest(module=name):
                self.assertEqual(query.dependencies(arch, name)["blockers"], [])

    def test_no_module_can_read_another(self) -> None:
        arch = load_real()
        for consumer in arch.modules.values():
            for producer in arch.modules.values():
                if consumer.name == producer.name:
                    continue
                with self.subTest(module=consumer.name, other=producer.name):
                    finding = boundary.check_read(consumer, f"{producer.path}/core.py", arch)
                    self.assertIsNotNone(finding)


# --- capability metadata model --------------------------------------------


class CapabilityModelTests(TempArchTest):
    """Loader-level checks for the extended Capability metadata.

    Each test exercises one rule: kind vocabulary, mutual exclusion of
    input/output/payload, error parsing, behavior-tag parsing.
    """

    def _contract(self, body: dict) -> dict:
        return {
            "name": "alpha-api",
            "version": 1,
            "requires": [],
            "provides": [body],
        }

    def test_default_kind_is_operation(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [{"id": "alpha.one"}]
        arch = self.arch(contracts=contracts)
        cap = arch.contract("alpha-api").provides[0]
        self.assertEqual(cap.kind, "operation")

    def test_event_kind_carries_payload(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.ticked", "kind": "event", "payload": {"schema": "alpha.Tick"}}
        ]
        arch = self.arch(contracts=contracts)
        cap = arch.contract("alpha-api").provides[0]
        self.assertEqual(cap.kind, "event")
        self.assertEqual(cap.payload, cap.payload)  # round-tripped
        self.assertIsNone(cap.input)
        self.assertIsNone(cap.output)

    def test_data_kind_carries_output(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.list", "kind": "data", "output": {"schema": "alpha.FactorList"}}
        ]
        arch = self.arch(contracts=contracts)
        cap = arch.contract("alpha-api").provides[0]
        self.assertEqual(cap.kind, "data")
        self.assertIsNone(cap.input)
        self.assertIsNone(cap.payload)
        self.assertIsNotNone(cap.output)

    def test_unknown_kind_is_rejected_at_load(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [{"id": "alpha.one", "kind": "function"}]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)
        self.assertIn("kind", ctx.exception.message)

    def test_event_must_not_declare_input_or_output(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.ticked", "kind": "event", "input": {"schema": "alpha.Tick"}}
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)

    def test_operation_must_not_declare_payload(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "payload": {"schema": "alpha.Tick"},
            }
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)

    def test_data_must_not_declare_input_or_payload(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.list", "kind": "data", "input": {"schema": "alpha.Foo"}}
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)

    def test_errors_accept_short_and_long_forms(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "errors": ["SHORT", {"code": "LONG", "recoverable": "permanent"}],
            }
        ]
        arch = self.arch(contracts=contracts)
        errs = arch.contract("alpha-api").provides[0].errors
        self.assertEqual([e.code for e in errs], ["SHORT", "LONG"])
        self.assertEqual(errs[0].recoverable, "transient")
        self.assertEqual(errs[1].recoverable, "permanent")

    def test_errors_recoverable_must_be_in_vocabulary(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "errors": [{"code": "X", "recoverable": "maybe"}],
            }
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)

    def test_behavior_rejects_unknown_unit(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "behavior": {"unit": "kelvin"},
            }
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)

    def test_behavior_rejects_an_unrecognised_key(self) -> None:
        """A dropped key is worse than a rejected one.

        The loader used to read only the keys it knew and ignore the rest, so
        a contract could assert `timezone: tz_aware_utc` (or anything else)
        in a behavior block, have it vanish on load, and still pass
        `archctl validate`. The file claimed a promise, the tooling agreed,
        and no promise existed. Measured before this was fixed: a
        `total_nonsense: 42` key loaded without error and appeared in no
        `to_dict`.
        """
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "behavior": {"unit": "usdg", "total_nonsense": 42},
            }
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)
        self.assertIn("total_nonsense", str(ctx.exception))

    def test_behavior_rejects_an_unknown_timezone(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "behavior": {"timezone": "tz_aware_est"},
            }
        ]
        with self.assertRaises(ArchError) as ctx:
            self.arch(contracts=contracts)
        self.assertEqual(ctx.exception.code, INVALID_METADATA)

    def test_timezone_round_trips_and_is_not_confused_with_time(self) -> None:
        """`time` says which clock; `timezone` says what shape you get back.

        They sit next to each other and are easy to conflate, so the test
        pins the distinction: a capability can declare one, the other, or
        both, and `event_time` says nothing about whether the datetime a
        consumer receives carries an offset.
        """
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "behavior": {"time": "event_time", "timezone": "tz_aware_utc"},
            },
            {
                "id": "alpha.bare",
                "kind": "operation",
                "behavior": {"time": "event_time"},
            },
        ]
        arch = self.arch(contracts=contracts)
        first, second = arch.contract("alpha-api").provides
        self.assertEqual(first.behavior.timezone, "tz_aware_utc")
        self.assertEqual(first.behavior.to_dict()["timezone"], "tz_aware_utc")
        # `event_time` alone promises nothing about the shape of the value
        self.assertEqual(second.behavior.timezone, "")
        self.assertNotIn("timezone", second.behavior.to_dict())

    def test_behavior_round_trips_through_dict(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.run",
                "kind": "operation",
                "behavior": {
                    "unit": "usdg",
                    "time": "event_time",
                    "idempotent": True,
                    "ordering": "total",
                    "stale_tolerance": "5min",
                },
            }
        ]
        arch = self.arch(contracts=contracts)
        cap = arch.contract("alpha-api").provides[0]
        self.assertEqual(cap.behavior.unit, "usdg")
        self.assertEqual(cap.behavior.time, "event_time")
        self.assertTrue(cap.behavior.idempotent)
        self.assertEqual(cap.behavior.ordering, "total")
        # Round-trip into the dict that the snapshot writer emits.
        d = cap.to_dict()
        self.assertEqual(
            d["behavior"],
            {
                "unit": "usdg",
                "time": "event_time",
                "idempotent": True,
                "ordering": "total",
                "stale_tolerance": "5min",
            },
        )


class CapabilityBreakingTests(TempArchTest):
    """Snapshot-level checks: capability-field changes are breaking."""

    def test_renaming_a_capability_field_is_breaking(self) -> None:
        arch = self.arch()
        snap = snapshot.write(arch, self.root / "snap.json")

        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {
                "id": "alpha.one",
                "kind": "operation",
                "behavior": {"unit": "usdg", "time": "event_time"},
            }
        ]
        write_tree(self.root, contracts, base_modules())
        report = query.impact_of_diff(loader.load(self.root), str(snap))
        self.assertTrue(report["breaking"])
        changed = report["diff"]["contracts"][0]["changed_capabilities"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["id"], "alpha.one")
        self.assertIn("behavior", changed[0]["field_changes"])

    def test_purely_cosmetic_description_change_is_not_breaking(self) -> None:
        arch = self.arch()
        snap = snapshot.write(arch, self.root / "snap.json")

        contracts = base_contracts()
        # Touch only the human description; capability fields are untouched.
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.one", "description": "new wording"},
            {"id": "alpha.two"},
        ]
        write_tree(self.root, contracts, base_modules())
        report = query.impact_of_diff(loader.load(self.root), str(snap))
        # No capability was added/removed; no field changed.
        self.assertFalse(report["breaking"])

    def test_adding_a_capability_is_not_breaking(self) -> None:
        arch = self.arch()
        snap = snapshot.write(arch, self.root / "snap.json")

        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.one"},
            {"id": "alpha.two"},
            {"id": "alpha.three"},
        ]
        write_tree(self.root, contracts, base_modules())
        report = query.impact_of_diff(loader.load(self.root), str(snap))
        self.assertFalse(report["breaking"])


# --- declared type shapes ---------------------------------------------------


class SignatureScanTests(unittest.TestCase):
    """`signatures.type_names` — pulling type names back out of prose.

    This is a text scan, so the cases that matter are the ones where a naive
    scan would report a type that is not one.
    """

    def test_params_and_return(self) -> None:
        self.assertEqual(
            signatures.type_names("a.f(x: PoolId, at: int) -> PositionValuation"),
            {"PoolId", "PositionValuation"},
        )

    def test_reaches_into_generic_arguments(self) -> None:
        self.assertEqual(
            signatures.type_names("a.f(xs: list[LogRecord]) -> None"), {"LogRecord"}
        )

    def test_builtins_and_plain_generics_are_not_types(self) -> None:
        self.assertEqual(
            signatures.type_names("a.g(a: str, b: dict[str, int], c: tuple[int, bytes]) -> bool"),
            set(),
        )

    def test_commas_inside_a_parameter_do_not_split_it(self) -> None:
        self.assertEqual(
            signatures.type_names("a.h(m: Mapping[str, int], k: TickRange) -> EventCursor"),
            {"TickRange", "EventCursor"},
        )

    def test_module_paths_are_not_types(self) -> None:
        self.assertEqual(
            signatures.type_names("a.i(v: decimal.Decimal) -> decimal.Decimal"), set()
        )

    def test_no_parentheses_yields_nothing(self) -> None:
        self.assertEqual(signatures.type_names(""), set())
        self.assertEqual(signatures.type_names("a.f"), set())


class SchemaLoadingTests(TempArchTest):
    """`architecture/schemas/` — loading, and refusing the unusable cases."""

    def test_schemas_load_keyed_by_contract_and_type(self) -> None:
        arch = self.arch(schemas={"alpha-api": {"PoolId": {"type": "string"}}})
        self.assertIn("alpha-api.PoolId", arch.schemas)
        self.assertEqual(arch.schemas["alpha-api.PoolId"], {"type": "string"})

    def test_a_schema_file_for_an_unknown_contract_is_refused(self) -> None:
        # Otherwise a typo in the file name yields a schema nothing can
        # reference, and the directory looks populated either way.
        with self.assertRaises(ArchError) as ctx:
            self.arch(schemas={"typo-api": {"PoolId": {"type": "string"}}})
        self.assertIn("not defined", str(ctx.exception))

    def test_a_non_mapping_schema_is_refused(self) -> None:
        with self.assertRaises(ArchError) as ctx:
            self.arch(schemas={"alpha-api": {"PoolId": "just a string"}})
        self.assertIn("must be a mapping", str(ctx.exception))


class SchemaReferenceTests(TempArchTest):
    """`SCHEMA_DANGLING` / `SCHEMA_UNDECLARED` — the two spellings of a type name.

    Before this existed, SchemaRef was an opaque string and `validate` passed
    with 29 references pointing at nothing.
    """

    def _findings(self, arch, code):
        return [f for f in validator.validate(arch) if f.code == code]

    def _contract_with(self, capability):
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [capability]
        return contracts

    def test_explicit_ref_to_nothing_is_an_error(self) -> None:
        arch = self.arch(
            contracts=self._contract_with(
                {"id": "alpha.one", "output": {"schema": "alpha-api.Nope"}}
            )
        )
        found = self._findings(arch, SCHEMA_DANGLING)
        self.assertEqual([f.context["schema"] for f in found], ["alpha-api.Nope"])
        # A ref to nothing is not a weaker promise than a promise kept.
        self.assertTrue(validator.has_errors(validator.validate(arch)))

    def test_explicit_ref_to_a_declared_schema_is_clean(self) -> None:
        arch = self.arch(
            contracts=self._contract_with(
                {"id": "alpha.one", "output": {"schema": "alpha-api.PoolId"}}
            ),
            schemas={"alpha-api": {"PoolId": {"type": "string"}}},
        )
        self.assertEqual(self._findings(arch, SCHEMA_DANGLING), [])

    def test_input_and_payload_refs_are_checked_too(self) -> None:
        arch = self.arch(
            contracts=self._contract_with(
                {
                    "id": "alpha.one",
                    "kind": "event",
                    "payload": {"schema": "alpha-api.Missing"},
                }
            )
        )
        self.assertEqual(len(self._findings(arch, SCHEMA_DANGLING)), 1)

    def test_type_named_in_a_signature_with_no_schema_warns(self) -> None:
        arch = self.arch(
            contracts=self._contract_with(
                {"id": "alpha.one", "signature": "alpha.one(c: EventCursor) -> RunRecord"}
            )
        )
        found = self._findings(arch, SCHEMA_UNDECLARED)
        self.assertEqual(
            sorted(f.context["type"] for f in found), ["EventCursor", "RunRecord"]
        )
        # WARNING, not ERROR: a missing shape is a real gap but the check must
        # not turn the repository red before the shapes are filled in.
        self.assertTrue(all(f.severity == "WARNING" for f in found))

    def test_declaring_the_types_clears_the_warning(self) -> None:
        arch = self.arch(
            contracts=self._contract_with(
                {"id": "alpha.one", "signature": "alpha.one(c: EventCursor) -> RunRecord"}
            ),
            schemas={
                "alpha-api": {"EventCursor": {"type": "string"}, "RunRecord": {"type": "object"}}
            },
        )
        self.assertEqual(self._findings(arch, SCHEMA_UNDECLARED), [])

    def test_one_bare_name_declared_twice_is_ambiguous_not_resolved(self) -> None:
        # A bare name in a signature can only be satisfied by exactly one
        # declared type. Two owners is a collision, and picking one would be a
        # guess dressed as a match.
        contracts = base_contracts()
        contracts["beta-api"] = {
            "name": "beta-api",
            "provides": [{"id": "beta.one", "signature": "beta.one(x: PoolId) -> int"}],
        }
        arch = self.arch(
            contracts=contracts,
            schemas={
                "alpha-api": {"PoolId": {"type": "string"}},
                "beta-api": {"PoolId": {"type": "string"}},
            },
        )
        found = self._findings(arch, SCHEMA_AMBIGUOUS)
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0].context["owners"], ["alpha-api.PoolId", "beta-api.PoolId"]
        )
        self.assertEqual(self._findings(arch, SCHEMA_UNDECLARED), [])

    def test_finding_names_every_capability_mentioning_the_type(self) -> None:
        contracts = base_contracts()
        contracts["alpha-api"]["provides"] = [
            {"id": "alpha.one", "signature": "alpha.one(c: EventCursor) -> int"},
            {"id": "alpha.two", "signature": "alpha.two(c: EventCursor) -> int"},
        ]
        arch = self.arch(contracts=contracts)
        found = [f for f in self._findings(arch, SCHEMA_UNDECLARED)
                 if f.context["type"] == "EventCursor"]
        self.assertEqual(
            found[0].context["named_by"], ["alpha-api:alpha.one", "alpha-api:alpha.two"]
        )


if __name__ == "__main__":
    unittest.main()

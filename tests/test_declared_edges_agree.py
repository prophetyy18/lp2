"""Do the two halves of a cross-module edge agree with each other?

A cross-module dependency in this repository is written down three times, in
two files, and no tool reads all three at once:

    architecture/modules/<m>/module.yaml
        depends_on:            which contract, and which capabilities from it
        readable_extra:        which files may be imported to use it
    architecture/contracts/<m>-api.yaml
        requires:             which contract this one is written against

`archctl validate` checks that every one of those names resolves to something
that exists, and `_check_readable_extra` checks that no grant reaches into a
whole module tree. It does **not** check that they agree with each other: a
`depends_on` entry with no grant is a dependency nothing can enforce, and a
`requires:` list that disagrees with the publishing module's `depends_on` is
two files making two claims about one edge.

That is not a hypothetical. `robinhood-application-api` listed eight contracts
in `requires:` while `robinhood-application` declared nine modules in
`depends_on` — the read path had no plug at the source, and the composition
root was declared against a module it did not wire. Both files were correct
in isolation and the framework had nothing to say, which is why the repair
took an architecture pass rather than a red build.

The tests here ask the question someone actually has — *if I add a
`depends_on` entry, is the other half already there?* — against the real tree
rather than a fixture. The alternative is a fixture, and a fixture can only
prove the checker works; it cannot notice a declaration that has drifted. The
cost of reading the real tree is that a correct architecture is a passing
state, and that is the correct answer.

`CrossModuleGateTests` in `tests/test_implement_state.py` used to cover this
by accident, by asserting on the live declarations as a side effect of testing
the state machine. That coupling is gone — one architecture edit broke four
tests whose subject was the gate — and these are where the coverage went.

**These tests currently assert nothing.** The architecture was withdrawn on
2026-10-03, so `arch.modules` and `arch.contracts` are both empty and every
test here iterates nothing and passes. That is the same shape as the defect
`RealArchitectureTests.OPEN_SCHEMA_REFS` had — a check that reports success
because the subject it was checking no longer exists — and it is recorded
here rather than left for the next reader to assume otherwise.

They stay because the alternative is worse. A fixture proves the checker runs
and nothing else, which is what the fixtures in `test_layer_direction.py`
already do; the first real `depends_on` to be declared needs this coverage
more than it needs a passing suite today. The honest summary is: three green
lines that assert nothing, in exchange for a check that will bite the moment
it has something to bite on.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from framework.architecture import loader


class DeclaredEdgesAgreeTests(unittest.TestCase):
    """Both pairings, over every module in the real architecture."""

    # One root, read through the class rather than through a module constant,
    # because the two halves of these tests have to be looking at the SAME
    # tree: the framework loader and the raw YAML walk. A constant for each
    # would let them disagree, and a test that half-reads a mutation is worse
    # than no test.
    ROOT = Path(__file__).resolve().parents[1]

    @classmethod
    def setUpClass(cls) -> None:
        cls.arch = loader.load(cls.ROOT)

    def _declared(self, module: str, key: str) -> list[str]:
        """`depends_on` or `readable_extra`, read off the file rather than
        through the loader.

        `readable_extra` has no accessor on the model that also answers "which
        contract is this", and the whole point of the first test is the
        pairing between the two, so the raw list is the honest input.
        """
        import yaml

        path = self.ROOT / "architecture/modules" / module / "module.yaml"
        return list(yaml.safe_load(path.read_text(encoding="utf-8")).get(key) or [])

    def _depends_on(self, module: str) -> list[dict]:
        return self._declared(module, "depends_on")

    def _grants(self, module: str) -> list[str]:
        return self._declared(module, "readable_extra")

    def test_a_depends_on_entry_and_its_readable_extra_grant_come_together(self) -> None:
        """AGENTS.md §3: a dependency needs BOTH halves, and both are checkable.

        `depends_on` says what is used and why; `readable_extra` says which
        files may be imported to use it. One without the other is a claim
        rather than a dependency — a grant with no declaration is a back door
        (and the AST scanner reports it), while a declaration with no grant is
        declared-but-unenforceable, and nothing reports that at all.
        """
        for mod in self.arch.modules.values():
            declared = {dep["contract"] for dep in self._depends_on(mod.name)}
            grants = set(self._grants(mod.name))
            for contract in sorted(declared):
                # The provider's public surface is `modules/<provider>/api/**`
                # for every contract in this repository, so the expected grant
                # is derivable rather than a list somebody has to maintain.
                provider = contract[: -len("-api")]
                expected = f"modules/{provider}/api/**"
                with self.subTest(module=mod.name, contract=contract):
                    self.assertIn(
                        expected, grants,
                        f"{mod.name} depends on {contract} but grants nothing "
                        f"importable, so the dependency cannot be used",
                    )
            for grant in sorted(grants):
                parts = grant.split("/")
                if len(parts) < 3 or parts[0] != "modules" or parts[1] == mod.name:
                    continue  # not a cross-module path, or the module's own tree
                with self.subTest(module=mod.name, grant=grant):
                    self.assertEqual(
                        parts[2:], ["api", "**"],
                        f"{mod.name} grants {grant}, which is not a provider's "
                        f"public surface: cross-module access goes through "
                        f"modules/<provider>/api/** and nothing wider",
                    )
                    self.assertIn(
                        f"{parts[1]}-api", declared,
                        f"{mod.name} grants {grant} but declares no "
                        f"dependency on {parts[1]}-api to justify it",
                    )

    def test_a_contracts_requires_matches_the_depends_on_of_its_module(self) -> None:
        """`requires:` and `depends_on` are two declarations of one edge.

        The contract says what it is written against; the module that
        publishes it says what it actually wires. When they disagree, the
        contract's blast radius (`archctl impact`) is computed from a list the
        module does not honour, and the module is declared against a contract
        whose own edge list never mentioned it.

        This is the pairing with a real failure behind it: see this module's
        docstring for the eight-against-nine instance.
        """
        for mod in self.arch.modules.values():
            for contract_name in mod.owns_contracts:
                contract = self.arch.contracts[contract_name]
                declared = sorted(
                    {dep["contract"] for dep in self._depends_on(mod.name)}
                )
                with self.subTest(module=mod.name, contract=contract_name):
                    self.assertEqual(
                        declared, sorted(contract.requires),
                        f"{contract_name} requires {sorted(contract.requires)} "
                        f"but {mod.name} declares depends_on {declared}; one of "
                        f"the two is describing an edge the other does not have",
                    )

    def test_every_contract_is_published_by_exactly_one_module(self) -> None:
        """The premise both of the above rests on: a contract has one owner.

        A contract two modules both publish would give the `requires:`
        comparison above two owners to disagree with, and `dependers-of` two
        answers for the same capability.
        """
        owners: dict[str, list[str]] = {}
        for mod in self.arch.modules.values():
            for contract_name in mod.owns_contracts:
                owners.setdefault(contract_name, []).append(mod.name)
        for contract_name, names in sorted(owners.items()):
            with self.subTest(contract=contract_name):
                self.assertEqual(
                    names, [names[0]],
                    f"{contract_name} is published by {names}",
                )
        for contract_name in sorted(self.arch.contracts):
            with self.subTest(contract=contract_name):
                self.assertIn(
                    contract_name, owners,
                    f"{contract_name} is declared but no module publishes it",
                )


if __name__ == "__main__":
    unittest.main()

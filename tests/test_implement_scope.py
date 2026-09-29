"""Write-scope audit: a module may only write its own tree, cards and tests.

Read scope is declared policy in the role prompts; write scope is what this
audit can actually see, so it is what gets tested.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from framework.architecture import loader
from framework.architecture.tests.fixtures import write_tree
from tools.implement import naming
from tools.implement.scope import allowed_roots, audit

CONTRACTS = {
    "alpha-api": {
        "name": "alpha-api",
        "version": 1,
        "requires": [],
        "provides": [{"id": "alpha.one"}],
    },
    "market-data-api": {
        "name": "market-data-api",
        "version": 1,
        "requires": [],
        "provides": [{"id": "series.get"}],
    },
}

MODULES = {
    "alpha": {
        "name": "alpha",
        "source": "modules/alpha",
        "provides_contracts": ["alpha-api"],
        "depends_on": [],
    },
    "beta": {
        "name": "beta",
        "source": "modules/beta",
        "provides_contracts": [],
        "depends_on": [{"contract": "alpha-api", "uses": ["alpha.one"]}],
        "readable_extra": ["modules/alpha/api/**"],
    },
    # Every real module is hyphenated and every real capability id is
    # dotted. `alpha` / `one` are the only names in this repository for which
    # a naive `test_{module}_{capability}` prefix is correct, which is
    # exactly why the audit shipped a prefix no writer could ever satisfy.
    "market-data": {
        "name": "market-data",
        "source": "modules/market-data",
        "provides_contracts": ["market-data-api"],
        "depends_on": [],
    },
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class ScopeAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        write_tree(self.repo, CONTRACTS, MODULES)
        for name in MODULES:
            (self.repo / "modules" / name).mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "implement").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests").mkdir(parents=True, exist_ok=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "baseline")
        self.arch = loader.load(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rel: str, body: str = "# new\n") -> Path:
        target = self.repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target

    def _audit(self, module: str, capability: str | None = None):
        return audit(module, capability, repo=self.repo, arch=self.arch)

    def test_clean_run_has_no_findings(self) -> None:
        self.assertEqual(self._audit("alpha"), [])

    def test_own_module_tree_is_writable(self) -> None:
        self._write("modules/alpha/api/one.py")
        self.assertEqual(self._audit("alpha"), [])

    def test_own_cards_are_writable(self) -> None:
        self._write("docs/implement/alpha/one.card.md")
        self.assertEqual(self._audit("alpha"), [])

    def test_own_tests_for_this_capability_are_writable(self) -> None:
        self._write("tests/test_alpha_one.py")
        self.assertEqual(self._audit("alpha", "one"), [])

    def test_another_modules_tree_is_not_writable(self) -> None:
        self._write("modules/beta/core.py")
        codes = {f.code for f in self._audit("alpha")}
        self.assertEqual(codes, {"SCOPE_VIOLATION"})

    def test_a_granted_public_surface_is_readable_but_not_writable(self) -> None:
        """beta holds a read grant on alpha/api; writing there is still a violation."""
        self._write("modules/alpha/api/one.py")
        findings = self._audit("beta")
        self.assertEqual({f.code for f in findings}, {"SCOPE_VIOLATION"})
        self.assertIn("readable, never writable", findings[0].message)

    def test_another_capabilitys_test_is_not_writable(self) -> None:
        self._write("tests/test_alpha_two.py")
        codes = {f.code for f in self._audit("alpha", "one")}
        self.assertEqual(codes, {"SCOPE_VIOLATION"})

    def test_architecture_is_not_writable(self) -> None:
        self._write("architecture/modules/alpha/module.yaml", "name: alpha\n")
        self.assertEqual({f.code for f in self._audit("alpha")}, {"SCOPE_VIOLATION"})

    def test_tools_and_root_docs_are_not_writable(self) -> None:
        self._write("AGENTS.md")
        self._write("tools/implement/scope.py")
        self.assertEqual({f.code for f in self._audit("alpha")}, {"SCOPE_VIOLATION"})

    def test_allowed_roots_follow_the_declared_source(self) -> None:
        roots = dict(allowed_roots("alpha", "one", self.arch))
        self.assertIn("modules/alpha/", roots)
        self.assertEqual(roots["modules/alpha/"], "own module implementation")

    def test_tests_root_is_absent_without_a_capability(self) -> None:
        roots = dict(allowed_roots("alpha", None, self.arch))
        self.assertNotIn("tests/", " ".join(roots))


class RoleScopedWriteTests(unittest.TestCase):
    """The test file and the implementation have different authors.

    A tester who can also write the implementation writes tests for whatever
    it built; a developer who can also edit the tests can edit them into
    passing. Both are the same failure — the spec and the thing that meets it
    are written by the same hand — and `--role` is what stops it, because it
    reuses the audited-write-scope layer that already exists rather than
    asking anyone to be careful.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        write_tree(self.repo, CONTRACTS, MODULES)
        for name in MODULES:
            (self.repo / "modules" / name).mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "implement").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests").mkdir(parents=True, exist_ok=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "baseline")
        self.arch = loader.load(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rel: str) -> None:
        target = self.repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# new\n", encoding="utf-8")

    def _audit(self, role: str | None):
        return audit(
            "market-data", "series.get", repo=self.repo, arch=self.arch, role=role
        )

    def test_the_developer_may_not_write_the_tests(self) -> None:
        """The whole point: the implementer cannot edit the spec it is held to."""
        self._write(naming.test_rel_path("market-data", "series.get"))
        findings = self._audit("developer")
        self.assertEqual({f.code for f in findings}, {"SCOPE_VIOLATION"})
        self.assertIn("test_market_data_series_get", findings[0].path)

    def test_the_developer_may_write_the_implementation(self) -> None:
        self._write("modules/market-data/series.py")
        self.assertEqual(self._audit("developer"), [])

    def test_the_tester_may_not_write_the_implementation(self) -> None:
        """The tester writing code is how the tests start describing the code."""
        self._write("modules/market-data/series.py")
        findings = self._audit("tester")
        self.assertEqual({f.code for f in findings}, {"SCOPE_VIOLATION"})

    def test_the_tester_may_write_the_tests_and_its_own_records(self) -> None:
        self._write(naming.test_rel_path("market-data", "series.get"))
        self._write("docs/implement/market-data/series.get.tests.md")
        self.assertEqual(self._audit("tester"), [])

    def test_either_role_may_not_reach_an_others_module(self) -> None:
        self._write("modules/pricing/position.py")
        for role in ("tester", "developer"):
            self.assertEqual({f.code for f in self._audit(role)}, {"SCOPE_VIOLATION"})

    def test_no_role_allows_both_halves(self) -> None:
        """The union is the ad-hoc default, and no single role may be it."""
        self._write(naming.test_rel_path("market-data", "series.get"))
        self._write("modules/market-data/series.py")
        for role in ("tester", "developer"):
            self.assertEqual(len(self._audit(role)), 1, role)
        self.assertEqual(self._audit(None), [])

    def test_an_unknown_role_is_refused_rather_than_defaulted(self) -> None:
        """Defaulting an unrecognised role to the union would open both halves."""
        with self.assertRaises(ValueError):
            allowed_roots("market-data", "series.get", self.arch, "reviewer")


class HyphenatedModuleDottedCapabilityTests(unittest.TestCase):
    """The naming rule against names that actually occur.

    Every module in `architecture/modules/` is hyphenated and every
    capability id in `architecture/contracts/` is dotted, so the audit's
    test allow-list has to translate both. It did not: it compared against
    `tests/test_market-data_series.get`, a filename no writer produces, and
    a developer's own test came back a SCOPE_VIOLATION — the layer AGENTS.md
    calls "the layer that actually holds" was the one thing guaranteed to
    stop the first real run.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        write_tree(self.repo, CONTRACTS, MODULES)
        (self.repo / "docs" / "implement").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests").mkdir(parents=True, exist_ok=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "baseline")
        self.arch = loader.load(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rel: str) -> None:
        target = self.repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# new\n", encoding="utf-8")

    def test_the_canonical_test_file_is_inside_the_grant(self) -> None:
        self._write(naming.test_rel_path("market-data", "series.get"))
        findings = audit("market-data", "series.get", repo=self.repo, arch=self.arch)
        self.assertEqual([f.format() for f in findings], [])

    def test_the_allow_list_uses_underscores_not_the_raw_names(self) -> None:
        roots = dict(allowed_roots("market-data", "series.get", self.arch))
        self.assertIn("tests/test_market_data_series_get", roots)
        for raw in ("market-data", "series.get", "test_market-data", "series_get"):
            self.assertNotIn(f"tests/test_{raw}", roots)

    def test_sibling_helpers_beside_the_test_are_allowed(self) -> None:
        self._write(naming.test_rel_path("market-data", "series.get"))
        self._write("tests/test_market_data_series_get_fixtures.py")
        findings = audit("market-data", "series.get", repo=self.repo, arch=self.arch)
        self.assertEqual([f.format() for f in findings], [])

    def test_another_capabilitys_test_is_still_outside_the_grant(self) -> None:
        self._write(naming.test_rel_path("market-data", "series.symbols"))
        findings = audit("market-data", "series.get", repo=self.repo, arch=self.arch)
        self.assertEqual({f.code for f in findings}, {"SCOPE_VIOLATION"})

    def test_another_modules_test_is_outside_the_grant(self) -> None:
        self._write(naming.test_rel_path("alpha", "alpha.one"))
        findings = audit("market-data", "series.get", repo=self.repo, arch=self.arch)
        self.assertEqual({f.code for f in findings}, {"SCOPE_VIOLATION"})


if __name__ == "__main__":
    unittest.main()

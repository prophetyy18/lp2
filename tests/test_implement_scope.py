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
from tools.implement.scope import allowed_roots, audit

CONTRACTS = {
    "alpha-api": {
        "name": "alpha-api",
        "version": 1,
        "requires": [],
        "provides": [{"id": "alpha.one"}],
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


if __name__ == "__main__":
    unittest.main()

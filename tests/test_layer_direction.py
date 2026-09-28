"""Cross-module import isolation: every module's source must be hermetic.

A module may read its own tree, `architecture/**`, and whatever its own
module.yaml grants through `readable_extra`. In practice a module publishes
its contract surface under `api/` and consumers grant exactly that:

    readable_extra:
      - modules/<provider>/api/**

Everything else — another module's implementation, a whole module tree, or a
public surface the consumer never declared `depends_on` on — is denied.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from framework.architecture import loader
from framework.architecture.tests.fixtures import write_tree
from tools.check_imports.scan import scan_module, scan_repo


CONTRACTS = {
    "alpha-api": {
        "name": "alpha-api",
        "version": 1,
        "requires": [],
        "provides": [{"id": "alpha.one"}],
    },
    "gamma-api": {
        "name": "gamma-api",
        "version": 1,
        "requires": [],
        "provides": [{"id": "gamma.one"}],
    },
    "delta-api": {
        "name": "delta-api",
        "version": 1,
        "requires": [],
        "provides": [{"id": "delta.one"}],
    },
}

MODULES = {
    # publishes a public surface, depends on nothing
    "alpha": {
        "name": "alpha",
        "source": "modules/alpha",
        "provides_contracts": ["alpha-api"],
        "depends_on": [],
    },
    "gamma": {
        "name": "gamma",
        "source": "modules/gamma",
        "provides_contracts": ["gamma-api"],
        "depends_on": [],
    },
    # depends on alpha AND is granted exactly alpha's public surface
    "beta": {
        "name": "beta",
        "source": "modules/beta",
        "provides_contracts": [],
        "depends_on": [{"contract": "alpha-api", "uses": ["alpha.one"]}],
        "readable_extra": ["modules/alpha/api/**"],
    },
    # declares no dependency at all
    "epsilon": {
        "name": "epsilon",
        "source": "modules/epsilon",
        "provides_contracts": [],
        "depends_on": [],
    },
    # hyphenated directory name -> underscore package name on import
    "robinhood-delta": {
        "name": "robinhood-delta",
        "source": "modules/robinhood-delta",
        "provides_contracts": ["delta-api"],
        "depends_on": [],
    },
    "robinhood-svc": {
        "name": "robinhood-svc",
        "source": "modules/robinhood-svc",
        "provides_contracts": [],
        "depends_on": [{"contract": "delta-api", "uses": ["delta.one"]}],
        "readable_extra": ["modules/robinhood-delta/api/**"],
    },
}


def _write(root: Path, module: str, files: dict[str, str]) -> None:
    pkg = root / "modules" / module
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name, body in files.items():
        target = pkg / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body), encoding="utf-8")


class LayerDirectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.modules = self.root / "modules"
        write_tree(self.root, CONTRACTS, MODULES)
        self.arch = loader.load(self.root)
        # every declared module needs a directory for scan_repo
        for name in MODULES:
            (self.modules / name).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _codes(self, module: str, **kwargs) -> set[str]:
        findings = scan_module(module, self.modules, self.arch, **kwargs)
        return {f.code for f in findings}

    # --- baseline ---------------------------------------------------------

    def test_clean_module_has_no_findings(self) -> None:
        _write(
            self.root,
            "alpha",
            {
                "core.py": (
                    """
                    import json
                    from dataclasses import dataclass

                    @dataclass
                    class X:
                        pass
                    """
                ),
            },
        )
        self.assertEqual(self._codes("alpha"), set())

    def test_own_module_self_import_is_allowed(self) -> None:
        _write(
            self.root,
            "alpha",
            {
                "a.py": "from modules.alpha.b import Y\n",
                "b.py": "class Y: pass\n",
            },
        )
        self.assertEqual(self._codes("alpha"), set())

    def test_legacy_package_is_forbidden(self) -> None:
        _write(self.root, "alpha", {"core.py": "from robinhood_lp.protocol import ids\n"})
        self.assertIn("LEGACY_LEAK", self._codes("alpha"))

    def test_framework_public_api_is_allowed(self) -> None:
        _write(
            self.root,
            "alpha",
            {"core.py": "from framework.architecture import load, validate\n"},
        )
        self.assertEqual(self._codes("alpha"), set())

    def test_framework_private_path_is_an_internal_leak(self) -> None:
        _write(
            self.root,
            "alpha",
            {"core.py": "from framework.architecture._private import thing\n"},
        )
        self.assertIn("INTERNAL_LEAK", self._codes("alpha"))

    # --- declared and granted: allowed ------------------------------------

    def test_granted_public_surface_is_allowed(self) -> None:
        _write(self.root, "alpha", {"api/one.py": "def one(): return 1\n"})
        _write(self.root, "beta", {"core.py": "from modules.alpha.api.one import one\n"})
        self.assertEqual(self._codes("beta"), set())

    def test_grant_covers_the_bare_package_form(self) -> None:
        """`from modules.alpha.api import one` names the package, not a file."""
        _write(self.root, "alpha", {"api/one.py": "def one(): return 1\n"})
        _write(self.root, "beta", {"core.py": "from modules.alpha.api import one\n"})
        self.assertEqual(self._codes("beta"), set())

    def test_hyphenated_module_dir_is_self_on_import(self) -> None:
        """modules/robinhood-delta imports as modules.robinhood_delta."""
        _write(
            self.root,
            "robinhood-delta",
            {"core.py": "from modules.robinhood_delta.api.one import one\n"},
        )
        self.assertEqual(self._codes("robinhood-delta"), set())

    def test_hyphenated_grant_is_allowed(self) -> None:
        _write(self.root, "robinhood-delta", {"api/one.py": "def one(): return 1\n"})
        _write(
            self.root,
            "robinhood-svc",
            {"core.py": "from modules.robinhood_delta.api.one import one\n"},
        )
        self.assertEqual(self._codes("robinhood-svc"), set())

    # --- not granted: denied ----------------------------------------------

    def test_ungranted_implementation_is_a_boundary_violation(self) -> None:
        _write(self.root, "alpha", {"impl/one.py": "def _one(): return 1\n"})
        _write(self.root, "beta", {"core.py": "from modules.alpha.impl.one import _one\n"})
        self.assertIn("BOUNDARY_VIOLATION", self._codes("beta"))

    def test_public_surface_without_a_declared_dependency_is_insufficient(self) -> None:
        """A grant alone is not enough: depends_on must declare the contract."""
        _write(self.root, "gamma", {"api/one.py": "def one(): return 1\n"})
        _write(self.root, "epsilon", {"core.py": "from modules.gamma.api.one import one\n"})
        codes = self._codes("epsilon")
        self.assertIn("CONTRACT_INSUFFICIENT", codes)

    def test_missing_dependency_message_names_the_contract(self) -> None:
        _write(self.root, "gamma", {"api/one.py": "def one(): return 1\n"})
        _write(self.root, "epsilon", {"core.py": "from modules.gamma.api.one import one\n"})
        findings = scan_module("epsilon", self.modules, self.arch)
        msg = next(f.message for f in findings if f.code == "CONTRACT_INSUFFICIENT")
        self.assertIn("gamma-api", msg)
        self.assertIn("depends_on", msg)

    def test_import_of_an_undeclared_module_is_a_violation(self) -> None:
        _write(self.root, "epsilon", {"core.py": "from modules.nope.thing import t\n"})
        self.assertIn("BOUNDARY_VIOLATION", self._codes("epsilon"))

    # --- absent sources are not violations --------------------------------

    def test_missing_source_tree_is_a_note_not_an_error(self) -> None:
        findings = scan_module("nowhere", self.modules, self.arch)
        self.assertEqual([f.code for f in findings], ["MODULE_NOT_FOUND"])
        self.assertEqual(findings[0].severity, "INFO")

    def test_strict_promotes_missing_source_tree_to_error(self) -> None:
        findings = scan_module("nowhere", self.modules, self.arch, strict_missing=True)
        self.assertEqual(findings[0].severity, "ERROR")

    def test_repo_scan_notes_an_absent_modules_tree(self) -> None:
        findings = scan_repo(self.root / "does-not-exist")
        self.assertEqual([f.code for f in findings], ["NO_MODULES_TREE"])
        self.assertEqual(findings[0].severity, "INFO")

    def test_repo_scan_flags_an_undeclared_implementation_dir(self) -> None:
        (self.modules / "rogue").mkdir()
        (self.modules / "rogue" / "__init__.py").write_text("", encoding="utf-8")
        findings = scan_repo(self.modules, self.arch)
        codes = {f.code for f in findings}
        self.assertIn("MODULE_UNDECLARED", codes)
        self.assertNotIn("BOUNDARY_VIOLATION", codes)


if __name__ == "__main__":
    unittest.main()
